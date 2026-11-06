#include "City/SWCityActors.h"

#include "City/SWCityJson.h"
#include "City/SWCityMesh.h"
#include "Components/BoxComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/StaticMeshComponent.h"
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
		{TEXT("Path"), EMat::Path}, {TEXT("Metal"), EMat::Metal}, {TEXT("Fabric"), EMat::Fabric}, {TEXT("Lantern"), EMat::Lantern}};
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
		if (Bk.CullCm > 0)
		{
			C->SetCullDistances(int32(Bk.CullCm * 0.8), int32(Bk.CullCm));
		}
		C->AddInstances(Bk.Xf, false, false, false);
		C->RegisterComponent();
		AddInstanceComponent(C);
		Built.Add(C);
		InstanceCount += Bk.Xf.Num();
		Tris += Bk.Xf.Num() * (Bk.Prim == P(EPrim::Blob) || Bk.Prim == P(EPrim::Stone) ? 80 : 24);
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

// =============================================================================================
// Ground

bool ASWCityGround::Build(const TSharedPtr<FJsonObject>& Obj, FString& Error)
{
	FSWMeshBuilder B;
	for (const TSharedPtr<FJsonObject>& S : J::Objs(Obj, TEXT("slabs")))
	{
		const int32 Slot = B.Slot(MatFromName(J::Str(S, TEXT("mat"), TEXT("Moss"))), J::Color(S, TEXT("tint"), Col::Grass()));
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
	AddMesh(B, false);

	// Scattered meadow flowers / clover / shrubs over rects.
	FInstances Inst;
	FRng Rng(Seed);
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
				const FLinearColor C = Rng.F() < 0.35 ? Col::Leaf(Rng.I(4)) : Col::Flower(Rng.I(6));
				Inst.Add(P(EPrim::Blob), M(EMat::Foliage), C, Xf(Pt, FVector(Rng.R(0.12, 0.3), Rng.R(0.12, 0.3), Rng.R(0.1, 0.25))), false, 25000);
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
				const FLinearColor Tint = Rng.F() < 0.25 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4));
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
struct FSpecies
{
	const TCHAR* Name;
	double TrunkH, TrunkR, CrownR, CrownH; // cm (CrownH = vertical radius)
	int32 Blobs;
	int32 Shape; // 0 round, 1 spreading, 2 willow, 3 columnar
	FColor Leaf[3];
	FColor Bloom;
	float BloomFrac;
	FColor BarkC;
};

const FSpecies GSpecies[] = {
	{TEXT("oak"), 520, 32, 520, 380, 9, 0, {FColor(70, 112, 50), FColor(84, 124, 56), FColor(60, 100, 46)}, FColor(0, 0, 0), 0.f, FColor(92, 74, 58)},
	{TEXT("maple"), 470, 26, 430, 400, 8, 0, {FColor(96, 140, 60), FColor(112, 150, 62), FColor(128, 158, 66)}, FColor(190, 90, 50), 0.0f, FColor(104, 86, 70)},
	{TEXT("flowering cherry"), 300, 22, 430, 240, 8, 1, {FColor(240, 170, 192), FColor(246, 196, 210), FColor(226, 150, 178)}, FColor(120, 150, 70), 0.15f, FColor(90, 60, 52)},
	{TEXT("willow"), 300, 38, 520, 300, 7, 2, {FColor(150, 170, 78), FColor(132, 160, 70), FColor(168, 180, 92)}, FColor(0, 0, 0), 0.f, FColor(96, 82, 64)},
	{TEXT("fig"), 160, 24, 360, 220, 7, 1, {FColor(70, 118, 56), FColor(86, 130, 60), FColor(64, 110, 52)}, FColor(0, 0, 0), 0.f, FColor(150, 140, 126)},
	{TEXT("persimmon"), 260, 22, 300, 280, 6, 0, {FColor(92, 132, 56), FColor(104, 140, 60), FColor(84, 124, 52)}, FColor(236, 130, 40), 0.18f, FColor(80, 64, 52)},
	{TEXT("pawpaw"), 180, 16, 220, 260, 5, 3, {FColor(70, 120, 52), FColor(80, 132, 58), FColor(66, 112, 50)}, FColor(0, 0, 0), 0.f, FColor(110, 96, 84)},
	{TEXT("chestnut"), 400, 34, 560, 400, 9, 0, {FColor(66, 106, 46), FColor(76, 118, 52), FColor(90, 128, 58)}, FColor(236, 226, 190), 0.12f, FColor(84, 66, 52)},
	{TEXT("fruit"), 170, 18, 260, 200, 6, 1, {FColor(96, 140, 64), FColor(108, 150, 66), FColor(88, 132, 60)}, FColor(250, 236, 238), 0.25f, FColor(96, 80, 66)},
	{TEXT("birch"), 520, 18, 260, 520, 7, 3, {FColor(130, 164, 70), FColor(116, 156, 66), FColor(146, 172, 80)}, FColor(0, 0, 0), 0.f, FColor(226, 222, 210)},
	{TEXT("shade"), 560, 42, 740, 440, 11, 1, {FColor(72, 114, 52), FColor(86, 126, 58), FColor(66, 104, 48)}, FColor(0, 0, 0), 0.f, FColor(96, 80, 64)},
	{TEXT("roof"), 140, 12, 170, 170, 5, 0, {FColor(84, 130, 58), FColor(100, 144, 64), FColor(72, 118, 54)}, FColor(214, 80, 150), 0.15f, FColor(98, 80, 62)},
	{TEXT("jacaranda"), 300, 24, 460, 260, 8, 1, {FColor(150, 120, 200), FColor(168, 138, 214), FColor(96, 136, 64)}, FColor(0, 0, 0), 0.f, FColor(96, 80, 66)},
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
} // namespace

void ASWCityTrees::AddShrub(FInstances& Out, const FVector& Base, double Radius, const FLinearColor& Tint, uint32 InSeed, double CullCm)
{
	FRng Rng(InSeed);
	const int32 N = 2 + Rng.I(2);
	for (int32 i = 0; i < N; ++i)
	{
		const double R = Radius * Rng.R(0.6, 1.0);
		const FVector Off(Rng.R(-0.5, 0.5) * Radius, Rng.R(-0.5, 0.5) * Radius, R * 0.55);
		Out.Add(P(EPrim::Blob), M(EMat::Foliage), Tint, Xf(Base + Off, FVector(R / 100, R / 100, R * 0.8 / 100), Rng.R(0, 360)), Radius > 60, CullCm);
	}
}

void ASWCityTrees::AddTree(FInstances& Out, const FString& SpeciesName, const FVector& Base, double Scale, uint32 InSeed)
{
	const FSpecies& S = FindSpecies(SpeciesName);
	FRng Rng(InSeed);
	const double K = Scale * Rng.R(0.85, 1.15);
	const double H = S.TrunkH * K, TR = S.TrunkR * K, CR = S.CrownR * K, CH = S.CrownH * K;
	const FLinearColor BarkT(S.BarkC);
	const double Lean = Rng.R(-4, 4);
	const double Yaw0 = Rng.R(0, 360);
	Out.Add(P(EPrim::Trunk), M(EMat::Bark), BarkT, Xf(Base - FVector(0, 0, 10), FVector(TR / 50, TR / 50, (H + CH * 0.4) / 100), Yaw0, Lean, 0));
	// limbs reaching into the crown
	const int32 Limbs = S.Shape == 3 ? 2 : 3 + Rng.I(2);
	for (int32 i = 0; i < Limbs; ++i)
	{
		const double Yaw = Yaw0 + 360.0 * i / Limbs + Rng.R(-20, 20);
		const double Pitch = S.Shape == 1 ? Rng.R(-55, -40) : Rng.R(-40, -25); // tilt from vertical
		const double Len = (S.Shape == 1 ? CR * 0.75 : CR * 0.55) * Rng.R(0.8, 1.1);
		const double Tilt = FMath::DegreesToRadians(-Pitch);
		const double Yr = FMath::DegreesToRadians(Yaw);
		const FVector Dir(FMath::Sin(Tilt) * FMath::Cos(Yr), FMath::Sin(Tilt) * FMath::Sin(Yr), FMath::Cos(Tilt));
		const FTransform T(FRotationMatrix::MakeFromZ(Dir).Rotator(), Base + FVector(0, 0, H * Rng.R(0.75, 0.95)), FVector(TR * 0.5 / 50, TR * 0.5 / 50, Len / 100));
		Out.Add(P(EPrim::Trunk), M(EMat::Bark), BarkT, T);
	}
	// crown blobs
	const FVector C = Base + FVector(0, 0, H + CH * (S.Shape == 1 ? 0.35 : 0.6));
	for (int32 i = 0; i < S.Blobs; ++i)
	{
		FVector Off;
		double R;
		if (i == 0)
		{
			Off = FVector::ZeroVector;
			R = (S.Shape == 3 ? CR * 0.8 : CR * 0.62);
		}
		else
		{
			const double A = 2 * PI * i / (S.Blobs - 1) + Rng.R(-0.3, 0.3);
			const double Rad = (S.Shape == 1 ? 0.62 : 0.5) * CR * Rng.R(0.8, 1.1);
			Off = FVector(FMath::Cos(A) * Rad, FMath::Sin(A) * Rad, Rng.R(-0.35, 0.45) * CH);
			R = CR * Rng.R(0.38, 0.55);
		}
		const double Vz = S.Shape == 3 ? 1.5 : (S.Shape == 1 ? 0.62 : 0.8);
		const bool bBloom = S.BloomFrac > 0 && Rng.F() < S.BloomFrac;
		const FLinearColor Tint = bBloom ? FLinearColor(S.Bloom) : FLinearColor(S.Leaf[Rng.I(3)]);
		Out.Add(P(EPrim::Blob), M(EMat::Foliage), Tint, Xf(C + Off, FVector(R / 100, R / 100, R * Vz / 100), Rng.R(0, 360)));
	}
	if (S.Shape == 2)
	{
		// willow curtain: long hanging drapes round the rim
		const int32 N = 14;
		for (int32 i = 0; i < N; ++i)
		{
			const double A = 2 * PI * i / N + Rng.R(-0.15, 0.15);
			const double Rad = CR * Rng.R(0.75, 0.95);
			const double Len = Rng.R(0.55, 0.8) * (H + CH * 0.3);
			const FVector Pc = C + FVector(FMath::Cos(A) * Rad, FMath::Sin(A) * Rad, -Len * 0.5);
			Out.Add(P(EPrim::Blob), M(EMat::Foliage), FLinearColor(S.Leaf[Rng.I(3)]), Xf(Pc, FVector(Rng.R(0.9, 1.4) * CR / 520, 0.45 * CR / 520, Len / 100), FMath::RadiansToDegrees(A) + 90));
		}
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
			AddShrub(Inst, Base, 80 * Sc, Rng.F() < 0.2 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4)), Rng.Next(), 40000);
		}
		else
		{
			AddTree(Inst, Sp, Base, Sc, Rng.Next());
		}
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
		Inst.Add(P(EPrim::Blob), M(EMat::Foliage), Col::Leaf(Rng.I(4)), Xf(FVector(0, 0, 14), FVector(0.45, 0.45, 0.22)), false, 25000);
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
		for (int32 k = 0; k < 7; ++k)
		{
			const FVector2D Pc(Rng.R(Mn.X + 1500, Mx.X - 1500), Rng.R(Mn.Y + 1200, Mx.Y - 1200));
			B.OBox(B.Slot(EMat::Fabric, Col::Flower(k)), FVector(Pc, 6), FVector(110, 80, 1), FRotator(0, Rng.R(0, 180), 0));
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
	else
	{
		B.Box(LawnS, FVector(Mn, 0), FVector(Mx, 4));
	}
	AddMesh(B);
	AddInstances(Inst);
	return true;
}
