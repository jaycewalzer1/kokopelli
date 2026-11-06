#include "City/SWCityActors.h"

#include "City/SWCityJson.h"
#include "City/SWCityMesh.h"
#include "SWCommon.h"

using namespace SWCity;
namespace J = SWCity::Json;

namespace
{
FTransform Xf(const FVector& Loc, const FVector& Scale, double Yaw = 0.0)
{
	return FTransform(FRotator(0, Yaw, 0), Loc, Scale);
}
uint8 P(EPrim Prim) { return uint8(Prim); }
uint8 M(EMat Mat) { return uint8(Mat); }

/**
 * Bar frame: u along the long axis, v across. Map() turns (u, v, z) into actor-local cm.
 * Boxes are axis aligned in both frames, so a swap is enough (winding is fixed from normals).
 */
struct FBarFrame
{
	bool bX = true;
	FVector Map(double U, double V, double Z) const { return bX ? FVector(U, V, Z) : FVector(V, U, Z); }
	FVector MapN(double U, double V, double Z) const { return bX ? FVector(U, V, Z) : FVector(V, U, Z); }
	FVector2D Unmap(const FVector2D& P) const { return bX ? P : FVector2D(P.Y, P.X); }
};

/** Everything a bar-style building needs while it is built. */
struct FBar
{
	FSWMeshBuilder& B;
	ASWCityActor::FInstances& Inst;
	FRng& Rng;
	FBarFrame F;
	double Lu = 0, D = 0; // long length, depth
	int32 N = 1;
	double FH = 350, H = 350;
	TArray<FBox2D> Clear; // (u,v) rects kept free of roof clutter
	FVector Off = FVector::ZeroVector; // footprint centre in actor-local cm

	FBar(FSWMeshBuilder& InB, ASWCityActor::FInstances& InI, FRng& InR) : B(InB), Inst(InI), Rng(InR) {}

	void Box(int32 S, double U0, double U1, double V0, double V1, double Z0, double Z1)
	{
		B.Box(S, F.Map(U0, V0, Z0) + Off, F.Map(U1, V1, Z1) + Off);
	}
	/** Box on a face: T along the face, Dd along the outward normal (0 = face plane), for face Axis (true = v face). */
	void FaceBox(int32 S, bool bVFace, double Plane, double Out, double T0, double T1, double D0, double D1, double Z0, double Z1)
	{
		if (bVFace) Box(S, T0, T1, Plane + Out * D0, Plane + Out * D1, Z0, Z1);
		else Box(S, Plane + Out * D0, Plane + Out * D1, T0, T1, Z0, Z1);
	}
	FVector FacePt(bool bVFace, double Plane, double Out, double T, double Dd, double Z) const
	{
		return bVFace ? F.Map(T, Plane + Out * Dd, Z) : F.Map(Plane + Out * Dd, T, Z);
	}
	bool Cleared(double U, double V) const
	{
		for (const FBox2D& C : Clear)
			if (C.IsInside(FVector2D(U, V))) return true;
		return false;
	}
	void Shrub(const FVector& Pt, double R, double FlowerChance = 0.25)
	{
		ASWCityTrees::AddShrub(Inst, Pt, R, Rng.F() < FlowerChance ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4)), Rng.Next(), 35000);
	}
	/** Hanging greenery from Top (a planter lip): trailing chains of shrinking blobs falling outward/down. */
	void Drapes(const FVector& Top, const FVector& Along, const FVector& Out, double Width, int32 Count, double MaxLen)
	{
		const double Yaw = FMath::RadiansToDegrees(FMath::Atan2(Along.Y, Along.X));
		for (int32 i = 0; i < Count; ++i)
		{
			const double Len = Rng.R(0.4, 1.0) * MaxLen;
			const bool bBloom = Rng.F() < 0.1;
			const FLinearColor T = bBloom ? Col::Flower(Rng.F() < 0.6 ? 0 : Rng.I(6)) : Col::Leaf(Rng.I(4));
			FVector C = Top + Along * Rng.R(-0.5, 0.5) * Width + Out * 8;
			double R = Rng.R(34, 48);
			double Fallen = 0;
			// a leafy curtain: wide flat blobs that overlap, narrowing as they fall
			while (Fallen < Len && R > 10)
			{
				Inst.Add(P(EPrim::Blob), M(EMat::Foliage), T, Xf(C - FVector(0, 0, R * 0.7), FVector(R * 1.6 / 100, R * 0.45 / 100, R * 1.0 / 100), Yaw), false, 35000);
				C += Out * R * 0.08 - FVector(0, 0, R * 0.95);
				Fallen += R * 0.95;
				R *= Rng.R(0.82, 0.92);
			}
		}
	}

};

bool Has(const FString& S, const TCHAR* Word) { return S.Contains(Word, ESearchCase::IgnoreCase); }
} // namespace

// =============================================================================================
// Buildings

bool ASWCityBuilding::Build(const TSharedPtr<FJsonObject>& Obj, FString& Error)
{
	FVector2D Mn, Mx;
	if (!J::Rect(Obj, TEXT("rect_cm"), Mn, Mx))
	{
		Error = TEXT("rect_cm missing");
		return false;
	}
	Mn = L2(Mn);
	Mx = L2(Mx);
	const FString Kind = J::Str(Obj, TEXT("kind"), TEXT("bar"));
	const FString Mats = J::Str(Obj, TEXT("materials"));
	const int32 Floors = FMath::Max(1, int32(J::Num(Obj, TEXT("floors"), 1)));
	const double Height = J::Num(Obj, TEXT("height_cm"), Floors * 350.0);
	const double Walk = J::Num(Obj, TEXT("walk_cm"), -1e9);
	const FString Feature = J::Str(Obj, TEXT("rooftop_feature"));
	const TArray<FString> Street = J::Strs(Obj, TEXT("street_sides"));
	TArray<FLinearColor> Pal = J::Palette(Obj);
	while (Pal.Num() < 3) Pal.Add(Pal.Num() ? Pal.Last() : Col::Timber());

	FSWMeshBuilder B;
	FInstances Inst;
	FRng Rng(Seed);
	const FVector2D Sz = Mx - Mn;
	const FVector2D Ctr = (Mn + Mx) * 0.5;

	const int32 Wood = B.Slot(EMat::Timber, Col::Timber());
	const int32 WoodDark = B.Slot(EMat::Timber, Col::TimberDark());
	const int32 WoodWash = B.Slot(EMat::Timber, FMath::Lerp(Col::Timber(), Pal[1], 0.22f));
	const int32 Glass = B.Slot(EMat::SolarGlass, Col::Glass());
	const int32 GlassLight = B.Slot(EMat::SolarGlass, Col::GlassWarm());
	const int32 Green = B.Slot(EMat::GreenRoof, Col::GreenRoof());
	const int32 Trim = B.Slot(EMat::Metal, Pal[2]);
	const int32 Accent = B.Slot(EMat::Fabric, Pal[0]);
	const int32 Accent2 = B.Slot(EMat::Fabric, FLinearColor::LerpUsingHSV(Pal[1], FLinearColor::White, 0.3f));
	const int32 StoneS = B.Slot(EMat::PermeableStone, Col::StoneDark());
	const FLinearColor EarthC = FMath::Lerp(Rng.F() < 0.5 ? Col::Ochre() : Col::Rose(), Pal[0], 0.05f);
	const int32 Earth = B.Slot(EMat::RammedEarth, EarthC);
	const int32 Earth2 = B.Slot(EMat::RammedEarth, EarthC * 0.86f);
	const int32 LeafWall = B.Slot(EMat::Foliage, Col::Leaf(1));

	// ---------------- special civic kinds -------------------------------------------------
	if (Kind == TEXT("market_hall"))
	{
		const bool bX = Sz.X >= Sz.Y;
		FBarFrame Fr{bX};
		const double Lu = bX ? Sz.X : Sz.Y, Dd = bX ? Sz.Y : Sz.X;
		const double Spring = Height * 0.62, Rise = Height - Spring;
		auto BoxF = [&](int32 S, double U0, double U1, double V0, double V1, double Z0, double Z1)
		{ B.Box(S, Fr.Map(U0, V0, Z0) + FVector(Ctr, 0), Fr.Map(U1, V1, Z1) + FVector(Ctr, 0)); };
		BoxF(StoneS, -Lu / 2 - 100, Lu / 2 + 100, -Dd / 2 - 100, Dd / 2 + 100, 0, 15);
		// branching timber columns (bamboo-pavilion like) carrying edge beams
		for (double U = -Lu / 2 + 150; U <= Lu / 2 - 149; U += (Lu - 300) / FMath::Max(1.0, FMath::RoundToDouble((Lu - 300) / 600)))
		{
			for (int32 Side = -1; Side <= 1; Side += 2)
			{
				const double V = Side * (Dd / 2 - 150);
				const FVector Base = Fr.Map(U, V, 15) + FVector(Ctr, 0);
				B.Cylinder(Wood, Base, 26, 20, Spring * 0.62, 8);
				const FVector Fork = Base + FVector(0, 0, Spring * 0.62);
				const FVector UA = Fr.MapN(1, 0, 0);
				B.Pole(Wood, Fork, Fork + UA * 180 + FVector(0, 0, Spring * 0.38), 12, 6);
				B.Pole(Wood, Fork, Fork - UA * 180 + FVector(0, 0, Spring * 0.38), 12, 6);
				B.Pole(Wood, Fork, Fork + Fr.MapN(0, -Side, 0) * 160 + FVector(0, 0, Spring * 0.38), 12, 6);
			}
		}
		for (int32 Side = -1; Side <= 1; Side += 2)
			BoxF(WoodDark, -Lu / 2, Lu / 2, Side * (Dd / 2 - 150) - 25, Side * (Dd / 2 - 150) + 25, Spring - 40, Spring);
		const FVector VMin = Fr.Map(-Lu / 2 - 100, -Dd / 2 + 100, Spring) + FVector(Ctr, 0);
		const FVector VMax = Fr.Map(Lu / 2 + 100, Dd / 2 - 100, Spring) + FVector(Ctr, 0);
		B.Vault(Wood, VMin.ComponentMin(VMax), VMin.ComponentMax(VMax), Rise, bX, 30, 18);
		// darker glulam ribs every 6 m and a solar-glass crown strip
		for (double U = -Lu / 2; U <= Lu / 2 + 1; U += 600)
		{
			const FVector R0 = Fr.Map(U - 20, -Dd / 2 + 100, Spring) + FVector(Ctr, 0);
			const FVector R1 = Fr.Map(U + 20, Dd / 2 - 100, Spring) + FVector(Ctr, 0);
			FVector Lo = R0.ComponentMin(R1), Hi = R0.ComponentMax(R1);
			B.Vault(WoodDark, Lo - FVector(0, 0, 0), Hi, Rise + 12, bX, 45, 18);
		}
		BoxF(Glass, -Lu / 2 + 100, Lu / 2 - 100, -260, 260, Height - 20, Height + 12);
		// stalls and long tables inside
		for (double U = -Lu / 2 + 500; U < Lu / 2 - 500; U += 700)
		{
			BoxF(Wood, U - 250, U + 250, -60, 60, 72, 80);
			BoxF(WoodDark, U - 230, U - 210, -40, 40, 15, 72);
			BoxF(WoodDark, U + 210, U + 230, -40, 40, 15, 72);
			for (int32 Side = -1; Side <= 1; Side += 2)
			{
				const double V = Side * (Dd / 2 - 500);
				BoxF(Wood, U - 120, U + 120, V - 80, V + 80, 15, 100);
				const FVector G0 = Fr.Map(U - 150, V - 110, 230) + FVector(Ctr, 0), G1 = Fr.Map(U + 150, V + 110, 230) + FVector(Ctr, 0);
				B.Gable(B.Slot(EMat::Fabric, Pal[Rng.I(3)]), G0.ComponentMin(G1), G0.ComponentMax(G1), 50, bX);
				for (int32 c = 0; c < 4; ++c)
				{
					const FVector Pp = Fr.Map(U + ((c & 1) ? 130 : -130), V + ((c & 2) ? 90 : -90), 15) + FVector(Ctr, 0);
					B.Box(WoodDark, Pp - FVector(5, 5, 0), Pp + FVector(5, 5, 215));
				}
				for (int32 k = 0; k < 5; ++k)
					Inst.Add(P(EPrim::Blob), M(EMat::Foliage), k % 2 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4)), Xf(Fr.Map(U + Rng.R(-90, 90), V + Rng.R(-60, 60), 108) + FVector(Ctr, 0), FVector(0.16)), false, 25000);
			}
		}
		// hanging planters from the edge beams
		for (double U = -Lu / 2 + 300; U < Lu / 2 - 200; U += 600)
		{
			for (int32 Side = -1; Side <= 1; Side += 2)
			{
				const FVector Top = Fr.Map(U, Side * (Dd / 2 - 150), Spring - 60) + FVector(Ctr, 0);
				B.Cylinder(B.Slot(EMat::RammedEarth, Col::Rose()), Top - FVector(0, 0, 40), 35, 45, 40, 8);
				FBar Tmp(B, Inst, Rng);
				Tmp.Drapes(Top, Fr.MapN(1, 0, 0), FVector(0, 0, 0), 60, 3, 220);
			}
		}
		AddCollisionBox(FVector(Mn, Spring), FVector(Mx, Height));
		AddMesh(B);
		AddInstances(Inst);
		return true;
	}

	if (Kind == TEXT("mobility_hub"))
	{
		B.Box(StoneS, FVector(Mn, 0), FVector(Mx, 10));
		const int32 Pv = B.Slot(EMat::SolarGlass, Col::Glass());
		for (double X = Mn.X + 300; X < Mx.X - 200; X += 600)
		{
			for (double Y = Mn.Y + 300; Y < Mx.Y - 200; Y += 900)
			{
				B.Cylinder(Wood, FVector(X, Y, 10), 18, 15, 360, 8);
				B.Pole(Wood, FVector(X, Y, 340), FVector(X, Y - 300, 400), 10);
				B.Pole(Wood, FVector(X, Y, 340), FVector(X, Y + 300, 400), 10);
			}
		}
		for (double Y = Mn.Y + 150; Y < Mx.Y - 100; Y += 450)
		{
			// sawtooth PV rows facing south
			B.OBox(Pv, FVector(Ctr.X, Y + 225, Height - 40), FVector(Sz.X * 0.5 - 50, 230, 4), FRotator(0, 0, 12));
			B.Box(WoodDark, FVector(Mn.X + 50, Y + 5, Height - 110), FVector(Mx.X - 50, Y + 25, Height - 70));
		}
		// parcel lockers and bike rows
		B.Box(Trim, FVector(Mn.X + 100, Mx.Y - 220, 10), FVector(Mn.X + 900, Mx.Y - 120, 220));
		B.Box(Accent, FVector(Mn.X + 100, Mx.Y - 225, 200), FVector(Mn.X + 900, Mx.Y - 215, 220));
		const int32 MetalS = B.Slot(EMat::Metal, Col::Metal());
		for (double Y = Mn.Y + 500; Y < Mx.Y - 600; Y += 600)
		{
			for (double X = Mn.X + 400; X < Mx.X - 300; X += 90)
			{
				B.Pole(MetalS, FVector(X, Y - 50, 10), FVector(X, Y - 50, 80), 2.5, 4);
				B.Pole(MetalS, FVector(X, Y + 50, 10), FVector(X, Y + 50, 80), 2.5, 4);
				B.Pole(MetalS, FVector(X, Y - 50, 80), FVector(X, Y + 50, 80), 2.5, 4);
				if (Rng.F() < 0.6)
				{
					// a parked bike: two wheels + frame
					const int32 Bike = B.Slot(EMat::Metal, Pal[Rng.I(3)]);
					B.Pole(Bike, FVector(X + 25, Y - 70, 40), FVector(X + 25, Y + 70, 40), 3, 4);
					B.Cylinder(MetalS, FVector(X + 25, Y - 70, 8), 32, 32, 3, 10, false);
				}
			}
		}
		// green edge planters
		for (double X = Mn.X + 100; X < Mx.X; X += 400)
		{
			B.Box(Wood, FVector(X, Mn.Y + 20, 0), FVector(X + 250, Mn.Y + 100, 60));
			ASWCityTrees::AddShrub(Inst, FVector(X + 125, Mn.Y + 60, 60), 60, Rng.F() < 0.3 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4)), Rng.Next(), 40000);
		}
		AddMesh(B);
		AddInstances(Inst);
		return true;
	}

	if (Kind == TEXT("greenhouse"))
	{
		const bool bX = Sz.X >= Sz.Y;
		const double Wall = Height * 0.62;
		B.Box(StoneS, FVector(Mn, 0), FVector(Mx, 40));
		B.Box(GlassLight, FVector(Mn + FVector2D(10), 40), FVector(Mx - FVector2D(10), Wall), 16);
		// three gables side by side
		const int32 Bays = 3;
		for (int32 i = 0; i < Bays; ++i)
		{
			FVector A, Bv;
			if (bX) { A = FVector(Mn.X, Mn.Y + Sz.Y * i / Bays, Wall); Bv = FVector(Mx.X, Mn.Y + Sz.Y * (i + 1) / Bays, Wall); }
			else { A = FVector(Mn.X + Sz.X * i / Bays, Mn.Y, Wall); Bv = FVector(Mn.X + Sz.X * (i + 1) / Bays, Mx.Y, Wall); }
			B.Gable(GlassLight, A, Bv, Height - Wall, bX);
		}
		// timber ribs
		const double L = bX ? Sz.X : Sz.Y;
		for (double T = 0; T <= L + 1; T += 300)
		{
			if (bX)
			{
				B.Box(WoodDark, FVector(Mn.X + T - 6, Mn.Y - 4, 40), FVector(Mn.X + T + 6, Mn.Y + 4, Wall));
				B.Box(WoodDark, FVector(Mn.X + T - 6, Mx.Y - 4, 40), FVector(Mn.X + T + 6, Mx.Y + 4, Wall));
			}
			else
			{
				B.Box(WoodDark, FVector(Mn.X - 4, Mn.Y + T - 6, 40), FVector(Mn.X + 4, Mn.Y + T + 6, Wall));
				B.Box(WoodDark, FVector(Mx.X - 4, Mn.Y + T - 6, 40), FVector(Mx.X + 4, Mn.Y + T + 6, Wall));
			}
		}
		// plants inside
		for (int32 k = 0; k < int32(Sz.X * Sz.Y / 60000); ++k)
		{
			const FVector Pt(Rng.R(Mn.X + 100, Mx.X - 100), Rng.R(Mn.Y + 100, Mx.Y - 100), 40);
			ASWCityTrees::AddShrub(Inst, Pt, Rng.R(40, 110), Rng.F() < 0.2 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4)), Rng.Next(), 40000);
		}
		AddCollisionBox(FVector(Mn, 0), FVector(Mx, Height));
		AddMesh(B);
		AddInstances(Inst);
		return true;
	}

	// ---------------- bar-style building (all housing bars, library, school, bathhouse) ------
	FBar Bar(B, Inst, Rng);
	Bar.F.bX = Sz.X >= Sz.Y;
	Bar.Lu = Bar.F.bX ? Sz.X : Sz.Y;
	Bar.D = Bar.F.bX ? Sz.Y : Sz.X;
	Bar.N = Floors;
	Bar.H = Height;
	Bar.FH = Height / Floors;
	// all geometry is relative to the footprint centre (the actor origin is placed there by the builder)
	const FVector Off(Ctr, 0);
	Bar.Off = Off;
	auto Box = [&](int32 S, double U0, double U1, double V0, double V1, double Z0, double Z1) { Bar.Box(S, U0, U1, V0, V1, Z0, Z1); };
	const double Lu = Bar.Lu, Dd = Bar.D, FH = Bar.FH;
	const int32 N = Floors;
	auto IsStreet = [&](int32 Side) // Side: 0 = v-, 1 = v+, 2 = u-, 3 = u+
	{
		static const TCHAR* XNames[] = {TEXT("N"), TEXT("S"), TEXT("W"), TEXT("E")};
		static const TCHAR* YNames[] = {TEXT("W"), TEXT("E"), TEXT("N"), TEXT("S")};
		return Street.Contains(Bar.F.bX ? XNames[Side] : YNames[Side]);
	};
	const bool bStreetM = IsStreet(0), bStreetP = IsStreet(1);
	// the courtyard side gets the deep stepped terraces; with no clear street side, the south side does
	const int32 CourtSide = bStreetM && !bStreetP ? 1 : (bStreetP && !bStreetM ? 0 : (Bar.F.bX ? 1 : 1));
	const int32 StreetSide = 1 - CourtSide;
	const bool bSouthIsVPlus = Bar.F.bX; // for bars along Y the south face is the u+ end
	const bool bGlassy = Has(Mats, TEXT("solar glass"));
	const bool bEarthBase = Has(Mats, TEXT("rammed earth"));
	const bool bLiving = Has(Mats, TEXT("living facade"));
	const bool bLouvers = Has(Mats, TEXT("louver"));
	const bool bCivic = Kind != TEXT("bar");

	// per-floor cuts on the v- and v+ sides
	TArray<double> CutM, CutP;
	for (int32 k = 0; k < N; ++k)
	{
		double Court = 0, StreetCut = 0;
		if (N >= 6) { if (k == N - 2) Court = 300; if (k == N - 1) { Court = 600; StreetCut = 300; } }
		else if (N == 5) { if (k == N - 1) Court = 350; }
		else if (N >= 3) { if (k == N - 1) Court = 300; }
		if (Dd < 1200) Court = FMath::Min(Court, Dd * 0.2);
		CutM.Add(CourtSide == 0 ? Court : StreetCut);
		CutP.Add(CourtSide == 1 ? Court : StreetCut);
	}
	auto VM = [&](int32 k) { return -Dd / 2 + CutM[k]; };
	auto VP = [&](int32 k) { return Dd / 2 - CutP[k]; };

	// courtyard passages and shopfronts (u positions)
	TArray<double> Passages;
	struct FShop { double U; int32 Side; };
	TArray<FShop> Shops;
	for (const TSharedPtr<FJsonObject>& E : J::Objs(Obj, TEXT("entrances")))
	{
		const TArray<double> Pc = J::Nums(E, TEXT("pos_cm"));
		if (Pc.Num() < 2) continue;
		const FVector2D Lp = Bar.F.Unmap(L2(FVector2D(Pc[0], Pc[1])) - Ctr);
		const FString T = J::Str(E, TEXT("type"));
		if (Has(T, TEXT("passage")))
		{
			Passages.Add(Lp.X);
		}
		else
		{
			Shops.Add({Lp.X, Lp.Y < 0 ? 0 : 1});
		}
	}

	const double Lip = 25, Recess = 20, Slab = 30;
	TArray<FVector> CollMin, CollMax;
	for (int32 k = 0; k < N; ++k)
	{
		const double Z0 = k * FH, Z1 = (k + 1) * FH;
		const double Vm = VM(k), Vp = VP(k);
		// slab: ceiling of the floor below, so it spans that floor (terraces sit on it)
		const double Sm = k > 0 ? VM(k - 1) : Vm, Sp = k > 0 ? VP(k - 1) : Vp;
		Box(k == 0 ? StoneS : WoodDark, -Lu / 2 - Lip, Lu / 2 + Lip, Sm - Lip, Sp + Lip, Z0, Z0 + Slab);
		// wall core
		const bool bEarth = bEarthBase && k <= 1;
		const int32 Core = bEarth ? Earth : (bGlassy && k > 0 ? Glass : Wood);
		TArray<TPair<double, double>> Segs;
		if (k == 0 && Passages.Num())
		{
			double U = -Lu / 2;
			TArray<double> Ps = Passages;
			Ps.Sort();
			for (double Pu : Ps)
			{
				if (Pu - 250 > U) Segs.Add({U, Pu - 250});
				U = Pu + 250;
			}
			if (U < Lu / 2) Segs.Add({U, Lu / 2});
		}
		else
		{
			Segs.Add({-Lu / 2, Lu / 2});
		}
		for (const auto& Sg : Segs)
		{
			Box(Core, Sg.Key, Sg.Value, Vm + Recess, Vp - Recess, Z0 + Slab, Z1);
			if (k == 0)
			{
				CollMin.Add(Bar.F.Map(Sg.Key, Vm, 0) + Off);
				CollMax.Add(Bar.F.Map(Sg.Value, Vp, FH) + Off);
			}
		}
		if (bEarth)
		{
			// rammed-earth strata: alternating proud bands
			for (double Z = Z0 + Slab; Z < Z1 - 1; Z += 36)
			{
				if (int32((Z - Z0) / 36) % 2) continue;
				for (const auto& Sg : Segs) Box(Earth2, Sg.Key - 1, Sg.Value + 1, Vm + Recess - 1.5, Vp - Recess + 1.5, Z, FMath::Min(Z + 18, Z1));
			}
		}

		// ---- facades: two long faces and two ends ----
		for (int32 Face = 0; Face < 4; ++Face)
		{
			const bool bV = Face < 2;
			const double Out = (Face % 2 == 0) ? -1.0 : 1.0;
			const double Plane = bV ? (Face == 0 ? Vm + Recess : Vp - Recess) : (Face == 2 ? -Lu / 2 : Lu / 2);
			const double T0 = bV ? -Lu / 2 : Vm + Recess, T1 = bV ? Lu / 2 : Vp - Recess;
			const double Len = T1 - T0;
			if (Len < 200) continue;
			const bool bStreetFace = IsStreet(Face);
			const bool bSouth = bSouthIsVPlus ? Face == 1 : Face == 3;
			const bool bCourt = bV && Face == CourtSide && !bCivic;
			const int32 Nb = FMath::Max(1, int32(FMath::RoundToDouble(Len / 330.0)));
			const double Bw = Len / Nb;
			// ground-floor shopfronts on the street face
			if (k == 0 && bStreetFace && bV && !bEarth)
			{
				Bar.FaceBox(GlassLight, bV, Plane, Out, T0 + 30, T1 - 30, 0, 3, Slab + 10, FH - 70);
			}
			if (k == 0 && bStreetFace && bV)
			{
				Bar.FaceBox(WoodWash, bV, Plane, Out, T0, T1, 0, 18, FH - 70, FH - 20); // sign band
			}
			// spandrel bands on glassy floors: solar glass above, timber below
			if (bGlassy && k > 0)
			{
				Bar.FaceBox(Wood, bV, Plane, Out, T0, T1, 0, 4, Z0 + Slab, Z0 + Slab + 85);
			}
			for (int32 i = 0; i <= Nb; ++i)
			{
				const double T = T0 + i * Bw;
				// vertical fins at bay lines
				Bar.FaceBox(k == 0 ? WoodDark : Wood, bV, Plane, Out, T - 7, T + 7, 0, bGlassy ? 45 : 30, Z0 + Slab, Z1);
				if (i == Nb) break;
				const double Tc = T + Bw * 0.5;
				const bool bShopBay = k == 0 && bStreetFace && bV;
				if (!bGlassy || k == 0)
				{
					if (!bShopBay || bEarth)
					{
						// punched window: dark solar glass, timber frame + sill
						const double Ww = Bw * (bEarth ? 0.45 : 0.62);
						const double S0 = Z0 + Slab + (bShopBay ? 20 : 85), S1 = Z1 - 45;
						Bar.FaceBox(Glass, bV, Plane, Out, Tc - Ww / 2, Tc + Ww / 2, 0, 3, S0, S1);
						Bar.FaceBox(WoodDark, bV, Plane, Out, Tc - Ww / 2 - 8, Tc + Ww / 2 + 8, 0, 12, S0 - 8, S0);
						if (k > 0 && !bEarth && (i + k) % 3 == 1)
						{
							// operable shutter panel in the palette accent
							Bar.FaceBox(Accent, bV, Plane, Out, Tc + Ww / 2 + 8, Tc + Ww / 2 + 8 + Ww * 0.45, 0, 5, S0, S1);
						}
					}
				}
				// living facade: green wall panels on alternate bays (street and south faces)
				if (bLiving && k > 0 && (bStreetFace || bSouth || !bV) && (i + k) % 2 == 0)
				{
					Bar.FaceBox(LeafWall, bV, Plane, Out, Tc - Bw * 0.4, Tc + Bw * 0.4, 0, 22, Z0 + Slab + 10, Z1 - 5);
					for (int32 b = 0; b < 3; ++b)
					{
						const FVector Pc = Bar.FacePt(bV, Plane, Out, Tc + Rng.R(-0.35, 0.35) * Bw, 24, Rng.R(Z0 + 60, Z1 - 40)) + Off;
						Inst.Add(P(EPrim::Blob), M(EMat::Foliage), Rng.F() < 0.2 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4)), Xf(Pc, FVector(Rng.R(0.4, 0.7), Rng.R(0.4, 0.7), Rng.R(0.4, 0.7))), true, 50000);
					}
				}
				// climbing jasmine up south walls: green ropes on fins with white flowers
				if (bSouth && !bLiving && i % 3 == 0 && k < 3 + (Seed + i) % 3)
				{
					Bar.FaceBox(LeafWall, bV, Plane, Out, T - 22, T + 22, 30, 52, Z0, Z1);
					if (Rng.F() < 0.5)
					{
						const FVector Pc = Bar.FacePt(bV, Plane, Out, T, 45, Rng.R(Z0 + 40, Z1 - 40)) + Off;
						Inst.Add(P(EPrim::Blob), M(EMat::Foliage), Col::Flower(3), Xf(Pc, FVector(0.22, 0.22, 0.35)), false, 30000);
					}
				}
				// bamboo louvers in front of the street face
				if (bLouvers && k > 0 && (bStreetFace || !bV) && i % 4 != 3)
				{
					const int32 Bam = B.Slot(EMat::Timber, Col::Bamboo());
					for (double Ts = T + 15; Ts < T + Bw - 10; Ts += 24)
						Bar.FaceBox(Bam, bV, Plane, Out, Ts - 3.5, Ts + 3.5, 52, 60, Z0 + Slab + 5, Z1 - 5);
				}
				// shop awnings at shopfront entrances
				if (bShopBay)
				{
					for (const FShop& Sh : Shops)
					{
						if (Sh.Side != Face || FMath::Abs(Sh.U - Tc) > Bw * 0.5) continue;
						const double W2 = 220;
						for (int32 Strip = 0; Strip < 8; ++Strip)
						{
							const double A0 = Tc - W2 + Strip * W2 / 4, A1 = A0 + W2 / 4;
							const int32 Sl = Strip % 2 ? Accent : Accent2;
							const FVector Pa = Bar.FacePt(bV, Plane, Out, A0, 0, FH - 80) + Off, Pb = Bar.FacePt(bV, Plane, Out, A1, 0, FH - 80) + Off;
							const FVector Pd = Bar.FacePt(bV, Plane, Out, A0, 190, FH - 135) + Off, Pc = Bar.FacePt(bV, Plane, Out, A1, 190, FH - 135) + Off;
							const FVector Nrm = Bar.F.MapN(bV ? 0 : Out * 55, bV ? Out * 55 : 0, 190).GetSafeNormal();
							B.Quad(Sl, Pa, Pb, Pc, Pd, Nrm);
							B.Quad(Sl, Pa, Pb, Pc, Pd, -Nrm);
							Bar.FaceBox(Sl, bV, Plane, Out, A0, A1, 186, 192, FH - 165, FH - 135);
						}
						// planters + bench either side of the door
						for (int32 s = -1; s <= 1; s += 2)
						{
							const double Tp = Tc + s * 170;
							Bar.FaceBox(Wood, bV, Plane, Out, Tp - 40, Tp + 40, 30, 110, 0, 55);
							Bar.Shrub(Bar.FacePt(bV, Plane, Out, Tp, 70, 55) + Off, 45);
						}
					}
				}
				// Bosco-style staggered balconies with planters and cascading greenery
				const bool bBalcony = k > 0 && bV && ((bCourt && (i + 2 * k) % 3 == 0) || (bStreetFace && k >= 2 && (i + 3 * k) % 5 == 0) || (!bCourt && !bStreetFace && (i + k) % 3 == 0));
				if (bBalcony && !(N >= 5 && k >= N - 2 && bCourt))
				{
					const double Wb = Bw * ((Seed + i * 7 + k) % 4 == 0 ? 1.6 : 0.92);
					const double Dp = bCourt ? 190 : 150;
					const double A0 = Tc - Wb / 2, A1 = Tc + Wb / 2;
					Bar.FaceBox(WoodDark, bV, Plane, Out, A0, A1, 0, Dp, Z0 + 5, Z0 + Slab);
					Bar.FaceBox(Trim, bV, Plane, Out, A0, A0 + 4, Dp - 60, Dp, Z0 + Slab, Z0 + Slab + 100);
					Bar.FaceBox(Trim, bV, Plane, Out, A1 - 4, A1, Dp - 60, Dp, Z0 + Slab, Z0 + Slab + 100);
					Bar.FaceBox((i + k) % 2 ? Wood : Accent, bV, Plane, Out, A0, A1, Dp - 55, Dp, Z0 + Slab, Z0 + Slab + 70);
					const FVector Lipp = Bar.FacePt(bV, Plane, Out, Tc, Dp, Z0 + Slab + 70) + Off;
					const FVector Along = Bar.FacePt(bV, Plane, Out, Tc + 1, Dp, 0) - Bar.FacePt(bV, Plane, Out, Tc, Dp, 0);
					const FVector OutV = Bar.FacePt(bV, Plane, Out, Tc, Dp + 1, 0) - Bar.FacePt(bV, Plane, Out, Tc, Dp, 0);
					for (int32 s = 0; s < 3; ++s) Bar.Shrub(Bar.FacePt(bV, Plane, Out, Tc + Rng.R(-0.4, 0.4) * Wb, Dp - 28, Z0 + Slab + 66) + Off, Rng.R(32, 50), 0.3);
					Bar.Drapes(Lipp, Along, OutV, Wb * 0.9, 2 + Rng.I(3), FMath::Min(FH * 0.9, 300.0));
					if (Rng.F() < 0.3)
						ASWCityTrees::AddTree(Inst, TEXT("roof"), Bar.FacePt(bV, Plane, Out, Tc + Wb * 0.3, Dp - 28, Z0 + Slab + 60) + Off, Rng.R(0.55, 0.8), Rng.Next());
				}
			}
		}

		// ---- terraces where this floor steps back ----
		if (k > 0)
		{
			for (int32 Side = 0; Side < 2; ++Side)
			{
				const double Prev = Side == 0 ? VM(k - 1) : VP(k - 1);
				const double Cur = Side == 0 ? Vm : Vp;
				const double Depth = FMath::Abs(Cur - Prev);
				if (Depth < 100) continue;
				const double Out = Side == 0 ? -1 : 1;
				const double Edge = Prev; // outer edge of the terrace
				const bool bWalkHere = FMath::Abs(Z0 - Walk) < 60 && Side == StreetSide;
				if (bWalkHere)
				{
					Box(WoodDark, -Lu / 2, Lu / 2, FMath::Min(Edge, Cur) + 20, FMath::Max(Edge, Cur) - 20, Z0 + Slab, Z0 + WalkDeckLift);
					CollMin.Add(Bar.F.Map(-Lu / 2, FMath::Min(Edge, Cur), Z0) + Off);
					CollMax.Add(Bar.F.Map(Lu / 2, FMath::Max(Edge, Cur), Z0 + WalkDeckLift) + Off);
					Box(Trim, -Lu / 2, Lu / 2, Edge - Out * 6, Edge, Z0 + WalkDeckLift, Z0 + WalkDeckLift + 110);
					Box(GlassLight, -Lu / 2, Lu / 2, Edge - Out * 4, Edge - Out * 2, Z0 + WalkDeckLift, Z0 + WalkDeckLift + 100);
				}
				else
				{
					// green terrace with an edge planter spilling over (Kampung Admiralty)
					Box(Green, -Lu / 2, Lu / 2, FMath::Min(Edge, Cur) + 10, FMath::Max(Edge, Cur) - 10, Z0 + Slab, Z0 + Slab + 12);
				}
				// planter along the outer edge
				const double In0 = Edge - Out * 70, In1 = Edge;
				Box(Wood, -Lu / 2, Lu / 2, FMath::Min(In0, In1), FMath::Max(In0, In1), Z0 + Slab, Z0 + Slab + 75 + (bWalkHere ? WalkDeckLift - Slab : 0));
				for (double U = -Lu / 2 + 100; U < Lu / 2 - 100; U += Rng.R(150, 280))
				{
					const double Zt = Z0 + Slab + 75 + (bWalkHere ? WalkDeckLift - Slab : 0);
					Bar.Shrub(Bar.F.Map(U, Edge - Out * 35, Zt) + Off, Rng.R(35, 60), 0.3);
					if (Rng.F() < 0.55) Bar.Drapes(Bar.F.Map(U, Edge, Zt) + Off, Bar.F.MapN(1, 0, 0), Bar.F.MapN(0, Out, 0), 120, 2, FH * 1.1);
					if (!bWalkHere && Rng.F() < 0.12) ASWCityTrees::AddTree(Inst, TEXT("roof"), Bar.F.Map(U, (Edge + Cur) * 0.5, Z0 + Slab + 12) + Off, Rng.R(0.7, 1.0), Rng.Next());
				}
			}
		}
	}

	// ---------------- roof ----------------
	{
		const int32 k = N - 1;
		const double Z = Height;
		const double Vm = VM(k), Vp = VP(k);
		Box(WoodDark, -Lu / 2 - Lip, Lu / 2 + Lip, Vm - Lip, Vp + Lip, Z, Z + Slab);
		Box(Green, -Lu / 2 + 30, Lu / 2 - 30, Vm + 30, Vp - 30, Z + Slab, Z + Slab + 14);
		const bool bWalkRoof = FMath::Abs(Z - Walk) < 60 && !bCivic;
		const double Zr = Z + Slab + 14;
		// keep-clear rects (landing towers on this roof) in (u,v)
		for (const TSharedPtr<FJsonObject>& Kc : J::Objs(Obj, TEXT("keep_clear")))
		{
			FVector2D A, Bv;
			if (J::Rect(Kc, TEXT("rect_cm"), A, Bv))
			{
				const FVector2D Ua = Bar.F.Unmap(L2(A) - Ctr), Ub = Bar.F.Unmap(L2(Bv) - Ctr);
				Bar.Clear.Add(FBox2D(Ua.ComponentMin(Ub) - FVector2D(150), Ua.ComponentMax(Ub) + FVector2D(150)));
			}
		}
		// edge planters with cascading plants (every roof), metal cap
		for (int32 Side = 0; Side < 2; ++Side)
		{
			const double Edge = Side == 0 ? Vm : Vp, Out = Side == 0 ? -1 : 1;
			Box(Wood, -Lu / 2, Lu / 2, FMath::Min(Edge, Edge - Out * 60), FMath::Max(Edge, Edge - Out * 60), Z + Slab, Z + Slab + 70);
			Box(Trim, -Lu / 2, Lu / 2, FMath::Min(Edge, Edge - Out * 4), FMath::Max(Edge, Edge - Out * 4), Z + Slab + 70, Z + Slab + 115);
			for (double U = -Lu / 2 + 80; U < Lu / 2 - 80; U += Rng.R(160, 300))
			{
				if (Bar.Cleared(U, Edge)) continue;
				Bar.Shrub(Bar.F.Map(U, Edge - Out * 30, Z + Slab + 70) + Off, Rng.R(30, 55), 0.3);
				if (Rng.F() < 0.5) Bar.Drapes(Bar.F.Map(U, Edge + Out * 5, Z + Slab + 70) + Off, Bar.F.MapN(1, 0, 0), Bar.F.MapN(0, Out, 0), 120, 2, FH * 1.2);
			}
		}
		for (int32 End = 0; End < 2; ++End)
		{
			const double U = End ? Lu / 2 : -Lu / 2;
			Box(Wood, FMath::Min(U, U - (End ? 1 : -1) * 60), FMath::Max(U, U - (End ? 1 : -1) * 60), Vm, Vp, Z + Slab, Z + Slab + 70);
		}
		// canopy walk deck down the middle, with pergolas, benches and trees in planters
		double DeckV0 = -150, DeckV1 = 150;
		if (bWalkRoof)
		{
			const double Vc = (Vm + Vp) * 0.5;
			DeckV0 = Vc - 160;
			DeckV1 = Vc + 160;
			Box(WoodDark, -Lu / 2 + 10, Lu / 2 - 10, DeckV0, DeckV1, Z + Slab, Z + WalkDeckLift);
			CollMin.Add(Bar.F.Map(-Lu / 2, DeckV0, Z) + Off);
			CollMax.Add(Bar.F.Map(Lu / 2, DeckV1, Z + WalkDeckLift) + Off);
			// spurs out to the bridges
			for (const FVector2D& Sp : J::Points(Obj, TEXT("deck_spurs_cm")))
			{
				const FVector2D Su = Bar.F.Unmap(L2(Sp) - Ctr);
				if (FMath::Abs(Su.Y) > FMath::Abs(Su.X) * 0 && FMath::Abs(Su.X) < Lu / 2 - 50)
				{
					// spur across v to a long side
					Box(WoodDark, Su.X - 200, Su.X + 200, FMath::Min(Su.Y, Vc), FMath::Max(Su.Y, Vc), Z + Slab + 1, Z + WalkDeckLift);
					Bar.Clear.Add(FBox2D(FVector2D(Su.X - 260, FMath::Min(Su.Y, Vc) - 100), FVector2D(Su.X + 260, FMath::Max(Su.Y, Vc) + 100)));
				}
				else
				{
					Box(WoodDark, FMath::Min(Su.X, 0.0), FMath::Max(Su.X, 0.0), Su.Y - 200, Su.Y + 200, Z + Slab + 1, Z + WalkDeckLift);
				}
			}
			Bar.Clear.Add(FBox2D(FVector2D(-Lu / 2, DeckV0 - 40), FVector2D(Lu / 2, DeckV1 + 40)));
			for (double U = -Lu / 2 + 600; U < Lu / 2 - 400; U += 1200)
			{
				if (Bar.Cleared(U, Vm + 1) && Bar.Cleared(U, Vp - 1)) continue;
				// pergola frame over the deck with vines
				for (int32 s = 0; s < 2; ++s)
				{
					const double V = s ? DeckV1 + 15 : DeckV0 - 15;
					Box(Wood, U - 10, U + 10, V - 10, V + 10, Z + WalkDeckLift, Z + WalkDeckLift + 290);
					Box(Wood, U + 290, U + 310, V - 10, V + 10, Z + WalkDeckLift, Z + WalkDeckLift + 290);
				}
				Box(WoodDark, U - 20, U + 320, DeckV0 - 30, DeckV0, Z + WalkDeckLift + 290, Z + WalkDeckLift + 310);
				Box(WoodDark, U - 20, U + 320, DeckV1, DeckV1 + 30, Z + WalkDeckLift + 290, Z + WalkDeckLift + 310);
				for (double Uu = U; Uu <= U + 300; Uu += 60) Box(Wood, Uu - 4, Uu + 4, DeckV0 - 30, DeckV1 + 30, Z + WalkDeckLift + 310, Z + WalkDeckLift + 322);
				for (int32 v = 0; v < 4; ++v)
					Inst.Add(P(EPrim::Blob), M(EMat::Foliage), v == 2 ? Col::Flower(Rng.F() < 0.5 ? 4 : 0) : Col::Leaf(v), Xf(Bar.F.Map(U + Rng.R(0, 300), Rng.R(DeckV0, DeckV1), Z + WalkDeckLift + 330) + Off, FVector(Rng.R(0.6, 1.0), Rng.R(0.6, 1.0), 0.3)), true, 60000);
				// bench + planter with a small tree beside the deck
				const double Vb = (U / 1200.0 - FMath::FloorToDouble(U / 1200.0)) < 0.5 ? DeckV1 + 70 : DeckV0 - 70;
				Box(Wood, U + 600, U + 780, Vb - 20, Vb + 20, Z + Slab + 14, Z + Slab + 60);
				Box(Wood, U + 860, U + 980, Vb - 60, Vb + 60, Z + Slab + 14, Z + Slab + 75);
				ASWCityTrees::AddTree(Inst, TEXT("roof"), Bar.F.Map(U + 920, Vb, Z + Slab + 75) + Off, Rng.R(0.8, 1.1), Rng.Next());
			}
		}
		// solar glass PV rows on one end of the roof (35-45 % of its length), tilted to the south
		const int32 Pv = Glass;
		const int32 MetalS = B.Slot(EMat::Metal, Col::Metal());
		const bool bPvAtStart = (Seed % 2) == 0;
		const double PvLen = Lu * (bCivic ? 0.5 : 0.38);
		const double PvU0 = bPvAtStart ? -Lu / 2 + 120 : Lu / 2 - 120 - PvLen, PvU1 = PvU0 + PvLen;
		if (Lu > 1500 && Vp - Vm > 600)
		{
			const double Tilt = 25.0;
			if (bSouthIsVPlus)
			{
				// rows run along u, panels face +v (south)
				for (double V = Vm + 120; V + 180 < Vp - 100; V += 300)
				{
					if (V + 180 > DeckV0 && V < DeckV1 && bWalkRoof) continue;
					for (double U = PvU0; U + 300 <= PvU1; U += 320)
					{
						if (Bar.Cleared(U, V) || Bar.Cleared(U + 300, V + 180)) continue;
						const double Zl = Zr + 25, Zh = Zr + 25 + 180 * FMath::Sin(FMath::DegreesToRadians(Tilt));
						const double Vl = V + 180 * FMath::Cos(FMath::DegreesToRadians(Tilt));
						const FVector A = Bar.F.Map(U, V, Zh) + Off, Bb = Bar.F.Map(U + 300, V, Zh) + Off, C = Bar.F.Map(U + 300, Vl, Zl) + Off, Dv = Bar.F.Map(U, Vl, Zl) + Off;
						const FVector Nrm = Bar.F.MapN(0, FMath::Sin(FMath::DegreesToRadians(Tilt)), FMath::Cos(FMath::DegreesToRadians(Tilt)));
						B.Quad(Pv, A, Bb, C, Dv, Nrm);
						B.Quad(MetalS, A - FVector(0, 0, 3), Bb - FVector(0, 0, 3), C - FVector(0, 0, 3), Dv - FVector(0, 0, 3), -Nrm);
						Box(MetalS, U + 140, U + 160, V, V + 8, Zr, Zh);
					}
				}
			}
			else
			{
				// bar along Y: rows run across v, panels face +u (south)
				for (double U = PvU0; U + 200 < PvU1; U += 300)
				{
					if (Bar.Cleared(U, 0)) continue;
					for (double V = Vm + 80; V + 300 <= Vp - 80; V += 320)
					{
						if (bWalkRoof && V + 300 > DeckV0 && V < DeckV1) continue;
						const double Zl = Zr + 25, Zh = Zr + 25 + 180 * FMath::Sin(FMath::DegreesToRadians(Tilt));
						const double Ul = U + 180 * FMath::Cos(FMath::DegreesToRadians(Tilt));
						const FVector A = Bar.F.Map(U, V, Zh) + Off, Bb = Bar.F.Map(U, V + 300, Zh) + Off, C = Bar.F.Map(Ul, V + 300, Zl) + Off, Dv = Bar.F.Map(Ul, V, Zl) + Off;
						const FVector Nrm = Bar.F.MapN(FMath::Sin(FMath::DegreesToRadians(Tilt)), 0, FMath::Cos(FMath::DegreesToRadians(Tilt)));
						B.Quad(Pv, A, Bb, C, Dv, Nrm);
						B.Quad(MetalS, A - FVector(0, 0, 3), Bb - FVector(0, 0, 3), C - FVector(0, 0, 3), Dv - FVector(0, 0, 3), -Nrm);
						Box(MetalS, U, U + 8, V + 140, V + 160, Zr, Zh);
					}
				}
			}
			Bar.Clear.Add(FBox2D(FVector2D(PvU0, Vm), FVector2D(PvU1, Vp)));
		}
		// rooftop feature from the cell (greenhouse, dye garden, ...)
		double FeatU = bPvAtStart ? Lu / 2 - 900 : -Lu / 2 + 900;
		if (!Feature.IsEmpty() && Lu > 2000)
		{
			const double Vc = bWalkRoof ? (DeckV1 + Vp) * 0.5 : (Vm + Vp) * 0.5;
			const double Vw = bWalkRoof ? FMath::Max(150.0, (Vp - DeckV1) * 0.5 - 60) : (Vp - Vm) * 0.5 - 120;
			const double U0 = FeatU - 600, U1 = FeatU + 600;
			if (Feature == TEXT("greenhouse") || Feature == TEXT("solar_lab"))
			{
				Box(GlassLight, U0, U1, Vc - Vw, Vc + Vw, Zr, Zr + 260);
				const FVector G0 = Bar.F.Map(U0, Vc - Vw, Zr + 260) + Off, G1 = Bar.F.Map(U1, Vc + Vw, Zr + 260) + Off;
				B.Gable(GlassLight, G0.ComponentMin(G1), G0.ComponentMax(G1), 160, Bar.F.bX);
				for (double U = U0; U <= U1 + 1; U += 200) Box(WoodDark, U - 5, U + 5, Vc - Vw - 3, Vc + Vw + 3, Zr, Zr + 262);
				for (int32 s = 0; s < 10; ++s) Bar.Shrub(Bar.F.Map(Rng.R(U0 + 80, U1 - 80), Rng.R(Vc - Vw + 60, Vc + Vw - 60), Zr) + Off, Rng.R(30, 60), 0.35);
				if (Feature == TEXT("solar_lab"))
				{
					// small wind turbine + extra PV
					const FVector T = Bar.F.Map(U1 + 250, Vc, Zr) + Off;
					B.Cylinder(MetalS, T, 10, 7, 650, 6);
					for (int32 Bl = 0; Bl < 3; ++Bl)
						B.OBox(B.Slot(EMat::Metal, FLinearColor(0.85f, 0.85f, 0.82f)), T + FVector(20, 0, 650) + FRotator(0, 0, Bl * 120).RotateVector(FVector(0, 0, 130)), FVector(3, 12, 130), FRotator(0, 0, Bl * 120));
				}
			}
			else if (Feature == TEXT("dye_garden") || Feature == TEXT("herb_terrace"))
			{
				for (double U = U0; U < U1; U += 150)
				{
					Box(Wood, U, U + 110, Vc - Vw, Vc + Vw, Zr, Zr + (Feature == TEXT("herb_terrace") ? 40 + (U - U0) * 0.06 : 45));
					const int32 Ci = int32((U - U0) / 150);
					for (int32 s = 0; s < 6; ++s)
					{
						const FVector Pt = Bar.F.Map(U + 55 + Rng.R(-30, 30), Rng.R(Vc - Vw + 40, Vc + Vw - 40), Zr + 45 + (Feature == TEXT("herb_terrace") ? (U - U0) * 0.06 : 0)) + Off;
						Inst.Add(P(EPrim::Blob), M(EMat::Foliage), Feature == TEXT("dye_garden") ? Col::Flower(Ci) : Col::Leaf(Ci + s), Xf(Pt, FVector(Rng.R(0.25, 0.4))), false, 40000);
					}
				}
			}
			else if (Feature == TEXT("hammock_deck") || Feature == TEXT("dance_deck"))
			{
				const FVector Ctr3 = Bar.F.Map(FeatU, Vc, Zr) + Off;
				B.Cylinder(Wood, Ctr3, FMath::Min(Vw, 500.0), FMath::Min(Vw, 500.0), 25, 16);
				for (int32 p = 0; p < 6; ++p)
				{
					const double A = 2 * PI * p / 6;
					const FVector Pp = Ctr3 + FVector(FMath::Cos(A), FMath::Sin(A), 0) * (FMath::Min(Vw, 500.0) - 30);
					B.Cylinder(Wood, Pp, 9, 8, 320, 6);
					B.Box(B.Slot(EMat::Lantern, Col::Lantern()), Pp + FVector(-8, -8, 320), Pp + FVector(8, 8, 336));
					if (Feature == TEXT("hammock_deck") && p % 2 == 0)
					{
						const FVector Q = Ctr3 + FVector(FMath::Cos(A + PI / 3), FMath::Sin(A + PI / 3), 0) * (FMath::Min(Vw, 500.0) - 30);
						B.Beam(B.Slot(EMat::Fabric, Pal[p % 3]), Pp + FVector(0, 0, 130), (Pp + Q) * 0.5 + FVector(0, 0, 70), 90, 4);
						B.Beam(B.Slot(EMat::Fabric, Pal[p % 3]), (Pp + Q) * 0.5 + FVector(0, 0, 70), Q + FVector(0, 0, 130), 90, 4);
					}
				}
				B.OBox(B.Slot(EMat::Fabric, FLinearColor(0.9f, 0.86f, 0.78f)), Ctr3 + FVector(0, 0, 360), FVector(FMath::Min(Vw, 500.0) * 0.8, FMath::Min(Vw, 500.0) * 0.8, 2), FRotator(4, 20, -5));
			}
			Bar.Clear.Add(FBox2D(FVector2D(U0 - 100, Vm), FVector2D(U1 + 100, Vp)));
		}
		if (Kind == TEXT("library") || Feature == TEXT("observatory"))
		{
			const FVector Dc = Bar.F.Map(Lu * 0.2, 0, Zr) + Off;
			const double R = FMath::Min(Dd * 0.28, 650.0);
			B.Cylinder(Earth, Dc, R + 40, R + 40, 220, 20);
			B.Ellipsoid(B.Slot(EMat::Metal, Col::Verdigris()), Dc + FVector(0, 0, 220), FVector(R, R, R), 20, 8, true);
			B.OBox(Glass, Dc + FVector(0, 0, 220 + R * 0.55), FVector(R * 0.6, 40, 8), FRotator(-40, 30, 0));
			Bar.Clear.Add(FBox2D(Bar.F.Unmap(FVector2D(Dc - Off)) - FVector2D(R + 200), Bar.F.Unmap(FVector2D(Dc - Off)) + FVector2D(R + 200)));
		}
		// roof garden: trees, shrubs, meadow tufts on what's left
		const double Area = Lu * (Vp - Vm);
		const int32 NT = int32(Area / 900000.0);
		for (int32 t = 0; t < NT; ++t)
		{
			const double U = Rng.R(-Lu / 2 + 150, Lu / 2 - 150), V = Rng.R(Vm + 120, Vp - 120);
			if (Bar.Cleared(U, V)) continue;
			ASWCityTrees::AddTree(Inst, TEXT("roof"), Bar.F.Map(U, V, Zr) + Off, Rng.R(0.7, 1.15), Rng.Next());
		}
		for (int32 t = 0; t < int32(Area / 150000.0); ++t)
		{
			const double U = Rng.R(-Lu / 2 + 100, Lu / 2 - 100), V = Rng.R(Vm + 80, Vp - 80);
			if (Bar.Cleared(U, V)) continue;
			Bar.Shrub(Bar.F.Map(U, V, Zr) + Off, Rng.R(30, 70), 0.35);
		}
		// chimney / vent stacks on bathhouse-type single storeys
		if (Kind == TEXT("bathhouse"))
		{
			for (int32 c = 0; c < 3; ++c)
				B.Cylinder(B.Slot(EMat::Metal, Col::Verdigris()), Bar.F.Map(-Lu / 3 + c * Lu / 3, Vm + 200, Zr) + Off, 30, 26, 350, 10);
		}
		// school veranda along the south side
		if (Kind == TEXT("willow_school"))
		{
			const double Vs = bSouthIsVPlus ? Vp : Vm;
			const double O = bSouthIsVPlus ? 1 : -1;
			Box(Wood, -Lu / 2, Lu / 2, FMath::Min(Vs, Vs + O * 350), FMath::Max(Vs, Vs + O * 350), FH - 10, FH + 20);
			Box(Green, -Lu / 2, Lu / 2, FMath::Min(Vs, Vs + O * 350), FMath::Max(Vs, Vs + O * 350), FH + 20, FH + 32);
			for (double U = -Lu / 2 + 50; U < Lu / 2; U += 450)
				Box(Wood, U - 12, U + 12, Vs + O * 320 - 12, Vs + O * 320 + 12, 0, FH - 10);
			for (double U = -Lu / 2 + 100; U < Lu / 2 - 100; U += Rng.R(150, 280))
				Bar.Drapes(Bar.F.Map(U, Vs + O * 350, FH + 30) + Off, Bar.F.MapN(1, 0, 0), Bar.F.MapN(0, O, 0), 120, 1, 180);
		}
	}

	// collision: ground-floor segments (passages stay open), the upper mass, decks
	for (int32 i = 0; i < CollMin.Num(); ++i)
	{
		AddCollisionBox(CollMin[i].ComponentMin(CollMax[i]), CollMin[i].ComponentMax(CollMax[i]));
	}
	AddCollisionBox(FVector(Bar.F.Map(-Lu / 2, -Dd / 2, FH) + Off).ComponentMin(Bar.F.Map(Lu / 2, Dd / 2, Height) + Off),
		FVector(Bar.F.Map(-Lu / 2, -Dd / 2, FH) + Off).ComponentMax(Bar.F.Map(Lu / 2, Dd / 2, Height) + Off));

	AddMesh(B);
	AddInstances(Inst);
	return true;
}

// =============================================================================================
// Sky bridge (local frame: X along the span, actor placed at the span midpoint with the span's yaw)

bool ASWSkyBridge::Build(const TSharedPtr<FJsonObject>& Obj, FString& Error)
{
	const double Ls = J::Num(Obj, TEXT("length_cm"), 3000);
	const double W = J::Num(Obj, TEXT("width_cm"), 400);
	const double E = J::Num(Obj, TEXT("elevation_cm"), 1750);
	FSWMeshBuilder B;
	FInstances Inst;
	FRng Rng(Seed);
	const int32 Wood = B.Slot(EMat::Timber, Col::Timber());
	const int32 Dark = B.Slot(EMat::Timber, Col::TimberDark());
	const int32 GlassL = B.Slot(EMat::SolarGlass, Col::GlassWarm());
	const int32 Brass = B.Slot(EMat::Metal, Col::Brass());
	const double Top = E + WalkDeckLift;
	const double L2v = Ls * 0.5 + 60;
	B.Box(Dark, FVector(-L2v, -W / 2, Top - 35), FVector(L2v, W / 2, Top));
	AddCollisionBox(FVector(-L2v, -W / 2, Top - 35), FVector(L2v, W / 2, Top));
	// glulam edge beams
	B.Box(Wood, FVector(-L2v, -W / 2 - 20, Top - 90), FVector(L2v, -W / 2 + 5, Top + 10));
	B.Box(Wood, FVector(-L2v, W / 2 - 5, Top - 90), FVector(L2v, W / 2 + 20, Top + 10));
	// under-arches and struts
	const int32 Seg = 16;
	for (int32 Side = -1; Side <= 1; Side += 2)
	{
		const double Y = Side * (W / 2 - 40);
		auto Za = [&](double X) { const double T = X / (Ls * 0.5); return Top - 90 - 380 * T * T; };
		for (int32 i = 0; i < Seg; ++i)
		{
			const double X0 = -Ls / 2 + Ls * i / Seg, X1 = -Ls / 2 + Ls * (i + 1) / Seg;
			B.Beam(Wood, FVector(X0, Y, Za(X0)), FVector(X1, Y, Za(X1)), 30, 40);
		}
		for (double X = -Ls / 2 + 300; X < Ls / 2 - 200; X += 300)
			B.Beam(Dark, FVector(X, Y, Za(X)), FVector(X, Y, Top - 90), 10, 10);
	}
	// railings: posts, glass, brass handrail
	for (int32 Side = -1; Side <= 1; Side += 2)
	{
		const double Y = Side * (W / 2 - 2);
		B.Box(GlassL, FVector(-Ls / 2, Y - 2, Top), FVector(Ls / 2, Y + 2, Top + 100));
		B.Box(Brass, FVector(-Ls / 2, Y - 5, Top + 100), FVector(Ls / 2, Y + 5, Top + 110));
		for (double X = -Ls / 2; X <= Ls / 2 + 1; X += 200)
			B.Box(Dark, FVector(X - 5, Y - 5, Top), FVector(X + 5, Y + 5, Top + 110));
		// planters hung outside the rail, cascading greenery below the deck
		for (double X = -Ls / 2 + 150; X < Ls / 2 - 100; X += 350)
		{
			B.Box(Wood, FVector(X - 80, Side * (W / 2 + 22), Top - 10), FVector(X + 80, Side * (W / 2 + 70), Top + 50));
			ASWCityTrees::AddShrub(Inst, FVector(X, Side * (W / 2 + 46), Top + 50), 42, Rng.F() < 0.3 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4)), Rng.Next(), 50000);
			FBar Tmp(B, Inst, Rng);
			Tmp.Drapes(FVector(X, Side * (W / 2 + 70), Top + 50), FVector(1, 0, 0), FVector(0, Side, 0), 140, 2, 320);
		}
	}
	// three vine arches over the deck
	for (int32 a = 0; a < 3; ++a)
	{
		const double X = -Ls / 4 + a * Ls / 4;
		const int32 S = 8;
		for (int32 i = 0; i < S; ++i)
		{
			const double T0 = PI * i / S, T1 = PI * (i + 1) / S;
			B.Pole(Dark, FVector(X, -FMath::Cos(T0) * W / 2, Top + FMath::Sin(T0) * 320), FVector(X, -FMath::Cos(T1) * W / 2, Top + FMath::Sin(T1) * 320), 6, 5);
		}
		for (int32 v = 0; v < 5; ++v)
		{
			const double T = Rng.R(0.15, 0.85) * PI;
			Inst.Add(P(EPrim::Blob), M(EMat::Foliage), v == 0 ? Col::Flower(4) : Col::Leaf(v), Xf(FVector(X + Rng.R(-30, 30), -FMath::Cos(T) * W / 2, Top + FMath::Sin(T) * 320), FVector(Rng.R(0.4, 0.6))), true, 60000);
		}
		B.Box(B.Slot(EMat::Lantern, Col::Lantern()), FVector(X - 8, -8, Top + 280), FVector(X + 8, 8, Top + 300));
	}
	AddMesh(B);
	AddInstances(Inst);
	return true;
}

// =============================================================================================
// Canopy landing tower

bool ASWCanopyLanding::Build(const TSharedPtr<FJsonObject>& Obj, FString& Error)
{
	FVector2D Mn, Mx;
	if (!J::Rect(Obj, TEXT("rect_cm"), Mn, Mx))
	{
		Error = TEXT("rect_cm missing");
		return false;
	}
	Mn = L2(Mn);
	Mx = L2(Mx);
	const double Base = J::Num(Obj, TEXT("base_cm"), 0);
	const double Top = J::Num(Obj, TEXT("top_cm"), 1750);
	const double Deck = Top + WalkDeckLift;
	FSWMeshBuilder B;
	FInstances Inst;
	FRng Rng(Seed);
	const int32 Wood = B.Slot(EMat::Timber, Col::Timber());
	const int32 Dark = B.Slot(EMat::Timber, Col::TimberDark());
	const int32 Bam = B.Slot(EMat::Timber, Col::Bamboo());
	const int32 GlassL = B.Slot(EMat::SolarGlass, Col::GlassWarm());
	const int32 Green = B.Slot(EMat::GreenRoof, Col::GreenRoof());
	const FVector2D C = (Mn + Mx) * 0.5;
	const double RoofZ = Deck + 330;
	// corner posts and floor rings
	for (int32 i = 0; i < 4; ++i)
	{
		const FVector2D Pc((i & 1) ? Mx.X - 20 : Mn.X + 20, (i & 2) ? Mx.Y - 20 : Mn.Y + 20);
		B.Box(Wood, FVector(Pc - FVector2D(22), Base), FVector(Pc + FVector2D(22), RoofZ));
	}
	for (double Z = Base + 350; Z < Deck - 10; Z += 350)
		B.Box(Dark, FVector(Mn, Z - 25), FVector(Mx, Z));
	B.Box(Dark, FVector(Mn - FVector2D(40), Deck - 35), FVector(Mx + FVector2D(40), Deck));
	AddCollisionBox(FVector(Mn - FVector2D(40), Deck - 35), FVector(Mx + FVector2D(40), Deck));
	// glass lift shaft
	B.Box(GlassL, FVector(C - FVector2D(130), Base), FVector(C + FVector2D(130), RoofZ - 20));
	B.Box(Dark, FVector(C - FVector2D(135), RoofZ - 60), FVector(C + FVector2D(135), RoofZ - 20));
	// stair flights zig-zagging round the shaft
	for (double Z = Base; Z + 350 <= Deck; Z += 350)
	{
		const bool bOdd = int32((Z - Base) / 350) % 2;
		const double Y = bOdd ? Mn.Y + 90 : Mx.Y - 90;
		B.OBox(Wood, FVector(C.X, Y, Z + 175), FVector(FMath::Sqrt(FMath::Square(Mx.X - Mn.X - 160) + 350 * 350) * 0.5, 60, 6), FRotator((bOdd ? 1 : -1) * FMath::RadiansToDegrees(FMath::Atan2(350, Mx.X - Mn.X - 160)), 0, 0));
	}
	// woven bamboo screen (vertical slats with gaps) up to deck level
	for (int32 Side = 0; Side < 4; ++Side)
	{
		const bool bAlongX = Side < 2;
		const double Fixed = Side == 0 ? Mn.Y - 6 : Side == 1 ? Mx.Y + 6 : Side == 2 ? Mn.X - 6 : Mx.X + 6;
		const double A0 = bAlongX ? Mn.X + 45 : Mn.Y + 45, A1 = bAlongX ? Mx.X - 45 : Mx.Y - 45;
		for (double A = A0; A < A1; A += 17)
		{
			const double Z1 = Deck - 40 - (int32(A / 17) % 3) * 25;
			if (bAlongX) B.Box(Bam, FVector(A - 3, Fixed - 3, Base + 30), FVector(A + 3, Fixed + 3, Z1));
			else B.Box(Bam, FVector(Fixed - 3, A - 3, Base + 30), FVector(Fixed + 3, A + 3, Z1));
		}
		// horizontal weave bands
		for (double Z = Base + 200; Z < Deck - 60; Z += 260)
		{
			if (bAlongX) B.Box(Dark, FVector(Mn.X, Fixed - 7, Z), FVector(Mx.X, Fixed + 7, Z + 10));
			else B.Box(Dark, FVector(Fixed - 7, Mn.Y, Z), FVector(Fixed + 7, Mx.Y, Z + 10));
		}
	}
	// rail at deck level, planted roof canopy above
	B.Box(B.Slot(EMat::Metal, Col::Brass()), FVector(Mn - FVector2D(40), Deck + 100), FVector(Mx + FVector2D(40), Deck + 108));
	B.Box(Dark, FVector(Mn - FVector2D(140), RoofZ), FVector(Mx + FVector2D(140), RoofZ + 30));
	B.Box(Green, FVector(Mn - FVector2D(120), RoofZ + 30), FVector(Mx + FVector2D(120), RoofZ + 42));
	for (int32 s = 0; s < 8; ++s)
		ASWCityTrees::AddShrub(Inst, FVector(Rng.R(Mn.X - 80, Mx.X + 80), Rng.R(Mn.Y - 80, Mx.Y + 80), RoofZ + 42), Rng.R(50, 90), Rng.F() < 0.3 ? Col::Flower(Rng.I(6)) : Col::Leaf(Rng.I(4)), Rng.Next(), 60000);
	{
		FBar Tmp(B, Inst, Rng);
		for (int32 d = 0; d < 12; ++d)
		{
			const double A = 2 * PI * d / 12;
			const FVector Dir(FMath::Cos(A), FMath::Sin(A), 0);
			const FVector Pc(C.X + Dir.X * ((Mx.X - Mn.X) * 0.5 + 140), C.Y + Dir.Y * ((Mx.Y - Mn.Y) * 0.5 + 140), RoofZ + 40);
			Tmp.Drapes(Pc, FVector(-Dir.Y, Dir.X, 0), Dir, 80, 1, 260);
		}
	}
	// climbing vines up two corners
	for (int32 i = 0; i < 2; ++i)
	{
		const FVector2D Pc(i ? Mx.X - 20 : Mn.X + 20, i ? Mx.Y - 20 : Mn.Y + 20);
		for (double Z = Base + 80; Z < Deck; Z += Rng.R(120, 200))
			Inst.Add(P(EPrim::Blob), M(EMat::Foliage), Col::Leaf(Rng.I(4)), Xf(FVector(Pc, Z), FVector(Rng.R(0.35, 0.5), Rng.R(0.35, 0.5), Rng.R(0.6, 0.9))), true, 60000);
	}
	AddMesh(B);
	AddInstances(Inst);
	return true;
}
