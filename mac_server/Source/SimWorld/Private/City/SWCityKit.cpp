#include "City/SWCityActors.h"

#include "City/SWCityJson.h"
#include "City/SWCityMesh.h"

using namespace SWCity;
namespace J = SWCity::Json;

namespace
{
EMat KitMat(const FString& N)
{
	FString K = N;
	K.RemoveFromStart(TEXT("M_"));
	for (int32 i = 0; i < int32(EMat::Count); ++i)
	{
		FString Name = MatName(EMat(i));
		Name.RemoveFromStart(TEXT("M_"));
		if (Name == K)
		{
			return EMat(i);
		}
	}
	return EMat::PermeableStone;
}

EPrim KitPrim(const FString& N)
{
	static const TMap<FString, EPrim> Prims = {
		{TEXT("Blob"), EPrim::Blob}, {TEXT("Trunk"), EPrim::Trunk}, {TEXT("Cube"), EPrim::Cube}, {TEXT("Cylinder"), EPrim::Cylinder},
		{TEXT("Reed"), EPrim::Reed}, {TEXT("Stone"), EPrim::Stone}, {TEXT("Disc"), EPrim::Disc}, {TEXT("Puff"), EPrim::Puff},
		{TEXT("Fringe"), EPrim::Fringe}, {TEXT("Cone"), EPrim::Cone}};
	const EPrim* Found = Prims.Find(N);
	return Found ? *Found : EPrim::Cube;
}

/** Numbers of one op row from index I on; strings count as 0. */
TArray<double> Row(const TArray<TSharedPtr<FJsonValue>>& A, int32 I)
{
	TArray<double> Out;
	for (; I < A.Num(); ++I)
	{
		Out.Add(A[I].IsValid() && A[I]->Type == EJson::Number ? A[I]->AsNumber() : 0.0);
	}
	return Out;
}

TArray<FVector2D> Pts(const TArray<double>& V, int32 From)
{
	TArray<FVector2D> Out;
	for (int32 i = From; i + 1 < V.Num(); i += 2)
	{
		Out.Add(FVector2D(V[i], V[i + 1]));
	}
	return Out;
}
}

/**
 * Ops (all lengths cm, positions actor-local, angles degrees; "s" = index into "slots"):
 *   ["box", s, x0,y0,z0, x1,y1,z1 (, skip_faces)]        axis box; skip bits 1=-X 2=+X 4=-Y 8=+Y 16=-Z 32=+Z
 *   ["obox", s, cx,cy,cz, hx,hy,hz, pitch,yaw,roll]      oriented box (half extents)
 *   ["beam", s, x0,y0,z0, x1,y1,z1, w,h]                 square beam between two points
 *   ["cyl", s, x,y,z, r0,r1,h, segs (, caps)]            tapered cylinder up +Z
 *   ["pole", s, x0,y0,z0, x1,y1,z1, r (, segs)]          cylinder between two points
 *   ["prism", s, z0,z1, bottom, x,y, x,y, ...]           extruded convex/star polygon
 *   ["ribbon", s, w,z0,z1, offset, x,y, x,y, ...]        slab along a polyline
 *   ["ell", s, cx,cy,cz, rx,ry,rz, segs,rings, hemi]     ellipsoid / dome
 *   ["gable", s, x0,y0,z0, x1,y1,z1, ridge_h, along_x]   triangular roof prism over a box
 *   ["vault", s, x0,y0,z0, x1,y1,z1, rise, axis_x, t, segs]
 *   ["quad", s, ax,ay,az, bx,by,bz, cx,cy,cz, dx,dy,dz, nx,ny,nz]
 *   ["tri", s, ax,ay,az, bx,by,bz, cx,cy,cz, nx,ny,nz]
 */
bool ASWCityKit::Build(const TSharedPtr<FJsonObject>& Obj, FString& Error)
{
	FSWMeshBuilder B;
	TArray<int32> Slots;
	if (const TArray<TSharedPtr<FJsonValue>>* SA = J::Arr(Obj, TEXT("slots")))
	{
		for (const TSharedPtr<FJsonValue>& V : *SA)
		{
			const TSharedPtr<FJsonObject>* SO = nullptr;
			if (!V.IsValid() || !V->TryGetObject(SO))
			{
				Error = TEXT("slot is not an object");
				return false;
			}
			Slots.Add(B.Slot(KitMat(J::Str(*SO, TEXT("mat"))), J::Color(*SO, TEXT("tint"), FLinearColor::White), float(J::Num(*SO, TEXT("scale"), 0.0))));
		}
	}
	int32 Bad = 0;
	if (const TArray<TSharedPtr<FJsonValue>>* Ops = J::Arr(Obj, TEXT("ops")))
	{
		for (const TSharedPtr<FJsonValue>& V : *Ops)
		{
			const TArray<TSharedPtr<FJsonValue>>* A = nullptr;
			if (!V.IsValid() || !V->TryGetArray(A) || A->Num() < 2)
			{
				++Bad;
				continue;
			}
			const FString Op = (*A)[0]->AsString();
			const int32 SI = int32((*A)[1]->AsNumber());
			if (!Slots.IsValidIndex(SI))
			{
				++Bad;
				continue;
			}
			const int32 S = Slots[SI];
			const TArray<double> R = Row(*A, 2);
			auto V3 = [&R](int32 i) { return FVector(R[i], R[i + 1], R[i + 2]); };
			const int32 N = R.Num();
			if (Op == TEXT("box") && N >= 6)
			{
				B.Box(S, V3(0).ComponentMin(V3(3)), V3(0).ComponentMax(V3(3)), N >= 7 ? uint8(R[6]) : 0);
			}
			else if (Op == TEXT("obox") && N >= 9)
			{
				B.OBox(S, V3(0), V3(3), FRotator(R[6], R[7], R[8]));
			}
			else if (Op == TEXT("beam") && N >= 8)
			{
				B.Beam(S, V3(0), V3(3), R[6], R[7]);
			}
			else if (Op == TEXT("cyl") && N >= 7)
			{
				B.Cylinder(S, V3(0), R[3], R[4], R[5], FMath::Clamp(int32(R[6]), 3, 48), N >= 8 ? R[7] != 0 : true);
			}
			else if (Op == TEXT("pole") && N >= 7)
			{
				B.Pole(S, V3(0), V3(3), R[6], N >= 8 ? FMath::Clamp(int32(R[7]), 3, 32) : 6);
			}
			else if (Op == TEXT("prism") && N >= 9)
			{
				B.Prism(S, Pts(R, 3), R[0], R[1], R[2] != 0);
			}
			else if (Op == TEXT("ribbon") && N >= 8)
			{
				B.Ribbon(S, Pts(R, 4), R[0], R[1], R[2], R[3]);
			}
			else if (Op == TEXT("ell") && N >= 9)
			{
				B.Ellipsoid(S, V3(0), V3(3), FMath::Clamp(int32(R[6]), 4, 48), FMath::Clamp(int32(R[7]), 2, 32), R[8] != 0);
			}
			else if (Op == TEXT("gable") && N >= 8)
			{
				B.Gable(S, V3(0).ComponentMin(V3(3)), V3(0).ComponentMax(V3(3)), R[6], R[7] != 0);
			}
			else if (Op == TEXT("vault") && N >= 10)
			{
				B.Vault(S, V3(0).ComponentMin(V3(3)), V3(0).ComponentMax(V3(3)), R[6], R[7] != 0, R[8], FMath::Clamp(int32(R[9]), 2, 48));
			}
			else if (Op == TEXT("quad") && N >= 15)
			{
				B.Quad(S, V3(0), V3(3), V3(6), V3(9), V3(12));
			}
			else if (Op == TEXT("tri") && N >= 12)
			{
				B.Tri(S, V3(0), V3(3), V3(6), V3(9));
			}
			else
			{
				++Bad;
			}
		}
	}
	FInstances Inst;
	if (const TArray<TSharedPtr<FJsonValue>>* IA = J::Arr(Obj, TEXT("inst")))
	{
		for (const TSharedPtr<FJsonValue>& V : *IA)
		{
			const TArray<TSharedPtr<FJsonValue>>* A = nullptr;
			if (!V.IsValid() || !V->TryGetArray(A) || A->Num() < 12)
			{
				++Bad;
				continue;
			}
			const TArray<double> R = Row(*A, 2);
			const FLinearColor Tint = Srgb(uint8(FMath::Clamp(R[0], 0.0, 255.0)), uint8(FMath::Clamp(R[1], 0.0, 255.0)), uint8(FMath::Clamp(R[2], 0.0, 255.0)));
			const bool bShadow = R.Num() >= 11 ? R[10] != 0 : true;
			Inst.Add(uint8(KitPrim((*A)[0]->AsString())), uint8(KitMat((*A)[1]->AsString())), Tint,
				FTransform(FRotator(R.Num() >= 13 ? R[12] : 0.0, R[6], R.Num() >= 14 ? R[13] : 0.0), FVector(R[3], R[4], R[5]), FVector(R[7], R[8], R[9])), bShadow, R.Num() >= 12 ? R[11] : 0.0);
		}
	}
	if (const TArray<TSharedPtr<FJsonValue>>* CA = J::Arr(Obj, TEXT("collide")))
	{
		for (const TSharedPtr<FJsonValue>& V : *CA)
		{
			const TArray<double> R = J::Nums(V.IsValid() ? &V->AsArray() : nullptr);
			if (R.Num() >= 6)
			{
				AddCollisionBox(FVector(R[0], R[1], R[2]).ComponentMin(FVector(R[3], R[4], R[5])), FVector(R[0], R[1], R[2]).ComponentMax(FVector(R[3], R[4], R[5])));
			}
		}
	}
	if (!B.IsEmpty())
	{
		AddMesh(B, J::Bool(Obj, TEXT("shadow"), true));
	}
	AddInstances(Inst);
	if (Bad)
	{
		Error = FString::Printf(TEXT("%d malformed ops"), Bad);
		UE_LOG(LogTemp, Warning, TEXT("%s: %s"), *GetName(), *Error);
	}
	return Bad == 0;
}
