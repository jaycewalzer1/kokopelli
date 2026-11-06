#include "SWTrafficLight.h"

#include "Components/SceneComponent.h"
#include "Components/StaticMeshComponent.h"
#include "SWCommon.h"

namespace
{
enum ELamp : int32 { VehicleRed, VehicleYellow, VehicleGreen, PedestrianStop, PedestrianWalk, LampCount };

const FLinearColor LampOn[LampCount] = {
	FLinearColor(1.f, 0.02f, 0.02f), FLinearColor(1.f, 0.6f, 0.f), FLinearColor(0.05f, 1.f, 0.1f),
	FLinearColor(1.f, 0.05f, 0.02f), FLinearColor(0.9f, 0.9f, 0.9f),
};
const FLinearColor LampOff(0.03f, 0.03f, 0.03f);
const FLinearColor PoleColor(0.08f, 0.08f, 0.09f);
}

ASWTrafficLight::ASWTrafficLight()
{
	PrimaryActorTick.bCanEverTick = true;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	Root->SetMobility(EComponentMobility::Movable); // the client sets it Static afterwards
	RootComponent = Root;
}

void ASWTrafficLight::BeginPlay()
{
	Super::BeginPlay();
	Lamps.Init(nullptr, LampCount);

	SW::AddShape(this, Root, ESWShape::Cylinder, FVector(0.0, 0.0, 200.0), FVector(16.0, 16.0, 400.0), PoleColor, true);
	if (HasVehicleHead())
	{
		// Vehicle head on top of the pole, lamps facing +X (the actor's yaw).
		SW::AddShape(this, Root, ESWShape::Box, FVector(0.0, 0.0, 445.0), FVector(30.0, 34.0, 100.0), PoleColor, false);
		for (int32 Lamp = VehicleRed; Lamp <= VehicleGreen; ++Lamp)
		{
			Lamps[Lamp] = SW::AddShape(this, Root, ESWShape::Sphere, FVector(16.0, 0.0, 475.0 - 30.0 * (Lamp - VehicleRed)),
				FVector(22.0), LampOff, false);
		}
	}
	// Pedestrian head at eye height.
	SW::AddShape(this, Root, ESWShape::Box, FVector(0.0, 0.0, 250.0), FVector(26.0, 30.0, 60.0), PoleColor, false);
	Lamps[PedestrianStop] = SW::AddShape(this, Root, ESWShape::Box, FVector(14.0, 0.0, 264.0), FVector(4.0, 22.0, 22.0), LampOff, false);
	Lamps[PedestrianWalk] = SW::AddShape(this, Root, ESWShape::Box, FVector(14.0, 0.0, 236.0), FVector(4.0, 22.0, 22.0), LampOff, false);
	UpdateLamps();
}

void ASWTrafficLight::SetDuration(float InGreenTime, float InYellowTime, float InPedestrianGreenTime)
{
	GreenTime = FMath::Max(0.f, InGreenTime);
	YellowTime = FMath::Max(0.f, InYellowTime);
	PedestrianGreenTime = FMath::Max(0.f, InPedestrianGreenTime);
}

void ASWTrafficLight::SwitchVehicleFrontGreen()
{
	EnterPhase(EPhase::VehicleGreen, GreenTime);
}

void ASWTrafficLight::SetPedestrianWalk()
{
	EnterPhase(EPhase::PedestrianWalk, PedestrianGreenTime);
}

void ASWTrafficLight::EnterPhase(EPhase NewPhase, float Duration)
{
	Phase = NewPhase;
	LeftTime = Duration;
	UpdateLamps();
}

void ASWTrafficLight::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (Phase == EPhase::AllRed)
	{
		return;
	}
	LeftTime -= DeltaSeconds;
	if (LeftTime > 0.f)
	{
		return;
	}
	if (Phase == EPhase::VehicleGreen)
	{
		EnterPhase(EPhase::VehicleYellow, YellowTime);
	}
	else
	{
		EnterPhase(EPhase::AllRed, 0.f);
	}
}

void ASWTrafficLight::UpdateLamps()
{
	if (Lamps.Num() != LampCount)
	{
		return; // before BeginPlay
	}
	const bool bOn[LampCount] = {
		Phase == EPhase::AllRed || Phase == EPhase::PedestrianWalk,
		Phase == EPhase::VehicleYellow,
		Phase == EPhase::VehicleGreen,
		Phase != EPhase::PedestrianWalk,
		Phase == EPhase::PedestrianWalk,
	};
	for (int32 Lamp = 0; Lamp < LampCount; ++Lamp)
	{
		SW::SetShapeColor(Lamps[Lamp], bOn[Lamp] ? LampOn[Lamp] : LampOff);
	}
}
