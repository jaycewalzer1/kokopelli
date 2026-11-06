#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SWTrafficLight.generated.h"

class UStaticMeshComponent;

/**
 * Street light with vehicle and pedestrian heads (/Game/city_props/.../BP_street_light, SPEC 6.4).
 * Python drives the cycle; each switch runs one timed phase here:
 *
 *   SwitchVehicleFrontGreen: vehicle green (GreenTime) -> yellow (YellowTime) -> all red
 *   SetPedestrianWalk:       pedestrian walk (PedestrianGreenTime) -> all red
 *
 * Yellow reports vehicle green = false, so the controller moves on to the next light then.
 */
UCLASS()
class SIMWORLD_API ASWTrafficLight : public AActor
{
	GENERATED_BODY()

public:
	ASWTrafficLight();

	virtual void Tick(float DeltaSeconds) override;

	UFUNCTION(BlueprintCallable, Category = "SimWorld|TrafficLight")
	void SetDuration(float InGreenTime, float InYellowTime, float InPedestrianGreenTime);

	UFUNCTION(BlueprintCallable, Category = "SimWorld|TrafficLight")
	void SwitchVehicleFrontGreen();

	UFUNCTION(BlueprintCallable, Category = "SimWorld|TrafficLight")
	void SetPedestrianWalk();

	bool IsVehicleGreen() const { return Phase == EPhase::VehicleGreen; }
	bool IsPedestrianWalk() const { return Phase == EPhase::PedestrianWalk; }
	/** Seconds left in the current phase, >= 0 (0 when all red). */
	float GetLeftTime() const { return FMath::Max(0.f, LeftTime); }

protected:
	virtual void BeginPlay() override;
	/** Whether this model has the vehicle head (the pedestrian-only light does not). */
	virtual bool HasVehicleHead() const { return true; }

private:
	enum class EPhase : uint8 { AllRed, VehicleGreen, VehicleYellow, PedestrianWalk };

	void EnterPhase(EPhase NewPhase, float Duration);
	void UpdateLamps();

	UPROPERTY(VisibleAnywhere, Category = "SimWorld")
	TObjectPtr<USceneComponent> Root;

	// Lamps: vehicle red, yellow, green; pedestrian stop, walk. Null when the head is absent.
	UPROPERTY(Transient)
	TArray<TObjectPtr<UStaticMeshComponent>> Lamps;

	float GreenTime = 10.f;
	float YellowTime = 2.f;
	float PedestrianGreenTime = 30.f;

	EPhase Phase = EPhase::AllRed;
	float LeftTime = 0.f;
};

/** Pedestrian-only light (BP_street_light_ped): same state machine, no vehicle head. */
UCLASS()
class SIMWORLD_API ASWPedestrianLight : public ASWTrafficLight
{
	GENERATED_BODY()

protected:
	virtual bool HasVehicleHead() const override { return false; }
};
