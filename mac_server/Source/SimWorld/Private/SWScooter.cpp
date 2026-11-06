#include "SWScooter.h"

#include "Components/StaticMeshComponent.h"
#include "Engine/World.h"
#include "SWCommon.h"
#include "SWHumanoid.h"

ASWScooter::ASWScooter()
{
	// Throttle 1 settles at 300 / 0.6 = 500 cm/s.
	MaxAccel = 300.0;
	Drag = 0.6;
	BrakeDecel = 600.0;
	Wheelbase = 100.0;
	MaxSteerAngle = 30.0;
	Length = 130.0;
	Width = 50.0;
	Height = 115.0;
}

void ASWScooter::BuildBody()
{
	const FLinearColor Frame(0.05f, 0.15f, 0.7f);
	const FLinearColor Tyre(0.01f, 0.01f, 0.01f);
	const double Wheel = 22.0;

	SW::AddShape(this, Root, ESWShape::Box, FVector(0.0, 0.0, Wheel), FVector(Length * 0.8, 18.0, 6.0), Frame, true);
	SW::AddShape(this, Root, ESWShape::Cylinder, FVector(Length * 0.38, 0.0, Height / 2.0), FVector(5.0, 5.0, Height - Wheel), Frame, true);
	SW::AddShape(this, Root, ESWShape::Box, FVector(Length * 0.38, 0.0, Height), FVector(5.0, 50.0, 4.0), Frame, false);
	for (const double Fore : {-0.5, 0.5})
	{
		UStaticMeshComponent* Part = SW::AddShape(this, Root, ESWShape::Cylinder, FVector(Fore * Wheelbase, 0.0, Wheel / 2.0),
			FVector(Wheel, Wheel, 6.0), Tyre, false);
		Part->SetRelativeRotation(FRotator(0.0, 0.0, 90.0));
	}

	// Rider standing on the deck, hidden until Mount.
	RiderParts.Add(SW::AddShape(this, Root, ESWShape::Cylinder, FVector(-5.0, 0.0, Wheel + 75.0), FVector(42.0, 42.0, 144.0), FLinearColor(0.05f, 0.2f, 0.6f), false));
	RiderParts.Add(SW::AddShape(this, Root, ESWShape::Sphere, FVector(-5.0, 0.0, Wheel + 163.0), FVector(26.0, 26.0, 30.0), FLinearColor(0.6f, 0.42f, 0.3f), false));
	SetRiderVisible(bMounted);
}

void ASWScooter::SetRiderVisible(bool bVisible)
{
	for (UStaticMeshComponent* Part : RiderParts)
	{
		if (Part)
		{
			Part->SetVisibility(bVisible);
		}
	}
}

void ASWScooter::Mount(float RiderWalkSpeed)
{
	bMounted = true;
	RiderSpeed = RiderWalkSpeed;
	SetRiderVisible(true);
}

void ASWScooter::GetOffScooter(bool& Success)
{
	Success = false;
	UWorld* World = GetWorld();
	if (!bMounted || !World)
	{
		return;
	}

	// The client renames the first "Base_User_Agent_C_" it finds, so pick a fresh number explicitly.
	FString Name;
	for (int32 Index = 0; ; ++Index)
	{
		Name = FString::Printf(TEXT("Base_User_Agent_C_%d"), Index);
		if (!SW::FindActorByName(World, Name) && !StaticFindObjectFast(nullptr, World->GetCurrentLevel(), FName(*Name)))
		{
			break;
		}
	}

	FActorSpawnParameters Params;
	Params.Name = FName(*Name);
	Params.NameMode = FActorSpawnParameters::ESpawnActorNameMode::Requested;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AdjustIfPossibleButAlwaysSpawn;
	// Step off to the right of the deck; capsule centre 90 cm above the ground.
	const FVector Location = GetActorTransform().TransformPosition(FVector(0.0, Width / 2.0 + 70.0, 0.0)) + FVector(0.0, 0.0, 95.0);
	ASWHumanoid* Rider = World->SpawnActor<ASWHumanoid>(ASWHumanoid::StaticClass(), Location, FRotator(0.0, GetActorRotation().Yaw, 0.0), Params);
	if (!Rider)
	{
		UE_LOG(LogSimWorld, Error, TEXT("%s: could not spawn the rider"), *GetName());
		return;
	}
	Rider->SetMaxSpeed(RiderSpeed);
	bMounted = false;
	SetRiderVisible(false);
	Success = true;
}
