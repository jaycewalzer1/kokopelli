#include "SWPedestrian.h"

#include "SWCommon.h"

ASWPedestrian::ASWPedestrian()
{
	WalkSpeed = 150.f; // until the controller's SetMaxSpeed (config 100..200)
}

void ASWPedestrian::BeginPlay()
{
	Super::BeginPlay();
	static const TArray<FLinearColor> Clothes = {
		FLinearColor(0.6f, 0.25f, 0.05f),
		FLinearColor(0.15f, 0.4f, 0.15f),
		FLinearColor(0.5f, 0.05f, 0.3f),
		FLinearColor(0.3f, 0.3f, 0.3f),
		FLinearColor(0.6f, 0.55f, 0.1f),
	};
	BuildHumanBody(SW::PickColor(GetName(), Clothes));
}

void ASWPedestrian::SetMaxSpeed(float Speed)
{
	SetWalkSpeed(Speed);
}

void ASWPedestrian::MoveForward()
{
	StartContinuousMove();
}

void ASWPedestrian::StopPedestrian()
{
	StopMotion();
}

void ASWPedestrian::SetWaypoints(const FString& Waypoints)
{
	if (!SetPathFromString(Waypoints))
	{
		UE_LOG(LogSimWorld, Warning, TEXT("%s: SetWaypoints could not parse '%s'"), *GetName(), *Waypoints);
	}
}

void ASWPedestrian::MovementSimulation()
{
	StartPath();
}
