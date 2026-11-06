#include "SimCVWorld.h"

#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "SimCVCameraActor.h"
#include "SimCVCameraComponent.h"
#include "SimCVLog.h"
#include "SimCVSettings.h"
#include "UObject/UObjectIterator.h"

namespace
{
TMap<FString, FString> GRedirects; // FString keys compare case-insensitively
TMap<TWeakObjectPtr<AActor>, FColor> GAnnotationColors;
TArray<TWeakObjectPtr<USimCVCameraComponent>> GCameras;

uint64 GUnpausedTicks = 0;
bool bGPauseAfterTick = false;
FDelegateHandle GPostActorTickHandle;

void OnWorldPostActorTick(UWorld* World, ELevelTick, float)
{
	if (World != SimCV::GetWorld() || World->IsPaused())
	{
		return;
	}
	++GUnpausedTicks;
	if (bGPauseAfterTick)
	{
		// Re-pause inside this same tick so exactly one simulation step runs, regardless of
		// whether the core ticker (where commands run) fires before or after the world tick.
		bGPauseAfterTick = false;
		UGameplayStatics::SetGamePaused(World, true);
	}
}
}

UWorld* SimCV::GetWorld()
{
	if (!GEngine)
	{
		return nullptr;
	}
	UWorld* Fallback = nullptr;
	for (const FWorldContext& Context : GEngine->GetWorldContexts())
	{
		UWorld* World = Context.World();
		if (!World)
		{
			continue;
		}
		if (Context.WorldType == EWorldType::Game || Context.WorldType == EWorldType::PIE)
		{
			return World;
		}
		if (Context.WorldType == EWorldType::Editor)
		{
			Fallback = World;
		}
	}
	return Fallback;
}

APlayerController* SimCV::GetPlayerController(UWorld* World)
{
	return World ? World->GetFirstPlayerController() : nullptr;
}

AActor* SimCV::FindActor(UWorld* World, const FString& Name)
{
	if (!World || Name.IsEmpty())
	{
		return nullptr;
	}

	// SimWorld polls hundreds of actors per step; a name cache keeps that O(1) per lookup.
	static TWeakObjectPtr<UWorld> CachedWorld;
	static TMap<FName, TWeakObjectPtr<AActor>> Cache;

	const FName Key(*Name, FNAME_Find);
	if (Key != NAME_None)
	{
		if (CachedWorld.Get() == World)
		{
			if (const TWeakObjectPtr<AActor>* Hit = Cache.Find(Key))
			{
				AActor* Actor = Hit->Get();
				if (IsValid(Actor) && Actor->GetFName() == Key && Actor->GetWorld() == World)
				{
					return Actor;
				}
			}
		}

		Cache.Reset();
		CachedWorld = World;
		AActor* Found = nullptr;
		for (TActorIterator<AActor> It(World); It; ++It)
		{
			Cache.Add(It->GetFName(), *It);
			if (It->GetFName() == Key)
			{
				Found = *It;
			}
		}
		if (Found)
		{
			return Found;
		}
	}

#if WITH_EDITOR
	for (TActorIterator<AActor> It(World); It; ++It)
	{
		if (It->GetActorLabel() == Name)
		{
			return *It;
		}
	}
#endif
	return nullptr;
}

UObject* SimCV::FindObject(UWorld* World, const FString& Name)
{
	if (AActor* Actor = FindActor(World, Name))
	{
		return Actor;
	}
	const FName Key(*Name, FNAME_Find);
	if (!World || Key == NAME_None)
	{
		return nullptr;
	}
	for (TObjectIterator<UObject> It; It; ++It)
	{
		if (It->GetFName() == Key && !It->HasAnyFlags(RF_ClassDefaultObject) && IsValid(*It) && It->GetWorld() == World)
		{
			return *It;
		}
	}
	return nullptr;
}

void SimCV::FreeStaleName(UWorld* World, const FString& Name)
{
	if (!World || !World->PersistentLevel)
	{
		return;
	}
	UObject* Existing = StaticFindObjectFast(nullptr, World->PersistentLevel, FName(*Name));
	if (Existing && !IsValid(Existing))
	{
		const FName Parking = MakeUniqueObjectName(World->PersistentLevel, Existing->GetClass(), FName(*(Name + TEXT("_destroyed"))));
		Existing->Rename(*Parking.ToString(), nullptr, REN_DontCreateRedirectors | REN_NonTransactional | REN_DoNotDirty);
	}
}

bool SimCV::ParseBool(const FString& Text, bool& bOut)
{
	if (Text == TEXT("1") || Text == TEXT("true") || Text == TEXT("yes") || Text == TEXT("on"))
	{
		bOut = true;
		return true;
	}
	if (Text == TEXT("0") || Text == TEXT("false") || Text == TEXT("no") || Text == TEXT("off"))
	{
		bOut = false;
		return true;
	}
	return false; // FString == is case-insensitive, so python's "True"/"False" are covered
}

FVector SimCV::VectorFromArgs(const TArray<FString>& Args, int32 First)
{
	return FVector(FCString::Atod(*Args[First]), FCString::Atod(*Args[First + 1]), FCString::Atod(*Args[First + 2]));
}

FString SimCV::FormatVector(const FVector& Value)
{
	return FString::Printf(TEXT("%.3f %.3f %.3f"), Value.X, Value.Y, Value.Z);
}

FString SimCV::FormatRotator(const FRotator& Value)
{
	return FString::Printf(TEXT("%.3f %.3f %.3f"), Value.Pitch, Value.Yaw, Value.Roll);
}

void SimCV::LoadRedirects()
{
	GRedirects.Reset();

	FString Path;
	if (!FParse::Value(FCommandLine::Get(), TEXT("cvredirects="), Path))
	{
		Path = FPaths::Combine(FPaths::ProjectConfigDir(), GetDefault<USimCVSettings>()->RedirectsFile);
	}

	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		UE_LOG(LogSimCV, Log, TEXT("No class redirect file at %s"), *Path);
		return;
	}

	TSharedPtr<FJsonObject> Root;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	const TSharedPtr<FJsonObject>* Map = nullptr;
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid() || !Root->TryGetObjectField(TEXT("redirects"), Map))
	{
		UE_LOG(LogSimCV, Error, TEXT("%s: expected {\"redirects\": {\"/Game/..._C\": \"/Script/Module.Class\"}}"), *Path);
		return;
	}

	for (const auto& Pair : (*Map)->Values)
	{
		FString Target;
		if (Pair.Value.IsValid() && Pair.Value->TryGetString(Target) && !Target.IsEmpty())
		{
			GRedirects.Add(FString(*Pair.Key), Target); // 5.8 JSON keys are TSharedString
		}
	}
	UE_LOG(LogSimCV, Display, TEXT("Loaded %d class redirects from %s"), GRedirects.Num(), *Path);
}

UClass* SimCV::ResolveActorClass(const FString& PathOrName, FString& OutError)
{
	const FString* Redirect = GRedirects.Find(PathOrName);
	const FString Target = Redirect ? *Redirect : PathOrName;

	UClass* Class = nullptr;
	if (Target.Contains(TEXT("/")))
	{
		Class = LoadClass<AActor>(nullptr, *Target);
		if (!Class && !Target.Contains(TEXT(".")))
		{
			// "/Game/Dir/BP_Foo" -> "/Game/Dir/BP_Foo.BP_Foo_C"
			Class = LoadClass<AActor>(nullptr, *FString::Printf(TEXT("%s.%s_C"), *Target, *FPackageName::GetShortName(Target)));
		}
	}
	else
	{
		Class = FindFirstObject<UClass>(*Target, EFindFirstObjectOptions::NativeFirst);
	}

	if (!Class || !Class->IsChildOf(AActor::StaticClass()) || Class->HasAnyClassFlags(CLASS_Abstract))
	{
		OutError = Redirect
			? FString::Printf(TEXT("Can not find a class with name '%s' (redirected to '%s')"), *PathOrName, *Target)
			: FString::Printf(TEXT("Can not find a class with name '%s' (add it to SimCVRedirects.json)"), *PathOrName);
		return nullptr;
	}
	return Class;
}

FColor SimCV::GetAnnotationColor(AActor* Actor)
{
	if (const FColor* Existing = GAnnotationColors.Find(Actor))
	{
		return *Existing;
	}
	if (GAnnotationColors.Num() > 8192)
	{
		for (auto It = GAnnotationColors.CreateIterator(); It; ++It)
		{
			if (!It->Key.IsValid())
			{
				It.RemoveCurrent();
			}
		}
	}
	// Stable per name across runs, never black (black = background in the mask).
	const uint32 Hash = FCrc::StrCrc32(*Actor->GetName()) * 2654435761u;
	FColor Color((Hash >> 16) & 0xFF, (Hash >> 8) & 0xFF, Hash & 0xFF, 255);
	if (Color.R + Color.G + Color.B < 48)
	{
		Color.R = 255;
	}
	GAnnotationColors.Add(Actor, Color);
	return Color;
}

void SimCV::SetAnnotationColor(AActor* Actor, const FColor& Color)
{
	GAnnotationColors.Add(Actor, Color);
}

uint64 SimCV::GetUnpausedTickCount()
{
	return GUnpausedTicks;
}

void SimCV::RequestPauseAfterNextTick()
{
	bGPauseAfterTick = true;
}

void SimCV::InitStepping()
{
	GPostActorTickHandle = FWorldDelegates::OnWorldPostActorTick.AddStatic(&OnWorldPostActorTick);
}

void SimCV::ShutdownStepping()
{
	FWorldDelegates::OnWorldPostActorTick.Remove(GPostActorTickHandle);
}

void SimCV::RegisterCamera(USimCVCameraComponent* Camera)
{
	GCameras.AddUnique(Camera);
}

void SimCV::UnregisterCamera(USimCVCameraComponent* Camera)
{
	GCameras.Remove(Camera);
}

TArray<USimCVCameraComponent*> SimCV::GetCameras(UWorld* World)
{
	GCameras.RemoveAll([](const TWeakObjectPtr<USimCVCameraComponent>& Camera) { return !Camera.IsValid(); });

	auto Collect = [World]()
	{
		TArray<USimCVCameraComponent*> Followers;
		TArray<USimCVCameraComponent*> Others;
		for (const TWeakObjectPtr<USimCVCameraComponent>& Weak : GCameras)
		{
			USimCVCameraComponent* Camera = Weak.Get();
			if (Camera->GetWorld() == World)
			{
				(Camera->bFollowPlayerView ? Followers : Others).Add(Camera);
			}
		}
		Followers.Append(Others);
		return Followers;
	};

	TArray<USimCVCameraComponent*> Cameras = Collect();
	const bool bHasPlayerCamera = Cameras.Num() > 0 && Cameras[0]->bFollowPlayerView;
	if (!bHasPlayerCamera && World && World->IsGameWorld())
	{
		FActorSpawnParameters Params;
		Params.Name = TEXT("SimCVPlayerCamera");
		Params.NameMode = FActorSpawnParameters::ESpawnActorNameMode::Requested;
		if (ASimCVCameraActor* Actor = World->SpawnActor<ASimCVCameraActor>(Params))
		{
			const USimCVSettings* Settings = GetDefault<USimCVSettings>();
			Actor->Camera->bFollowPlayerView = true;
			Actor->Camera->FOVAngle = Settings->DefaultFOV;
			Actor->Camera->SetFilmSize(Settings->DefaultWidth, Settings->DefaultHeight);
			Cameras = Collect();
		}
	}
	return Cameras;
}
