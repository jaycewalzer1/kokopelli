#include "SWHumanoid.h"

#include "Components/CapsuleComponent.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "SimCVCameraComponent.h"
#include "SimCVSettings.h"
#include "SWCommon.h"
#include "SWPickup.h"
#include "SWProp.h"
#include "SWScooter.h"
#include "SWVehicle.h"

namespace
{
constexpr double SameContactSeconds = 1.0;
const FVector EyeOffset(12.0, 0.0, 70.0);      // from the capsule centre: ~160 cm above the feet
const FVector HandOffset(40.0, 25.0, 0.0);     // light items, at waist height on the right
const FVector CarryOffset(45.0, 0.0, 10.0);    // heavy items, in front of the body
}

ASWHumanoid::ASWHumanoid()
{
	Camera = CreateDefaultSubobject<USimCVCameraComponent>(TEXT("Camera"));
	Camera->SetupAttachment(GetCapsuleComponent());
	Camera->SetRelativeLocation(EyeOffset);
	WalkSpeed = 200.f; // config user.speed
}

void ASWHumanoid::BeginPlay()
{
	Super::BeginPlay();
	const USimCVSettings* CameraSettings = GetDefault<USimCVSettings>();
	Camera->FOVAngle = CameraSettings->DefaultFOV;
	Camera->SetFilmSize(CameraSettings->DefaultWidth, CameraSettings->DefaultHeight);
	BuildHumanBody(FLinearColor(0.05f, 0.2f, 0.6f));
}

void ASWHumanoid::EndPlay(const EEndPlayReason::Type Reason)
{
	if (ASWPickup* Item = Held.Get())
	{
		Item->DetachAt(GetFeetLocation());
	}
	Super::EndPlay(Reason);
}

FVector ASWHumanoid::GetFeetLocation() const
{
	return GetActorLocation() - FVector(0.0, 0.0, GetCapsuleComponent()->GetScaledCapsuleHalfHeight());
}

bool ASWHumanoid::CanMove() const
{
	return Gesture == EGesture::None && !bSitting && !CurrentVehicle.IsValid();
}

// --- Walking -----------------------------------------------------------------------------------

void ASWHumanoid::SetMaxSpeed(float Speed)
{
	SetWalkSpeed(Speed);
}

void ASWHumanoid::MoveForward()
{
	if (CanMove())
	{
		StartContinuousMove();
	}
}

void ASWHumanoid::StopAgent()
{
	StopMotion();
}

void ASWHumanoid::TurnAround(float Duration, float Angle, int32 Clockwise)
{
	// Angle already carries the sign (left = -angle); Clockwise repeats it (SPEC 6.1).
	if (!CurrentVehicle.IsValid())
	{
		StartRotation(Duration, Angle);
	}
}

void ASWHumanoid::StepForward(float Duration, int32 Direction)
{
	if (CanMove())
	{
		StartTimedMove(FVector2D(Direction == 1 ? -1.0 : 1.0, 0.0), Duration);
	}
}

void ASWHumanoid::SetPath(const FString& Path)
{
	if (!SetPathFromString(Path))
	{
		UE_LOG(LogSimWorld, Warning, TEXT("%s: SetPath could not parse '%s'"), *GetName(), *Path);
	}
}

void ASWHumanoid::FollowPath()
{
	if (CanMove())
	{
		StartPath();
	}
}

// --- Collisions --------------------------------------------------------------------------------

void ASWHumanoid::NotifyHit(UPrimitiveComponent* MyComp, AActor* Other, UPrimitiveComponent* OtherComp, bool bSelfMoved,
	FVector HitLocation, FVector HitNormal, FVector NormalImpulse, const FHitResult& Hit)
{
	Super::NotifyHit(MyComp, Other, OtherComp, bSelfMoved, HitLocation, HitNormal, NormalImpulse, Hit);
	if (!Other || Hit.ImpactNormal.Z > 0.7)
	{
		return; // standing on something is not a collision
	}

	int32* Counter = nullptr;
	if (Other->IsA<ASWCharacterBase>())
	{
		Counter = &HumanHits;
	}
	else if (Other->IsA<ASWVehicle>())
	{
		Counter = &VehicleHits;
	}
	else if (Other->IsA<ASWBuilding>())
	{
		Counter = &BuildingHits;
	}
	else if ((Other->IsA<ASWProp>() && !Other->IsA<ASWRoad>()) || Other->IsA<ASWPickup>())
	{
		Counter = &ObjectHits;
	}
	if (!Counter)
	{
		return; // floor, roads, engine actors
	}

	// Walking into a wall reports a hit every frame; count one per contact.
	const double Now = GetWorld()->GetTimeSeconds();
	double& Last = LastHitTime.FindOrAdd(TWeakObjectPtr<AActor>(Other), -1.0e9);
	if (Now - Last > SameContactSeconds)
	{
		++*Counter;
	}
	Last = Now;
}

void ASWHumanoid::GetCollisionNum(int32& HumanCollision, int32& ObjectCollision, int32& BuildingCollision, int32& VehicleCollision) const
{
	HumanCollision = HumanHits;
	ObjectCollision = ObjectHits;
	BuildingCollision = BuildingHits;
	VehicleCollision = VehicleHits;
}

// --- Interactions ------------------------------------------------------------------------------

void ASWHumanoid::SitDown(bool& Success)
{
	Success = bSitting;
	if (bSitting || CurrentVehicle.IsValid())
	{
		return;
	}
	for (TActorIterator<ASWProp> It(GetWorld()); It; ++It)
	{
		if (It->IsSeat() && SW::DistanceToActor(GetActorLocation(), *It) <= SeatReach)
		{
			StopMotion();
			bSitting = true;
			Success = true;
			return;
		}
	}
}

void ASWHumanoid::StandUp(bool& Success)
{
	Success = bSitting;
	bSitting = false;
}

void ASWHumanoid::PickUp(const FString& Object, bool& Success)
{
	Success = false;
	ASWPickup* Item = Cast<ASWPickup>(SW::FindActorByName(GetWorld(), Object));
	if (!Item || Item->IsHeld() || Held.IsValid() || CurrentVehicle.IsValid()
		|| SW::DistanceToActor(GetActorLocation(), Item) > PickUpReach)
	{
		return;
	}
	Item->AttachToCarrier(this, Item->IsHeavy() ? CarryOffset : HandOffset);
	Held = Item;
	Success = true;
}

void ASWHumanoid::DropOff(bool& Success)
{
	ASWPickup* Item = Held.Get();
	Success = Item != nullptr;
	if (Item)
	{
		Item->DetachAt(GetFeetLocation() + GetActorForwardVector() * 50.0);
		Held.Reset();
	}
}

void ASWHumanoid::EnterVehicle(const FString& Vehicle, bool& Success)
{
	Success = false;
	ASWVehicle* Car = Cast<ASWVehicle>(SW::FindActorByName(GetWorld(), Vehicle));
	if (!Car || CurrentVehicle.IsValid() || SW::DistanceToActor(GetActorLocation(), Car) > VehicleReach)
	{
		return;
	}
	StopMotion();
	bSitting = false;
	GetCharacterMovement()->DisableMovement();
	SetActorEnableCollision(false);
	SetActorHiddenInGame(true);
	SetActorLocation(Car->GetActorTransform().TransformPosition(Car->GetSeatOffset()), false, nullptr, ETeleportType::TeleportPhysics);
	SetActorRotation(FRotator(0.0, Car->GetActorRotation().Yaw, 0.0));
	AttachToActor(Car, FAttachmentTransformRules::KeepWorldTransform);
	CurrentVehicle = Car;
	Success = true;
}

void ASWHumanoid::ExitVehicle(const FString& Vehicle, bool& Success)
{
	ASWVehicle* Car = CurrentVehicle.Get();
	AActor* Named = SW::FindActorByName(GetWorld(), Vehicle);
	Success = Car && (Vehicle.IsEmpty() || Named == Car);
	if (!Success)
	{
		return;
	}
	DetachFromActor(FDetachmentTransformRules::KeepWorldTransform);
	const float HalfHeight = GetCapsuleComponent()->GetScaledCapsuleHalfHeight();
	SetActorLocation(Car->GetExitLocation() + FVector(0.0, 0.0, HalfHeight + 5.0), false, nullptr, ETeleportType::TeleportPhysics);
	SetActorHiddenInGame(false);
	SetActorEnableCollision(true);
	GetCharacterMovement()->SetMovementMode(MOVE_Falling);
	CurrentVehicle.Reset();
}

void ASWHumanoid::GetOnScooter(bool& Success)
{
	Success = false;
	if (CurrentVehicle.IsValid())
	{
		return;
	}
	ASWScooter* Nearest = nullptr;
	float NearestDistance = ScooterReach;
	for (TActorIterator<ASWScooter> It(GetWorld()); It; ++It)
	{
		const float Distance = SW::DistanceToActor(GetActorLocation(), *It);
		if (!It->IsMounted() && Distance <= NearestDistance)
		{
			Nearest = *It;
			NearestDistance = Distance;
		}
	}
	if (!Nearest)
	{
		return;
	}
	// The rider becomes part of the scooter; GetOffScooter spawns a fresh agent (SPEC 6.5).
	Nearest->Mount(GetWalkSpeed());
	Success = true;
	Destroy(); // EndPlay drops anything held
}

// --- Gestures ----------------------------------------------------------------------------------

void ASWHumanoid::StartGesture(EGesture NewGesture)
{
	if (CurrentVehicle.IsValid())
	{
		return;
	}
	StopMotion();
	Gesture = NewGesture;
}

void ASWHumanoid::Discussion(int32 Type)
{
	StartGesture(EGesture::Discussion);
}

void ASWHumanoid::Arguing(int32 Type)
{
	StartGesture(EGesture::Arguing);
}

void ASWHumanoid::Listening()
{
	StartGesture(EGesture::Listening);
}

void ASWHumanoid::Wave2Dog()
{
	StartGesture(EGesture::Wave2Dog);
}

void ASWHumanoid::Directing()
{
	StartGesture(EGesture::Directing);
}

void ASWHumanoid::StopAction()
{
	Gesture = EGesture::None;
}
