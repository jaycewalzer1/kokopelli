#include "SWPlayerController.h"

#include "Camera/CameraComponent.h"
#include "Components/CapsuleComponent.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Misc/App.h"
#include "SWHumanoid.h"
#include "SWPedestrian.h"

// --- controller ----------------------------------------------------------------------------------

ASWPlayerController::ASWPlayerController()
{
	// The agent loop pauses the game between steps; the person at the window should still move.
	PrimaryActorTick.bTickEvenWhenPaused = true;
	bShouldPerformFullTickWhenPaused = true;
}

void ASWPlayerController::BeginPlay()
{
	Super::BeginPlay();
	SetInputMode(FInputModeGameOnly());
	bShowMouseCursor = false;
}

void ASWPlayerController::PlayerTick(float DeltaTime)
{
	Super::PlayerTick(DeltaTime);
	if (!Spectator && GetPawn() && GetPawn() != Walker)
	{
		Spectator = GetPawn(); // the game mode's default pawn
	}

	if (WasInputKeyJustPressed(EKeys::H)) { bShowHelp = !bShowHelp; }
	if (WasInputKeyJustPressed(EKeys::V)) { CycleWatch(); }
	if (Watched.IsValid())
	{
		return; // watching someone: the view is theirs, keys only switch back
	}
	if (WasInputKeyJustPressed(EKeys::F)) { ToggleWalk(); }

	Look();
	if (IsWalking())
	{
		Walk();
	}
	else
	{
		Fly(DeltaTime);
	}
}

void ASWPlayerController::Look()
{
	float DX = 0.f, DY = 0.f;
	GetInputMouseDelta(DX, DY);
	if (DX == 0.f && DY == 0.f)
	{
		return;
	}
	FRotator R = GetControlRotation();
	R.Yaw += DX * MouseSensitivity;
	R.Pitch = FMath::Clamp(FRotator::NormalizeAxis(R.Pitch + DY * MouseSensitivity), -89.f, 89.f);
	R.Roll = 0.f;
	SetControlRotation(R);
}

void ASWPlayerController::Fly(float DeltaTime)
{
	APawn* P = GetPawn();
	if (!P)
	{
		return;
	}
	if (WasInputKeyJustPressed(EKeys::MouseScrollUp)) { FlySpeed = FMath::Min(FlySpeed * 1.25f, 20000.f); }
	if (WasInputKeyJustPressed(EKeys::MouseScrollDown)) { FlySpeed = FMath::Max(FlySpeed / 1.25f, 100.f); }

	const FRotator R = GetControlRotation();
	const FVector Fwd = R.Vector();
	const FVector Right = FRotationMatrix(R).GetScaledAxis(EAxis::Y);
	FVector Dir = FVector::ZeroVector;
	if (IsInputKeyDown(EKeys::W)) { Dir += Fwd; }
	if (IsInputKeyDown(EKeys::S)) { Dir -= Fwd; }
	if (IsInputKeyDown(EKeys::D)) { Dir += Right; }
	if (IsInputKeyDown(EKeys::A)) { Dir -= Right; }
	if (IsInputKeyDown(EKeys::E) || IsInputKeyDown(EKeys::SpaceBar)) { Dir += FVector::UpVector; }
	if (IsInputKeyDown(EKeys::Q) || IsInputKeyDown(EKeys::C)) { Dir -= FVector::UpVector; }
	if (Dir.IsNearlyZero())
	{
		return;
	}
	const float Boost = IsInputKeyDown(EKeys::LeftShift) || IsInputKeyDown(EKeys::RightShift) ? 4.f : 1.f;
	// Real seconds, so flying feels the same whether or not the simulation is paused or fixed-step.
	const float Dt = FMath::Min(FApp::GetDeltaTime(), 0.1);
	P->AddActorWorldOffset(Dir.GetSafeNormal() * FlySpeed * Boost * Dt, false, nullptr, ETeleportType::TeleportPhysics);
}

void ASWPlayerController::Walk()
{
	const FRotator Yaw(0.f, GetControlRotation().Yaw, 0.f);
	const FVector Fwd = Yaw.Vector();
	const FVector Right = FRotationMatrix(Yaw).GetScaledAxis(EAxis::Y);
	FVector Dir = FVector::ZeroVector;
	if (IsInputKeyDown(EKeys::W)) { Dir += Fwd; }
	if (IsInputKeyDown(EKeys::S)) { Dir -= Fwd; }
	if (IsInputKeyDown(EKeys::D)) { Dir += Right; }
	if (IsInputKeyDown(EKeys::A)) { Dir -= Right; }
	const bool bRun = IsInputKeyDown(EKeys::LeftShift) || IsInputKeyDown(EKeys::RightShift);
	Walker->GetCharacterMovement()->MaxWalkSpeed = bRun ? 450.f : 160.f;
	if (!Dir.IsNearlyZero())
	{
		Walker->AddMovementInput(Dir.GetSafeNormal());
	}
	if (WasInputKeyJustPressed(EKeys::SpaceBar))
	{
		Walker->Jump();
	}
}

void ASWPlayerController::ToggleWalk()
{
	UWorld* World = GetWorld();
	const FRotator View = GetControlRotation();
	if (IsWalking())
	{
		const FVector Eye = Walker->GetActorLocation() + FVector(0, 0, Walker->BaseEyeHeight);
		Possess(Spectator);
		Spectator->SetActorLocation(Eye, false, nullptr, ETeleportType::TeleportPhysics);
		Walker->Destroy();
		Walker = nullptr;
		SetControlRotation(View);
		return;
	}
	if (!Spectator)
	{
		return;
	}
	// Drop straight down from where you are flying, onto whatever is there (street, roof, deck).
	const FVector From = Spectator->GetActorLocation();
	FHitResult Hit;
	FCollisionQueryParams Q(TEXT("SWWalkerDrop"), false, Spectator);
	const FVector Ground = World->LineTraceSingleByChannel(Hit, From, From - FVector(0, 0, 100000), ECC_Visibility, Q)
		? Hit.ImpactPoint : FVector(From.X, From.Y, 0.0);
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AdjustIfPossibleButAlwaysSpawn;
	Walker = World->SpawnActor<ASWWalker>(ASWWalker::StaticClass(), Ground + FVector(0, 0, 100), FRotator(0, View.Yaw, 0), Params);
	if (Walker)
	{
		Possess(Walker);
		SetControlRotation(View);
	}
}

void ASWPlayerController::CycleWatch()
{
	// Everyone worth watching: the agent (humanoids) first, then the pedestrians, then back to yourself.
	TArray<AActor*> People;
	for (TActorIterator<ASWHumanoid> It(GetWorld()); It; ++It) { People.Add(*It); }
	for (TActorIterator<ASWPedestrian> It(GetWorld()); It; ++It) { People.Add(*It); }
	People.RemoveAll([](AActor* A) { return !IsValid(A); });

	const int32 Index = Watched.IsValid() ? People.IndexOfByKey(Watched.Get()) : INDEX_NONE;
	if (Index + 1 < People.Num())
	{
		Watched = People[Index + 1];
		SetViewTargetWithBlend(Watched.Get(), 0.25f);
	}
	else
	{
		Watched = nullptr;
		SetViewTargetWithBlend(GetPawn(), 0.25f);
	}
}

// --- pawns ---------------------------------------------------------------------------------------

ASWSpectator::ASWSpectator()
{
	bAddDefaultMovementBindings = false; // ASWPlayerController moves it
	PrimaryActorTick.bTickEvenWhenPaused = true;
}

ASWWalker::ASWWalker()
{
	PrimaryActorTick.bTickEvenWhenPaused = true;
	GetCapsuleComponent()->InitCapsuleSize(34.f, 88.f);
	// Block the city, but walk through simulated people and vehicles so you never disturb a run.
	GetCapsuleComponent()->SetCollisionResponseToChannel(ECC_Pawn, ECR_Ignore);
	GetCapsuleComponent()->SetCollisionResponseToChannel(ECC_Vehicle, ECR_Ignore);
	GetCapsuleComponent()->SetCollisionResponseToChannel(ECC_PhysicsBody, ECR_Ignore);
	BaseEyeHeight = 70.f; // eyes ~1.6 m above the ground
	bUseControllerRotationYaw = true;

	UCharacterMovementComponent* Move = GetCharacterMovement();
	Move->PrimaryComponentTick.bTickEvenWhenPaused = true;
	Move->MaxWalkSpeed = 160.f;
	Move->JumpZVelocity = 420.f;
	Move->MaxStepHeight = 45.f;
	Move->SetWalkableFloorAngle(50.f);

	UCameraComponent* Eyes = CreateDefaultSubobject<UCameraComponent>(TEXT("Eyes"));
	Eyes->SetupAttachment(GetCapsuleComponent());
	Eyes->SetRelativeLocation(FVector(0, 0, BaseEyeHeight));
	Eyes->bUsePawnControlRotation = true;
	Eyes->FieldOfView = 90.f;
}

// --- help overlay --------------------------------------------------------------------------------

void ASWHUD::DrawHUD()
{
	Super::DrawHUD();
	const ASWPlayerController* PC = Cast<ASWPlayerController>(GetOwningPlayerController());
	if (!PC || !Canvas)
	{
		return;
	}
	UFont* Font = GEngine->GetSmallFont();
	const FLinearColor Ink(0.95f, 0.92f, 0.86f, 0.9f);
	float Y = 14.f;
	auto Line = [&](const FString& Text)
	{
		Canvas->SetDrawColor(Ink.ToFColor(true));
		Canvas->DrawText(Font, Text, 16.f, Y);
		Y += 16.f;
	};
	if (const AActor* W = PC->GetWatched())
	{
		Line(FString::Printf(TEXT("WATCHING  %s   (V next, back to you after the last)"), *W->GetName()));
		return;
	}
	if (!PC->bShowHelp)
	{
		return;
	}
	if (PC->IsWalking())
	{
		Line(TEXT("WALK   WASD move   Shift run   Space jump   mouse look"));
	}
	else
	{
		Line(FString::Printf(TEXT("FLY   WASD move   E/Q up/down   Shift x4   wheel speed (%.0f m/s)   mouse look"), PC->GetFlySpeed() / 100.f));
	}
	Line(TEXT("F walk/fly   V watch the agent and people   H hide this   click the window first to capture the mouse"));
}
