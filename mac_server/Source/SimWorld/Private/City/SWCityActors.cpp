#include "City/SWCityActors.h"

#include "City/SWCityJson.h"
#include "City/SWCityMesh.h"
#include "Components/BoxComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/VolumetricCloudComponent.h"
#include "Engine/DirectionalLight.h"
#include "Engine/PostProcessVolume.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "DynamicRHI.h"
#include "EngineUtils.h"
#include "Misc/App.h"
#include "RenderTimer.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "SWCommon.h"

using namespace SWCity;
namespace J = SWCity::Json;

namespace
{
EMat MatFromName(const FString& N)
{
	static const TMap<FString, EMat> M = {
		{TEXT("Timber"), EMat::Timber}, {TEXT("RammedEarth"), EMat::RammedEarth}, {TEXT("SolarGlass"), EMat::SolarGlass},
		{TEXT("GreenRoof"), EMat::GreenRoof}, {TEXT("Moss"), EMat::Moss}, {TEXT("Foliage"), EMat::Foliage},
		{TEXT("Bark"), EMat::Bark}, {TEXT("Water"), EMat::Water}, {TEXT("PermeableStone"), EMat::PermeableStone},
		{TEXT("Path"), EMat::Path}, {TEXT("Metal"), EMat::Metal}, {TEXT("Fabric"), EMat::Fabric}, {TEXT("Lantern"), EMat::Lantern}, {TEXT("Plain"), EMat::Plain}};
	FString K = N;
	K.RemoveFromStart(TEXT("M_"));
	const EMat* Found = M.Find(K);
	return Found ? *Found : EMat::PermeableStone;
}

FTransform Xf(const FVector& Loc, const FVector& Scale, double Yaw = 0.0, double Pitch = 0.0, double Roll = 0.0)
{
	return FTransform(FRotator(Pitch, Yaw, Roll), Loc, Scale);
}

uint8 P(EPrim Prim) { return uint8(Prim); }
uint8 M(EMat Mat) { return uint8(Mat); }

/** Ellipse polygon. */
TArray<FVector2D> Ellipse(const FVector2D& C, double Rx, double Ry, int32 N)
{
	TArray<FVector2D> Out;
	for (int32 i = 0; i < N; ++i)
	{
		const double A = 2 * PI * i / N;
		Out.Add(C + FVector2D(FMath::Cos(A) * Rx, FMath::Sin(A) * Ry));
	}
	return Out;
}

/** Resample a polyline every Step cm. */
TArray<FVector2D> Resample(const TArray<FVector2D>& Pts, double Step)
{
	TArray<FVector2D> Out;
	if (Pts.Num() < 2) return Pts;
	Out.Add(Pts[0]);
	double Carry = 0.0;
	for (int32 i = 0; i + 1 < Pts.Num(); ++i)
	{
		const FVector2D A = Pts[i], B = Pts[i + 1];
		const double Len = FVector2D::Distance(A, B);
		double T = Step - Carry;
		while (T < Len)
		{
			Out.Add(A + (B - A) * (T / Len));
			T += Step;
		}
		Carry = Len - (T - Step);
	}
	if (FVector2D::Distance(Out.Last(), Pts.Last()) > 1.0) Out.Add(Pts.Last());
	return Out;
}

/** Annular sector (r0..r1, angles a0..a1 radians) as a solid Z0..Z1. */
void Sector(FSWMeshBuilder& B, int32 S, const FVector2D& C, double R0, double R1, double A0, double A1, double Z0, double Z1, int32 Segs)
{
	for (int32 i = 0; i < Segs; ++i)
	{
		const double T0 = A0 + (A1 - A0) * i / Segs, T1 = A0 + (A1 - A0) * (i + 1) / Segs;
		const FVector2D D0(FMath::Cos(T0), FMath::Sin(T0)), D1(FMath::Cos(T1), FMath::Sin(T1));
		const FVector2D I0 = C + D0 * R0, I1 = C + D1 * R0, O0 = C + D0 * R1, O1 = C + D1 * R1;
		B.Quad(S, FVector(I0, Z1), FVector(I1, Z1), FVector(O1, Z1), FVector(O0, Z1), FVector::UpVector);
		const FVector2D Dm = (D0 + D1).GetSafeNormal();
		B.Quad(S, FVector(O0, Z0), FVector(O1, Z0), FVector(O1, Z1), FVector(O0, Z1), FVector(Dm, 0));
		B.Quad(S, FVector(I0, Z0), FVector(I1, Z0), FVector(I1, Z1), FVector(I0, Z1), FVector(-Dm, 0));
	}
}
} // namespace

// =============================================================================================
// Base

void ASWCityActor::FInstances::Add(uint8 Prim, uint8 Mat, const FLinearColor& Tint, const FTransform& T, bool bShadow, double CullCm)
{
	const FColor Q = Tint.ToFColor(false);
	for (FInstanceBucket& Bk : Buckets)
	{
		if (Bk.Prim == Prim && Bk.Mat == Mat && Bk.bShadow == bShadow && Bk.CullCm == CullCm && Bk.Tint.ToFColor(false) == Q)
		{
			Bk.Xf.Add(T);
			return;
		}
	}
	FInstanceBucket& Bk = Buckets.AddDefaulted_GetRef();
	Bk.Prim = Prim;
	Bk.Mat = Mat;
	Bk.Tint = Tint;
	Bk.bShadow = bShadow;
	Bk.CullCm = CullCm;
	Bk.Xf.Add(T);
}

ASWCityActor::ASWCityActor()
{
	PrimaryActorTick.bCanEverTick = false;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	Root->SetMobility(EComponentMobility::Static);
	RootComponent = Root;
}

void ASWCityActor::ClearBuilt()
{
	for (UActorComponent* C : Built)
	{
		if (IsValid(C))
		{
			C->DestroyComponent();
		}
	}
	Built.Reset();
	Tris = 0;
	InstanceCount = 0;
}

void ASWCityActor::Configure(const FString& Json)
{
	const double T0 = FPlatformTime::Seconds();
	TSharedPtr<FJsonObject> Obj;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
	bOk = false;
	LastError.Reset();
	if (!FJsonSerializer::Deserialize(Reader, Obj) || !Obj.IsValid())
	{
		LastError = TEXT("bad json");
		UE_LOG(LogSimWorld, Warning, TEXT("%s Configure: bad JSON (%d chars)"), *GetName(), Json.Len());
		return;
	}
	ClearBuilt();
	Seed = GetTypeHash(GetName().ToLower());

	const TArray<double> Loc = J::Nums(Obj, TEXT("loc_cm"));
	Origin = Loc.Num() >= 2 ? FVector(Loc[0], Loc[1], Loc.Num() >= 3 ? Loc[2] : 0.0) : FVector::ZeroVector;
	const double Yaw = J::Num(Obj, TEXT("yaw"), 0.0);
	// Static root keeps the virtual shadow map cache valid; flip it movable just to place the actor.
	Root->SetMobility(EComponentMobility::Movable);
	SetActorLocationAndRotation(Origin, FRotator(0, Yaw, 0));
	Root->SetMobility(EComponentMobility::Static);

	bGI = J::Bool(Obj, TEXT("gi"), true);
	bOk = Build(Obj, LastError);
	UE_LOG(LogSimWorld, Log, TEXT("%s Configure: %s, %d tris, %d instances, %d components, %.1f ms"), *GetName(),
		bOk ? TEXT("ok") : *LastError, Tris, InstanceCount, Built.Num(), (FPlatformTime::Seconds() - T0) * 1000.0);
}

void ASWCityActor::GetBuildInfo(FString& Info)
{
	Info = FString::Printf(TEXT("{\"ok\": %s, \"tris\": %d, \"instances\": %d, \"components\": %d, \"error\": \"%s\"}"),
		bOk ? TEXT("true") : TEXT("false"), Tris, InstanceCount, Built.Num(), *LastError.ReplaceCharWithEscapedChar());
}

UStaticMeshComponent* ASWCityActor::AddMesh(const FSWMeshBuilder& B, bool bShadow)
{
	UStaticMesh* Mesh = B.Build(this, GetName());
	if (!Mesh)
	{
		return nullptr;
	}
	UStaticMeshComponent* C = NewObject<UStaticMeshComponent>(this);
	C->SetMobility(EComponentMobility::Static);
	C->SetupAttachment(Root);
	C->SetStaticMesh(Mesh);
	C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	C->SetGenerateOverlapEvents(false);
	C->SetCastShadow(bShadow);
	if (!bGI)
	{
		C->bAffectDynamicIndirectLighting = false;
		C->bAffectDistanceFieldLighting = false;
	}
	C->RegisterComponent();
	AddInstanceComponent(C);
	Built.Add(C);
	Tris += B.NumTris();
	return C;
}

void ASWCityActor::AddInstances(const FInstances& Inst)
{
	for (const FInstanceBucket& Bk : Inst.Buckets)
	{
		if (Bk.Xf.Num() == 0) continue;
		UInstancedStaticMeshComponent* C = NewObject<UInstancedStaticMeshComponent>(this);
		C->SetMobility(EComponentMobility::Static);
		C->SetupAttachment(Root);
		C->SetStaticMesh(GetPrim(EPrim(Bk.Prim)));
		C->SetMaterial(0, GetMaterial(EMat(Bk.Mat), Bk.Tint));
		C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		C->SetGenerateOverlapEvents(false);
		C->SetCastShadow(Bk.bShadow);
		if (!bGI)
		{
			C->bAffectDynamicIndirectLighting = false;
			C->bAffectDistanceFieldLighting = false;
		}
		if (Bk.CullCm > 0)
		{
			C->SetCullDistances(int32(Bk.CullCm * 0.8), int32(Bk.CullCm));
		}
		C->AddInstances(Bk.Xf, false, false, false);
		C->RegisterComponent();
		AddInstanceComponent(C);
		Built.Add(C);
		InstanceCount += Bk.Xf.Num();
		const uint8 Pr = Bk.Prim;
		Tris += Bk.Xf.Num() * (Pr == P(EPrim::Blob) || Pr == P(EPrim::Stone) || Pr == P(EPrim::Puff) ? 80 : (Pr == P(EPrim::Cone) ? 48 : (Pr == P(EPrim::Fringe) ? 36 : 24)));
	}
}

void ASWCityActor::AddCollisionBox(const FVector& Min, const FVector& Max)
{
	UBoxComponent* C = NewObject<UBoxComponent>(this);
	C->SetMobility(EComponentMobility::Static);
	C->SetupAttachment(Root);
	C->SetRelativeLocation((Min + Max) * 0.5);
	C->SetBoxExtent((Max - Min).GetAbs() * 0.5);
	C->SetCollisionProfileName(TEXT("BlockAllDynamic"));
	C->SetGenerateOverlapEvents(false);
	C->SetHiddenInGame(true);
	C->RegisterComponent();
	AddInstanceComponent(C);
	Built.Add(C);
}

// =============================================================================================
// Manager

ASWCityManager::ASWCityManager()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.bTickEvenWhenPaused = true;
	SetActorTickEnabled(true);
	RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
}

void ASWCityManager::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	const double Delta = FApp::GetDeltaTime() * 1000.0;
	SumDelta += Delta;
	MaxDelta = FMath::Max(MaxDelta, Delta);
	SumGame += FPlatformTime::ToMilliseconds(GGameThreadTime);
	SumRender += FPlatformTime::ToMilliseconds(GRenderThreadTime);
	SumGpu += FPlatformTime::ToMilliseconds(RHIGetGPUFrameCycles(0));
	++Frames;
}

void ASWCityManager::ResetFrameStats()
{
	Frames = 0;
	SumDelta = SumGame = SumRender = SumGpu = MaxDelta = 0;
}

void ASWCityManager::GetFrameStats(FString& Stats)
{
	int32 Actors = 0, Comps = 0, Tris = 0, Inst = 0;
	if (UWorld* World = GetWorld())
	{
		for (TActorIterator<ASWCityActor> It(World); It; ++It)
		{
			++Actors;
			FString Info;
			It->GetBuildInfo(Info);
			TSharedPtr<FJsonObject> O;
			if (FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Info), O) && O.IsValid())
			{
				Tris += int32(O->GetNumberField(TEXT("tris")));
				Inst += int32(O->GetNumberField(TEXT("instances")));
				Comps += int32(O->GetNumberField(TEXT("components")));
			}
		}
	}
	const double N = FMath::Max(1, Frames);
	Stats = FString::Printf(TEXT("{\"frames\": %d, \"delta_ms\": %.3f, \"max_delta_ms\": %.3f, \"game_ms\": %.3f, \"render_ms\": %.3f, \"gpu_ms\": %.3f, \"fps\": %.2f, \"city_actors\": %d, \"components\": %d, \"tris\": %d, \"instances\": %d}"),
		Frames, SumDelta / N, MaxDelta, SumGame / N, SumRender / N, SumGpu / N, Frames ? 1000.0 / (SumDelta / N) : 0.0, Actors, Comps, Tris, Inst);
}

void ASWCityManager::Look(const FString& Json, FString& Result)
{
	TSharedPtr<FJsonObject> Obj;
	if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Obj) || !Obj.IsValid())
	{
		Result = TEXT("bad json");
		return;
	}
	UWorld* World = GetWorld();
	TArray<FString> Out;
	if (const TSharedPtr<FJsonObject>* Cloud = nullptr; Obj->TryGetObjectField(TEXT("cloud"), Cloud))
	{
		for (TActorIterator<AVolumetricCloud> It(World); It; ++It)
		{
			UVolumetricCloudComponent* C = It->FindComponentByClass<UVolumetricCloudComponent>();
			if (!C) continue;
			UMaterialInstanceDynamic* Mid = Cast<UMaterialInstanceDynamic>(C->GetMaterial());
			if (!Mid && C->GetMaterial())
			{
				Mid = UMaterialInstanceDynamic::Create(C->GetMaterial(), C);
				C->SetMaterial(Mid);
			}
			if (!Mid) continue;
			for (const auto& Kv : (*Cloud)->Values)
			{
				double V = 0;
				if (Kv.Value.IsValid() && Kv.Value->TryGetNumber(V)) Mid->SetScalarParameterValue(FName(*Kv.Key), float(V));
				float Cur = 0.f;
				const bool bHas = Mid->GetScalarParameterValue(FName(*Kv.Key), Cur);
				Out.Add(FString::Printf(TEXT("\"%s\": %s"), *Kv.Key, bHas ? *FString::SanitizeFloat(Cur) : TEXT("null")));
			}
			for (const TCHAR* K : {TEXT("layer_bottom_km"), TEXT("layer_height_km")})
			{
				double V = 0;
				if (Obj->TryGetNumberField(K, V)) (FCString::Strcmp(K, TEXT("layer_bottom_km")) == 0) ? C->SetLayerBottomAltitude(float(V)) : C->SetLayerHeight(float(V));
			}
			break;
		}
	}
	if (TActorIterator<ADirectionalLight> It(World); It)
	{
		double V = 0;
		if (Obj->TryGetNumberField(TEXT("sun_pitch"), V))
		{
			FRotator R = It->GetActorRotation();
			R.Pitch = V;
			It->SetActorRotation(R);
		}
		if (Obj->TryGetNumberField(TEXT("sun_yaw"), V))
		{
			FRotator R = It->GetActorRotation();
			R.Yaw = V;
			It->SetActorRotation(R);
		}
		if (Obj->TryGetNumberField(TEXT("sun_intensity"), V)) It->GetLightComponent()->SetIntensity(float(V));
	}
	if (TActorIterator<APostProcessVolume> It(World); It)
	{
		double V = 0;
		if (Obj->TryGetNumberField(TEXT("saturation"), V)) It->Settings.ColorSaturation = FVector4(V, V, V, 1.0);
		if (Obj->TryGetNumberField(TEXT("contrast"), V)) It->Settings.ColorContrast = FVector4(1, 1, 1, V);
	}
	Result = TEXT("{") + FString::Join(Out, TEXT(", ")) + TEXT("}");
}

// =============================================================================================
// Ground

bool ASWCityGround::Build(const TSharedPtr<FJsonObject>& Obj, FString& Error)
{
	FSWMeshBuilder B;
	for (const TSharedPtr<FJsonObject>& S : J::Objs(Obj, TEXT("slabs")))
	{
		const int32 Slot = B.Slot(MatFromName(J::Str(S, TEXT("mat"), TEXT("Moss"))), J::Color(S, TEXT("tint"), Col::Grass()), float(J::Num(S, TEXT("scale"), 0.0)));
		const double Z0 = J::Num(S, TEXT("z0"), 0), Z1 = J::Num(S, TEXT("z1"), 2);
		FVector2D Mn, Mx;
		if (J::Rect(S, TEXT("rect_cm"), Mn, Mx))
		{
			B.Box(Slot, FVector(L2(Mn), Z0), FVector(L2(Mx), Z1), 16);
		}
		TArray<FVector2D> Poly = J::Points(S, TEXT("poly_cm"));
		if (Poly.Num() >= 3)
		{
			for (FVector2D& Pt : Poly) Pt = L2(Pt);
			B.Prism(Slot, Poly, Z0, Z1);
		}
	}
	// Backdrop hills: low hemispheres far out (they hide the edge of the 4 km floor and the grey horizon band).
	for (const TSharedPtr<FJsonObject>& Hl : J::Objs(Obj, TEXT("hills")))
	{
		const TArray<double> Hc = J::Nums(Hl, TEXT("c")), Hr = J::Nums(Hl, TEXT("r"));
		if (Hc.Num() < 2 || Hr.Num() < 3) continue;
		const int32 Slot = B.Slot(MatFromName(J::Str(Hl, TEXT("mat"), TEXT("Moss"))), J::Color(Hl, TEXT("tint"), Col::Grass()), float(J::Num(Hl, TEXT("scale"), 0.0)));
		B.Ellipsoid(Slot, L(Hc[0], Hc[1], -Hr[2] * 0.08), FVector(Hr[0], Hr[1], Hr[2]), 28, 7, true);
	}
	AddMesh(B, false);

	// Scattered meadow flowers / clover / shrubs over rects.
	FInstances Inst;
	FRng Rng(Seed);
	// Hedgerows: chains of overlapping cushions along polylines (field boundaries)
	for (const TSharedPtr<FJsonObject>& Hd : J::Objs(Obj, TEXT("hedges")))
	{
		TArray<FVector2D> Pts = J::Points(Hd, TEXT("pts"));
		if (Pts.Num() < 2) continue;
		for (FVector2D& Pt : Pts) Pt = L2(Pt);
		const double Hh = J::Num(Hd, TEXT("h"), 220), Wd = J::Num(Hd, TEXT("w"), 260);
		const FLinearColor Tc = J::Color(Hd, TEXT("tint"), Col::Leaf(1));
		// "step": cushion spacing as a multiple of the width (long cushions = fewer instances); "shadow": cast shadows
		const TArray<FVector2D> Rs = Resample(Pts, Wd * J::Num(Hd, TEXT("step"), 1.1));
		const bool bHedgeShadow = J::Bool(Hd, TEXT("shadow"), true);
		const double HedgeCull = J::Num(Hd, TEXT("cull_cm"), 0.0);
		for (int32 i = 0; i + 1 < Rs.Num(); ++i)
		{
			const FVector2D D = Rs[i + 1] - Rs[i];
			const double Yaw = FMath::RadiansToDegrees(FMath::Atan2(D.Y, D.X));
			const FVector2D Mid = (Rs[i] + Rs[i + 1]) * 0.5;
			const float Kc = (Rng.I(3) - 1) * 0.1f + 1.0f; // 3 levels (each tint is a component)
			Inst.Add(P(EPrim::Puff), M(EMat::Foliage), FLinearColor(Tc.R * Kc, Tc.G * Kc, Tc.B * Kc), Xf(FVector(Mid, Hh * 0.35), FVector(D.Size() * 0.62 / 100, Wd * 0.5 / 100, Hh * 0.75 / 100), Yaw), bHedgeShadow, HedgeCull);
		}
	}
	for (const TSharedPtr<FJsonObject>& S : J::Objs(Obj, TEXT("scatter")))
	{
		FVector2D Mn, Mx;
		if (!J::Rect(S, TEXT("rect_cm"), Mn, Mx)) continue;
		const FString Kind = J::Str(S, TEXT("kind"), TEXT("flowers"));
		const int32 Count = int32(J::Num(S, TEXT("count"), 100));
		const double Z = J::Num(S, TEXT("z"), 2);
		for (int32 i = 0; i < Count; ++i)
		{
			const FVector Pt(L2(FVector2D(Rng.R(Mn.X, Mx.X), Rng.R(Mn.Y, Mx.Y))), Z);
			if (Kind == TEXT("shrubs"))
			{
				ASWCityTrees::AddShrub(Inst, Pt, Rng.R(50, 120), Col::Leaf(Rng.I(4)), Rng.Next(), 40000);
			}
			else if (Kind == TEXT("grass"))
			{
				Inst.Add(P(EPrim::Blob), M(EMat::Foliage), Col::Meadow(), Xf(Pt, FVector(Rng.R(0.3, 0.6), Rng.R(0.3, 0.6), Rng.R(0.12, 0.25)), Rng.R(0, 360)), false, 30000);
			}
			else
			{
				const FLinearColor C = Rng.F() < 0.25 ? Col::Leaf(Rng.I(4)) : Col::Flower(Rng.I(6));
				Inst.Add(P(EPrim::Blob), M(EMat::Foliage), C, Xf(Pt, FVector(Rng.R(0.09, 0.2), Rng.R(0.09, 0.2), Rng.R(0.08, 0.16))), false, 25000);
			}
		}
	}
	// Things in the sky (city/VIBE.md 7: Isono's balloons, birds over every painting). No shadows: they are
	// small, high and would only add virtual-shadow-map pages.
	// "balloons": [[x_cm, y_cm, z_cm, colour index], ...]: striped hot-air balloon, ~16 m tall.
	for (const TSharedPtr<FJsonValue>& V : J::Arr(Obj, TEXT("balloons")) ? *J::Arr(Obj, TEXT("balloons")) : TArray<TSharedPtr<FJsonValue>>())
	{
		const TArray<double> Bv = J::Nums(V.IsValid() ? &V->AsArray() : nullptr);
		if (Bv.Num() < 3) continue;
		const FVector C = L(Bv[0], Bv[1], Bv[2]);
		const int32 Ci = Bv.Num() > 3 ? int32(Bv[3]) : 0;
		static const FColor Env[][3] = {{FColor(222, 64, 52), FColor(246, 200, 64), FColor(80, 160, 90)},
										 {FColor(246, 206, 70), FColor(74, 150, 196), FColor(232, 110, 60)},
										 {FColor(240, 240, 232), FColor(214, 90, 140), FColor(96, 170, 120)}};
		const FColor* E = Env[((Ci % 3) + 3) % 3];
		const double Yaw = Rng.R(0, 360);
		// envelope: lower body, a contrasting belt, crown; then the narrowing skirt and the basket on ropes
		// body, then three thin full-height slabs crossing the centre: their caps poke through the body as six
		// vertical gore stripes (Isono's balloons; horizontal bands read as a hamburger)
		Inst.Add(P(EPrim::Blob), M(EMat::Fabric), FLinearColor(E[0]), Xf(C, FVector(7.0, 7.0, 8.2), Yaw), false, 0.0);
		for (int32 k = 0; k < 3; ++k)
		{
			Inst.Add(P(EPrim::Blob), M(EMat::Fabric), FLinearColor(k == 1 ? E[2] : E[1]), Xf(C, FVector(7.12, 1.5, 8.3), Yaw + 60 * k), false, 0.0);
		}
		Inst.Add(P(EPrim::Cone), M(EMat::Fabric), FLinearColor(E[0]), FTransform(FRotator(180, Yaw, 0), C + FVector(0, 0, -420), FVector(7.6, 7.6, 3.4)), false, 0.0);
		Inst.Add(P(EPrim::Cube), M(EMat::Timber), Col::Bamboo(), Xf(C + FVector(0, 0, -1000), FVector(1.3, 1.3, 1.0), Yaw), false, 0.0);
		for (int32 k = 0; k < 4; ++k)
		{
			const double A = FMath::DegreesToRadians(Yaw + 45 + 90 * k);
			const FVector Top = C + FVector(FMath::Cos(A) * 160, FMath::Sin(A) * 160, -770), Bot = C + FVector(FMath::Cos(A) * 60, FMath::Sin(A) * 60, -950);
			const FVector D = Top - Bot;
			Inst.Add(P(EPrim::Cylinder), M(EMat::Metal), Col::Metal(), FTransform(FRotationMatrix::MakeFromZ(D.GetSafeNormal()).Rotator(), Bot, FVector(0.04, 0.04, D.Size() / 100)), false, 0.0);
		}
	}
	// "birds": [[x_cm, y_cm, z_cm, count, spread_cm], ...]: a loose flock of small dark V shapes.
	for (const TSharedPtr<FJsonValue>& V : J::Arr(Obj, TEXT("birds")) ? *J::Arr(Obj, TEXT("birds")) : TArray<TSharedPtr<FJsonValue>>())
	{
		const TArray<double> Fv = J::Nums(V.IsValid() ? &V->AsArray() : nullptr);
		if (Fv.Num() < 3) continue;
		const FVector C = L(Fv[0], Fv[1], Fv[2]);
		const int32 N = Fv.Num() > 3 ? int32(Fv[3]) : 12;
		const double Sp = Fv.Num() > 4 ? Fv[4] : 2500.0;
		const double Heading = Rng.R(0, 360);
		for (int32 i = 0; i < N; ++i)
		{
			const FVector Pb = C + FVector(Rng.R(-1, 1) * Sp, Rng.R(-1, 1) * Sp * 0.6, Rng.R(-0.25, 0.25) * Sp);
			const double Yw = Heading + Rng.R(-15, 15), Flap = Rng.R(10, 30), Wing = Rng.R(28, 40);
			for (int32 s = -1; s <= 1; s += 2)
			{
				// each wing a thin slab hinged at the body, raised by Flap degrees
				const FRotator R(0, Yw, s * Flap);
				const FVector Off = R.RotateVector(FVector(0, s * Wing * 0.5, 0));
				Inst.Add(P(EPrim::Cube), M(EMat::Plain), Srgb(46, 44, 42), FTransform(R, Pb + Off, FVector(0.12, Wing / 100, 0.02)), false, 60000);
			}
		}
	}
	AddInstances(Inst);
	return true;
}

// =============================================================================================
// Lane

bool ASWCityLane::Build(const TSharedPtr<FJsonObject>& Obj, FString& Error)
{
	FVector2D Mn, Mx;
	if (!J::Rect(Obj, TEXT("rect_cm"), Mn, Mx))
	{
		Error = TEXT("rect_cm missing");
		return false;
	}
	Mn = L2(Mn);
	Mx = L2(Mx);
	const bool bAlongX = (Mx.X - Mn.X) >= (Mx.Y - Mn.Y);
	const double Top = 8.0 + J::Num(Obj, TEXT("z_bias"), 0.0);
	const bool bRunnel = J::Bool(Obj, TEXT("runnel"));
	FSWMeshBuilder B;
	const int32 Stone = B.Slot(EMat::PermeableStone, Srgb(192, 172, 142));
	const int32 MossS = B.Slot(EMat::Moss, Col::Moss());
	const int32 Edge = B.Slot(EMat::PermeableStone, Col::StoneDark());
	const int32 WaterS = B.Slot(EMat::Water, Col::Water());

	// along-axis helpers: a = along, c = across
	auto Box2 = [&](int32 S, double A0, double A1, double C0, double C1, double Z0, double Z1)
	{
		if (bAlongX) B.Box(S, FVector(A0, C0, Z0), FVector(A1, C1, Z1));
		else B.Box(S, FVector(C0, A0, Z0), FVector(C1, A1, Z1));
	};
	const double A0 = bAlongX ? Mn.X : Mn.Y, A1 = bAlongX ? Mx.X : Mx.Y;
	const double C0 = bAlongX ? Mn.Y : Mn.X, C1 = bAlongX ? Mx.Y : Mx.X;
	const double Cm = (C0 + C1) * 0.5 + J::Num(Obj, TEXT("runnel_offset_cm"), 0.0);
	const double Width = C1 - C0;

	if (bRunnel)
	{
		const double Hw = 30.0;
		Box2(Stone, A0, A1, C0, Cm - Hw - 25, 0, Top);
		Box2(Stone, A0, A1, Cm + Hw + 25, C1, 0, Top);
		Box2(Edge, A0, A1, Cm - Hw - 25, Cm - Hw, 0, Top + 6);
		Box2(Edge, A0, A1, Cm + Hw, Cm + Hw + 25, 0, Top + 6);
		Box2(WaterS, A0, A1, Cm - Hw, Cm + Hw, 0, Top - 3);
	}
	else
	{
		Box2(Stone, A0, A1, C0, C1, 0, Top);
	}
	FRng Rng(Seed);
	if (Width > 1200)
	{
		// soft verges with low planting either side, 1.6 m in from the building line
		Box2(MossS, A0, A1, C0 + 60, C0 + 220, 0, Top + 4);
		Box2(MossS, A0, A1, C1 - 220, C1 - 60, 0, Top + 4);
		FInstances Inst;
		for (double A = A0 + 300; A < A1 - 300; A += Rng.R(160, 320))
		{
			for (int32 Side = 0; Side < 2; ++Side)
			{
				if (Rng.F() < 0.3) continue;
				const double Cc = Side ? Rng.R(C1 - 200, C1 - 80) : Rng.R(C0 + 80, C0 + 200);
				const FVector Pt = bAlongX ? FVector(A, Cc, Top + 4) : FVector(Cc, A, Top + 4);
				const FLinearColor Tint = Rng.F() < 0.4 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4));
				ASWCityTrees::AddShrub(Inst, Pt, Rng.R(35, 70), Tint, Rng.Next(), 30000);
			}
		}
		AddInstances(Inst);
	}
	AddMesh(B, false);
	return true;
}

// =============================================================================================
// Path

bool ASWCityPath::Build(const TSharedPtr<FJsonObject>& Obj, FString& Error)
{
	TArray<FVector2D> Pts = J::Points(Obj, TEXT("polyline_cm"));
	if (Pts.Num() < 2)
	{
		Error = TEXT("polyline_cm missing");
		return false;
	}
	for (FVector2D& Pt : Pts) Pt = L2(Pt);
	const FString Type = J::Str(Obj, TEXT("type"), TEXT("trail"));
	const double W = J::Num(Obj, TEXT("width_cm"), 300);
	FSWMeshBuilder B;
	FInstances Inst;
	FRng Rng(Seed);
	if (Type == TEXT("boardwalk"))
	{
		const double Deck = J::Num(Obj, TEXT("deck_cm"), 60);
		const int32 Wood = B.Slot(EMat::Timber, Col::Timber());
		const int32 Dark = B.Slot(EMat::Timber, Col::TimberDark());
		B.Ribbon(Wood, Pts, W, Deck - 12, Deck);
		B.Ribbon(Dark, Pts, 10, Deck + 90, Deck + 100, W * 0.5 - 6);
		B.Ribbon(Dark, Pts, 10, Deck + 90, Deck + 100, -W * 0.5 + 6);
		const TArray<FVector2D> Posts = Resample(Pts, 250);
		for (int32 i = 0; i < Posts.Num(); ++i)
		{
			const FVector2D D = (Posts[FMath::Min(i + 1, Posts.Num() - 1)] - Posts[FMath::Max(i - 1, 0)]).GetSafeNormal();
			const FVector2D Nn(-D.Y, D.X);
			for (int32 Side = -1; Side <= 1; Side += 2)
			{
				const FVector2D Q = Posts[i] + Nn * Side * (W * 0.5 - 6);
				B.Box(Dark, FVector(Q - FVector2D(6, 6), -5), FVector(Q + FVector2D(6, 6), Deck + 100));
			}
			if (i % 5 == 2 && Rng.F() < 0.6)
			{
				// planter box hung on the rail with trailing plants
				const FVector2D Q = Posts[i] + Nn * (Rng.F() < 0.5 ? -1 : 1) * (W * 0.5 + 15);
				B.Box(Wood, FVector(Q - FVector2D(30, 30), Deck + 50), FVector(Q + FVector2D(30, 30), Deck + 85));
				ASWCityTrees::AddShrub(Inst, FVector(Q, Deck + 85), 40, Rng.F() < 0.4 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4)), Rng.Next(), 30000);
			}
		}
		const FVector2D A = Pts[0], Bp = Pts.Last();
		AddCollisionBox(FVector(A.ComponentMin(Bp) - FVector2D(W), Deck - 12), FVector(A.ComponentMax(Bp) + FVector2D(W), Deck));
	}
	else
	{
		const int32 Gravel = B.Slot(EMat::Path, Col::Gravel());
		const int32 Edge = B.Slot(EMat::PermeableStone, Col::StoneDark());
		const double Z = J::Num(Obj, TEXT("z_cm"), 11);
		B.Ribbon(Gravel, Pts, W, 0, Z);
		B.Ribbon(Edge, Pts, 14, 0, Z + 4, W * 0.5 + 7);
		B.Ribbon(Edge, Pts, 14, 0, Z + 4, -W * 0.5 - 7);
	}
	AddMesh(B, Type == TEXT("boardwalk"));
	AddInstances(Inst);
	return true;
}

// =============================================================================================
// Water

bool ASWCityWater::Build(const TSharedPtr<FJsonObject>& Obj, FString& Error)
{
	const FString Type = J::Str(Obj, TEXT("type"), TEXT("creek"));
	FSWMeshBuilder B;
	FInstances Inst;
	FRng Rng(Seed);
	const int32 WaterS = B.Slot(EMat::Water, Col::Water());
	const int32 Bank = B.Slot(EMat::Moss, Col::Moss());
	const int32 SandS = B.Slot(EMat::PermeableStone, Col::Sand());
	const int32 Wood = B.Slot(EMat::Timber, Col::Timber());
	const int32 Dark = B.Slot(EMat::Timber, Col::TimberDark());

	// Optional ellipse to keep banks out of (the pond the creek runs into).
	FVector2D SkipC(0, 0);
	double SkipRx = 0, SkipRy = 0;
	if (const TArray<double> Sk = J::Nums(Obj, TEXT("skip_ellipse_cm")); Sk.Num() >= 4)
	{
		SkipC = L2(FVector2D(Sk[0], Sk[1]));
		SkipRx = Sk[2];
		SkipRy = Sk[3];
	}
	auto Skipped = [&](const FVector2D& Q)
	{
		if (SkipRx <= 0) return false;
		const FVector2D D = (Q - SkipC) / FVector2D(SkipRx, SkipRy);
		return D.SizeSquared() < 1.0;
	};
	auto Reeds = [&](const FVector2D& C, int32 N, double Spread)
	{
		for (int32 k = 0; k < N; ++k)
		{
			const FVector2D Q = C + FVector2D(Rng.R(-Spread, Spread), Rng.R(-Spread, Spread));
			const FLinearColor T = Rng.F() < 0.3 ? Srgb(170, 160, 90) : Srgb(96, 130, 60);
			Inst.Add(P(EPrim::Reed), M(EMat::Foliage), T, Xf(FVector(Q, 0), FVector(Rng.R(0.8, 1.6), Rng.R(0.8, 1.6), Rng.R(0.9, 1.9)), Rng.R(0, 360), Rng.R(-10, 10), Rng.R(-10, 10)), false, 30000);
		}
	};

	if (Type == TEXT("pond"))
	{
		const TArray<double> E = J::Nums(Obj, TEXT("ellipse_cm")); // cx cy rx ry
		if (E.Num() < 4)
		{
			Error = TEXT("ellipse_cm missing");
			return false;
		}
		const FVector2D C = L2(FVector2D(E[0], E[1]));
		const double Rx = E[2], Ry = E[3];
		B.Prism(WaterS, Ellipse(C, Rx, Ry, 64), 0, 9);
		B.Prism(SandS, Ellipse(C, Rx + 350, Ry + 350, 64), 0, 6);
		// stones and reeds around the rim (reeds on the east, the wild side)
		for (int32 i = 0; i < 90; ++i)
		{
			const double A = 2 * PI * i / 90 + Rng.R(-0.02, 0.02);
			const FVector2D D(FMath::Cos(A), FMath::Sin(A));
			const FVector2D Q = C + D * FVector2D(Rx + Rng.R(-30, 90), Ry + Rng.R(-30, 90));
			if (Rng.F() < 0.6)
				Inst.Add(P(EPrim::Stone), M(EMat::PermeableStone), Rng.F() < 0.5 ? Col::Stone() : Col::StoneDark(), Xf(FVector(Q, 0), FVector(Rng.R(0.25, 0.7)), Rng.R(0, 360)), true, 60000);
			if (D.X > 0.2 && Rng.F() < 0.7) Reeds(C + D * FVector2D(Rx - 80, Ry - 80), 14, 120);
		}
		// lily pads in the north and south ends
		for (int32 i = 0; i < 70; ++i)
		{
			const double A = Rng.R(0, 2 * PI), R = Rng.R(0.55, 0.92);
			const FVector2D Q = C + FVector2D(FMath::Cos(A) * Rx * R, FMath::Sin(A) * Ry * R);
			if (FMath::Abs(FMath::Sin(A)) < 0.6) continue;
			Inst.Add(P(EPrim::Disc), M(EMat::Foliage), Col::Leaf(Rng.I(4)), Xf(FVector(Q, 9), FVector(Rng.R(0.6, 1.4), Rng.R(0.6, 1.4), 0.3)), false, 30000);
			if (Rng.F() < 0.2)
				Inst.Add(P(EPrim::Blob), M(EMat::Foliage), Col::Flower(Rng.F() < 0.5 ? 1 : 3), Xf(FVector(Q, 14), FVector(0.1, 0.1, 0.07)), false, 20000);
		}
		// swim dock off the west shore + a floating raft
		const double DeckZ = 45;
		const FVector2D D0 = C + FVector2D(-Rx - 200, -400), D1 = C + FVector2D(-Rx * 0.35, -400);
		B.Box(Wood, FVector(D0.X, D0.Y - 150, DeckZ - 10), FVector(D1.X, D1.Y + 150, DeckZ));
		for (double X = D0.X; X <= D1.X; X += 250)
		{
			B.Box(Dark, FVector(X - 8, D0.Y - 158, -10), FVector(X + 8, D0.Y - 142, DeckZ));
			B.Box(Dark, FVector(X - 8, D0.Y + 142, -10), FVector(X + 8, D0.Y + 158, DeckZ));
		}
		B.Pole(B.Slot(EMat::Metal, Col::Brass()), FVector(D1.X - 10, D1.Y - 40, -20), FVector(D1.X - 10, D1.Y - 40, DeckZ + 90), 4);
		B.Pole(B.Slot(EMat::Metal, Col::Brass()), FVector(D1.X - 10, D1.Y + 40, -20), FVector(D1.X - 10, D1.Y + 40, DeckZ + 90), 4);
		const FVector2D R0 = C + FVector2D(Rx * 0.1, 900);
		B.Cylinder(Wood, FVector(R0, 5), 260, 260, 25, 10);
		AddCollisionBox(FVector(D0.X, D0.Y - 150, DeckZ - 10), FVector(D1.X, D1.Y + 150, DeckZ));
	}
	else // creek or runnel
	{
		TArray<FVector2D> Pts = J::Points(Obj, TEXT("centerline_cm"));
		if (Pts.Num() < 2)
		{
			Error = TEXT("centerline_cm missing");
			return false;
		}
		for (FVector2D& Pt : Pts) Pt = L2(Pt);
		const double W = J::Num(Obj, TEXT("width_cm"), 800);
		// smooth the centreline a bit (Chaikin) so the creek meanders rather than kinks
		for (int32 It = 0; It < 3; ++It)
		{
			TArray<FVector2D> S;
			S.Add(Pts[0]);
			for (int32 i = 0; i + 1 < Pts.Num(); ++i)
			{
				S.Add(Pts[i] * 0.75 + Pts[i + 1] * 0.25);
				S.Add(Pts[i] * 0.25 + Pts[i + 1] * 0.75);
			}
			S.Add(Pts.Last());
			Pts = S;
		}
		B.Ribbon(WaterS, Pts, W, 0, 7);
		// Banks: split into runs outside the skip ellipse.
		const TArray<FVector2D> Fine = Resample(Pts, 200);
		TArray<FVector2D> Run;
		auto Flush = [&]()
		{
			if (Run.Num() >= 2)
			{
				B.Ribbon(Bank, Run, 220, 0, 16, W * 0.5 + 110);
				B.Ribbon(Bank, Run, 220, 0, 16, -W * 0.5 - 110);
				B.Ribbon(SandS, Run, 60, 0, 9, W * 0.5 + 10);
				B.Ribbon(SandS, Run, 60, 0, 9, -W * 0.5 - 10);
			}
			Run.Reset();
		};
		for (int32 i = 0; i < Fine.Num(); ++i)
		{
			const FVector2D D = (Fine[FMath::Min(i + 1, Fine.Num() - 1)] - Fine[FMath::Max(i - 1, 0)]).GetSafeNormal();
			const FVector2D Nn(-D.Y, D.X);
			const bool bSkip = Skipped(Fine[i] + Nn * (W * 0.5 + 200)) || Skipped(Fine[i] - Nn * (W * 0.5 + 200));
			if (bSkip) { Flush(); continue; }
			Run.Add(Fine[i]);
			for (int32 Side = -1; Side <= 1; Side += 2)
			{
				if (Rng.F() < 0.55)
				{
					const FVector2D Q = Fine[i] + Nn * Side * (W * 0.5 + Rng.R(-20, 60));
					Inst.Add(P(EPrim::Stone), M(EMat::PermeableStone), Rng.F() < 0.5 ? Col::Stone() : Col::StoneDark(), Xf(FVector(Q, 0), FVector(Rng.R(0.2, 0.6)), Rng.R(0, 360)), true, 60000);
				}
				if (Rng.F() < 0.35) Reeds(Fine[i] + Nn * Side * (W * 0.5 - 40), 10, 90);
			}
			if (Rng.F() < 0.15)
			{
				const FVector2D Q = Fine[i] + Nn * Rng.R(-W * 0.3, W * 0.3);
				Inst.Add(P(EPrim::Stone), M(EMat::PermeableStone), Col::StoneDark(), Xf(FVector(Q, -10), FVector(Rng.R(0.3, 0.6), Rng.R(0.3, 0.6), 0.5), Rng.R(0, 360)), true, 60000);
			}
		}
		Flush();
	}
	AddMesh(B, Type == TEXT("pond"));
	AddInstances(Inst);
	return true;
}

// =============================================================================================
// Trees

namespace
{
/** Tree silhouettes. Every crown is built from Puff cushions (flat undersides), so canopies read as layered
 *  Ghibli-style clouds of foliage rather than single blobs. */
enum class ETreeShape : uint8
{
	Layered,   // broadleaf: 3 tiers of cushions, darker below, lighter on top (oak, maple, chestnut, shade)
	Spreading, // wide umbrella of 2 flat tiers (cherry, jacaranda, fig)
	Willow,    // dome + rings of hanging fringe curtains reaching near the ground
	Columnar,  // narrow stacked cushions (birch, poplar, pawpaw)
	Conifer,   // stacked cone skirts (cypress)
	Bamboo,    // clump of culms with leaf sprays
	Orchard,   // small round crown on a short trunk, fruit / blossom dots
	Small,     // roof / planter tree: 4-6 cushions
};

struct FSpecies
{
	const TCHAR* Name;
	double TrunkH, TrunkR, CrownR, CrownH; // cm (CrownH = crown height)
	ETreeShape Shape;
	FColor Leaf[3];  // dark, mid, light
	FColor Bloom;    // blossom / fruit colour
	float BloomFrac; // fraction of cushions in bloom (Spreading/Layered) or fruit density (Orchard)
	FColor BarkC;
};

using TS = ETreeShape;
const FSpecies GSpecies[] = {
	{TEXT("oak"), 380, 34, 560, 560, TS::Layered, {FColor(50, 88, 40), FColor(70, 112, 50), FColor(104, 140, 62)}, FColor(0, 0, 0), 0.f, FColor(92, 74, 58)},
	{TEXT("maple"), 360, 26, 470, 560, TS::Layered, {FColor(70, 108, 46), FColor(98, 140, 60), FColor(140, 166, 70)}, FColor(196, 96, 52), 0.0f, FColor(104, 86, 70)},
	{TEXT("flowering cherry"), 240, 22, 480, 300, TS::Spreading, {FColor(214, 140, 166), FColor(240, 174, 196), FColor(250, 206, 218)}, FColor(110, 146, 70), 0.18f, FColor(90, 60, 52)},
	{TEXT("willow"), 280, 40, 560, 400, TS::Willow, {FColor(88, 120, 52), FColor(112, 142, 60), FColor(140, 162, 72)}, FColor(0, 0, 0), 0.f, FColor(96, 82, 64)},
	{TEXT("fig"), 160, 24, 380, 260, TS::Spreading, {FColor(52, 96, 46), FColor(70, 118, 56), FColor(94, 136, 62)}, FColor(120, 70, 110), 0.f, FColor(150, 140, 126)},
	{TEXT("persimmon"), 200, 20, 300, 320, TS::Orchard, {FColor(76, 116, 48), FColor(96, 136, 58), FColor(124, 156, 66)}, FColor(238, 128, 36), 1.f, FColor(80, 64, 52)},
	{TEXT("pawpaw"), 180, 16, 200, 420, TS::Columnar, {FColor(56, 104, 46), FColor(74, 124, 54), FColor(100, 142, 60)}, FColor(0, 0, 0), 0.f, FColor(110, 96, 84)},
	{TEXT("chestnut"), 380, 36, 600, 560, TS::Layered, {FColor(48, 86, 40), FColor(66, 106, 46), FColor(92, 128, 58)}, FColor(240, 230, 200), 0.22f, FColor(84, 66, 52)},
	{TEXT("fruit"), 160, 18, 280, 260, TS::Orchard, {FColor(84, 128, 56), FColor(104, 146, 64), FColor(132, 164, 72)}, FColor(250, 236, 238), 0.f, FColor(96, 80, 66)},
	{TEXT("apple"), 160, 18, 290, 260, TS::Orchard, {FColor(78, 122, 52), FColor(98, 140, 60), FColor(128, 160, 70)}, FColor(204, 46, 40), 1.f, FColor(96, 80, 66)},
	{TEXT("birch"), 480, 16, 230, 620, TS::Columnar, {FColor(98, 140, 58), FColor(126, 162, 68), FColor(160, 184, 84)}, FColor(0, 0, 0), 0.f, FColor(228, 224, 214)},
	{TEXT("poplar"), 300, 22, 210, 1050, TS::Columnar, {FColor(60, 100, 44), FColor(84, 124, 52), FColor(116, 148, 62)}, FColor(0, 0, 0), 0.f, FColor(130, 120, 104)},
	{TEXT("cypress"), 60, 18, 170, 1000, TS::Conifer, {FColor(34, 66, 40), FColor(44, 80, 46), FColor(58, 96, 52)}, FColor(0, 0, 0), 0.f, FColor(90, 72, 58)},
	{TEXT("shade"), 440, 44, 780, 600, TS::Layered, {FColor(54, 92, 42), FColor(76, 116, 52), FColor(106, 142, 62)}, FColor(0, 0, 0), 0.f, FColor(96, 80, 64)},
	{TEXT("roof"), 130, 12, 180, 200, TS::Small, {FColor(70, 116, 52), FColor(92, 138, 62), FColor(124, 160, 70)}, FColor(214, 80, 150), 0.12f, FColor(98, 80, 62)},
	{TEXT("jacaranda"), 260, 24, 500, 300, TS::Spreading, {FColor(124, 98, 182), FColor(150, 122, 204), FColor(176, 150, 222)}, FColor(96, 136, 64), 0.2f, FColor(96, 80, 66)},
	{TEXT("copse"), 300, 36, 560, 520, TS::Small, {FColor(48, 84, 40), FColor(66, 104, 46), FColor(92, 126, 56)}, FColor(0, 0, 0), 0.f, FColor(88, 72, 58)},
	// vibe pass: red-flowering spreader (flame tree / poinciana), the red crowns in every Isono painting
	{TEXT("flame"), 260, 26, 520, 300, TS::Spreading, {FColor(58, 108, 46), FColor(78, 128, 54), FColor(102, 146, 60)}, FColor(244, 92, 56), 0.6f, FColor(100, 82, 66)},
	{TEXT("bamboo"), 750, 4, 110, 0, TS::Bamboo, {FColor(92, 138, 52), FColor(116, 156, 60), FColor(146, 174, 72)}, FColor(150, 164, 76), 0.f, FColor(150, 162, 80)},
};

const FSpecies& FindSpecies(const FString& Name)
{
	for (const FSpecies& S : GSpecies)
	{
		if (Name.Equals(S.Name, ESearchCase::IgnoreCase)) return S;
	}
	if (Name.Contains(TEXT("cherry"))) return GSpecies[2];
	return GSpecies[0];
}

FLinearColor Shade(const FColor& C, float K)
{
	return FLinearColor(FColor(uint8(FMath::Clamp(C.R * K, 0.f, 255.f)), uint8(FMath::Clamp(C.G * K, 0.f, 255.f)), uint8(FMath::Clamp(C.B * K, 0.f, 255.f))));
}

/** One cushion of foliage (Puff) of radius R, flattened by Vz. */
void Cushion(ASWCityActor::FInstances& Out, const FVector& C, double R, double Vz, const FLinearColor& T, FRng& Rng, bool bShadow = true, double Cull = 0.0)
{
	Out.Add(P(EPrim::Puff), M(EMat::Foliage), T, Xf(C, FVector(R * Rng.R(0.9, 1.1) / 100, R * Rng.R(0.9, 1.1) / 100, R * Vz / 100), Rng.R(0, 360)), bShadow, Cull);
}
} // namespace

void ASWCityTrees::AddShrub(FInstances& Out, const FVector& Base, double Radius, const FLinearColor& Tint, uint32 InSeed, double CullCm)
{
	FRng Rng(InSeed);
	// A flowering tint becomes a green cushion carrying a cap of blossom; leafy shrubs are 2-3 cushions.
	const bool bFlower = Tint.G < Tint.R * 0.9f || (Tint.R > 0.5f && Tint.G > 0.5f && Tint.B > 0.35f);
	const int32 N = 2 + Rng.I(2);
	for (int32 i = 0; i < N; ++i)
	{
		const double R = Radius * Rng.R(0.6, 1.0);
		const FVector Off(Rng.R(-0.5, 0.5) * Radius, Rng.R(-0.5, 0.5) * Radius, R * 0.3);
		const FLinearColor T = bFlower ? Col::Leaf(Rng.I(4)) : Tint;
		Out.Add(P(EPrim::Puff), M(EMat::Foliage), T, Xf(Base + Off, FVector(R / 100, R / 100, R * 0.85 / 100), Rng.R(0, 360)), Radius > 60, CullCm);
		if (bFlower)
		{
			Out.Add(P(EPrim::Puff), M(EMat::Foliage), Tint, Xf(Base + Off + FVector(Rng.R(-0.2, 0.2) * R, Rng.R(-0.2, 0.2) * R, R * 0.6), FVector(R * 0.7 / 100, R * 0.7 / 100, R * 0.35 / 100), Rng.R(0, 360)), false, CullCm);
		}
	}
}

void ASWCityTrees::AddTree(FInstances& Out, const FString& InName, const FVector& Base, double Scale, uint32 InSeed)
{
	// "<species>@far": landscape tree seen only from far away, a trunk plus one crown cushion (2 instances)
	FString SpeciesName = InName;
	const bool bDistant = SpeciesName.RemoveFromEnd(TEXT("@far"));
	const FSpecies& S = FindSpecies(SpeciesName);
	FRng Rng(InSeed);
	const double K = Scale * Rng.R(0.85, 1.15);
	const double H = S.TrunkH * K, TR = S.TrunkR * K, CR = S.CrownR * K, CH = S.CrownH * K;
	const FLinearColor BarkT(S.BarkC);
	const double Lean = Rng.R(-4, 4);
	const double Yaw0 = Rng.R(0, 360);
	// per-tree brightness so rows don't look cloned; quantised to 3 levels because every distinct tint is its own
	// instanced component (draw call)
	static const float Lights[3] = {0.92f, 1.0f, 1.08f};
	const float Light = Lights[Rng.I(3)];
	auto LeafT = [&](int32 Tier) { return Shade(S.Leaf[FMath::Clamp(Tier, 0, 2)], Light); };
	auto Limb = [&](const FVector& From, double Yaw, double TiltDeg, double Len, double R)
	{
		const double Tilt = FMath::DegreesToRadians(TiltDeg), Yr = FMath::DegreesToRadians(Yaw);
		const FVector Dir(FMath::Sin(Tilt) * FMath::Cos(Yr), FMath::Sin(Tilt) * FMath::Sin(Yr), FMath::Cos(Tilt));
		Out.Add(P(EPrim::Trunk), M(EMat::Bark), BarkT, FTransform(FRotationMatrix::MakeFromZ(Dir).Rotator(), From, FVector(R / 50, R / 50, Len / 100)));
		return From + Dir * Len;
	};

	if (S.Shape == TS::Bamboo)
	{
		// clump: culms leaning slightly outward, leaf sprays on the upper half
		const int32 Nc = 7 + Rng.I(5);
		const double Rc = 70 * K;
		for (int32 i = 0; i < Nc; ++i)
		{
			const double A = Rng.R(0, 2 * PI), Rr = Rc * FMath::Sqrt(Rng.F());
			const FVector B0 = Base + FVector(FMath::Cos(A) * Rr, FMath::Sin(A) * Rr, -5);
			const double Hc = H * Rng.R(0.7, 1.15);
			const double Tilt = 3 + 7 * Rr / FMath::Max(Rc, 1.0);
			const FVector Dir = FVector(FMath::Cos(A) * FMath::Sin(FMath::DegreesToRadians(Tilt)), FMath::Sin(A) * FMath::Sin(FMath::DegreesToRadians(Tilt)), FMath::Cos(FMath::DegreesToRadians(Tilt)));
			const double Rcm = Rng.R(3.0, 5.0) * FMath::Max(K, 0.6);
			Out.Add(P(EPrim::Cylinder), M(EMat::Timber), Shade(S.BarkC, Rng.F() < 0.5f ? 0.88f : 1.05f), FTransform(FRotationMatrix::MakeFromZ(Dir).Rotator(), B0, FVector(Rcm / 50, Rcm / 50, Hc / 100)));
			for (int32 l = 0; l < 2; ++l)
			{
				const FVector Pc = B0 + Dir * Hc * Rng.R(0.55, 1.0) + FVector(Rng.R(-50, 50), Rng.R(-50, 50), 0) * K;
				Out.Add(P(EPrim::Puff), M(EMat::Foliage), LeafT(Rng.I(3)), Xf(Pc, FVector(Rng.R(0.5, 0.8), Rng.R(0.3, 0.45), Rng.R(0.22, 0.32)) * K, Rng.R(0, 360)), true, 0.0);
			}
		}
		return;
	}

	if (bDistant)
	{
		Out.Add(P(EPrim::Trunk), M(EMat::Bark), BarkT, Xf(Base - FVector(0, 0, 10), FVector(TR / 50, TR / 50, (H + CH * 0.3) / 100), Yaw0));
		const bool bTall = S.Shape == TS::Columnar || S.Shape == TS::Conifer;
		const double R = bTall ? CR * 1.05 : CR * 0.95;
		Out.Add(P(EPrim::Puff), M(EMat::Foliage), LeafT(1), Xf(Base + FVector(0, 0, H + CH * (bTall ? 0.42 : 0.4)), FVector(R / 100, R / 100, (bTall ? CH * 0.55 : CH * 0.5) / 100), Rng.R(0, 360)));
		return;
	}
	// trunk
	const double TrunkLen = S.Shape == TS::Conifer ? H + CH * 0.3 : H + CH * 0.35;
	Out.Add(P(EPrim::Trunk), M(EMat::Bark), BarkT, Xf(Base - FVector(0, 0, 10), FVector(TR / 50, TR / 50, TrunkLen / 100), Yaw0, Lean, 0));

	switch (S.Shape)
	{
	case TS::Layered:
	case TS::Spreading:
	case TS::Small:
	{
		const bool bSpread = S.Shape == TS::Spreading;
		const int32 Tiers = 2; // two layered tiers: three read better close up but cost ~1.5 ms of shadow-map overdraw city-wide
		// visible limbs fanning into the lowest tier
		const int32 Limbs = S.Shape == TS::Small ? 0 : 3 + Rng.I(2);
		for (int32 i = 0; i < Limbs; ++i)
		{
			const double Yaw = Yaw0 + 360.0 * i / Limbs + Rng.R(-20, 20);
			Limb(Base + FVector(0, 0, H * Rng.R(0.75, 0.95)), Yaw, bSpread ? Rng.R(48, 62) : Rng.R(28, 42), CR * (bSpread ? 0.62 : 0.48) * Rng.R(0.85, 1.1), TR * 0.45);
		}
		for (int32 t = 0; t < Tiers; ++t)
		{
			const double Ft = Tiers > 1 ? double(t) / (Tiers - 1) : 0.0; // 0 bottom .. 1 top
			const double Z = H + CH * (bSpread ? 0.15 + 0.45 * Ft : 0.15 + 0.55 * Ft);
			const double Rt = CR * (bSpread ? 1.0 - 0.3 * Ft : 1.0 - 0.35 * Ft);
			const int32 Ring = S.Shape == TS::Small ? 3 : (t == 0 ? 6 : 4);
			const double Vz = bSpread ? 0.5 : 0.66;
			const int32 Tier = t == 0 ? 0 : 2;
			const FVector C = Base + FVector(Rng.R(-0.05, 0.05) * CR, Rng.R(-0.05, 0.05) * CR, Z);
			Cushion(Out, C, Rt * 0.6, Vz, LeafT(FMath::Min(Tier + 1, 2)), Rng);
			const double A0 = Rng.R(0, 2 * PI);
			for (int32 i = 0; i < Ring; ++i)
			{
				const double A = A0 + 2 * PI * i / Ring + Rng.R(-0.25, 0.25);
				const double Rad = Rt * Rng.R(0.5, 0.62);
				// red/orange blossom only on the top tier: from the street the lower tier is seen from below, in
				// shade, where red reads as brown rock (vibe pass, flame tree)
				const bool bRedBloom = S.Bloom.R > S.Bloom.G * 2;
				const bool bBloom = S.BloomFrac > 0 && Rng.F() < S.BloomFrac && !(bSpread && bRedBloom && t == 0);
				FLinearColor T = bBloom ? Shade(S.Bloom, Light) : LeafT(Tier);
				// flowering spreaders (cherry, jacaranda): the lower tier is leaf green; blossom from below read as brown rock
				if (bSpread && t == 0 && S.Bloom.G > S.Bloom.R) T = Shade(S.Bloom, Light * (i % 2 ? 0.85f : 1.0f));
				Cushion(Out, C + FVector(FMath::Cos(A) * Rad, FMath::Sin(A) * Rad, Rng.R(-0.08, 0.1) * CH), Rt * Rng.R(0.36, 0.48), Vz, T, Rng);
			}
		}
		break;
	}
	case TS::Willow:
	{
		// short leaning trunk, arching limbs, dome of cushions, then curtains of hanging fringes
		const FVector Top = Base + FVector(0, 0, H);
		for (int32 i = 0; i < 4; ++i) Limb(Top - FVector(0, 0, H * 0.15), Yaw0 + 90 * i + Rng.R(-20, 20), Rng.R(40, 58), CR * 0.55, TR * 0.45);
		const FVector C = Top + FVector(0, 0, CH * 0.45);
		Cushion(Out, C + FVector(0, 0, CH * 0.15), CR * 0.55, 0.55, LeafT(2), Rng);
		for (int32 i = 0; i < 6; ++i)
		{
			const double A = 2 * PI * i / 6 + Rng.R(-0.2, 0.2);
			Cushion(Out, C + FVector(FMath::Cos(A) * CR * 0.5, FMath::Sin(A) * CR * 0.5, -CH * 0.05), CR * 0.42, 0.5, LeafT(1), Rng);
		}
		// outer curtain: tangential fringe sheets round the rim, flaring out a little, hem ~0.6 m above ground
		const double Drop = (C.Z - Base.Z) - 60;
		for (int32 Ringi = 0; Ringi < 2; ++Ringi)
		{
			const int32 N = Ringi == 0 ? 16 : 9;
			const double Rr = CR * (Ringi == 0 ? 0.88 : 0.55);
			const double Wd = 2 * PI * Rr / N * 1.35;
			for (int32 i = 0; i < N; ++i)
			{
				const double A = 2 * PI * (i + (Ringi ? 0.5 : 0.0)) / N + Rng.R(-0.08, 0.08);
				const double Len = Drop * (Ringi == 0 ? Rng.R(0.8, 1.0) : Rng.R(0.6, 0.8));
				const FVector Pc = C + FVector(FMath::Cos(A) * Rr, FMath::Sin(A) * Rr, CH * (Ringi == 0 ? -0.05 : 0.1));
				// yaw: local +Y (the fringe's bow) points radially outward; roll flares the hem outward
				Out.Add(P(EPrim::Fringe), M(EMat::Foliage), LeafT(Ringi == 0 ? Rng.I(3) : 0),
					FTransform(FRotator(0, FMath::RadiansToDegrees(A) - 90, Ringi == 0 ? -7 : -3), Pc, FVector(Wd / 100, 1.0, Len / 100)));
			}
		}
		break;
	}
	case TS::Columnar:
	{
		const int32 Nl = 5;
		for (int32 i = 0; i < Nl; ++i)
		{
			const double F = double(i) / (Nl - 1);
			const double R = CR * (0.95 - 0.55 * F * F);
			const FVector Pc = Base + FVector(Rng.R(-0.12, 0.12) * CR, Rng.R(-0.12, 0.12) * CR, H + CH * (0.1 + 0.78 * F));
			Cushion(Out, Pc, R, CH / (Nl * R) * 1.25, LeafT(i < 2 ? 0 : (i < 4 ? 1 : 2)), Rng);
			if (i == 1 || i == 3)
			{
				const double A = Rng.R(0, 2 * PI);
				Cushion(Out, Pc + FVector(FMath::Cos(A), FMath::Sin(A), 0) * R * 0.55, R * 0.6, CH / (Nl * R) * 1.1, LeafT(1), Rng);
			}
		}
		break;
	}
	case TS::Conifer:
	{
		const int32 Nc = 3;
		for (int32 i = 0; i < Nc; ++i)
		{
			const double F = double(i) / Nc;
			const double R = CR * (1.0 - 0.3 * F);
			Out.Add(P(EPrim::Cone), M(EMat::Foliage), LeafT(i), Xf(Base + FVector(0, 0, H + CH * F * 0.85), FVector(R / 50, R / 50, CH * 0.42 / 100), Rng.R(0, 360)));
		}
		break;
	}
	case TS::Orchard:
	{
		for (int32 i = 0; i < 3; ++i) Limb(Base + FVector(0, 0, H * 0.85), Yaw0 + 120 * i + Rng.R(-15, 15), Rng.R(40, 55), CR * 0.5, TR * 0.5);
		const FVector C = Base + FVector(0, 0, H + CH * 0.45);
		Cushion(Out, C + FVector(0, 0, CH * 0.12), CR * 0.62, 0.7, LeafT(2), Rng);
		for (int32 i = 0; i < 4; ++i)
		{
			const double A = 2 * PI * i / 4 + Rng.R(-0.3, 0.3);
			Cushion(Out, C + FVector(FMath::Cos(A) * CR * 0.5, FMath::Sin(A) * CR * 0.5, -CH * 0.08), CR * 0.45, 0.6, LeafT(Rng.I(2)), Rng);
		}
		// fruit (or, for plain "fruit" trees, blossom flecks): small dots on the crown surface
		const bool bFruit = S.BloomFrac > 0.5f;
		const int32 Nf = bFruit ? 6 + Rng.I(4) : 5;
		for (int32 i = 0; i < Nf; ++i)
		{
			const double A = Rng.R(0, 2 * PI), El = Rng.R(-0.5, 0.6);
			const FVector D(FMath::Cos(A) * FMath::Cos(El), FMath::Sin(A) * FMath::Cos(El), FMath::Sin(El) * 0.6);
			const double Sz = bFruit ? 0.075 : 0.22;
			Out.Add(P(EPrim::Blob), M(EMat::Foliage), FLinearColor(S.Bloom), Xf(C + D * CR * 0.92, FVector(Sz * K, Sz * K, Sz * K * (bFruit ? 1.0 : 0.6))), false, 22000);
		}
		break;
	}
	default:
		break;
	}
}

bool ASWCityTrees::Build(const TSharedPtr<FJsonObject>& Obj, FString& Error)
{
	FInstances Inst;
	const TArray<TSharedPtr<FJsonValue>>* Trees = J::Arr(Obj, TEXT("trees"));
	if (!Trees)
	{
		Error = TEXT("trees missing");
		return false;
	}
	const double Z = J::Num(Obj, TEXT("z_cm"), 0);
	FRng Rng(Seed);
	for (const TSharedPtr<FJsonValue>& V : *Trees)
	{
		const TArray<TSharedPtr<FJsonValue>>* T = nullptr;
		if (!V.IsValid() || !V->TryGetArray(T) || T->Num() < 3) continue;
		const FVector Base(L2(FVector2D((*T)[0]->AsNumber(), (*T)[1]->AsNumber())), Z + (T->Num() > 4 ? (*T)[4]->AsNumber() : 0.0));
		const FString Sp = (*T)[2]->AsString();
		const double Sc = T->Num() > 3 ? (*T)[3]->AsNumber() : 1.0;
		if (Sp == TEXT("shrub"))
		{
			AddShrub(Inst, Base, 80 * Sc, Rng.F() < 0.35 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4)), Rng.Next(), 40000);
		}
		else
		{
			AddTree(Inst, Sp, Base, Sc, Rng.Next());
		}
	}
	// far landscape groups skip shadows: virtual shadow maps would otherwise draw kilometres of casters
	if (!J::Bool(Obj, TEXT("shadow"), true))
	{
		for (FInstanceBucket& Bk : Inst.Buckets) Bk.bShadow = false;
	}
	// "cull_cm": draw distance for the whole group (landscape trees are sub-pixel past ~1.5 km)
	if (const double Cull = J::Num(Obj, TEXT("cull_cm"), 0.0); Cull > 0)
	{
		for (FInstanceBucket& Bk : Inst.Buckets) Bk.CullCm = Bk.CullCm > 0 ? FMath::Min(Bk.CullCm, Cull) : Cull;
	}
	AddInstances(Inst);
	return true;
}

// =============================================================================================
// Street furniture (local frame: X forward, actor yaw from JSON)

bool ASWStreetFurniture::Build(const TSharedPtr<FJsonObject>& Obj, FString& Error)
{
	const FString Type = J::Str(Obj, TEXT("type"));
	FSWMeshBuilder B;
	FInstances Inst;
	FRng Rng(Seed);
	const int32 Wood = B.Slot(EMat::Timber, Col::Timber());
	const int32 Dark = B.Slot(EMat::Timber, Col::TimberDark());
	const int32 MetalS = B.Slot(EMat::Metal, Col::Metal());
	const int32 BrassS = B.Slot(EMat::Metal, Col::Brass());
	const int32 StoneS = B.Slot(EMat::PermeableStone, Col::Stone());
	const int32 Glow = B.Slot(EMat::Lantern, Col::Lantern());
	if (Type == TEXT("lantern_post"))
	{
		B.Cylinder(StoneS, FVector(0, 0, 0), 18, 15, 25, 8);
		B.Cylinder(MetalS, FVector(0, 0, 25), 5, 4, 300, 6);
		B.Beam(BrassS, FVector(0, 0, 300), FVector(45, 0, 312), 4, 4);
		B.Box(Glow, FVector(32, -12, 255), FVector(58, 12, 300));
		B.Cylinder(BrassS, FVector(45, 0, 300), 24, 3, 22, 6);
		// knee-height path light too (low glare)
		B.Box(Glow, FVector(-8, -8, 45), FVector(8, 8, 60));
		B.Cylinder(BrassS, FVector(0, 0, 60), 12, 2, 8, 6);
		Inst.Add(P(EPrim::Puff), M(EMat::Foliage), Col::Leaf(Rng.I(4)), Xf(FVector(0, 0, 14), FVector(0.45, 0.45, 0.3)), false, 25000);
		// hanging flower basket on a second arm
		B.Beam(BrassS, FVector(0, 0, 230), FVector(-40, 0, 230), 3, 3);
		B.Cylinder(B.Slot(EMat::Timber, Col::TimberDark()), FVector(-45, 0, 175), 14, 22, 22, 8);
		Inst.Add(P(EPrim::Puff), M(EMat::Foliage), Col::Flower(Rng.I(6)), Xf(FVector(-45, 0, 198), FVector(0.3, 0.3, 0.2)), false, 25000);
		Inst.Add(P(EPrim::Fringe), M(EMat::Foliage), Col::Leaf(Rng.I(4)), FTransform(FRotator(0, Rng.R(0, 360), 0), FVector(-45, 0, 195), FVector(0.5, 1.0, 0.7)), false, 25000);
	}
	else if (Type == TEXT("bench"))
	{
		B.Box(StoneS, FVector(-25, -85, 0), FVector(20, -65, 42));
		B.Box(StoneS, FVector(-25, 65, 0), FVector(20, 85, 42));
		for (int32 i = 0; i < 4; ++i) B.Box(Wood, FVector(-25 + i * 11.5, -95, 42), FVector(-16 + i * 11.5, 95, 47));
		B.OBox(Wood, FVector(-30, 0, 70), FVector(3, 95, 18), FRotator(0, 0, 0) + FRotator(-12, 0, 0));
		B.Box(Wood, FVector(-38, -120, 0), FVector(10, -95, 45));
		Inst.Add(P(EPrim::Blob), M(EMat::Foliage), Col::Flower(Rng.I(6)), Xf(FVector(-14, -108, 55), FVector(0.25, 0.22, 0.2)), false, 25000);
		Inst.Add(P(EPrim::Blob), M(EMat::Foliage), Col::Leaf(Rng.I(4)), Xf(FVector(-14, -108, 48), FVector(0.3, 0.25, 0.22)), false, 25000);
	}
	else if (Type == TEXT("bike_rack"))
	{
		B.Box(StoneS, FVector(-40, -230, 0), FVector(40, 230, 4));
		for (int32 i = 0; i < 5; ++i)
		{
			const double Y = -200 + i * 100;
			B.Pole(MetalS, FVector(-30, Y, 0), FVector(-30, Y, 75), 3, 6);
			B.Pole(MetalS, FVector(30, Y, 0), FVector(30, Y, 75), 3, 6);
			B.Pole(MetalS, FVector(-32, Y, 75), FVector(32, Y, 75), 3, 6);
			if (Rng.F() < 0.6)
			{
				// a parked bike: wheels on edge, coloured frame, saddle, bars
				const int32 Fr = B.Slot(EMat::Metal, Col::Flower(Rng.I(6)));
				const FVector Wf(70, Y + 14, 33), Wb(-70, Y + 14, 33);
				B.Pole(MetalS, Wf - FVector(0, 2.5, 0), Wf + FVector(0, 2.5, 0), 33, 10); // tyre ring
				B.Pole(MetalS, Wb - FVector(0, 2.5, 0), Wb + FVector(0, 2.5, 0), 33, 10);
				B.Pole(Fr, Wb, FVector(0, Y + 14, 70), 2.5, 4);
				B.Pole(Fr, FVector(0, Y + 14, 70), Wf, 2.5, 4);
				B.Pole(Fr, FVector(-20, Y + 14, 33), FVector(-25, Y + 14, 90), 2.5, 4);
				B.Pole(Fr, FVector(55, Y + 14, 95), Wf, 2.5, 4);
				B.Box(Dark, FVector(-35, Y + 7, 90), FVector(-15, Y + 21, 96));
				B.Pole(MetalS, FVector(55, Y - 10, 98), FVector(55, Y + 38, 98), 2, 4);
			}
		}
	}
	else if (Type == TEXT("outdoor_gym_station"))
	{
		B.Box(B.Slot(EMat::Path, Col::Gravel()), FVector(-250, -250, 0), FVector(250, 250, 4));
		for (int32 i = 0; i < 4; ++i)
		{
			const double X = (i & 1) ? 120 : -120, Y = (i & 2) ? 120 : -120;
			B.Box(Wood, FVector(X - 10, Y - 10, 0), FVector(X + 10, Y + 10, 250));
		}
		B.Box(Dark, FVector(-130, -130, 240), FVector(130, -110, 255));
		B.Box(Dark, FVector(-130, 110, 240), FVector(130, 130, 255));
		B.Pole(MetalS, FVector(-120, 0, 230), FVector(120, 0, 230), 3);
		B.Pole(Wood, FVector(-200, 180, 35), FVector(200, 180, 35), 14, 8);
		B.Pole(MetalS, FVector(-60, -60, 110), FVector(60, -60, 110), 3);
		B.Pole(MetalS, FVector(-60, -10, 110), FVector(60, -10, 110), 3);
	}
	else if (Type == TEXT("wayfinding_totem"))
	{
		B.Box(StoneS, FVector(-35, -25, 0), FVector(35, 25, 30));
		B.Box(Wood, FVector(-12, -18, 30), FVector(12, 18, 260));
		for (int32 i = 0; i < 3; ++i)
		{
			B.OBox(BrassS, FVector(0, 0, 220 - i * 32), FVector(55, 2, 11), FRotator(0, -30 + i * 45, 0));
		}
		B.Box(Dark, FVector(-25, -25, 260), FVector(25, 25, 268));
		ASWCityTrees::AddShrub(Inst, FVector(0, 0, 268), 28, Col::Flower(Rng.I(6)), Rng.Next(), 25000);
	}
	else if (Type == TEXT("water_fountain"))
	{
		B.Cylinder(StoneS, FVector(0, 0, 0), 70, 60, 70, 12);
		B.Cylinder(B.Slot(EMat::Water, Col::Water()), FVector(0, 0, 70), 52, 52, 2, 12);
		B.Cylinder(StoneS, FVector(0, 0, 0), 18, 14, 110, 8);
		B.Beam(BrassS, FVector(0, 0, 105), FVector(25, 0, 98), 4, 4);
		B.Cylinder(StoneS, FVector(110, 0, 0), 30, 26, 35, 8); // low dog/kid basin
	}
	else if (Type == TEXT("mural_wall"))
	{
		// local frame: wall along Y, facing +X; wall_w_cm wide, wall_h_cm high
		const double W = J::Num(Obj, TEXT("wall_w_cm"), 1200), H = J::Num(Obj, TEXT("wall_h_cm"), 900);
		const TArray<FLinearColor> Pal = J::Palette(Obj);
		auto C = [&](int32 i) { return Pal.Num() ? Pal[i % Pal.Num()] : Col::Flower(i); };
		// painted landscape: sky, sun, three rows of rolling hills, a meadow of flowers, a palette frame
		const int32 Sky = B.Slot(EMat::Fabric, Srgb(150, 196, 222));
		const int32 SkyLo = B.Slot(EMat::Fabric, Srgb(246, 214, 170));
		B.Box(Sky, FVector(0, -W / 2, H * 0.45), FVector(4, W / 2, H));
		B.Box(SkyLo, FVector(0, -W / 2, 60), FVector(4, W / 2, H * 0.45));
		B.Ellipsoid(B.Slot(EMat::Fabric, Srgb(250, 200, 80)), FVector(4, W * 0.22, H * 0.7), FVector(3, H * 0.13, H * 0.13), 16, 8);
		const FLinearColor Hills[3] = {Srgb(120, 160, 110), Srgb(86, 140, 90), Srgb(60, 112, 74)};
		for (int32 Row = 0; Row < 3; ++Row)
		{
			const int32 S = B.Slot(EMat::Fabric, Hills[Row]);
			const int32 N = 3 + Row;
			for (int32 k = 0; k < N; ++k)
			{
				const double Y = -W / 2 + W * (k + 0.5) / N + Rng.R(-W * 0.05, W * 0.05);
				const double R = W / N * Rng.R(0.6, 0.8);
				// clip to the panel: hills are half-ellipses resting on their row line
				B.Ellipsoid(S, FVector(6 + Row * 2, FMath::Clamp(Y, -W / 2 + R, W / 2 - R), 60 + H * (0.38 - Row * 0.12)), FVector(2, R, H * (0.22 - Row * 0.03)), 16, 6, true);
			}
		}
		B.Box(B.Slot(EMat::Fabric, Hills[2]), FVector(10, -W / 2, 60), FVector(12, W / 2, 60 + H * 0.14));
		for (int32 k = 0; k < 24; ++k)
		{
			const int32 S = B.Slot(EMat::Fabric, Col::Flower(k));
			B.Ellipsoid(S, FVector(14, -W / 2 + W * (k + 0.5) / 24 + Rng.R(-20, 20), 70 + Rng.R(0, H * 0.12)), FVector(2, 18, 18), 8, 4);
		}
		const int32 Frame = B.Slot(EMat::Fabric, C(0));
		B.Box(Frame, FVector(0, -W / 2 - 15, 45), FVector(16, W / 2 + 15, 60));
		B.Box(Frame, FVector(0, -W / 2 - 15, H), FVector(16, W / 2 + 15, H + 15));
		B.Box(Frame, FVector(0, -W / 2 - 15, 45), FVector(16, -W / 2, H + 15));
		B.Box(Frame, FVector(0, W / 2, 45), FVector(16, W / 2 + 15, H + 15));
	}
	else
	{
		B.Box(Wood, FVector(-30, -30, 0), FVector(30, 30, 90));
	}
	AddMesh(B, Type != TEXT("mural_wall"));
	AddInstances(Inst);
	return true;
}

// =============================================================================================
// Places (local frame: +X points away from the building into the lane / open space)

bool ASWCityPlace::Build(const TSharedPtr<FJsonObject>& Obj, FString& Error)
{
	const FString Cat = J::Str(Obj, TEXT("category"));
	const bool bOpen = J::Bool(Obj, TEXT("open"));
	FSWMeshBuilder B;
	FInstances Inst;
	FRng Rng(Seed);
	const int32 Wood = B.Slot(EMat::Timber, Col::Timber());
	const int32 Dark = B.Slot(EMat::Timber, Col::TimberDark());
	const int32 MetalS = B.Slot(EMat::Metal, Col::Metal());
	const int32 BrassS = B.Slot(EMat::Metal, Col::Brass());
	const int32 Glow = B.Slot(EMat::Lantern, Col::Lantern());
	TArray<FLinearColor> Pal = J::Palette(Obj);
	if (Pal.Num() == 0) Pal = {Srgb(200, 90, 70), Srgb(230, 200, 120), Srgb(90, 140, 110)};
	const double X0 = bOpen ? -150 : 120; // keep clear of the facade

	auto Planter = [&](const FVector& Pc, double R, bool bTree)
	{
		B.Box(Wood, Pc - FVector(R, R, 0), Pc + FVector(R, R, 60));
		if (bTree) ASWCityTrees::AddTree(Inst, TEXT("roof"), Pc + FVector(0, 0, 60), 0.8, Rng.Next());
		else ASWCityTrees::AddShrub(Inst, Pc + FVector(0, 0, 55), R * 0.9, Rng.F() < 0.4 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4)), Rng.Next(), 30000);
	};
	auto Table = [&](const FVector& Pc, bool bUmbrella, const FLinearColor& Canopy)
	{
		B.Cylinder(MetalS, Pc, 4, 4, 72, 6);
		B.Cylinder(Wood, Pc + FVector(0, 0, 72), 45, 45, 4, 10);
		for (int32 s = 0; s < 3; ++s)
		{
			const double A = 2 * PI * s / 3 + 0.4;
			const FVector Sp = Pc + FVector(FMath::Cos(A) * 75, FMath::Sin(A) * 75, 0);
			B.Box(Dark, Sp - FVector(18, 18, 0), Sp + FVector(18, 18, 45));
		}
		if (bUmbrella)
		{
			B.Cylinder(Wood, Pc + FVector(0, 0, 76), 3, 3, 170, 5, false);
			B.Cylinder(B.Slot(EMat::Fabric, Canopy), Pc + FVector(0, 0, 215), 150, 4, 45, 8);
		}
	};

	if (Cat == TEXT("cafe") || Cat == TEXT("bakery") || Cat == TEXT("pub_music"))
	{
		for (int32 i = 0; i < 4; ++i) Table(FVector(X0 + 140 + (i % 2) * 220, -330 + i * 220, 0), true, Pal[i % Pal.Num()]);
		Planter(FVector(X0 + 30, -520, 0), 45, false);
		Planter(FVector(X0 + 30, 520, 0), 45, false);
		B.OBox(Dark, FVector(X0 + 20, 0, 50), FVector(3, 30, 50), FRotator(0, 0, 0)); // chalkboard
		if (Cat == TEXT("pub_music"))
		{
			for (int32 i = 0; i < 6; ++i) B.Box(Glow, FVector(X0 + 300, -500 + i * 200, 300), FVector(X0 + 315, -485 + i * 200, 318));
			B.Beam(MetalS, FVector(X0 + 300, -520, 320), FVector(X0 + 300, 520, 320), 2, 2);
		}
	}
	else if (Cat == TEXT("market"))
	{
		for (int32 i = 0; i < 6; ++i)
		{
			const FVector Pc(X0 + 250 + (i / 3) * 450, -500 + (i % 3) * 500, 0);
			B.Box(Wood, Pc + FVector(-90, -120, 0), Pc + FVector(90, 120, 85));
			for (int32 c = 0; c < 4; ++c)
			{
				const FVector Pp = Pc + FVector((c & 1) ? 95 : -95, (c & 2) ? 125 : -125, 0);
				B.Box(Dark, Pp - FVector(5, 5, 0), Pp + FVector(5, 5, 230));
			}
			B.Gable(B.Slot(EMat::Fabric, Pal[i % Pal.Num()]), Pc + FVector(-120, -150, 230), Pc + FVector(120, 150, 230), 60, false);
			for (int32 k = 0; k < 6; ++k)
				Inst.Add(P(EPrim::Blob), M(EMat::Foliage), k % 2 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4)), Xf(Pc + FVector(Rng.R(-60, 60), Rng.R(-90, 90), 95), FVector(0.18)), false, 25000);
		}
	}
	else if (Cat == TEXT("common_house") || Cat == TEXT("community_kitchen"))
	{
		B.Box(Wood, FVector(X0 + 150, -400, 72), FVector(X0 + 250, 400, 78));
		B.Box(Dark, FVector(X0 + 160, -380, 0), FVector(X0 + 240, -360, 72));
		B.Box(Dark, FVector(X0 + 160, 360, 0), FVector(X0 + 240, 380, 72));
		B.Box(Wood, FVector(X0 + 90, -400, 42), FVector(X0 + 125, 400, 47));
		B.Box(Wood, FVector(X0 + 275, -400, 42), FVector(X0 + 310, 400, 47));
		for (int32 i = 0; i < 2; ++i)
		{
			const double Y = i ? 450 : -450;
			B.Box(Dark, FVector(X0 + 195, Y - 8, 0), FVector(X0 + 205, Y + 8, 300));
		}
		for (int32 i = 0; i < 9; ++i) B.Box(Glow, FVector(X0 + 195, -400 + i * 100, 285), FVector(X0 + 205, -390 + i * 100, 295));
		B.Beam(MetalS, FVector(X0 + 200, -450, 298), FVector(X0 + 200, 450, 298), 2, 2);
	}
	else if (Cat == TEXT("farm"))
	{
		B.Box(Wood, FVector(X0, -150, 0), FVector(X0 + 250, 150, 220));
		B.Gable(B.Slot(EMat::GreenRoof, Col::GreenRoof()), FVector(X0 - 30, -180, 220), FVector(X0 + 280, 180, 220), 80, true);
		for (int32 i = 0; i < 3; ++i) B.Box(Dark, FVector(X0 + 300, -150 + i * 110, 0), FVector(X0 + 390, -60 + i * 110, 90));
	}
	else if (Cat == TEXT("swimming"))
	{
		for (int32 i = 0; i < 5; ++i)
		{
			B.OBox(Wood, FVector(X0 + 100, -400 + i * 200, 30), FVector(90, 32, 5), FRotator(-10, 0, 0));
			if (i % 2 == 0)
			{
				B.Cylinder(Wood, FVector(X0 + 200, -400 + i * 200, 0), 3, 3, 220, 5, false);
				B.Cylinder(B.Slot(EMat::Fabric, Pal[i % Pal.Num()]), FVector(X0 + 200, -400 + i * 200, 200), 140, 4, 40, 8);
			}
		}
	}
	else if (Cat == TEXT("transit") || Cat == TEXT("park") || Cat == TEXT("performance"))
	{
		for (int32 i = 0; i < 4; ++i)
		{
			B.OBox(B.Slot(EMat::Fabric, Pal[i % Pal.Num()]), FVector(X0 + Rng.R(150, 600), Rng.R(-600, 600), 10), FVector(100, 75, 1), FRotator(0, Rng.R(0, 180), 0));
		}
		for (int32 i = 0; i < 2; ++i)
		{
			const double Y = i ? 400 : -400;
			B.Cylinder(MetalS, FVector(X0 + 150, Y, 0), 4, 4, 320, 6);
			B.Box(Glow, FVector(X0 + 140, Y - 10, 300), FVector(X0 + 160, Y + 10, 325));
		}
	}
	else
	{
		// shop / studio frontage: planters with small trees, hanging blade sign, bench, bike hoops
		Planter(FVector(X0 + 30, -260, 0), 50, true);
		Planter(FVector(X0 + 30, 260, 0), 50, Cat == TEXT("library") || Cat == TEXT("health"));
		B.Beam(BrassS, FVector(-5, 160, 380), FVector(110, 160, 380), 4, 4);
		B.Box(B.Slot(EMat::Fabric, Pal[0]), FVector(20, 158, 300), FVector(100, 162, 370));
		B.Box(Wood, FVector(X0 + 60, -110, 42), FVector(X0 + 105, 110, 47));
		B.Box(Dark, FVector(X0 + 65, -100, 0), FVector(X0 + 100, -85, 42));
		B.Box(Dark, FVector(X0 + 65, 85, 0), FVector(X0 + 100, 100, 42));
		if (Cat == TEXT("grocery"))
		{
			for (int32 i = 0; i < 4; ++i)
			{
				B.Box(Wood, FVector(X0 + 150, -150 + i * 80, 0), FVector(X0 + 210, -90 + i * 80, 60));
				for (int32 k = 0; k < 4; ++k)
					Inst.Add(P(EPrim::Blob), M(EMat::Foliage), Col::Flower(i + 2), Xf(FVector(X0 + 165 + (k % 2) * 30, -135 + i * 80 + (k / 2) * 30, 66), FVector(0.1)), false, 20000);
			}
		}
		else if (Cat == TEXT("childcare") || Cat == TEXT("school"))
		{
			B.Box(B.Slot(EMat::Path, Col::Sand()), FVector(X0 + 150, -200, 0), FVector(X0 + 450, 200, 10));
			B.Pole(Wood, FVector(X0 + 200, -150, 30), FVector(X0 + 400, 150, 30), 18, 8);
		}
	}
	AddMesh(B);
	AddInstances(Inst);
	return true;
}

// =============================================================================================
// Open spaces

bool ASWCityOpenSpace::Build(const TSharedPtr<FJsonObject>& Obj, FString& Error)
{
	FVector2D Mn, Mx;
	if (!J::Rect(Obj, TEXT("rect_cm"), Mn, Mx))
	{
		Error = TEXT("rect_cm missing");
		return false;
	}
	Mn = L2(Mn);
	Mx = L2(Mx);
	const FVector2D C = (Mn + Mx) * 0.5;
	const FVector2D Sz = Mx - Mn;
	const FString Kind = J::Str(Obj, TEXT("kind"));
	FSWMeshBuilder B;
	FInstances Inst;
	FRng Rng(Seed);
	const int32 Wood = B.Slot(EMat::Timber, Col::Timber());
	const int32 Dark = B.Slot(EMat::Timber, Col::TimberDark());
	const int32 StoneS = B.Slot(EMat::PermeableStone, Col::Stone());
	const int32 Gravel = B.Slot(EMat::Path, Col::Gravel());
	const int32 SoilS = B.Slot(EMat::Path, Col::Soil());
	const int32 LawnS = B.Slot(EMat::Moss, Col::Lawn());
	const int32 MetalS = B.Slot(EMat::Metal, Col::Metal());
	const int32 Glow = B.Slot(EMat::Lantern, Col::Lantern());
	const int32 WaterS = B.Slot(EMat::Water, Col::Water());

	auto Bed = [&](const FVector2D& P0, const FVector2D& P1, double H, int32 CropKind)
	{
		B.Box(Wood, FVector(P0, 0), FVector(P1, H));
		B.Box(SoilS, FVector(P0 + FVector2D(8, 8), H), FVector(P1 - FVector2D(8, 8), H + 2));
		const FVector2D D = P1 - P0;
		const int32 N = FMath::Clamp(int32(D.X * D.Y / 9000.0), 2, 24);
		for (int32 k = 0; k < N; ++k)
		{
			const FVector Pc(P0.X + 20 + Rng.F() * (D.X - 40), P0.Y + 20 + Rng.F() * (D.Y - 40), H + 2);
			FLinearColor T = Col::Leaf(CropKind + Rng.I(2));
			double S = Rng.R(0.16, 0.3);
			if (CropKind % 5 == 3) T = Col::Flower(Rng.I(6));
			if (CropKind % 5 == 4) { T = Srgb(80, 110, 120); S *= 0.8; } // kale
			Inst.Add(P(EPrim::Blob), M(EMat::Foliage), T, Xf(Pc, FVector(S, S, S * 0.8)), false, 30000);
		}
	};

	if (Kind == TEXT("courtyard"))
	{
		B.Box(LawnS, FVector(Mn, 0), FVector(Mx, 4));
		// paths between the passages (north and south gates) and across
		const TArray<double> Gates = J::Nums(Obj, TEXT("gates_x_cm"));
		const double Gx = Gates.Num() ? Gates[0] - Origin.X : C.X;
		B.Box(StoneS, FVector(Gx - 140, Mn.Y, 0), FVector(Gx + 140, Mx.Y, 7));
		B.Box(StoneS, FVector(Mn.X, C.Y - 120, 0), FVector(Mx.X, C.Y + 120, 7));
		// water runnel meandering beside the cross path, with a small basin at the centre
		B.Box(B.Slot(EMat::PermeableStone, Col::StoneDark()), FVector(Mn.X + 200, C.Y + 120, 0), FVector(Mx.X - 200, C.Y + 190, 9));
		B.Box(WaterS, FVector(Mn.X + 200, C.Y + 135, 0), FVector(Mx.X - 200, C.Y + 175, 10));
		B.Cylinder(B.Slot(EMat::PermeableStone, Col::StoneDark()), FVector(Gx + 500, C.Y + 450, 0), 260, 260, 30, 16);
		B.Cylinder(WaterS, FVector(Gx + 500, C.Y + 450, 30), 230, 230, 1, 16);
		// raised garden beds in the four quadrants
		int32 Kc = 0;
		for (int32 Q = 0; Q < 4; ++Q)
		{
			const bool bE = Q & 1, bS = Q & 2;
			const double Qx0 = bE ? Gx + 300 : Mn.X + 300, Qx1 = bE ? Mx.X - 300 : Gx - 300;
			const double Qy0 = bS ? C.Y + 350 : Mn.Y + 350, Qy1 = bS ? Mx.Y - 350 : C.Y - 300;
			if (Qx1 - Qx0 < 400 || Qy1 - Qy0 < 400) continue;
			if (Q == 0)
			{
				// long dining table under a vine pergola with string lights
				const double Tx0 = Qx0 + 100, Tx1 = FMath::Min(Qx1 - 100, Qx0 + 1600), Ty = (Qy0 + Qy1) * 0.5;
				B.Box(Wood, FVector(Tx0, Ty - 55, 72), FVector(Tx1, Ty + 55, 78));
				B.Box(Wood, FVector(Tx0, Ty - 110, 42), FVector(Tx1, Ty - 80, 47));
				B.Box(Wood, FVector(Tx0, Ty + 80, 42), FVector(Tx1, Ty + 110, 47));
				for (double X = Tx0; X <= Tx1 + 1; X += (Tx1 - Tx0) / 4)
				{
					B.Box(Dark, FVector(X - 10, Ty - 220, 0), FVector(X + 10, Ty - 200, 300));
					B.Box(Dark, FVector(X - 10, Ty + 200, 0), FVector(X + 10, Ty + 220, 300));
					B.Box(Dark, FVector(X - 8, Ty - 230, 300), FVector(X + 8, Ty + 230, 318));
					for (int32 k = 0; k < 3; ++k)
						Inst.Add(P(EPrim::Blob), M(EMat::Foliage), k == 1 ? Col::Flower(0) : Col::Leaf(k), Xf(FVector(X + Rng.R(-80, 80), Ty + Rng.R(-200, 200), 320), FVector(Rng.R(0.6, 1.0), Rng.R(0.6, 1.0), 0.3)), true, 50000);
				}
				for (double X = Tx0; X < Tx1; X += 90) B.Box(Glow, FVector(X, Ty - 5, 285), FVector(X + 10, Ty + 5, 295));
			}
			else if (Q == 3)
			{
				// play area: sand, logs, a little climbing frame
				const double Qcx = (Qx0 + Qx1) * 0.5, Qcy = (Qy0 + Qy1) * 0.5, Qw = (Qx1 - Qx0) * 0.3, Qh = (Qy1 - Qy0) * 0.3;
				B.Cylinder(B.Slot(EMat::Path, Col::Sand()), FVector(Qcx, Qcy, 0), FMath::Min(Qw, Qh), FMath::Min(Qw, Qh), 9, 20);
				for (int32 k = 0; k < 4; ++k)
				{
					const FVector P0(Rng.R(Qcx - Qw, Qcx + Qw * 0.3), Rng.R(Qcy - Qh * 0.8, Qcy + Qh * 0.8), 25);
					B.Pole(B.Slot(EMat::Bark, Col::Bark()), P0, P0 + FVector(Rng.R(200, 350), Rng.R(-80, 80), 0), Rng.R(16, 24), 7);
				}
				const FVector F((Qx0 + Qx1) * 0.5, (Qy0 + Qy1) * 0.5, 0);
				for (int32 k = 0; k < 4; ++k)
					B.Pole(Wood, F + FVector((k & 1) ? 120 : -120, (k & 2) ? 120 : -120, 0), F + FVector(0, 0, 260), 7, 6);
				B.Gable(B.Slot(EMat::Fabric, Srgb(230, 170, 80)), F + FVector(-90, -90, 150), F + FVector(90, 90, 150), 60, true);
			}
			else
			{
				for (double Y = Qy0; Y + 120 < Qy1; Y += 220)
					Bed(FVector2D(Qx0, Y), FVector2D(Qx1, Y + 120), 45, Kc++);
			}
		}
		// benches and lanterns along the cross path
		for (double X = Mn.X + 600; X < Mx.X - 600; X += 1200)
		{
			B.Box(Wood, FVector(X - 90, C.Y - 200, 42), FVector(X + 90, C.Y - 160, 47));
			B.Box(StoneS, FVector(X - 80, C.Y - 200, 0), FVector(X - 60, C.Y - 160, 42));
			B.Box(StoneS, FVector(X + 60, C.Y - 200, 0), FVector(X + 80, C.Y - 160, 42));
			B.Cylinder(MetalS, FVector(X, C.Y + 230, 0), 3, 3, 80, 6);
			B.Box(Glow, FVector(X - 8, C.Y + 222, 70), FVector(X + 8, C.Y + 238, 88));
		}
		// edge planting against the bars
		for (double X = Mn.X + 100; X < Mx.X - 100; X += Rng.R(120, 260))
		{
			ASWCityTrees::AddShrub(Inst, FVector(X, Mn.Y + 80, 4), Rng.R(50, 90), Rng.F() < 0.3 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4)), Rng.Next(), 40000);
			ASWCityTrees::AddShrub(Inst, FVector(X, Mx.Y - 80, 4), Rng.R(50, 90), Rng.F() < 0.3 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4)), Rng.Next(), 40000);
		}
	}
	else if (Kind == TEXT("amphitheater"))
	{
		// bowl focus at the east edge (toward the creek), tiers step up westward
		B.Box(LawnS, FVector(Mn, 0), FVector(Mx, 3));
		const FVector2D F(Mx.X - 300, C.Y);
		const double Rmax = FMath::Min(Sz.X - 400, Sz.Y * 0.5 - 100);
		const int32 Tiers = 9;
		const double Step = (Rmax - 650) / Tiers;
		const int32 Earth = B.Slot(EMat::RammedEarth, Col::Rose());
		const int32 Earth2 = B.Slot(EMat::RammedEarth, Col::Ochre());
		for (int32 t = 0; t < Tiers; ++t)
		{
			const double R0 = 650 + t * Step, R1 = R0 + Step;
			const double Z = 40 + t * 42;
			Sector(B, t % 2 ? Earth : Earth2, F, R0, R1, PI * 0.55, PI * 1.45, 0, Z - 6, 24);
			Sector(B, t % 3 == 2 ? LawnS : Wood, F, R0, R0 + 55, PI * 0.55, PI * 1.45, Z - 6, Z, 24);
			Sector(B, LawnS, F, R0 + 55, R1, PI * 0.55, PI * 1.45, Z - 6, Z - 2, 24);
		}
		B.Cylinder(Wood, FVector(F, 0), 520, 520, 55, 24);
		// shade sail over the stage
		const int32 Sail = B.Slot(EMat::Fabric, Srgb(236, 226, 206));
		for (int32 k = 0; k < 3; ++k)
		{
			const double A = PI * (0.7 + 0.3 * k);
			B.Pole(Dark, FVector(F + FVector2D(FMath::Cos(A), FMath::Sin(A)) * 600, 0), FVector(F + FVector2D(FMath::Cos(A), FMath::Sin(A)) * 560, 650), 10, 6);
		}
		B.OBox(Sail, FVector(F, 620), FVector(500, 520, 2), FRotator(-6, 0, 4));
	}
	else if (Kind == TEXT("chess_garden"))
	{
		B.Box(StoneS, FVector(Mn, 0), FVector(Mx, 8));
		const int32 Light = B.Slot(EMat::PermeableStone, Srgb(226, 216, 196));
		const int32 DarkSq = B.Slot(EMat::PermeableStone, Srgb(84, 80, 74));
		for (int32 t = 0; t < 6; ++t)
		{
			const FVector2D T(Mn.X + Sz.X * (0.2 + 0.3 * (t % 3)), Mn.Y + Sz.Y * (t < 3 ? 0.3 : 0.72));
			B.Cylinder(StoneS, FVector(T, 8), 30, 22, 66, 8);
			B.Box(StoneS, FVector(T - FVector2D(45, 45), 74), FVector(T + FVector2D(45, 45), 80));
			for (int32 i = 0; i < 8; ++i)
				for (int32 j = 0; j < 8; ++j)
					B.Box((i + j) % 2 ? DarkSq : Light, FVector(T + FVector2D(-40 + i * 10, -40 + j * 10), 80), FVector(T + FVector2D(-30 + i * 10, -30 + j * 10), 81));
			for (int32 s = 0; s < 2; ++s)
				B.Cylinder(StoneS, FVector(T + FVector2D(s ? 95 : -95, 0), 8), 20, 20, 38, 8);
		}
		// pergola with wisteria along the north edge
		for (double X = Mn.X + 200; X < Mx.X - 100; X += 400)
		{
			B.Box(Dark, FVector(X - 10, Mn.Y + 150, 8), FVector(X + 10, Mn.Y + 170, 300));
			B.Box(Dark, FVector(X - 10, Mn.Y + 450, 8), FVector(X + 10, Mn.Y + 470, 300));
			B.Box(Dark, FVector(X - 8, Mn.Y + 130, 300), FVector(X + 8, Mn.Y + 490, 318));
			for (int32 k = 0; k < 3; ++k)
				Inst.Add(P(EPrim::Blob), M(EMat::Foliage), k == 0 ? Col::Leaf(1) : Col::Flower(4), Xf(FVector(X + Rng.R(-150, 150), Mn.Y + Rng.R(150, 470), Rng.R(250, 320)), FVector(Rng.R(0.5, 0.9), Rng.R(0.5, 0.9), Rng.R(0.3, 0.6))), true, 50000);
		}
	}
	else if (Kind == TEXT("playground"))
	{
		B.Box(B.Slot(EMat::Path, Col::Sand()), FVector(Mn, 0), FVector(Mx, 8));
		for (int32 k = 0; k < 8; ++k)
		{
			const FVector P0(Rng.R(Mn.X + 200, Mx.X - 600), Rng.R(Mn.Y + 200, Mx.Y - 200), 30);
			B.Pole(B.Slot(EMat::Bark, Col::Bark()), P0, P0 + FVector(Rng.R(250, 450), Rng.R(-150, 150), Rng.R(-10, 40)), Rng.R(18, 30), 7);
		}
		// grassy slide mound + slide
		const FVector Mound(Mx.X - 700, C.Y, 0);
		B.Ellipsoid(LawnS, Mound, FVector(500, 450, 280), 16, 6, true);
		B.OBox(B.Slot(EMat::Metal, Col::Brass()), Mound + FVector(-450, 0, 140), FVector(260, 45, 4), FRotator(-30, 0, 0));
		// swing frame
		const FVector Sw(Mn.X + 600, Mx.Y - 500, 0);
		B.Pole(Wood, Sw + FVector(-300, -120, 0), Sw + FVector(-300, 0, 280), 8);
		B.Pole(Wood, Sw + FVector(-300, 120, 0), Sw + FVector(-300, 0, 280), 8);
		B.Pole(Wood, Sw + FVector(300, -120, 0), Sw + FVector(300, 0, 280), 8);
		B.Pole(Wood, Sw + FVector(300, 120, 0), Sw + FVector(300, 0, 280), 8);
		B.Pole(Wood, Sw + FVector(-300, 0, 280), Sw + FVector(300, 0, 280), 9);
		for (int32 k = 0; k < 2; ++k)
		{
			const double X = k ? 120 : -120;
			B.Pole(MetalS, Sw + FVector(X - 25, 0, 280), Sw + FVector(X - 25, 0, 60), 1.5, 4);
			B.Pole(MetalS, Sw + FVector(X + 25, 0, 280), Sw + FVector(X + 25, 0, 60), 1.5, 4);
			B.Box(Wood, Sw + FVector(X - 30, -12, 55), Sw + FVector(X + 30, 12, 60));
		}
		// climbing net dome
		const FVector Dm(C.X - 300, Mn.Y + 600, 0);
		for (int32 k = 0; k < 8; ++k)
		{
			const double A = 2 * PI * k / 8;
			B.Pole(B.Slot(EMat::Fabric, Srgb(214, 120, 70)), Dm + FVector(FMath::Cos(A) * 350, FMath::Sin(A) * 350, 0), Dm + FVector(0, 0, 330), 4, 5);
		}
	}
	else if (Kind == TEXT("village_green"))
	{
		B.Box(LawnS, FVector(Mn, 0), FVector(Mx, 5));
		// picnics (VIBE.md 6: Isono's picnickers on the lawn): blanket, basket, cushions, sometimes a parasol;
		// and pairs of timber deck chairs. Built into the actor's merged mesh, so they add no draw calls.
		const int32 Wicker = B.Slot(EMat::Timber, Col::Bamboo());
		for (int32 k = 0; k < 12; ++k)
		{
			const FVector2D Pc(Rng.R(Mn.X + 1500, Mx.X - 1500), Rng.R(Mn.Y + 1200, Mx.Y - 1200));
			const double Yw = Rng.R(0, 180);
			const FQuat Qp = FRotator(0, Yw, 0).Quaternion();
			auto At = [&](double X, double Y, double Z) { return FVector(Pc, 0) + Qp.RotateVector(FVector(X, Y, Z)); };
			B.OBox(B.Slot(EMat::Fabric, Col::Flower(k)), At(0, 0, 6), FVector(110, 80, 1), FRotator(0, Yw, 0));
			B.OBox(Wicker, At(60, 40, 20), FVector(22, 15, 14), FRotator(0, Yw + 10, 0));
			B.OBox(B.Slot(EMat::Fabric, Col::Flower(k + 3)), At(-70, -30, 14), FVector(25, 25, 7), FRotator(0, Yw + 30, 0));
			B.OBox(B.Slot(EMat::Fabric, Col::Flower(k + 1)), At(-60, 35, 14), FVector(25, 25, 7), FRotator(0, Yw - 20, 0));
			if (k % 3 == 0)
			{
				// striped parasol: pole + 8 alternating canopy wedges
				const FVector Top = At(-90, -70, 230);
				B.Pole(Wood, At(-90, -70, 0), Top, 3);
				for (int32 w = 0; w < 8; ++w)
				{
					const double A = 2 * PI * (w + 0.5) / 8;
					B.OBox(B.Slot(EMat::Fabric, w % 2 ? Srgb(246, 240, 228) : Col::Flower(k)), Top + FVector(FMath::Cos(A) * 70, FMath::Sin(A) * 70, -22),
						FVector(75, 28, 1.5), FRotator(-17, FMath::RadiansToDegrees(A), 0));
				}
			}
		}
		for (int32 k = 0; k < 8; ++k)
		{
			const FVector2D Pc(Rng.R(Mn.X + 1200, Mx.X - 1200), Rng.R(Mn.Y + 900, Mx.Y - 900));
			const double Yw = Rng.R(0, 360);
			const FQuat Qp = FRotator(0, Yw, 0).Quaternion();
			for (int32 c = 0; c < 2; ++c)
			{
				auto At = [&](double X, double Y, double Z) { return FVector(Pc, 0) + Qp.RotateVector(FVector(X, Y + c * 90, Z)); };
				// deck chair: canvas seat sloping back, timber side frames
				B.OBox(B.Slot(EMat::Fabric, Col::Flower(k + c * 2)), At(0, 0, 40), FVector(55, 26, 2), FRotator(-30, Yw, 0));
				B.OBox(Wood, At(0, -28, 30), FVector(55, 2, 3), FRotator(-30, Yw, 0));
				B.OBox(Wood, At(0, 28, 30), FVector(55, 2, 3), FRotator(-30, Yw, 0));
			}
		}
		for (int32 k = 0; k < 900; ++k)
			Inst.Add(P(EPrim::Blob), M(EMat::Foliage), k % 3 ? Col::Flower(3) : Col::Flower(2), Xf(FVector(Rng.R(Mn.X, Mx.X), Rng.R(Mn.Y, Mx.Y), 5), FVector(0.08, 0.08, 0.05)), false, 15000);
	}
	else if (Kind == TEXT("plots"))
	{
		B.Box(B.Slot(EMat::Moss, Col::Meadow()), FVector(Mn, 0), FVector(Mx, 3));
		TArray<FBox2D> Excl;
		for (const TSharedPtr<FJsonObject>& E : J::Objs(Obj, TEXT("exclude")))
		{
			FVector2D A, Bv;
			if (J::Rect(E, TEXT("rect_cm"), A, Bv)) Excl.Add(FBox2D(L2(A) - FVector2D(300), L2(Bv) + FVector2D(300)));
		}
		int32 Kc = 0;
		for (double X = Mn.X + 200; X + 140 < Mx.X - 200; X += 230)
		{
			for (double Y = Mn.Y + 450; Y + 900 < Mx.Y - 150; Y += 1150)
			{
				const FBox2D Bx(FVector2D(X, Y), FVector2D(X + 140, Y + 900));
				bool bHit = false;
				for (const FBox2D& E : Excl) bHit |= E.Intersect(Bx);
				if (bHit) continue;
				Bed(Bx.Min, Bx.Max, 30, Kc);
				if (Rng.F() < 0.7) ++Kc;
			}
		}
		// gravel spine
		B.Box(Gravel, FVector(Mn.X, Mn.Y + 30, 0), FVector(Mx.X, Mn.Y + 200, 6));
	}
	else if (Kind == TEXT("food_forest"))
	{
		B.Box(B.Slot(EMat::Path, Srgb(110, 88, 62)), FVector(Mn, 0), FVector(Mx, 3));
		B.Box(Gravel, FVector(C.X - 100, Mn.Y, 0), FVector(C.X + 100, Mx.Y, 6));
		const int32 N = int32(Sz.X * Sz.Y / 120000.0);
		for (int32 k = 0; k < N; ++k)
		{
			const FVector Pc(Rng.R(Mn.X, Mx.X), Rng.R(Mn.Y, Mx.Y), 3);
			if (FMath::Abs(Pc.X - C.X) < 180) continue;
			const FLinearColor T = Rng.F() < 0.15 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4));
			ASWCityTrees::AddShrub(Inst, Pc, Rng.R(50, 130), T, Rng.Next(), 40000);
		}
	}
	else if (Kind == TEXT("plaza"))
	{
		// paving comes from the ground actor; this only carries the props below
	}
	else
	{
		B.Box(LawnS, FVector(Mn, 0), FVector(Mx, 4));
	}

	// ---- props (any open space): market stalls, shade sails, planter benches, pools, bikes, string lights ----
	const int32 BrassS = B.Slot(EMat::Metal, Col::Brass());
	for (const TSharedPtr<FJsonObject>& Pr : J::Objs(Obj, TEXT("props")))
	{
		const FString T = J::Str(Pr, TEXT("t"));
		const TArray<double> Pp = J::Nums(Pr, TEXT("p"));
		if (Pp.Num() < 2) continue;
		const FVector Pc = L(Pp[0], Pp[1], 0);
		const double Yaw = J::Num(Pr, TEXT("yaw"), 0);
		const FQuat Q = FRotator(0, Yaw, 0).Quaternion();
		auto W = [&](double X, double Y, double Z) { return Pc + Q.RotateVector(FVector(X, Y, Z)); };
		auto RBox = [&](int32 S, double X0, double Y0, double Z0, double X1, double Y1, double Z1)
		{ B.OBox(S, W((X0 + X1) * 0.5, (Y0 + Y1) * 0.5, (Z0 + Z1) * 0.5), FVector(FMath::Abs(X1 - X0) * 0.5, FMath::Abs(Y1 - Y0) * 0.5, FMath::Abs(Z1 - Z0) * 0.5), FRotator(0, Yaw, 0)); };
		const FLinearColor Cc = J::Color(Pr, TEXT("c"), Col::Flower(Rng.I(6)));
		if (T == TEXT("stall"))
		{
			// produce stall: counter, crates of produce, four posts, striped canopy, a hanging lantern
			const int32 Can = B.Slot(EMat::Fabric, Cc);
			RBox(Wood, -100, -140, 0, 100, 140, 88);
			RBox(Dark, -105, -145, 88, 105, 145, 95);
			for (int32 c = 0; c < 4; ++c) RBox(Dark, (c & 1) ? 95 : -105, (c & 2) ? 135 : -145, 0, (c & 1) ? 105 : -95, (c & 2) ? 145 : -135, 250);
			const FVector G0 = W(-140, -175, 250), G1 = W(140, 175, 250);
			if (FMath::Abs(FMath::Fmod(Yaw, 180.0)) < 45 || FMath::Abs(FMath::Fmod(Yaw, 180.0)) > 135)
				B.Gable(Can, G0.ComponentMin(G1), G0.ComponentMax(G1), 65, false);
			else
				B.Gable(Can, G0.ComponentMin(G1), G0.ComponentMax(G1), 65, true);
			for (int32 k = 0; k < 6; ++k)
			{
				const double X = -60 + (k % 2) * 70, Y = -100 + (k / 2) * 95;
				RBox(Wood, X - 30, Y - 38, 95, X + 30, Y + 38, 112);
				const FLinearColor Prod = k % 3 == 0 ? Srgb(220, 60, 40) : (k % 3 == 1 ? Srgb(240, 170, 40) : Srgb(110, 160, 60));
				for (int32 d = 0; d < 4; ++d)
					Inst.Add(P(EPrim::Blob), M(EMat::Foliage), Prod, Xf(W(X + Rng.R(-18, 18), Y + Rng.R(-25, 25), 116), FVector(0.1)), false, 15000);
			}
			B.Box(Glow, W(0, 0, 215) - FVector(9), W(0, 0, 215) + FVector(9));
		}
		else if (T == TEXT("sail"))
		{
			// tensile shade sail: a hypar quad between two high and two low mast tops
			const double Hs = J::Num(Pr, TEXT("size"), 900) * 0.5;
			const int32 Sail = B.Slot(EMat::Fabric, Cc);
			FVector Tops[4];
			for (int32 c = 0; c < 4; ++c)
			{
				const double A = PI * 0.5 * c + PI * 0.25;
				const FVector Foot = W(FMath::Cos(A) * Hs * 1.15, FMath::Sin(A) * Hs * 1.15, 0);
				Tops[c] = W(FMath::Cos(A) * Hs, FMath::Sin(A) * Hs, c % 2 ? 330 : 470);
				B.Pole(MetalS, Foot, Tops[c] + FVector(0, 0, 25), 6, 6);
				B.Cylinder(StoneS, Foot, 22, 18, 20, 6);
			}
			B.Tri(Sail, Tops[0], Tops[1], Tops[2], FVector::UpVector);
			B.Tri(Sail, Tops[0], Tops[2], Tops[3], FVector::UpVector);
		}
		else if (T == TEXT("planter_bench"))
		{
			const double R = J::Num(Pr, TEXT("size"), 300) * 0.5;
			RBox(Wood, -R, -R, 0, R, R, 65);
			B.Box(B.Slot(EMat::Path, Col::Soil()), W(0, 0, 65) - FVector(R - 12, R - 12, 0), W(0, 0, 67) + FVector(R - 12, R - 12, 0));
			for (int32 s = 0; s < 4; ++s)
			{
				const FQuat Qs = FRotator(0, Yaw + 90 * s, 0).Quaternion();
				const FVector A = Pc + Qs.RotateVector(FVector(R + 25, 0, 44));
				B.OBox(Wood, A, FVector(22, R * 0.85, 3), FRotator(0, Yaw + 90 * s, 0));
				B.OBox(Dark, Pc + Qs.RotateVector(FVector(R + 25, -R * 0.6, 21)), FVector(16, 5, 21), FRotator(0, Yaw + 90 * s, 0));
				B.OBox(Dark, Pc + Qs.RotateVector(FVector(R + 25, R * 0.6, 21)), FVector(16, 5, 21), FRotator(0, Yaw + 90 * s, 0));
			}
			ASWCityTrees::AddTree(Inst, J::Str(Pr, TEXT("tree"), TEXT("maple")), W(0, 0, 66), J::Num(Pr, TEXT("scale"), 0.75), Rng.Next());
			for (int32 k = 0; k < 4; ++k)
				ASWCityTrees::AddShrub(Inst, W(Rng.R(-R * 0.7, R * 0.7), Rng.R(-R * 0.7, R * 0.7), 66), Rng.R(30, 45), Rng.F() < 0.5 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4)), Rng.Next(), 30000);
		}
		else if (T == TEXT("pool"))
		{
			// shallow reflecting pool with a stone rim, splash jets, stepping stones and lilies
			const double Rx = J::Num(Pr, TEXT("rx"), 600), Ry = J::Num(Pr, TEXT("ry"), 300);
			TArray<FVector2D> Rim = Ellipse(FVector2D(Pc), Rx + 40, Ry + 40, 28), In = Ellipse(FVector2D(Pc), Rx, Ry, 28);
			B.Prism(StoneS, Rim, 0, 30);
			B.Prism(WaterS, In, 0, 32);
			for (int32 k = 0; k < 7; ++k)
			{
				const FVector Jp = Pc + FVector((k - 3) * Rx / 4.0, 0, 32);
				B.Cylinder(B.Slot(EMat::Water, Srgb(200, 225, 230)), Jp, 6, 1, 40 + 25 * (k % 3), 5, false);
			}
			for (int32 k = 0; k < 6; ++k)
				Inst.Add(P(EPrim::Disc), M(EMat::Foliage), Col::Leaf(1), Xf(Pc + FVector(Rng.R(-Rx, Rx) * 0.7, Rng.R(-Ry, Ry) * 0.6, 33), FVector(Rng.R(0.5, 0.9), Rng.R(0.5, 0.9), 0.3)), false, 20000);
			for (int32 k = 0; k < 5; ++k)
				Inst.Add(P(EPrim::Disc), M(EMat::PermeableStone), Col::Stone(), Xf(Pc + FVector(-Rx * 0.6 + k * Rx * 0.3, Ry * 0.55, 30), FVector(1.1, 0.9, 1.0)), false, 20000);
			for (int32 k = 0; k < 14; ++k)
			{
				const double A = Rng.R(0, 2 * PI);
				Inst.Add(P(EPrim::Reed), M(EMat::Foliage), Col::Meadow(), Xf(Pc + FVector(FMath::Cos(A) * Rx * 0.95, FMath::Sin(A) * Ry * 0.95, 30), FVector(1.0, 1.0, Rng.R(0.8, 1.4))), false, 20000);
			}
		}
		else if (T == TEXT("bikes"))
		{
			const int32 Nbk = int32(J::Num(Pr, TEXT("n"), 6));
			for (int32 i = 0; i < Nbk; ++i)
			{
				const double Y = (i - (Nbk - 1) * 0.5) * 80;
				B.Pole(MetalS, W(-30, Y, 0), W(-30, Y, 75), 3, 6);
				B.Pole(MetalS, W(30, Y, 0), W(30, Y, 75), 3, 6);
				B.Pole(MetalS, W(-30, Y, 75), W(30, Y, 75), 3, 6);
				if (Rng.F() < 0.75)
				{
					// bike: two wheels (thin discs on edge), frame, saddle, handlebar
					const int32 Fr = B.Slot(EMat::Metal, Col::Flower(Rng.I(6)));
					const FVector Wf = W(70, Y + 15, 33), Wb = W(-70, Y + 15, 33);
					const FVector Ax = Q.RotateVector(FVector(0, 2.5, 0));
					B.Pole(MetalS, Wf - Ax, Wf + Ax, 33, 10);
					B.Pole(MetalS, Wb - Ax, Wb + Ax, 33, 10);
					B.Pole(Fr, Wb, W(0, Y + 15, 70), 2.5, 4);
					B.Pole(Fr, W(0, Y + 15, 70), Wf, 2.5, 4);
					B.Pole(Fr, W(-20, Y + 15, 33), W(-25, Y + 15, 90), 2.5, 4);
					B.Pole(Fr, W(55, Y + 15, 95), Wf, 2.5, 4);
					RBox(Dark, -35, Y + 8, 90, -15, Y + 22, 96);
					B.Pole(MetalS, W(55, Y - 10, 98), W(55, Y + 40, 98), 2, 4);
				}
			}
		}
		else if (T == TEXT("lights"))
		{
			// festoon string between two masts: sagging cable with warm bulbs
			const TArray<double> Qp = J::Nums(Pr, TEXT("q"));
			if (Qp.Num() < 2) continue;
			const FVector A = L(Pp[0], Pp[1], 0), Bq = L(Qp[0], Qp[1], 0);
			B.Pole(Dark, A, A + FVector(0, 0, 480), 7, 6);
			B.Pole(Dark, Bq, Bq + FVector(0, 0, 480), 7, 6);
			const int32 Nseg = 12;
			FVector Prev = A + FVector(0, 0, 460);
			for (int32 i = 1; i <= Nseg; ++i)
			{
				const double F = double(i) / Nseg;
				const FVector Cur = FMath::Lerp(A, Bq, F) + FVector(0, 0, 460 - 120 * 4 * F * (1 - F));
				B.Pole(MetalS, Prev, Cur, 1, 3);
				if (i < Nseg) B.Box(Glow, Cur - FVector(6, 6, 14), Cur + FVector(6, 6, -2));
				Prev = Cur;
			}
		}
		else if (T == TEXT("tables"))
		{
			for (int32 i = 0; i < 3; ++i)
			{
				const FVector Tp = W(0, (i - 1) * 260, 0);
				B.Cylinder(MetalS, Tp, 4, 4, 72, 6);
				B.Cylinder(Wood, Tp + FVector(0, 0, 72), 50, 50, 4, 10);
				for (int32 c = 0; c < 4; ++c)
				{
					const double A = PI * 0.5 * c;
					B.Box(Dark, Tp + FVector(FMath::Cos(A) * 80 - 18, FMath::Sin(A) * 80 - 18, 0), Tp + FVector(FMath::Cos(A) * 80 + 18, FMath::Sin(A) * 80 + 18, 45));
				}
				B.Cylinder(Wood, Tp + FVector(0, 0, 76), 3, 3, 170, 5, false);
				B.Cylinder(B.Slot(EMat::Fabric, i % 2 ? Cc : Srgb(240, 232, 214)), Tp + FVector(0, 0, 215), 150, 4, 45, 8);
			}
		}
		else if (T == TEXT("flowerbed"))
		{
			const double Lx = J::Num(Pr, TEXT("lx"), 600) * 0.5, Ly = J::Num(Pr, TEXT("ly"), 200) * 0.5;
			RBox(Wood, -Lx, -Ly, 0, Lx, Ly, 35);
			RBox(SoilS, -Lx + 8, -Ly + 8, 35, Lx - 8, Ly - 8, 37);
			const int32 Nb = FMath::Clamp(int32(Lx * Ly / 1500), 6, 80);
			for (int32 k = 0; k < Nb; ++k)
			{
				const double X = Rng.R(-Lx + 20, Lx - 20), Y = Rng.R(-Ly + 20, Ly - 20);
				const int32 Band = int32((X + Lx) / FMath::Max(1.0, Lx * 2 / 4));
				const FLinearColor Fc = k % 4 == 0 ? Col::Leaf(Rng.I(4)) : Col::Flower(Band + int32(Pp[0]) % 6);
				Inst.Add(P(EPrim::Puff), M(EMat::Foliage), Fc, Xf(W(X, Y, 37), FVector(Rng.R(0.18, 0.3), Rng.R(0.18, 0.3), Rng.R(0.15, 0.3)), Rng.R(0, 360)), false, 25000);
			}
		}
		else if (T == TEXT("kiosk"))
		{
			RBox(Wood, -150, -120, 0, 150, 120, 240);
			RBox(B.Slot(EMat::SolarGlass, Col::GlassWarm(), 5.f), 148, -100, 80, 153, 100, 210);
			RBox(Dark, 150, -120, 95, 200, 120, 102);
			const FVector G0 = W(-190, -160, 240), G1 = W(190, 160, 240);
			B.Gable(B.Slot(EMat::GreenRoof, Col::GreenRoof()), G0.ComponentMin(G1), G0.ComponentMax(G1), 90, FMath::Abs(FMath::Fmod(Yaw, 180.0)) > 45 && FMath::Abs(FMath::Fmod(Yaw, 180.0)) < 135);
			B.Box(BrassS, W(210, 0, 250) - FVector(4), W(210, 0, 250) + FVector(4, 4, 30));
		}
	}
	AddMesh(B);
	AddInstances(Inst);
	return true;
}
