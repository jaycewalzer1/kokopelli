#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "SWTypes.h"
#include "SWCharacterBase.generated.h"

class UStaticMeshComponent;

/**
 * Shared walking logic for humanoids, pedestrians and the robot dog.
 *
 * A UCharacterMovementComponent keeps the capsule on the ground (gravity, steps, collision),
 * but motion commands drive it deterministically: acceleration and braking are so high that
 * the character is at full speed, or stopped, within one frame. So "walk 1 s at 200 cm/s"
 * moves ~200 cm. Commands only set state and return; Tick does the motion (SPEC 7.1).
 *
 * No controller is needed (bRunPhysicsWithNoController); EnableController adds the engine's
 * default AI controller on request, as SimWorld does for the robot dog.
 */
UCLASS(Abstract)
class SIMWORLD_API ASWCharacterBase : public ACharacter
{
	GENERATED_BODY()

public:
	ASWCharacterBase();

	virtual void Tick(float DeltaSeconds) override;

	/** Possess with (true) or release and destroy (false) the default AI controller (SPEC 2.4). */
	UFUNCTION(BlueprintCallable, Category = "SimWorld")
	void EnableController(bool bEnable);

	/** Turn by Angle degrees (signed; + is clockwise seen from above) over Duration seconds.
	 *  The third client argument repeats the sign and is ignored. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld")
	void Rotate_Angle(float Duration, float Angle, int32 Direction);

	float GetWalkSpeed() const { return WalkSpeed; }
	void SetWalkSpeed(float Speed);
	bool IsMoving() const { return Motion != EMotion::Idle; }

protected:
	enum class EMotion : uint8
	{
		Idle,
		Continuous, // until stopped
		Timed,      // for MoveTimeLeft seconds
		Path,       // through PathPoints, then stop
	};

	virtual void BeginPlay() override;
	virtual void Destroyed() override;

	/** Walk along LocalDirection (x = forward, y = right) until StopMotion. */
	void StartContinuousMove(const FVector2D& LocalDirection = FVector2D(1.0, 0.0));
	void StartTimedMove(const FVector2D& LocalDirection, float Duration);
	/** Walk the stored PathPoints in order, facing each one. */
	bool StartPath();
	void StopMotion();
	void StartRotation(float Duration, float Angle);
	/** Parses "x,y;x,y" into PathPoints. */
	bool SetPathFromString(const FString& Points);

	/** Movement commands are ignored while this is false (sitting, in a vehicle, gesturing). */
	virtual bool CanMove() const { return true; }

	/**
	 * Human look shared by agents and pedestrians: the configured skeletal mesh (USWSettings), or
	 * a placeholder of body, head and a nose that shows the facing direction.
	 */
	void BuildHumanBody(const FLinearColor& Clothes);

	/** Adds a visible placeholder part attached to the capsule (no collision; the capsule collides). */
	UStaticMeshComponent* AddBodyPart(ESWShape Shape, const FVector& Center, const FVector& Size, const FLinearColor& Color);
	/** Placeholder parts, hidden when a real skeletal mesh is configured. */
	UPROPERTY(Transient)
	TArray<TObjectPtr<UStaticMeshComponent>> BodyParts;

	float WalkSpeed = 150.f;
	/** Fraction of a commanded rotation's duration actually used, so the client's equal sleep always sees the final yaw. */
	static constexpr float RotationTimeFraction = 0.75f;
	static constexpr float PathAcceptRadius = 30.f;
	static constexpr float PathTurnRate = 540.f; // deg/s while following a path

private:
	EMotion Motion = EMotion::Idle;
	FVector2D MoveDirection = FVector2D(1.0, 0.0);
	float MoveTimeLeft = 0.f;

	TArray<FVector2D> PathPoints;
	int32 PathIndex = 0;

	bool bRotating = false;
	double RotationStartYaw = 0.0;
	double RotationAngle = 0.0;
	float RotationElapsed = 0.f;
	float RotationDuration = 0.f;
};
