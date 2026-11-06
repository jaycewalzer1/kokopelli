#include "SWGameMode.h"

#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/PlayerStart.h"
#include "GameFramework/WorldSettings.h"
#include "SWPlayerController.h"
#include "SWCommon.h"
#include "SWEnvironment.h"

ASWGameMode::ASWGameMode()
{
	DefaultPawnClass = ASWSpectator::StaticClass();
	PlayerControllerClass = ASWPlayerController::StaticClass();
	HUDClass = ASWHUD::StaticClass();
}

void ASWGameMode::InitGame(const FString& MapName, const FString& Options, FString& ErrorMessage)
{
	Super::InitGame(MapName, Options, ErrorMessage);

	// Runs before any player logs in, so the player start below is used for the first pawn.
	UWorld* World = GetWorld();
	SW::EnsureFloor(World);
	// Anything that walks off the edge of the floor is removed 200 m down, instead of falling for ~10 km with
	// growing coordinates (stray pedestrians did that, and UE 5.8's scene culling later asserted).
	if (AWorldSettings* Settings = World->GetWorldSettings())
	{
		Settings->KillZ = -20000.f;
	}
	SW::FindOrSpawnEnvironment(World);

	TActorIterator<APlayerStart> Existing(World);
	if (!Existing)
	{
		FActorSpawnParameters Params;
		Params.Name = TEXT("SWPlayerStart");
		Params.NameMode = FActorSpawnParameters::ESpawnActorNameMode::Requested;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		World->SpawnActor<APlayerStart>(APlayerStart::StaticClass(), FVector(-1500.0, 0.0, 400.0), FRotator::ZeroRotator, Params);
	}
	UE_LOG(LogSimWorld, Display, TEXT("SimWorld level ready on map %s"), *MapName);
}
