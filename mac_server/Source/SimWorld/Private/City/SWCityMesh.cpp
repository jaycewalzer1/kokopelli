#include "City/SWCityMesh.h"

#include "Dom/JsonValue.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Materials/Material.h"
#include "MaterialShared.h"
#include "MeshDescription.h"
#include "StaticMeshAttributes.h"
#include "SWCommon.h"
#include "UObject/Package.h"

namespace
{
const TCHAR* const GMatNames[] = {
	TEXT("M_Timber"), TEXT("M_RammedEarth"), TEXT("M_SolarGlass"), TEXT("M_GreenRoof"), TEXT("M_Moss"),
	TEXT("M_Foliage"), TEXT("M_Bark"), TEXT("M_Water"), TEXT("M_PermeableStone"), TEXT("M_Path"),
	TEXT("M_Metal"), TEXT("M_Fabric"), TEXT("M_Lantern")};
static_assert(UE_ARRAY_COUNT(GMatNames) == int32(SWCity::EMat::Count), "material names");

struct FParent
{
	UMaterialInterface* Material = nullptr;
	bool bReal = false;
	bool bTried = false;
};
FParent GParents[int32(SWCity::EMat::Count)];
TMap<uint64, UMaterialInterface*> GMids;
UStaticMesh* GPrims[int32(SWCity::EPrim::Count)] = {};

FLinearColor RefColor(SWCity::EMat Mat)
{
	using namespace SWCity;
	auto S = [](uint8 R, uint8 G, uint8 B) { return FLinearColor(FColor(R, G, B)); };
	switch (Mat)
	{
	case EMat::Timber: return S(196, 148, 98);
	case EMat::RammedEarth: return S(200, 146, 92);
	case EMat::SolarGlass: return S(52, 72, 96);
	case EMat::GreenRoof: return S(112, 140, 70);
	case EMat::Moss: return S(104, 142, 66);
	case EMat::Foliage: return S(78, 124, 56);
	case EMat::Bark: return S(98, 76, 58);
	case EMat::Water: return S(64, 118, 128);
	case EMat::PermeableStone: return S(176, 166, 150);
	case EMat::Path: return S(206, 190, 160);
	case EMat::Metal: return S(196, 160, 84);
	case EMat::Lantern: return S(255, 196, 120);
	default: return FLinearColor::White; // fabric: colour as is
	}
}

FParent& Parent(SWCity::EMat Mat)
{
	FParent& P = GParents[int32(Mat)];
	if (!P.bTried)
	{
		P.bTried = true;
		const FString Name = GMatNames[int32(Mat)];
		const FString Path = FString::Printf(TEXT("/Game/Solarpunk/Materials/%s.%s"), *Name, *Name);
		P.Material = FSoftObjectPath(Path).TryLoad() ? Cast<UMaterialInterface>(FSoftObjectPath(Path).ResolveObject()) : nullptr;
		P.bReal = P.Material != nullptr;
		if (!P.Material)
		{
			P.Material = LoadObject<UMaterialInterface>(nullptr, TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"));
		}
		if (P.Material)
		{
			P.Material->AddToRoot();
#if WITH_EDITOR
			// Foliage, stones etc. are drawn as instanced static meshes. Assets saved without the
			// "Used with Instanced Static Meshes" flag render with the default material there, so set
			// the usage now (uncooked editor-game only; a packaged build needs the flag saved in the asset).
			if (UMaterial* Base = P.Material->GetMaterial())
			{
				if (!Base->GetUsageByFlag(MATUSAGE_InstancedStaticMeshes))
				{
					// UMaterial::SetMaterialUsage only does this in the editor proper (not -game), so do it here.
					{
						FMaterialUpdateContext Ctx(FMaterialUpdateContext::EOptions::SyncWithRenderingThread);
						Ctx.AddMaterial(Base);
						Base->SetUsageByFlag(MATUSAGE_InstancedStaticMeshes, true);
						Base->ForceRecompileForRendering();
					}
					UE_LOG(LogSimWorld, Warning, TEXT("City material %s lacked bUsedWithInstancedStaticMeshes; set and recompiled at runtime. Save the flag in the asset."), *Name);
				}
			}
#endif
		}
		UE_LOG(LogSimWorld, Log, TEXT("City material %s: %s"), *Name, P.bReal ? TEXT("loaded") : TEXT("missing, using BasicShapeMaterial"));
	}
	return P;
}

FVector AnyPerp(const FVector& N)
{
	const FVector T = FMath::Abs(N.Z) < 0.9 ? FVector::CrossProduct(FVector::UpVector, N) : FVector::CrossProduct(FVector::ForwardVector, N);
	return T.GetSafeNormal();
}
} // namespace

const TCHAR* SWCity::MatName(EMat Mat)
{
	return GMatNames[int32(Mat)];
}

bool SWCity::HasRealMaterial(EMat Mat)
{
	return Parent(Mat).bReal;
}

UMaterialInterface* SWCity::GetMaterial(EMat Mat, const FLinearColor& Tint, float Scale)
{
	const FColor Q = Tint.ToFColor(false);
	const uint64 Key = (uint64(FMath::Clamp(int32(Scale * 4.f), 0, 0xFFFF)) << 40) | (uint64(Mat) << 32) | Q.DWColor();
	if (UMaterialInterface** Found = GMids.Find(Key))
	{
		return *Found;
	}
	FParent& P = Parent(Mat);
	if (!P.Material)
	{
		return nullptr;
	}
	UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(P.Material, GetTransientPackage());
	if (P.bReal)
	{
		// The real materials are textured and look natural at Tint = white, so pass our colour
		// relative to the colour we picked as "natural" for that material.
		const FLinearColor Ref = RefColor(Mat);
		FLinearColor T(Tint.R / FMath::Max(Ref.R, 0.002f), Tint.G / FMath::Max(Ref.G, 0.002f), Tint.B / FMath::Max(Ref.B, 0.002f), 1.0f);
		T.R = FMath::Clamp(T.R, 0.0f, 1.8f);
		T.G = FMath::Clamp(T.G, 0.0f, 1.8f);
		T.B = FMath::Clamp(T.B, 0.0f, 1.8f);
		if (Mat == EMat::Metal && Tint.GetMax() < 0.12f)
		{
			Mid->SetScalarParameterValue(TEXT("Steel"), 1.0f); // dark steel instead of bronze
			T = FLinearColor::White;
		}
		Mid->SetVectorParameterValue(TEXT("Tint"), T);
		if (Scale > 0.f)
		{
			Mid->SetScalarParameterValue(TEXT("Scale"), Scale);
		}
	}
	else
	{
		Mid->SetVectorParameterValue(TEXT("Color"), Tint);
	}
	Mid->AddToRoot();
	GMids.Add(Key, Mid);
	return Mid;
}

FLinearColor SWCity::Srgb(uint8 R, uint8 G, uint8 B)
{
	return FLinearColor(FColor(R, G, B));
}

FLinearColor SWCity::ColorFromJson(const TArray<TSharedPtr<FJsonValue>>* Arr, const FLinearColor& Default)
{
	if (!Arr || Arr->Num() < 3)
	{
		return Default;
	}
	double C[3];
	bool bUnit = true;
	for (int32 i = 0; i < 3; ++i)
	{
		C[i] = (*Arr)[i]->AsNumber();
		bUnit &= C[i] <= 1.0;
	}
	const double K = bUnit ? 255.0 : 1.0;
	return Srgb(uint8(FMath::Clamp(C[0] * K, 0.0, 255.0)), uint8(FMath::Clamp(C[1] * K, 0.0, 255.0)), uint8(FMath::Clamp(C[2] * K, 0.0, 255.0)));
}

// ---------------------------------------------------------------------------------------------
// FSWMeshBuilder

int32 FSWMeshBuilder::Slot(SWCity::EMat Mat, const FLinearColor& Tint, float Scale)
{
	const FColor Q = Tint.ToFColor(false);
	for (int32 i = 0; i < Sections.Num(); ++i)
	{
		if (Sections[i].Mat == Mat && Sections[i].Scale == Scale && Sections[i].Tint.ToFColor(false) == Q)
		{
			return i;
		}
	}
	FSection& S = Sections.AddDefaulted_GetRef();
	S.Mat = Mat;
	S.Tint = Tint;
	S.Scale = Scale;
	return Sections.Num() - 1;
}

int32 FSWMeshBuilder::NumTris() const
{
	int32 N = 0;
	for (const FSection& S : Sections)
	{
		N += S.Idx.Num() / 3;
	}
	return N;
}

void FSWMeshBuilder::Tri(int32 SI, const FVector& A, const FVector& B, const FVector& C, const FVector& Normal)
{
	FSection& S = Sections[SI];
	// UE's front face: normal = (C-A) x (B-A) (see FStaticMeshOperations::ComputeTriangleTangentsAndNormals).
	const FVector Geo = FVector::CrossProduct(C - A, B - A);
	const bool bFlip = FVector::DotProduct(Geo, Normal) < 0.0;
	const FVector N = Normal.GetSafeNormal();
	const uint32 Base = S.Pos.Num();
	S.Pos.Add(FVector3f(A));
	S.Pos.Add(FVector3f(bFlip ? C : B));
	S.Pos.Add(FVector3f(bFlip ? B : C));
	for (int32 i = 0; i < 3; ++i)
	{
		S.Nrm.Add(FVector3f(N));
		S.Idx.Add(Base + i);
	}
}

void FSWMeshBuilder::Quad(int32 S, const FVector& A, const FVector& B, const FVector& C, const FVector& D, const FVector& Normal)
{
	Tri(S, A, B, C, Normal);
	Tri(S, A, C, D, Normal);
}

void FSWMeshBuilder::Box(int32 S, const FVector& InMin, const FVector& InMax, uint8 Skip)
{
	const FVector Mn = InMin.ComponentMin(InMax);
	const FVector Mx = InMin.ComponentMax(InMax);
	const FVector P[8] = {
		{Mn.X, Mn.Y, Mn.Z}, {Mx.X, Mn.Y, Mn.Z}, {Mx.X, Mx.Y, Mn.Z}, {Mn.X, Mx.Y, Mn.Z},
		{Mn.X, Mn.Y, Mx.Z}, {Mx.X, Mn.Y, Mx.Z}, {Mx.X, Mx.Y, Mx.Z}, {Mn.X, Mx.Y, Mx.Z}};
	if (!(Skip & 1)) Quad(S, P[0], P[3], P[7], P[4], FVector(-1, 0, 0));
	if (!(Skip & 2)) Quad(S, P[1], P[2], P[6], P[5], FVector(1, 0, 0));
	if (!(Skip & 4)) Quad(S, P[0], P[1], P[5], P[4], FVector(0, -1, 0));
	if (!(Skip & 8)) Quad(S, P[3], P[2], P[6], P[7], FVector(0, 1, 0));
	if (!(Skip & 16)) Quad(S, P[0], P[1], P[2], P[3], FVector(0, 0, -1));
	if (!(Skip & 32)) Quad(S, P[4], P[5], P[6], P[7], FVector(0, 0, 1));
}

void FSWMeshBuilder::OBox(int32 S, const FVector& C, const FVector& H, const FRotator& Rot)
{
	const FQuat Q = Rot.Quaternion();
	auto P = [&](double X, double Y, double Z) { return C + Q.RotateVector(FVector(X * H.X, Y * H.Y, Z * H.Z)); };
	const FVector X = Q.GetAxisX(), Y = Q.GetAxisY(), Z = Q.GetAxisZ();
	Quad(S, P(-1, -1, -1), P(-1, 1, -1), P(-1, 1, 1), P(-1, -1, 1), -X);
	Quad(S, P(1, -1, -1), P(1, 1, -1), P(1, 1, 1), P(1, -1, 1), X);
	Quad(S, P(-1, -1, -1), P(1, -1, -1), P(1, -1, 1), P(-1, -1, 1), -Y);
	Quad(S, P(-1, 1, -1), P(1, 1, -1), P(1, 1, 1), P(-1, 1, 1), Y);
	Quad(S, P(-1, -1, -1), P(1, -1, -1), P(1, 1, -1), P(-1, 1, -1), -Z);
	Quad(S, P(-1, -1, 1), P(1, -1, 1), P(1, 1, 1), P(-1, 1, 1), Z);
}

void FSWMeshBuilder::Beam(int32 S, const FVector& P0, const FVector& P1, double W, double H)
{
	const FVector D = P1 - P0;
	const double L = D.Size();
	if (L < 1e-3)
	{
		return;
	}
	const FVector Dir = D / L;
	FVector Side = FVector::CrossProduct(FVector::UpVector, Dir);
	if (Side.SizeSquared() < 1e-6)
	{
		Side = FVector::RightVector;
	}
	Side.Normalize();
	const FVector Up = FVector::CrossProduct(Dir, Side).GetSafeNormal();
	const FMatrix M(Dir, Side, Up, FVector::ZeroVector);
	OBox(S, (P0 + P1) * 0.5, FVector(L * 0.5, W * 0.5, H * 0.5), M.Rotator());
}

void FSWMeshBuilder::Cylinder(int32 S, const FVector& Base, double R0, double R1, double Height, int32 Segs, bool bCaps)
{
	Segs = FMath::Max(3, Segs);
	const FVector Top = Base + FVector(0, 0, Height);
	for (int32 i = 0; i < Segs; ++i)
	{
		const double A0 = 2 * PI * i / Segs, A1 = 2 * PI * (i + 1) / Segs;
		const FVector D0(FMath::Cos(A0), FMath::Sin(A0), 0), D1(FMath::Cos(A1), FMath::Sin(A1), 0);
		const FVector N = ((D0 + D1) * 0.5).GetSafeNormal();
		Quad(S, Base + D0 * R0, Base + D1 * R0, Top + D1 * R1, Top + D0 * R1, N);
		if (bCaps)
		{
			if (R1 > 0) Tri(S, Top, Top + D0 * R1, Top + D1 * R1, FVector::UpVector);
			if (R0 > 0) Tri(S, Base, Base + D0 * R0, Base + D1 * R0, -FVector::UpVector);
		}
	}
}

void FSWMeshBuilder::Pole(int32 S, const FVector& P0, const FVector& P1, double R, int32 Segs)
{
	const FVector D = P1 - P0;
	const double L = D.Size();
	if (L < 1e-3)
	{
		return;
	}
	const FVector Z = D / L;
	const FVector X = AnyPerp(Z);
	const FVector Y = FVector::CrossProduct(Z, X);
	for (int32 i = 0; i < Segs; ++i)
	{
		const double A0 = 2 * PI * i / Segs, A1 = 2 * PI * (i + 1) / Segs;
		const FVector D0 = X * FMath::Cos(A0) + Y * FMath::Sin(A0), D1 = X * FMath::Cos(A1) + Y * FMath::Sin(A1);
		Quad(S, P0 + D0 * R, P0 + D1 * R, P1 + D1 * R, P1 + D0 * R, (D0 + D1).GetSafeNormal());
	}
}

void FSWMeshBuilder::Prism(int32 S, const TArray<FVector2D>& Poly, double Z0, double Z1, bool bBottom)
{
	const int32 N = Poly.Num();
	if (N < 3)
	{
		return;
	}
	FVector2D C(0, 0);
	for (const FVector2D& P : Poly) C += P;
	C /= N;
	for (int32 i = 0; i < N; ++i)
	{
		const FVector2D& A = Poly[i];
		const FVector2D& B = Poly[(i + 1) % N];
		Tri(S, FVector(C, Z1), FVector(A, Z1), FVector(B, Z1), FVector::UpVector);
		if (bBottom) Tri(S, FVector(C, Z0), FVector(A, Z0), FVector(B, Z0), -FVector::UpVector);
		FVector2D E = B - A;
		FVector2D Out(E.Y, -E.X);
		if (FVector2D::DotProduct(Out, A - C) < 0) Out = -Out;
		Quad(S, FVector(A, Z0), FVector(B, Z0), FVector(B, Z1), FVector(A, Z1), FVector(Out.GetSafeNormal(), 0));
	}
}

void FSWMeshBuilder::Ribbon(int32 S, const TArray<FVector2D>& Pts, double W, double Z0, double Z1, double Offset)
{
	const int32 N = Pts.Num();
	if (N < 2)
	{
		return;
	}
	TArray<FVector2D> L, R;
	for (int32 i = 0; i < N; ++i)
	{
		const FVector2D Din = i > 0 ? (Pts[i] - Pts[i - 1]).GetSafeNormal() : (Pts[1] - Pts[0]).GetSafeNormal();
		const FVector2D Dout = i < N - 1 ? (Pts[i + 1] - Pts[i]).GetSafeNormal() : Din;
		FVector2D T = (Din + Dout).GetSafeNormal();
		if (T.IsNearlyZero()) T = Dout;
		const FVector2D Nrm(-T.Y, T.X);
		const FVector2D Nin(-Din.Y, Din.X);
		const double Miter = 1.0 / FMath::Max(0.3, FVector2D::DotProduct(Nrm, Nin));
		L.Add(Pts[i] + Nrm * (Offset + W * 0.5) * Miter);
		R.Add(Pts[i] + Nrm * (Offset - W * 0.5) * Miter);
	}
	for (int32 i = 0; i < N - 1; ++i)
	{
		Quad(S, FVector(L[i], Z1), FVector(L[i + 1], Z1), FVector(R[i + 1], Z1), FVector(R[i], Z1), FVector::UpVector);
		const FVector2D D = (Pts[i + 1] - Pts[i]).GetSafeNormal();
		const FVector2D Nl(-D.Y, D.X);
		Quad(S, FVector(L[i], Z0), FVector(L[i + 1], Z0), FVector(L[i + 1], Z1), FVector(L[i], Z1), FVector(Nl, 0));
		Quad(S, FVector(R[i], Z0), FVector(R[i + 1], Z0), FVector(R[i + 1], Z1), FVector(R[i], Z1), FVector(-Nl, 0));
	}
	// end caps
	{
		const FVector2D D = (Pts[1] - Pts[0]).GetSafeNormal();
		Quad(S, FVector(L[0], Z0), FVector(R[0], Z0), FVector(R[0], Z1), FVector(L[0], Z1), FVector(-D, 0));
		const FVector2D E = (Pts[N - 1] - Pts[N - 2]).GetSafeNormal();
		Quad(S, FVector(L[N - 1], Z0), FVector(R[N - 1], Z0), FVector(R[N - 1], Z1), FVector(L[N - 1], Z1), FVector(E, 0));
	}
}

void FSWMeshBuilder::Ellipsoid(int32 SI, const FVector& C, const FVector& R, int32 Segs, int32 Rings, bool bHemi)
{
	FSection& S = Sections[SI];
	const uint32 Base = S.Pos.Num();
	const int32 R0 = 0;
	for (int32 r = R0; r <= Rings; ++r)
	{
		const double Phi = (bHemi ? 0.5 * PI : PI) * r / Rings; // from top
		for (int32 s = 0; s <= Segs; ++s)
		{
			const double Th = 2 * PI * s / Segs;
			const FVector U(FMath::Sin(Phi) * FMath::Cos(Th), FMath::Sin(Phi) * FMath::Sin(Th), FMath::Cos(Phi));
			S.Pos.Add(FVector3f(C + U * R));
			S.Nrm.Add(FVector3f((U / R).GetSafeNormal()));
		}
	}
	const int32 Row = Segs + 1;
	for (int32 r = 0; r < Rings; ++r)
	{
		for (int32 s = 0; s < Segs; ++s)
		{
			const uint32 A = Base + r * Row + s, B = A + 1, Cc = A + Row, D = Cc + 1;
			// outward front face: normal = (C-A)x(B-A) must point out
			const FVector PA(S.Pos[A]), PB(S.Pos[B]), PC(S.Pos[Cc]), PD(S.Pos[D]);
			const FVector Mid = (PA + PB + PC + PD) * 0.25;
			auto Add = [&](uint32 I0, uint32 I1, uint32 I2)
			{
				const FVector P0(S.Pos[I0]), P1(S.Pos[I1]), P2(S.Pos[I2]);
				const FVector G = FVector::CrossProduct(P2 - P0, P1 - P0);
				if (G.SizeSquared() < 1e-8) return;
				if (FVector::DotProduct(G, Mid - C) < 0) Swap(I1, I2);
				S.Idx.Add(I0); S.Idx.Add(I1); S.Idx.Add(I2);
			};
			Add(A, B, D);
			Add(A, D, Cc);
		}
	}
}

void FSWMeshBuilder::Gable(int32 S, const FVector& Mn, const FVector& Mx, double RidgeH, bool bX)
{
	const double Z = Mx.Z;
	if (bX)
	{
		const double Ym = (Mn.Y + Mx.Y) * 0.5;
		const FVector A(Mn.X, Mn.Y, Z), B(Mx.X, Mn.Y, Z), C(Mx.X, Ym, Z + RidgeH), D(Mn.X, Ym, Z + RidgeH);
		const FVector E(Mn.X, Mx.Y, Z), F(Mx.X, Mx.Y, Z);
		Quad(S, A, B, C, D, FVector(0, -RidgeH, (Mx.Y - Mn.Y) * 0.5).GetSafeNormal());
		Quad(S, E, F, C, D, FVector(0, RidgeH, (Mx.Y - Mn.Y) * 0.5).GetSafeNormal());
		Tri(S, A, E, D, FVector(-1, 0, 0));
		Tri(S, B, F, C, FVector(1, 0, 0));
	}
	else
	{
		const double Xm = (Mn.X + Mx.X) * 0.5;
		const FVector A(Mn.X, Mn.Y, Z), B(Mn.X, Mx.Y, Z), C(Xm, Mx.Y, Z + RidgeH), D(Xm, Mn.Y, Z + RidgeH);
		const FVector E(Mx.X, Mn.Y, Z), F(Mx.X, Mx.Y, Z);
		Quad(S, A, B, C, D, FVector(-RidgeH, 0, (Mx.X - Mn.X) * 0.5).GetSafeNormal());
		Quad(S, E, F, C, D, FVector(RidgeH, 0, (Mx.X - Mn.X) * 0.5).GetSafeNormal());
		Tri(S, A, E, D, FVector(0, -1, 0));
		Tri(S, B, F, C, FVector(0, 1, 0));
	}
}

void FSWMeshBuilder::Vault(int32 S, const FVector& Mn, const FVector& Mx, double Rise, bool bX, double T, int32 Segs)
{
	// Elliptic arch across the short axis, extruded along the vault axis.
	const double Half = bX ? (Mx.Y - Mn.Y) * 0.5 : (Mx.X - Mn.X) * 0.5;
	const double Mid = bX ? (Mx.Y + Mn.Y) * 0.5 : (Mx.X + Mn.X) * 0.5;
	const double A0 = bX ? Mn.X : Mn.Y, A1 = bX ? Mx.X : Mx.Y;
	auto P = [&](double Along, double Across, double Z) { return bX ? FVector(Along, Across, Z) : FVector(Across, Along, Z); };
	for (int32 i = 0; i < Segs; ++i)
	{
		const double T0 = PI * i / Segs, T1 = PI * (i + 1) / Segs;
		for (int32 Layer = 0; Layer < 2; ++Layer)
		{
			const double Hr = Layer == 0 ? Half : Half - T;
			const double Rr = Layer == 0 ? Rise : Rise - T;
			const double c0 = Mid - FMath::Cos(T0) * Hr, z0 = Mn.Z + FMath::Sin(T0) * Rr;
			const double c1 = Mid - FMath::Cos(T1) * Hr, z1 = Mn.Z + FMath::Sin(T1) * Rr;
			FVector N = bX ? FVector(0, -FMath::Cos((T0 + T1) * 0.5) * Rise, FMath::Sin((T0 + T1) * 0.5) * Half)
						   : FVector(-FMath::Cos((T0 + T1) * 0.5) * Rise, 0, FMath::Sin((T0 + T1) * 0.5) * Half);
			N.Normalize();
			if (Layer == 1) N = -N;
			Quad(S, P(A0, c0, z0), P(A1, c0, z0), P(A1, c1, z1), P(A0, c1, z1), N);
		}
	}
}

UStaticMesh* FSWMeshBuilder::Build(UObject* Outer, const FString& DebugName) const
{
	if (IsEmpty())
	{
		return nullptr;
	}
	FMeshDescription MD;
	FStaticMeshAttributes Attr(MD);
	Attr.Register();
	TVertexAttributesRef<FVector3f> Pos = Attr.GetVertexPositions();
	TVertexInstanceAttributesRef<FVector3f> Nrm = Attr.GetVertexInstanceNormals();
	TVertexInstanceAttributesRef<FVector3f> Tan = Attr.GetVertexInstanceTangents();
	TVertexInstanceAttributesRef<float> Sign = Attr.GetVertexInstanceBinormalSigns();
	TVertexInstanceAttributesRef<FVector2f> UVs = Attr.GetVertexInstanceUVs();
	TVertexInstanceAttributesRef<FVector4f> Colors = Attr.GetVertexInstanceColors();
	TPolygonGroupAttributesRef<FName> SlotNames = Attr.GetPolygonGroupMaterialSlotNames();
	UVs.SetNumChannels(1);

	int32 NV = 0, NT = 0;
	for (const FSection& S : Sections) { NV += S.Pos.Num(); NT += S.Idx.Num() / 3; }
	MD.ReserveNewVertices(NV);
	MD.ReserveNewVertexInstances(NV);
	MD.ReserveNewTriangles(NT);
	MD.ReserveNewPolygons(NT);
	MD.ReserveNewEdges(NT * 3);

	UStaticMesh* Mesh = NewObject<UStaticMesh>(Outer, NAME_None, RF_Transient);
	TArray<FVertexInstanceID> Inst;
	for (int32 SI = 0; SI < Sections.Num(); ++SI)
	{
		const FSection& S = Sections[SI];
		if (S.Idx.Num() == 0)
		{
			continue;
		}
		const FName SlotName(*FString::Printf(TEXT("S%d_%s"), SI, SWCity::MatName(S.Mat)));
		const FPolygonGroupID G = MD.CreatePolygonGroup();
		SlotNames[G] = SlotName;
		Mesh->GetStaticMaterials().Add(FStaticMaterial(SWCity::GetMaterial(S.Mat, S.Tint, S.Scale), SlotName, SlotName));
		Inst.Reset(S.Pos.Num());
		for (int32 i = 0; i < S.Pos.Num(); ++i)
		{
			const FVertexID V = MD.CreateVertex();
			Pos[V] = S.Pos[i];
			const FVertexInstanceID I = MD.CreateVertexInstance(V);
			const FVector3f N = S.Nrm[i];
			Nrm[I] = N;
			Tan[I] = FVector3f(AnyPerp(FVector(N)));
			Sign[I] = 1.0f;
			// box projection (materials are world aligned; this is only a sane default)
			const FVector3f A = N.GetAbs();
			const FVector3f P = S.Pos[i] / 100.0f;
			UVs.Set(I, 0, A.Z >= A.X && A.Z >= A.Y ? FVector2f(P.X, P.Y) : (A.X >= A.Y ? FVector2f(P.Y, P.Z) : FVector2f(P.X, P.Z)));
			Colors[I] = FVector4f(1, 1, 1, 1);
			Inst.Add(I);
		}
		for (int32 t = 0; t + 2 < S.Idx.Num(); t += 3)
		{
			MD.CreateTriangle(G, {Inst[S.Idx[t]], Inst[S.Idx[t + 1]], Inst[S.Idx[t + 2]]});
		}
	}

	UStaticMesh::FBuildMeshDescriptionsParams Params;
	Params.bMarkPackageDirty = false;
	Params.bUseHashAsGuid = false;
	Params.bBuildSimpleCollision = false;
	Params.bCommitMeshDescription = false;
	Params.bFastBuild = true;
	Params.bAllowCpuAccess = false;
	TArray<const FMeshDescription*> Descs{&MD};
	if (!Mesh->BuildFromMeshDescriptions(Descs, Params))
	{
		UE_LOG(LogSimWorld, Error, TEXT("City mesh %s: BuildFromMeshDescriptions failed"), *DebugName);
		return nullptr;
	}
	return Mesh;
}

// ---------------------------------------------------------------------------------------------
// Primitives

UStaticMesh* SWCity::GetPrim(EPrim Prim)
{
	UStaticMesh*& Slot = GPrims[int32(Prim)];
	if (Slot)
	{
		return Slot;
	}
	FSWMeshBuilder B;
	const int32 S = B.Slot(EMat::Foliage, FLinearColor::White);
	switch (Prim)
	{
	case EPrim::Blob:
	case EPrim::Stone:
	case EPrim::Puff:
	{
		// Icosahedron subdivided once, vertices jittered: soft, slightly lumpy blob.
		const double t = (1.0 + FMath::Sqrt(5.0)) / 2.0;
		TArray<FVector> V = {{-1, t, 0}, {1, t, 0}, {-1, -t, 0}, {1, -t, 0}, {0, -1, t}, {0, 1, t}, {0, -1, -t}, {0, 1, -t}, {t, 0, -1}, {t, 0, 1}, {-t, 0, -1}, {-t, 0, 1}};
		TArray<FIntVector> F = {{0, 11, 5}, {0, 5, 1}, {0, 1, 7}, {0, 7, 10}, {0, 10, 11}, {1, 5, 9}, {5, 11, 4}, {11, 10, 2}, {10, 7, 6}, {7, 1, 8},
			{3, 9, 4}, {3, 4, 2}, {3, 2, 6}, {3, 6, 8}, {3, 8, 9}, {4, 9, 5}, {2, 4, 11}, {6, 2, 10}, {8, 6, 7}, {9, 8, 1}};
		for (FVector& P : V) P.Normalize();
		TMap<uint64, int32> MidCache;
		auto MidPt = [&](int32 A, int32 Bv)
		{
			const uint64 K = A < Bv ? (uint64(A) << 32 | Bv) : (uint64(Bv) << 32 | A);
			if (int32* Found = MidCache.Find(K)) return *Found;
			const int32 I = V.Add(((V[A] + V[Bv]) * 0.5).GetSafeNormal());
			MidCache.Add(K, I);
			return I;
		};
		TArray<FIntVector> F2;
		for (const FIntVector& Fa : F)
		{
			const int32 a = MidPt(Fa.X, Fa.Y), b = MidPt(Fa.Y, Fa.Z), c = MidPt(Fa.Z, Fa.X);
			F2.Append({{Fa.X, a, c}, {Fa.Y, b, a}, {Fa.Z, c, b}, {a, b, c}});
		}
		FRng Rng(Prim == EPrim::Blob ? 7 : (Prim == EPrim::Puff ? 23 : 11));
		const FVector Scale = Prim == EPrim::Stone ? FVector(100, 80, 45) : FVector(100, 100, 100);
		const double Jit = Prim == EPrim::Stone ? 0.22 : (Prim == EPrim::Puff ? 0.16 : 0.13);
		for (FVector& P : V)
		{
			P = P * Scale * (1.0 + Rng.R(-Jit, Jit));
			// Puff: cumulus cushion, round top and a flattened, slightly concave underside (reads as a layer)
			if (Prim == EPrim::Puff && P.Z < 0) P.Z *= 0.6;
		}
		FSWMeshBuilder::FSection& Sec = B.Sections[S];
		// smooth normals: average of adjacent faces
		TArray<FVector> Acc;
		Acc.SetNumZeroed(V.Num());
		for (const FIntVector& Fa : F2)
		{
			const FVector N = FVector::CrossProduct(V[Fa.Y] - V[Fa.X], V[Fa.Z] - V[Fa.X]);
			Acc[Fa.X] += N; Acc[Fa.Y] += N; Acc[Fa.Z] += N;
		}
		for (int32 i = 0; i < V.Num(); ++i)
		{
			Sec.Pos.Add(FVector3f(V[i]));
			FVector N = Acc[i].GetSafeNormal();
			if (FVector::DotProduct(N, V[i]) < 0) N = -N;
			Sec.Nrm.Add(FVector3f(N));
		}
		for (const FIntVector& Fa : F2)
		{
			int32 A = Fa.X, Bi = Fa.Y, C = Fa.Z;
			const FVector G = FVector::CrossProduct(V[C] - V[A], V[Bi] - V[A]);
			if (FVector::DotProduct(G, V[A] + V[Bi] + V[C]) < 0) Swap(Bi, C);
			Sec.Idx.Append({uint32(A), uint32(Bi), uint32(C)});
		}
		break;
	}
	case EPrim::Trunk:
		B.Cylinder(S, FVector::ZeroVector, 50, 28, 100, 7, true);
		break;
	case EPrim::Cube:
		B.Box(S, FVector(-50), FVector(50));
		break;
	case EPrim::Cylinder:
		B.Cylinder(S, FVector::ZeroVector, 50, 50, 100, 12, true);
		break;
	case EPrim::Reed:
		B.Cylinder(S, FVector::ZeroVector, 4, 0, 100, 4, false);
		break;
	case EPrim::Disc:
		B.Cylinder(S, FVector::ZeroVector, 50, 50, 4, 10, true);
		break;
	case EPrim::Fringe:
	{
		// 9 overlapping strands hanging from a common top line, ragged hem, slight outward bow (+Y).
		// The foliage material is two-sided, so one face per strand is enough.
		FRng Rng(31);
		const int32 Ns = 9;
		const double Pitch = 100.0 / Ns;
		for (int32 i = 0; i < Ns; ++i)
		{
			const double X = -50 + Pitch * (i + 0.5) + Rng.R(-2, 2);
			const double Len = 100.0 * (i % 2 ? Rng.R(0.62, 0.85) : Rng.R(0.85, 1.0));
			const double W0 = Pitch * 0.8, W1 = Pitch * 0.42, W2 = Pitch * 0.1;
			const double Y0 = (i % 2) ? 2.5 : -2.5;
			const FVector A0(X - W0, Y0, 0), A1(X + W0, Y0, 0);
			const FVector M0(X - W1, Y0 + 7, -Len * 0.5), M1(X + W1, Y0 + 7, -Len * 0.5);
			const FVector T0(X - W2, Y0 + 4, -Len), T1(X + W2, Y0 + 4, -Len);
			B.Quad(S, A0, A1, M1, M0, FVector(0, 1, -0.1));
			B.Quad(S, M0, M1, T1, T0, FVector(0, 1, 0.1));
		}
		break;
	}
	case EPrim::Cone:
	{
		const double Tiers[3][3] = {{50, 0, 55}, {40, 28, 80}, {28, 56, 100}}; // radius, base z, apex z
		for (const auto& T : Tiers)
		{
			const int32 Segs = 8;
			const FVector Apex(0, 0, T[2]);
			for (int32 i = 0; i < Segs; ++i)
			{
				const double A0 = 2 * PI * i / Segs, A1 = 2 * PI * (i + 1) / Segs;
				const FVector P0(FMath::Cos(A0) * T[0], FMath::Sin(A0) * T[0], T[1]), P1(FMath::Cos(A1) * T[0], FMath::Sin(A1) * T[0], T[1]);
				const FVector Mid = (P0 + P1) * 0.5;
				const FVector N = FVector(Mid.X, Mid.Y, 0).GetSafeNormal() * (T[2] - T[1]) + FVector(0, 0, T[0]);
				B.Tri(S, Apex, P0, P1, N.GetSafeNormal());
				B.Tri(S, FVector(0, 0, T[1] + 6), P0, P1, -FVector::UpVector);
			}
		}
		break;
	}
	default:
		break;
	}
	Slot = B.Build(GetTransientPackage(), TEXT("CityPrim"));
	if (Slot)
	{
		Slot->AddToRoot();
	}
	return Slot;
}
