#pragma once

#include "CoreMinimal.h"
#include "SWCharacterBase.h"
#include "SWRobotDog.generated.h"

class USimCVCameraComponent;

/**
 * Quadruped robot (/Game/Robot_Dog/Blueprint/BP_SpotRobot, SPEC 6.9). Owns one camera on its
 * head. Rotate_Angle and EnableController come from ASWCharacterBase.
 */
UCLASS()
class SIMWORLD_API ASWRobotDog : public ASWCharacterBase
{
	GENERATED_BODY()

public:
	ASWRobotDog();

	/** Move |Speed| cm/s for Duration s; Direction 0 forward, 1 back, 2 left, 3 right (strafe). */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|RobotDog")
	void Move_Speed(float Speed, float Duration, int32 Direction);

	/** Tilt the camera up by CameraTiltStep degrees (client sends "lookup"; vbp names are case-insensitive). */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|RobotDog")
	void LookUp();

	UFUNCTION(BlueprintCallable, Category = "SimWorld|RobotDog")
	void LookDown();

	static constexpr float CameraTiltStep = 15.f;
	static constexpr float CameraTiltLimit = 60.f;

protected:
	virtual void BeginPlay() override;

	UPROPERTY(VisibleAnywhere, Category = "SimWorld")
	TObjectPtr<USimCVCameraComponent> Camera;

private:
	void TiltCamera(float Delta);
};
