#pragma once

#include "CoreMinimal.h"

class UMaterialInterface;
class UStaticMesh;
class FJsonObject;
class FJsonValue;

/**
 * Geometry + material helpers for the solarpunk city actors (docs/CITY.md).
 *
 * Every city actor builds its unique geometry into one runtime UStaticMesh (one section per
 * material+tint), and its repeated pieces (leaves, shrubs, reeds, stones) as instances of a few
 * shared primitive meshes. Materials are loaded from /Game/Solarpunk/Materials by soft path and
 * fall back to /Engine/BasicShapes/BasicShapeMaterial ("Color") while those assets are missing.
 */
namespace SWCity
{
	enum class EMat : uint8
	{
		Timber,
		RammedEarth,
		SolarGlass,
		GreenRoof,
		Moss,
		Foliage,
		Bark,
		Water,
		PermeableStone,
		Path,
		Metal,
		Fabric,
		Lantern,
		Count
	};

	/** Shared material instance for (material, tint); cached so equal pieces batch across actors. */
	UMaterialInterface* GetMaterial(EMat Mat, const FLinearColor& Tint);
	/** True once the real /Game/Solarpunk material for Mat loaded (false = BasicShapeMaterial fallback). */
	bool HasRealMaterial(EMat Mat);
	const TCHAR* MatName(EMat Mat);

	/** Shared primitives for instancing, all centred on the origin unless noted. */
	enum class EPrim : uint8
	{
		Blob,      // jittered icosphere, radius 100, smooth normals (canopies, shrubs, drapes)
		Trunk,     // tapered 7-sided cylinder, base radius 50 at z=0, top radius 28 at z=100
		Cube,      // 100 cm cube centred
		Cylinder,  // 12-sided, radius 50, z 0..100
		Reed,      // thin 4-sided spike, base radius 4, height 100
		Stone,     // flattened low-poly rock, radius 100
		Disc,      // 10-sided flat disc radius 50, 4 cm thick (lily pads, stepping stones)
		Count
	};
	UStaticMesh* GetPrim(EPrim Prim);

	/** sRGB [r,g,b] 0-255 (or 0-1) JSON array -> linear colour. */
	FLinearColor ColorFromJson(const TArray<TSharedPtr<FJsonValue>>* Arr, const FLinearColor& Default);
	FLinearColor Srgb(uint8 R, uint8 G, uint8 B);

	/** Small deterministic RNG (same name -> same city). */
	struct FRng
	{
		uint32 S;
		explicit FRng(uint32 Seed) : S(Seed * 2654435761u + 12345u) { if (!S) S = 1; }
		uint32 Next() { S ^= S << 13; S ^= S >> 17; S ^= S << 5; return S; }
		float F() { return (Next() & 0xFFFFFF) / float(0x1000000); }
		float R(float A, float B) { return A + (B - A) * F(); }
		int32 I(int32 N) { return N > 0 ? int32(Next() % uint32(N)) : 0; }
	};

	/** Deck lift: walk decks sit this far above the structural roof / bridge elevation (cm). */
	constexpr double WalkDeckLift = 55.0;
}

/** Triangle soup builder, one section per (material, tint). Positions are in the owner's local cm. */
class FSWMeshBuilder
{
public:
	int32 Slot(SWCity::EMat Mat, const FLinearColor& Tint);

	/** One triangle whose front faces along Normal (winding is fixed up from the normal). */
	void Tri(int32 S, const FVector& A, const FVector& B, const FVector& C, const FVector& Normal);
	/** Planar quad A-B-C-D (in order around the edge), facing Normal. */
	void Quad(int32 S, const FVector& A, const FVector& B, const FVector& C, const FVector& D, const FVector& Normal);

	/** Axis-aligned box. Faces listed in SkipFaces bits (1=-X 2=+X 4=-Y 8=+Y 16=-Z 32=+Z) are left out. */
	void Box(int32 S, const FVector& Min, const FVector& Max, uint8 SkipFaces = 0);
	/** Oriented box: centre, half extents, rotation. */
	void OBox(int32 S, const FVector& Center, const FVector& Half, const FRotator& Rot);
	/** Square beam of section W x H (cm) from P0 to P1 (H measured toward world up where possible). */
	void Beam(int32 S, const FVector& P0, const FVector& P1, double W, double H);
	/** Tapered cylinder on Base along +Z. */
	void Cylinder(int32 S, const FVector& Base, double R0, double R1, double Height, int32 Segments, bool bCaps = true);
	/** Cylinder between two arbitrary points. */
	void Pole(int32 S, const FVector& P0, const FVector& P1, double R, int32 Segments = 6);
	/** Extruded convex polygon (or star-shaped about its centroid), Z0..Z1. */
	void Prism(int32 S, const TArray<FVector2D>& Poly, double Z0, double Z1, bool bBottom = false);
	/** Slab following a polyline with mitred joints, Z0..Z1, width W. */
	void Ribbon(int32 S, const TArray<FVector2D>& Pts, double W, double Z0, double Z1, double Offset = 0.0);
	/** Ellipsoid (UV sphere). bHemi keeps only the top half. */
	void Ellipsoid(int32 S, const FVector& C, const FVector& R, int32 Segs, int32 Rings, bool bHemi = false);
	/** Prism with a triangular section: gable roof over [Min,Max] rising RidgeH above Max.Z, ridge along X (or Y). */
	void Gable(int32 S, const FVector& Min, const FVector& Max, double RidgeH, bool bRidgeAlongX);
	/** Barrel vault shell over [Min,Max] (springing at Min.Z), axis along X (or Y), thickness T. */
	void Vault(int32 S, const FVector& Min, const FVector& Max, double Rise, bool bAxisX, double T, int32 Segs);

	int32 NumTris() const;
	bool IsEmpty() const { return NumTris() == 0; }

	/** Builds a transient UStaticMesh (fast build path, no collision). Null when empty. */
	UStaticMesh* Build(UObject* Outer, const FString& DebugName) const;

	struct FSection
	{
		SWCity::EMat Mat = SWCity::EMat::Timber;
		FLinearColor Tint = FLinearColor::White;
		TArray<FVector3f> Pos;
		TArray<FVector3f> Nrm;
		TArray<uint32> Idx;
	};
	TArray<FSection> Sections;
	bool bSmooth = false; // Ellipsoid/primitives share vertices when true
};
