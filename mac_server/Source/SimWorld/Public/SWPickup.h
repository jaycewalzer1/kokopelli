#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SWTypes.h"
#include "SWPickup.generated.h"

/**
 * Something a humanoid can PickUp (SPEC 6.8). Pivot at the bottom centre; movable so it can be
 * attached to the carrier and dropped again. Subclasses only set size, shape and colour.
 */
UCLASS(Abstract)
class SIMWORLD_API ASWPickup : public AActor
{
	GENERATED_BODY()

public:
	ASWPickup();

	/** Attaches to Carrier's root at Offset (carrier-relative). */
	void AttachToCarrier(AActor* Carrier, const FVector& Offset);
	/** Detaches and stands the item at Location (its bottom centre). */
	void DetachAt(const FVector& Location);
	bool IsHeld() const { return Carrier.IsValid(); }

	/** Heavy items are carried in front of the body instead of in the hand. */
	bool IsHeavy() const { return bHeavy; }

protected:
	virtual void BeginPlay() override;

	UPROPERTY(VisibleAnywhere, Category = "SimWorld")
	TObjectPtr<USceneComponent> Root;

	FVector Size = FVector(10.0);
	ESWShape Shape = ESWShape::Box;
	FLinearColor Color = FLinearColor::White;
	bool bHeavy = false;
	TWeakObjectPtr<AActor> Carrier;
};

/** /Game/InteractableAsset/Cup/BP_Mug: light pickup. */
UCLASS()
class SIMWORLD_API ASWMug : public ASWPickup
{
	GENERATED_BODY()

public:
	ASWMug();
};

/** /Game/InteractableAsset/Box/BP_Interactable_Box: heavy pickup. */
UCLASS()
class SIMWORLD_API ASWInteractableBox : public ASWPickup
{
	GENERATED_BODY()

public:
	ASWInteractableBox();
};
