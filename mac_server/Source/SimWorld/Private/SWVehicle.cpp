#include "SWVehicle.h"

#include "Components/SceneComponent.h"
#include "SWCommon.h"

ASWVehicle::ASWVehicle()
{
	PrimaryActorTick.bCanEverTick = true;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	Root->SetMobility(EComponentMobility::Movable);
	RootComponent = Root;
}

void ASWVehicle::BeginPlay()
{
	Super::BeginPlay();
	BuildBody();
}

void ASWVehicle::BuildBody()
{
	static const TArray<FLinearColor> Paints = {
		FLinearColor(0.6f, 0.02f, 0.02f),
		FLinearColor(0.02f, 0.12f, 0.5f),
		FLinearColor(0.8f, 0.8f, 0.8f),
		FLinearColor(0.03f, 0.03f, 0.03f),
		FLinearColor(0.7f, 0.5f, 0.02f),
	};
	const FLinearColor Paint = SW::PickColor(GetName(), Paints);
	const FLinearColor Glass(0.02f, 0.03f, 0.05f);
	const FLinearColor Tyre(0.01f, 0.01f, 0.01f);

	const double WheelDiameter = 0.14 * Length;
	const double BodyBottom = 0.4 * WheelDiameter;
	const double BodyTop = 0.62 * Height;
	SW::AddShape(this, Root, ESWShape::Box, FVector(0.0, 0.0, (BodyBottom + BodyTop) / 2.0),
		FVector(Length, Width, BodyTop - BodyBottom), Paint, true);
	SW::AddShape(this, Root, ESWShape::Box, FVector(-0.05 * Length, 0.0, (BodyTop + Height) / 2.0),
		FVector(0.55 * Length, 0.9 * Width, Height - BodyTop), Glass, true);

	// Wheels: cylinders turned on their side (cylinder axis is local Z, so scale X/Z and rotate 90 deg roll).
	for (const double Fore : {-1.0, 1.0})
	{
		for (const double Side : {-1.0, 1.0})
		{
			UStaticMeshComponent* Wheel = SW::AddShape(this, Root, ESWShape::Cylinder,
				FVector(Fore * 0.5 * Wheelbase, Side * (Width / 2.0 - 0.06 * Width), WheelDiameter / 2.0),
				FVector(WheelDiameter, WheelDiameter, 0.12 * Width), Tyre, false);
			Wheel->SetRelativeRotation(FRotator(0.0, 0.0, 90.0));
		}
	}
}

void ASWVehicle::SetState(float Throttle, float Brake, float Steering)
{
	ThrottleInput = FMath::Clamp(Throttle, 0.f, 1.f);
	BrakeInput = FMath::Clamp(Brake, 0.f, 1.f);
	SteeringInput = FMath::Clamp(Steering, -1.f, 1.f);
}

void ASWVehicle::MakeUTurn()
{
	bUTurn = true;
	UTurnDone = 0.0;
}

FVector ASWVehicle::GetExitLocation() const
{
	// Left side (-Y local), 60 cm clear of the body, at the actor's ground height.
	return GetActorTransform().TransformPosition(FVector(0.0, -(Width / 2.0 + 60.0), 0.0));
}

void ASWVehicle::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	const double Dt = DeltaSeconds;

	const double Accel = ThrottleInput * MaxAccel - Drag * Speed - BrakeInput * BrakeDecel;
	Speed = FMath::Max(0.0, Speed + Accel * Dt);

	double YawRate = 0.0; // degrees per second
	if (bUTurn)
	{
		// Kinematic turn that fits the 300 cm lane offset regardless of speed (SPEC 6.2).
		if (SteeringInput != 0.f)
		{
			const double Step = FMath::Min(UTurnRate * FMath::Abs(SteeringInput) * Dt, 180.0 - UTurnDone);
			YawRate = FMath::Sign(SteeringInput) * Step / FMath::Max(Dt, UE_SMALL_NUMBER);
			UTurnDone += Step;
			if (UTurnDone >= 180.0 - UE_KINDA_SMALL_NUMBER)
			{
				bUTurn = false;
			}
		}
	}
	else if (Speed > 0.0)
	{
		YawRate = FMath::RadiansToDegrees(Speed / Wheelbase * FMath::Tan(FMath::DegreesToRadians(SteeringInput * MaxSteerAngle)));
	}

	if (Speed <= 0.0 && YawRate == 0.0)
	{
		return;
	}

	SW::EnsureMovable(this);
	const double Yaw = GetActorRotation().Yaw + YawRate * Dt;
	const FVector Forward = FRotator(0.0, Yaw, 0.0).Vector();
	SetActorLocationAndRotation(GetActorLocation() + Forward * Speed * Dt, FRotator(0.0, Yaw, 0.0));
}
