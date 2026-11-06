#pragma once

#include "CoreMinimal.h"
#include "SWCharacterBase.h"
#include "SWPedestrian.generated.h"

/**
 * Traffic pedestrian (/Game/TrafficSystem/Pedestrian/Base_Pedestrian, SPEC 6.3). The python
 * TrafficController steers it with MoveForward / StopPedestrian / Rotate_Angle; SetWaypoints +
 * MovementSimulation walks a stored polyline on its own. No camera.
 */
UCLASS()
class SIMWORLD_API ASWPedestrian : public ASWCharacterBase
{
	GENERATED_BODY()

public:
	ASWPedestrian();

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Pedestrian")
	void SetMaxSpeed(float Speed);

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Pedestrian")
	void MoveForward();

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Pedestrian")
	void StopPedestrian();

	/** "x,y;x,y" in cm. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Pedestrian")
	void SetWaypoints(const FString& Waypoints);

	/** Walk the stored waypoints in order, then stop. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Pedestrian")
	void MovementSimulation();

protected:
	virtual void BeginPlay() override;
};
