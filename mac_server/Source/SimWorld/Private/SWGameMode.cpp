#include "SWGameMode.h"

#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/PlayerStart.h"
#include "GameFramework/SpectatorPawn.h"
#include "SWCommon.h"
#include "SWEnvironment.h"

ASWGameMode::ASWGameMode()
{
	DefaultPawnClass = ASpectatorPawn::StaticClass();
}

void ASWGameMode::InitGame(const FString& MapName, const FString& Options, FString& ErrorMessage)
{
	Super::InitGame(MapName, Options, ErrorMessage);

	// Runs before any player logs in, so the player start below is used for the first pawn.
	UWorld* World = GetWorld();
	SW::EnsureFloor(World);
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
