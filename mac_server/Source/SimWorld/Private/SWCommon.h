#pragma once

#include "CoreMinimal.h"
#include "SWTypes.h"

class AActor;
class UMaterialInstanceDynamic;
class USceneComponent;
class UStaticMesh;
class UStaticMeshComponent;
class UWorld;

DECLARE_LOG_CATEGORY_EXTERN(LogSimWorld, Log, All);

/** Small helpers shared by the SimWorld actor classes. Game thread only. */
namespace SW
{
	/** /Engine/BasicShapes mesh for a shape (loaded once, kept alive). */
	UStaticMesh* GetShapeMesh(ESWShape Shape);

	/** Dynamic instance of /Engine/BasicShapes/BasicShapeMaterial with its "Color" parameter set. */
	UMaterialInstanceDynamic* MakeColorMaterial(UObject* Outer, const FLinearColor& Color);
	void SetShapeColor(UStaticMeshComponent* Shape, const FLinearColor& Color);

	/**
	 * Adds a registered, movable placeholder mesh under Parent.
	 * Center is relative to Parent; Size is the full extent in cm (before the actor's scale).
	 * bCollision picks the BlockAllDynamic profile, otherwise NoCollision.
	 */
	UStaticMeshComponent* AddShape(AActor* Owner, USceneComponent* Parent, ESWShape Shape, const FVector& Center,
		const FVector& Size, const FLinearColor& Color, bool bCollision);

	/** The running game (or PIE) world, else the editor world, like SimCV::GetWorld. */
	UWorld* GetGameWorld();

	/** Case-insensitive name lookup (FName semantics), like SimCV's own FindActor. */
	AActor* FindActorByName(UWorld* World, const FString& Name);

	/** Distance from Point to the collision-or-visual bounds of Target (0 inside). */
	float DistanceToActor(const FVector& Point, const AActor* Target);

	/** Makes the root movable (SPEC 2.4: static actors must still accept moves). */
	void EnsureMovable(AActor* Actor);

	/** "x,y;x,y;..." (cm). Also tolerates "X=..,Y=.." pieces and a trailing ';'. */
	bool ParsePoints(const FString& Text, TArray<FVector2D>& OutPoints);

	/** UnrealCV/ExportText float format, e.g. "7.500000" (always has a decimal point, never an exponent). */
	FString FloatString(double Value);

	/** Pretty JSON object of string values with exactly these keys, like the plugin's vbp replies. */
	FString JsonObjectString(const TArray<TPair<FString, FString>>& Fields);

	/** Stable pick from Palette by hashing Name, so the same actor name always gets the same colour. */
	FLinearColor PickColor(const FString& Name, const TArray<FLinearColor>& Palette);

	/** Looks up the generated size table: the longest key found in Name (case-insensitive, whole token) of that kind. */
	const FSWPropInfo* FindPropInfo(const FString& Name, ESWPropKind Kind);

	FLinearColor CategoryColor(ESWPropCategory Category);
}
