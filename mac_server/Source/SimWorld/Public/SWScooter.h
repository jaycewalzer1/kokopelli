#pragma once

#include "CoreMinimal.h"
#include "SWVehicle.h"
#include "SWScooter.generated.h"

class UStaticMeshComponent;

/**
 * Rideable scooter (/Game/ScooterAssets/Blueprints/BP_Scooter_Pawn, SPEC 6.5). Drives like a
 * vehicle (SetState) with smaller numbers. While a humanoid rides it, that humanoid's actor is
 * gone and a rider placeholder is shown on the deck instead.
 */
UCLASS()
class SIMWORLD_API ASWScooter : public ASWVehicle
{
	GENERATED_BODY()

public:
	ASWScooter();

	/** Called by ASWHumanoid::GetOnScooter just before the humanoid destroys itself. */
	void Mount(float RiderWalkSpeed);
	bool IsMounted() const { return bMounted; }

	/**
	 * Spawn a new humanoid beside the scooter, named "Base_User_Agent_C_<n>" (the client finds it by
	 * that substring and renames it back to GEN_BP_Humanoid_<id>), and hide the rider.
	 * Success is false (and nothing is spawned) when nobody is riding.
	 */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Scooter")
	void GetOffScooter(bool& Success);

protected:
	virtual void BuildBody() override;

private:
	void SetRiderVisible(bool bVisible);

	UPROPERTY(Transient)
	TArray<TObjectPtr<UStaticMeshComponent>> RiderParts;

	bool bMounted = false;
	float RiderSpeed = 200.f;
};
