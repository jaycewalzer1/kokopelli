#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SWVehicle.generated.h"

class UStaticMeshComponent;

/**
 * Traffic car (/Game/TrafficSystem/Vehicle/Vehicle1..5, SPEC 6.2). No Chaos: a kinematic
 * bicycle model integrated every tick from the last SetState, positions set directly at the
 * spawn height (z = 0 on the road).
 *
 *   speed' = throttle * MaxAccel - Drag * speed - brake * BrakeDecel     (speed >= 0, no reverse)
 *   yaw'   = speed / Wheelbase * tan(steering * MaxSteerAngle)          (positive steering = +yaw = right)
 *
 * With the defaults throttle 1 settles at MaxAccel / Drag = 1000 cm/s (10 m/s) and brake 1
 * stops from that speed in about 1.3 s. MakeUTurn switches to an in-place kinematic turn of
 * 180 degrees in the direction of the next steering sign, then returns to the normal model.
 */
UCLASS()
class SIMWORLD_API ASWVehicle : public AActor
{
	GENERATED_BODY()

public:
	ASWVehicle();

	virtual void Tick(float DeltaSeconds) override;

	/** throttle 0..1, brake 0..1, steering -1..1. Held until changed. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Vehicle")
	void SetState(float Throttle, float Brake, float Steering);

	/** Next steering input turns the car 180 degrees (almost) in place. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Vehicle")
	void MakeUTurn();

	float GetSpeed() const { return Speed; }
	/** Where an occupant sits, relative to the actor (EnterVehicle). */
	FVector GetSeatOffset() const { return FVector(0.0, -0.2 * Width, 0.55 * Height); }
	/** Where an occupant gets out: beside the driver door, at ground level. */
	FVector GetExitLocation() const;

protected:
	virtual void BeginPlay() override;
	/** Adds the placeholder body meshes. */
	virtual void BuildBody();

	UPROPERTY(VisibleAnywhere, Category = "SimWorld")
	TObjectPtr<USceneComponent> Root;

	// Model parameters (cm, s, degrees). Subclasses change them in their constructor.
	double MaxAccel = 500.0;
	double Drag = 0.5;
	double BrakeDecel = 800.0;
	double Wheelbase = 280.0;
	double MaxSteerAngle = 35.0;
	double UTurnRate = 60.0;
	double Length = 490.0;
	double Width = 200.0;
	double Height = 145.0;

	// Controls and state.
	float ThrottleInput = 0.f;
	float BrakeInput = 0.f;
	float SteeringInput = 0.f;
	double Speed = 0.0;
	bool bUTurn = false;
	double UTurnDone = 0.0;
};

/**
 * /Game/Interactable_Vehicle/Blueprint/BP_VehicleBase_Destruction: the car a humanoid can
 * EnterVehicle / ExitVehicle (SPEC 6.8). Drivable like any ASWVehicle.
 */
UCLASS()
class SIMWORLD_API ASWEnterableCar : public ASWVehicle
{
	GENERATED_BODY()
};
