#include "SimCVCommands.h"

#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/App.h"
#include "SimCVCommandRouter.h"
#include "SimCVWorld.h"

namespace
{
using namespace SimCV;

FSimCVReply SetPaused(bool bPaused)
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return FSimCVReply::Error(TEXT("No valid world"));
	}
	if (!GetPlayerController(World))
	{
		return FSimCVReply::Error(TEXT("No player controller"));
	}
	UGameplayStatics::SetGamePaused(World, bPaused);
	return FSimCVReply::Ok();
}

/**
 * Sync-mode step. SimWorld pauses the game, sets tick_intervel, then sends "tick" each step.
 * We unpause, let exactly one world tick run (re-paused from OnWorldPostActorTick), and only
 * then reply, so the client's blocking request returns after the step has happened.
 */
FSimCVReply TickOnce()
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return FSimCVReply::Error(TEXT("No valid world"));
	}
	const uint64 Target = GetUnpausedTickCount() + 1;
	if (World->IsPaused())
	{
		if (!UGameplayStatics::SetGamePaused(World, false))
		{
			return FSimCVReply::Error(TEXT("Could not unpause the game for a tick"));
		}
		RequestPauseAfterNextTick();
	}

	TWeakObjectPtr<UWorld> WeakWorld(World);
	return FSimCVReply::Pending([WeakWorld, Target](FSimCVReply& Out)
	{
		if (!WeakWorld.IsValid())
		{
			Out = FSimCVReply::Error(TEXT("World was destroyed during tick"));
			return true;
		}
		if (GetUnpausedTickCount() < Target)
		{
			return false;
		}
		Out = FSimCVReply::Ok();
		return true;
	});
}
}

void SimCV::RegisterActionCommands(FSimCVCommandRouter& Router)
{
	Router.Register(TEXT("vset /action/game/pause"), [](const FSimCVArgs&) { return SetPaused(true); }, TEXT("Pause the game"));
	Router.Register(TEXT("vset /action/game/resume"), [](const FSimCVArgs&) { return SetPaused(false); }, TEXT("Resume the game"));

	Router.Register(TEXT("vget /action/game/is_paused"), [](const FSimCVArgs&)
	{
		UWorld* World = GetWorld();
		if (!World)
		{
			return FSimCVReply::Error(TEXT("No valid world"));
		}
		return FSimCVReply::Ok(World->IsPaused() ? TEXT("true") : TEXT("false"));
	}, TEXT("true/false"));

	Router.Register(TEXT("vset /action/game/level [str]"), [](const FSimCVArgs& Args)
	{
		UWorld* World = GetWorld();
		if (!World)
		{
			return FSimCVReply::Error(TEXT("No valid world"));
		}
		UGameplayStatics::OpenLevel(World, FName(*Args[0]));
		return FSimCVReply::Ok();
	}, TEXT("Open a level by name or path"));

	Router.Register(TEXT("vset /action/set_fixed_frame_rate [float]"), [](const FSimCVArgs& Args)
	{
		if (!GEngine)
		{
			return FSimCVReply::Error(TEXT("No engine"));
		}
		const float Fps = FCString::Atof(*Args[0]);
		GEngine->bUseFixedFrameRate = Fps > 0.f;
		GEngine->FixedFrameRate = Fps > 0.f ? Fps : GEngine->FixedFrameRate;
		return FSimCVReply::Ok();
	}, TEXT("Fixed frame rate (engine waits, delta = 1/fps); 0 disables"));

	// Spelling matches the SimWorld client.
	Router.Register(TEXT("vset /action/tick_intervel [float]"), [](const FSimCVArgs& Args)
	{
		const double Interval = FCString::Atod(*Args[0]);
		FApp::SetUseFixedTimeStep(Interval > 0.0);
		if (Interval > 0.0)
		{
			FApp::SetFixedDeltaTime(Interval);
		}
		return FSimCVReply::Ok();
	}, TEXT("Simulated seconds per world tick (fixed timestep, no real-time wait); 0 restores real time"));

	Router.Register(TEXT("vset /action/tick"), [](const FSimCVArgs&) { return TickOnce(); },
		TEXT("Advance exactly one world tick, then reply"));

	Router.Register(TEXT("vset /action/clean_garbage"), [](const FSimCVArgs&)
	{
		if (GEngine)
		{
			GEngine->ForceGarbageCollection(true);
		}
		return FSimCVReply::Ok();
	}, TEXT("Full garbage collection at the next opportunity"));

	Router.Register(TEXT("vrun [rest]"), [](const FSimCVArgs& Args)
	{
		const FString& Command = Args[0];
		if (Command.IsEmpty())
		{
			return FSimCVReply::Error(TEXT("This command requires at least one argument"));
		}
		UWorld* World = GetWorld();
		if (APlayerController* PC = GetPlayerController(World))
		{
			PC->ConsoleCommand(Command, true);
		}
		else if (GEngine)
		{
			GEngine->Exec(World, *Command);
		}
		return FSimCVReply::Ok();
	}, TEXT("Run a console command"));
}
