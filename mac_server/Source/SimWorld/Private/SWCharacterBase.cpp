#include "SWCharacterBase.h"

#include "Animation/AnimInstance.h"
#include "Components/CapsuleComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/Controller.h"
#include "SWCommon.h"
#include "SWSettings.h"

ASWCharacterBase::ASWCharacterBase()
{
	PrimaryActorTick.bCanEverTick = true;

	// SPEC 7.9: humanoids spawn at z=600 and fall, pedestrians spawn at z=110 = 20 cm sidewalk + 90.
	GetCapsuleComponent()->InitCapsuleSize(34.f, 90.f);

	// Rotation belongs to the commands, never to a controller or to the velocity.
	bUseControllerRotationYaw = false;
	bUseControllerRotationPitch = false;
	bUseControllerRotationRoll = false;
	AutoPossessAI = EAutoPossessAI::Disabled; // no AIController actors cluttering /objects

	UCharacterMovementComponent* Movement = GetCharacterMovement();
	Movement->bRunPhysicsWithNoController = true; // gravity and input without a controller
	Movement->bOrientRotationToMovement = false;
	Movement->bUseControllerDesiredRotation = false;
	Movement->MaxWalkSpeed = WalkSpeed;
	// Effectively instant start and stop, so distance = speed x time.
	Movement->MaxAcceleration = 100000.f;
	Movement->BrakingDecelerationWalking = 100000.f;
	Movement->GroundFriction = 8.f;
	Movement->MaxStepHeight = 45.f; // 20 cm curbs
}

void ASWCharacterBase::BeginPlay()
{
	Super::BeginPlay();
	SetWalkSpeed(WalkSpeed);
}

void ASWCharacterBase::Destroyed()
{
	// A controller added by EnableController would otherwise outlive its pawn.
	if (AController* OwnController = GetController(); OwnController && !OwnController->IsPlayerController())
	{
		OwnController->UnPossess();
		OwnController->Destroy();
	}
	Super::Destroyed();
}

void ASWCharacterBase::EnableController(bool bEnable)
{
	if (bEnable && !GetController())
	{
		SpawnDefaultController();
	}
	else if (!bEnable && GetController() && !GetController()->IsPlayerController())
	{
		AController* OwnController = GetController();
		OwnController->UnPossess();
		OwnController->Destroy();
	}
}

void ASWCharacterBase::Rotate_Angle(float Duration, float Angle, int32 Direction)
{
	StartRotation(Duration, Angle);
}

void ASWCharacterBase::SetWalkSpeed(float Speed)
{
	WalkSpeed = FMath::Max(0.f, Speed);
	GetCharacterMovement()->MaxWalkSpeed = WalkSpeed;
}

void ASWCharacterBase::StartContinuousMove(const FVector2D& LocalDirection)
{
	Motion = EMotion::Continuous;
	MoveDirection = LocalDirection;
}

void ASWCharacterBase::StartTimedMove(const FVector2D& LocalDirection, float Duration)
{
	if (Duration <= 0.f)
	{
		return;
	}
	Motion = EMotion::Timed;
	MoveDirection = LocalDirection;
	MoveTimeLeft = Duration;
}

bool ASWCharacterBase::SetPathFromString(const FString& Points)
{
	PathIndex = 0;
	return SW::ParsePoints(Points, PathPoints);
}

bool ASWCharacterBase::StartPath()
{
	if (PathPoints.Num() == 0)
	{
		return false;
	}
	PathIndex = 0;
	Motion = EMotion::Path;
	return true;
}

void ASWCharacterBase::StopMotion()
{
	Motion = EMotion::Idle;
	MoveTimeLeft = 0.f;
	// Keep the vertical speed so a falling character keeps falling.
	UCharacterMovementComponent* Movement = GetCharacterMovement();
	Movement->Velocity = FVector(0.0, 0.0, Movement->Velocity.Z);
	ConsumeMovementInputVector();
}

void ASWCharacterBase::StartRotation(float Duration, float Angle)
{
	RotationStartYaw = GetActorRotation().Yaw;
	RotationAngle = Angle;
	RotationElapsed = 0.f;
	RotationDuration = FMath::Max(0.f, Duration) * RotationTimeFraction;
	bRotating = true;
}

void ASWCharacterBase::BuildHumanBody(const FLinearColor& Clothes)
{
	const USWSettings* Settings = GetDefault<USWSettings>();
	USkeletalMesh* Mesh = Settings->CharacterMesh.IsNull() ? nullptr : Cast<USkeletalMesh>(Settings->CharacterMesh.TryLoad());
	if (Mesh)
	{
		GetMesh()->SetSkeletalMeshAsset(Mesh);
		GetMesh()->SetRelativeLocationAndRotation(Settings->CharacterMeshOffset, FRotator(0.0, Settings->CharacterMeshYaw, 0.0));
		if (UClass* AnimClass = Settings->CharacterAnimClass.TryLoadClass<UAnimInstance>())
		{
			GetMesh()->SetAnimInstanceClass(AnimClass);
		}
		return;
	}
	if (!Settings->CharacterMesh.IsNull())
	{
		UE_LOG(LogSimWorld, Warning, TEXT("CharacterMesh '%s' did not load; using the placeholder body"), *Settings->CharacterMesh.ToString());
	}

	// Capsule centre is 90 cm above the feet.
	const float HalfHeight = GetCapsuleComponent()->GetUnscaledCapsuleHalfHeight();
	AddBodyPart(ESWShape::Cylinder, FVector(0.0, 0.0, -HalfHeight + 72.0), FVector(42.0, 42.0, 144.0), Clothes);
	AddBodyPart(ESWShape::Sphere, FVector(0.0, 0.0, -HalfHeight + 160.0), FVector(26.0, 26.0, 30.0), FLinearColor(0.6f, 0.42f, 0.3f));
	AddBodyPart(ESWShape::Box, FVector(15.0, 0.0, -HalfHeight + 160.0), FVector(10.0, 6.0, 6.0), FLinearColor(0.6f, 0.42f, 0.3f));
}

UStaticMeshComponent* ASWCharacterBase::AddBodyPart(ESWShape Shape, const FVector& Center, const FVector& Size, const FLinearColor& Color)
{
	UStaticMeshComponent* Part = SW::AddShape(this, GetCapsuleComponent(), Shape, Center, Size, Color, false);
	BodyParts.Add(Part);
	return Part;
}

void ASWCharacterBase::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	if (bRotating)
	{
		RotationElapsed += DeltaSeconds;
		const double Alpha = RotationDuration > 0.f ? FMath::Min(1.0, RotationElapsed / RotationDuration) : 1.0;
		SetActorRotation(FRotator(0.0, RotationStartYaw + RotationAngle * Alpha, 0.0));
		bRotating = Alpha < 1.0;
	}

	if (Motion == EMotion::Idle || !CanMove())
	{
		return;
	}

	FVector Direction;
	if (Motion == EMotion::Path)
	{
		const FVector Location = GetActorLocation();
		FVector2D ToTarget = PathPoints[PathIndex] - FVector2D(Location.X, Location.Y);
		while (ToTarget.Size() < PathAcceptRadius)
		{
			if (++PathIndex >= PathPoints.Num())
			{
				StopMotion();
				return;
			}
			ToTarget = PathPoints[PathIndex] - FVector2D(Location.X, Location.Y);
		}
		Direction = FVector(ToTarget.GetSafeNormal(), 0.0);
		if (!bRotating)
		{
			const float TargetYaw = FMath::RadiansToDegrees(FMath::Atan2(ToTarget.Y, ToTarget.X));
			const float Yaw = FMath::FixedTurn(GetActorRotation().Yaw, TargetYaw, PathTurnRate * DeltaSeconds);
			SetActorRotation(FRotator(0.0, Yaw, 0.0));
		}
	}
	else
	{
		const FRotator YawOnly(0.0, GetActorRotation().Yaw, 0.0);
		Direction = FRotationMatrix(YawOnly).GetUnitAxis(EAxis::X) * MoveDirection.X
			+ FRotationMatrix(YawOnly).GetUnitAxis(EAxis::Y) * MoveDirection.Y;
	}
	AddMovementInput(Direction.GetSafeNormal(), 1.f);

	if (Motion == EMotion::Timed)
	{
		MoveTimeLeft -= DeltaSeconds;
		if (MoveTimeLeft <= 0.f)
		{
			StopMotion();
		}
	}
}
