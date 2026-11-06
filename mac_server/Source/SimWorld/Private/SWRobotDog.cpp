#include "SWRobotDog.h"

#include "Components/CapsuleComponent.h"
#include "SimCVCameraComponent.h"
#include "SimCVSettings.h"
#include "SWCommon.h"

namespace
{
constexpr float DogHalfHeight = 40.f; // body centre 40 cm above the ground
}

ASWRobotDog::ASWRobotDog()
{
	GetCapsuleComponent()->InitCapsuleSize(35.f, DogHalfHeight);
	Camera = CreateDefaultSubobject<USimCVCameraComponent>(TEXT("Camera"));
	Camera->SetupAttachment(GetCapsuleComponent());
	Camera->SetRelativeLocation(FVector(55.0, 0.0, 25.0));
	WalkSpeed = 100.f;
}

void ASWRobotDog::BeginPlay()
{
	Super::BeginPlay();
	const USimCVSettings* CameraSettings = GetDefault<USimCVSettings>();
	Camera->FOVAngle = CameraSettings->DefaultFOV;
	Camera->SetFilmSize(CameraSettings->DefaultWidth, CameraSettings->DefaultHeight);

	const FLinearColor Shell(0.8f, 0.65f, 0.05f);
	const FLinearColor Dark(0.03f, 0.03f, 0.03f);
	AddBodyPart(ESWShape::Box, FVector(0.0, 0.0, 10.0), FVector(100.0, 36.0, 26.0), Shell);
	AddBodyPart(ESWShape::Box, FVector(55.0, 0.0, 20.0), FVector(20.0, 26.0, 18.0), Dark);
	for (const double Fore : {-38.0, 38.0})
	{
		for (const double Side : {-16.0, 16.0})
		{
			AddBodyPart(ESWShape::Cylinder, FVector(Fore, Side, -DogHalfHeight / 2.0), FVector(8.0, 8.0, DogHalfHeight + 6.0), Dark);
		}
	}
}

void ASWRobotDog::Move_Speed(float Speed, float Duration, int32 Direction)
{
	// For speed < 0 the client flips Direction but keeps the sign; use |speed| (SPEC 6.9).
	static const FVector2D Directions[4] = {FVector2D(1.0, 0.0), FVector2D(-1.0, 0.0), FVector2D(0.0, -1.0), FVector2D(0.0, 1.0)};
	SetWalkSpeed(FMath::Abs(Speed));
	StartTimedMove(Directions[FMath::Clamp(Direction, 0, 3)], Duration);
}

void ASWRobotDog::LookUp()
{
	TiltCamera(CameraTiltStep);
}

void ASWRobotDog::LookDown()
{
	TiltCamera(-CameraTiltStep);
}

void ASWRobotDog::TiltCamera(float Delta)
{
	FRotator Rotation = Camera->GetRelativeRotation();
	Rotation.Pitch = FMath::Clamp(Rotation.Pitch + Delta, -CameraTiltLimit, CameraTiltLimit);
	Camera->SetRelativeRotation(Rotation);
}
