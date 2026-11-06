#pragma once

#include "CoreMinimal.h"

class AActor;
class APlayerController;
class UWorld;
class USimCVCameraComponent;

/** Shared game-thread helpers for command handlers. */
namespace SimCV
{
	/** PIE or game world if one exists, else the editor world (UnrealCV does the same). */
	UWorld* GetWorld();
	APlayerController* GetPlayerController(UWorld* World);

	/** By object name (AActor::GetName, UnrealCV semantics); editor builds fall back to the actor label. */
	AActor* FindActor(UWorld* World, const FString& Name);
	/** FindActor, then any UObject in the world with that name (vbp can target non-actors). */
	UObject* FindObject(UWorld* World, const FString& Name);
	/** Moves a destroyed-but-not-yet-collected object off Name so the name can be reused at once. */
	void FreeStaleName(UWorld* World, const FString& Name);

	bool ParseBool(const FString& Text, bool& bOut);
	/** Args[First..First+2] as a vector (already validated as [float] by the router). */
	FVector VectorFromArgs(const TArray<FString>& Args, int32 First);

	/** UnrealCV formats: "%.3f %.3f %.3f"; rotators as "pitch yaw roll". */
	FString FormatVector(const FVector& Value);
	FString FormatRotator(const FRotator& Value);

	/** Class lookup for spawn commands: redirect table first, then load by path or find by short name. */
	UClass* ResolveActorClass(const FString& PathOrName, FString& OutError);
	void LoadRedirects();

	FColor GetAnnotationColor(AActor* Actor);
	void SetAnnotationColor(AActor* Actor, const FColor& Color);

	/** Number of world ticks so far in which actors ticked (game not paused). */
	uint64 GetUnpausedTickCount();
	/** Pause the game again right after the next unpaused world tick (single-step). */
	void RequestPauseAfterNextTick();
	void InitStepping();
	void ShutdownStepping();

	void RegisterCamera(USimCVCameraComponent* Camera);
	void UnregisterCamera(USimCVCameraComponent* Camera);
	/** Cameras of World in id order. In game worlds a player-view camera is created on demand as id 0. */
	TArray<USimCVCameraComponent*> GetCameras(UWorld* World);
}
