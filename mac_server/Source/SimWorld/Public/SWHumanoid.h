#pragma once

#include "CoreMinimal.h"
#include "SWCharacterBase.h"
#include "SWHumanoid.generated.h"

class ASWPickup;
class ASWVehicle;
class USimCVCameraComponent;

/**
 * The controllable agent: Base_User_Agent_C and BP_Default_Character_C (SPEC 6.1).
 * Owns one SimCV camera at eye height looking along the actor's yaw, so the n-th humanoid
 * spawned is camera n (camera 0 is the player view, SPEC 3.1).
 *
 * Every function returns at once; walking, turning and timed steps run in Tick.
 * Functions with a bool& Success reply {"Success":"true"|"false"} through vbp.
 */
UCLASS()
class SIMWORLD_API ASWHumanoid : public ASWCharacterBase
{
	GENERATED_BODY()

public:
	ASWHumanoid();

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid")
	void SetMaxSpeed(float Speed);

	/** Walk along the current yaw until StopAgent. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid")
	void MoveForward();

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid")
	void StopAgent();

	/** Client sends "1 <signed angle> <+-1>": yaw += Angle within Duration (the client sleeps 1 s). */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid")
	void TurnAround(float Duration, float Angle, int32 Clockwise);

	/** Walk Duration seconds forward (Direction 0) or backward (1), then stop. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid")
	void StepForward(float Duration, int32 Direction);

	/** "x,y;x,y;..." in cm, walked by FollowPath. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid")
	void SetPath(const FString& Path);

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid")
	void FollowPath();

	/** Cumulative hit counts since spawn. A contact with the same actor counts once per second. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid")
	void GetCollisionNum(int32& HumanCollision, int32& ObjectCollision, int32& BuildingCollision, int32& VehicleCollision) const;

	/** Succeeds when a seat (couch) is within SeatReach. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid")
	void SitDown(bool& Success);

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid")
	void StandUp(bool& Success);

	/** Object must be a mug or interactable box within PickUpReach; it then moves with the agent. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid")
	void PickUp(const FString& Object, bool& Success);

	/** Puts the held object down at the agent's feet. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid")
	void DropOff(bool& Success);

	/** Hide in Vehicle's seat if it is within VehicleReach. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid")
	void EnterVehicle(const FString& Vehicle, bool& Success);

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid")
	void ExitVehicle(const FString& Vehicle, bool& Success);

	/** Mount the nearest free scooter within ScooterReach. Destroys this actor (SPEC 6.5). */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid")
	void GetOnScooter(bool& Success);

	// Gestures (placeholders: they only block movement until StopAction).
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid|Gesture")
	void Discussion(int32 Type);

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid|Gesture")
	void Arguing(int32 Type);

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid|Gesture")
	void Listening();

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid|Gesture")
	void Wave2Dog();

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid|Gesture")
	void Directing();

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Humanoid|Gesture")
	void StopAction();

	USimCVCameraComponent* GetCamera() const { return Camera; }

	static constexpr float SeatReach = 150.f;
	static constexpr float PickUpReach = 200.f;
	static constexpr float VehicleReach = 400.f;
	static constexpr float ScooterReach = 300.f;

protected:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;
	virtual void NotifyHit(UPrimitiveComponent* MyComp, AActor* Other, UPrimitiveComponent* OtherComp, bool bSelfMoved,
		FVector HitLocation, FVector HitNormal, FVector NormalImpulse, const FHitResult& Hit) override;
	virtual bool CanMove() const override;

	UPROPERTY(VisibleAnywhere, Category = "SimWorld")
	TObjectPtr<USimCVCameraComponent> Camera;

private:
	enum class EGesture : uint8 { None, Discussion, Arguing, Listening, Wave2Dog, Directing };

	void StartGesture(EGesture NewGesture);
	FVector GetFeetLocation() const;

	int32 HumanHits = 0;
	int32 ObjectHits = 0;
	int32 BuildingHits = 0;
	int32 VehicleHits = 0;
	TMap<TWeakObjectPtr<AActor>, double> LastHitTime;

	EGesture Gesture = EGesture::None;
	bool bSitting = false;
	TWeakObjectPtr<ASWPickup> Held;
	TWeakObjectPtr<ASWVehicle> CurrentVehicle;
};
