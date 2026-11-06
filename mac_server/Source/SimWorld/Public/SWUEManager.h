#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SWUEManager.generated.h"

/**
 * Traffic state reporter and batch controller (/Game/TrafficSystem/UE_Manager, spawned as
 * GEN_BP_UEManager, SPEC 6.6). It finds actors by name prefix and re-scans the world on every
 * call, so it works whether it was spawned before or after the traffic.
 */
UCLASS()
class SIMWORLD_API ASWUEManager : public AActor
{
	GENERATED_BODY()

public:
	ASWUEManager();

	/**
	 * All nine strings, each one "<name>X=.. Y=.. Z=.." (FVector::ToString) / "<name>P=.. Y=.. R=.."
	 * (FRotator::ToString) / "<name><green><walk><left_time>" per actor, entries joined by '\n'.
	 */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Manager")
	void GetInformation(FString& VLocations, FString& VRotations, FString& PLocations, FString& PRotations, FString& LStates,
		FString& ALocations, FString& ARotations, FString& SLocations, FString& SRotations) const;

	/** Kept for the client; GetInformation always re-scans. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Manager")
	void UpdateObjects();

	/** "name,throttle,brake,steering;..." -> ASWVehicle::SetState for each (scooters included). */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Manager")
	void VSetState(const FString& States);

	/**
	 * "name,state;..." for pedestrians; unused by simworld. State 0 stops, any other number
	 * walks forward at that speed (1 keeps the current speed). Malformed entries are ignored.
	 */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Manager")
	void PSetState(const FString& States);

	/** The nine GetInformation fields in the client's key order, for an exact-key JSON reply. */
	TArray<TPair<FString, FString>> GetInformationFields() const;
};
