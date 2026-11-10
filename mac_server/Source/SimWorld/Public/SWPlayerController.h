#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "GameFramework/HUD.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/SpectatorPawn.h"
#include "SWPlayerController.generated.h"

/**
 * Whoever sits at the game window. Keys are polled here directly (no input assets to cook), and
 * everything keeps working while the simulation is paused between agent steps.
 *
 *   Fly  (start)  WASD move, E/Space up, Q/C down, Shift x4, mouse wheel speed. Passes through walls.
 *   Walk  F       first-person body with gravity and collision; Shift run, Space jump. F again: fly.
 *   Watch V       look through someone's eyes: the agent first, then each pedestrian, then back to you.
 *   Help  H       show or hide the key list.
 *   Rest  M       minimize the window (click the Dock icon to bring it back).
 *
 * Why minimizing matters: UE 5.8's Mac present path leaks one Metal shared event per presented frame
 * (IOSurfaceSharedEventReference ports, ~60/s). They are a system-wide resource: after ~20-25 min of
 * visible rendering, other apps' Metal (MLX/Qwen) fails with "Failed to create Metal shared event".
 * A minimized window presents nothing, so the leak stops while the simulation keeps running. The window
 * minimizes itself after AutoRestSeconds without focus, and the HUD shows how much of the budget is used.
 */
UCLASS()
class SIMWORLD_API ASWPlayerController : public APlayerController
{
	GENERATED_BODY()

public:
	ASWPlayerController();

	virtual void BeginPlay() override;
	virtual void PlayerTick(float DeltaTime) override;

	bool IsWalking() const { return Walker != nullptr && GetPawn() == Walker; }
	float GetFlySpeed() const { return FlySpeed; }
	AActor* GetWatched() const { return Watched.Get(); }
	bool bShowHelp = true;
	/** Frames presented to the window since launch (each leaks one Metal shared event). */
	int64 PresentedFrames = 0;
	static constexpr int64 PresentBudget = 70000; // MLX failed after roughly 85k; warn well before
	void Rest();

private:
	void Look();
	void Fly(float DeltaTime);
	void Walk();
	void ToggleWalk();
	void CycleWatch();

	UPROPERTY()
	TObjectPtr<APawn> Spectator;
	UPROPERTY()
	TObjectPtr<ACharacter> Walker;
	TWeakObjectPtr<AActor> Watched;

	float FlySpeed = 1500.f; // cm/s
	float UnfocusedSeconds = 0.f;
	float AutoRestSeconds = 120.f;
	float MouseSensitivity = 0.6f;
	bool bMouseLook = true; // false with -nomouse: capture runs, where a bumped mouse would turn camera 0
};

/** The flying camera: the engine spectator without its own key bindings (the controller drives it). */
UCLASS()
class SIMWORLD_API ASWSpectator : public ASpectatorPawn
{
	GENERATED_BODY()

public:
	ASWSpectator();
};

/** The walking body: a 1.75 m person who stands on buildings and ground but never pushes the simulated people. */
UCLASS()
class SIMWORLD_API ASWWalker : public ACharacter
{
	GENERATED_BODY()

public:
	ASWWalker();
};

/** A small key list in the corner. Scene captures don't include it, so camera images stay clean. */
UCLASS()
class SIMWORLD_API ASWHUD : public AHUD
{
	GENERATED_BODY()

public:
	virtual void DrawHUD() override;
};
