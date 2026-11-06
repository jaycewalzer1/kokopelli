#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "SWGameMode.generated.h"

/**
 * Global default game mode (DefaultEngine.ini). There is no .umap content in this project, so the
 * engine's empty Entry map is loaded and InitGame dresses it as the flat SimWorld level: floor
 * at z = 0, sun, sky, fog, and a player start overlooking the origin. The python client then
 * builds the city with generate_world.
 *
 * The player pawn is a spectator: camera 0 follows it, and it collides with neither characters
 * nor vehicles, so it never pushes the simulation around.
 */
UCLASS()
class SIMWORLD_API ASWGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	ASWGameMode();

	virtual void InitGame(const FString& MapName, const FString& Options, FString& ErrorMessage) override;
};
