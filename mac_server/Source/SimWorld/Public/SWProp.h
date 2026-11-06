#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SWTypes.h"
#include "SWProp.generated.h"

class UStaticMeshComponent;

/**
 * Static city placeholder for every /Game/CityDatabase/blueprints/... prefab (SPEC 4.1).
 *
 * The pivot is at ground level in the footprint centre (the city generator places buildings by
 * their centre). Size and shape come from the generated table Private/SWPropTable.inl, keyed by
 * the asset name found inside the actor's name: generate_world names nodes after their asset
 * ("GEN_BP_Building_64_C_55", "GEN_BP_Tree5_3_637"), and the redirect table can only name a
 * class, not pass the original path. Names without an asset fall back to the class default.
 *
 * This base class covers small street elements; buildings, trees and roads are subclasses.
 */
UCLASS()
class SIMWORLD_API ASWProp : public AActor
{
	GENERATED_BODY()

public:
	ASWProp();

	/** Couches etc. accept SitDown (SPEC 6.1). */
	bool IsSeat() const { return bSeat; }

protected:
	virtual void BeginPlay() override;

	virtual ESWPropKind GetKind() const { return ESWPropKind::Small; }
	/** Size used when the name matches no table entry. */
	virtual FVector GetDefaultSize() const { return FVector(60.0, 60.0, 90.0); }
	/** Adds the placeholder meshes for a footprint of Size (cm), pivot at ground centre. */
	virtual void BuildPlaceholder(const FSWPropInfo* Info, const FVector& Size);

	UPROPERTY(VisibleAnywhere, Category = "SimWorld")
	TObjectPtr<USceneComponent> Root;

	bool bSeat = false;
};

UCLASS()
class SIMWORLD_API ASWBuilding : public ASWProp
{
	GENERATED_BODY()

protected:
	virtual ESWPropKind GetKind() const override { return ESWPropKind::Building; }
	virtual FVector GetDefaultSize() const override { return FVector(2500.0, 2300.0, 2000.0); }
	virtual void BuildPlaceholder(const FSWPropInfo* Info, const FVector& Size) override;
};

UCLASS()
class SIMWORLD_API ASWTree : public ASWProp
{
	GENERATED_BODY()

protected:
	virtual ESWPropKind GetKind() const override { return ESWPropKind::Tree; }
	virtual FVector GetDefaultSize() const override { return FVector(1000.0, 1000.0, 1600.0); }
	virtual void BuildPlaceholder(const FSWPropInfo* Info, const FVector& Size) override;
};

/**
 * One road segment (BP_Road, BP_Road1). generate_world places it at the segment midpoint with
 * scale ~(0.95, 0.9, 1); segments are 20000 cm long. Native size is chosen so that after that
 * scale the asphalt spans the whole segment, lanes sit at +-300 cm, the 20 cm high sidewalks
 * cover the pedestrian line at +-1700 cm, and the road edge meets the building fronts at
 * +-2700 cm (citygen building_side_distance). Sidewalks stop short of intersections.
 */
UCLASS()
class SIMWORLD_API ASWRoad : public ASWProp
{
	GENERATED_BODY()

protected:
	virtual ESWPropKind GetKind() const override { return ESWPropKind::Road; }
	virtual FVector GetDefaultSize() const override;
	virtual void BuildPlaceholder(const FSWPropInfo* Info, const FVector& Size) override;
};
