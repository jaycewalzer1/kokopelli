#include "SimCVCommands.h"

#include "Components/PrimitiveComponent.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Actor.h"
#include "SimCVCommandRouter.h"
#include "SimCVWorld.h"
#include "UObject/UObjectGlobals.h"

namespace
{
using namespace SimCV;

FSimCVReply CannotFind()
{
	return FSimCVReply::Error(TEXT("Cannot find object"));
}

bool IsValidActorName(const FString& Name)
{
	return !Name.IsEmpty() && FName::IsValidXName(Name, INVALID_OBJECTNAME_CHARACTERS);
}

/** Shared by spawn and spawn_bp_asset. Replies with the new actor's name, like UnrealCV. */
FSimCVReply SpawnActor(const FString& ClassPath, const FString& Name, const FVector* Location)
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return FSimCVReply::Error(TEXT("Cannot get world"));
	}
	if (!Name.IsEmpty())
	{
		if (FindActor(World, Name))
		{
			return FSimCVReply::Error(FString::Printf(TEXT("Failed to spawn %s, object exists."), *Name));
		}
		if (!IsValidActorName(Name))
		{
			return FSimCVReply::Error(FString::Printf(TEXT("Invalid object name '%s'"), *Name));
		}
	}

	FString ClassError;
	UClass* Class = ResolveActorClass(ClassPath, ClassError);
	if (!Class)
	{
		return FSimCVReply::Error(ClassError);
	}

	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	if (!Name.IsEmpty())
	{
		// SimWorld destroys and respawns under the same name; free it from the not-yet-GC'd actor.
		FreeStaleName(World, Name);
		Params.Name = FName(*Name);
		Params.NameMode = FActorSpawnParameters::ESpawnActorNameMode::Requested;
	}
	AActor* Actor = World->SpawnActor<AActor>(Class, Location ? *Location : FVector::ZeroVector, FRotator::ZeroRotator, Params);
	if (!Actor)
	{
		return FSimCVReply::Error(TEXT("Failed to spawn actor"));
	}
	return FSimCVReply::Ok(Actor->GetName());
}

/** "spawn <class> [name] [x y z]" in any of UnrealCV's four argument layouts. */
void RegisterSpawn(FSimCVCommandRouter& Router, const FString& Verb)
{
	Router.Register(Verb + TEXT(" [str]"), [](const FSimCVArgs& A) { return SpawnActor(A[0], FString(), nullptr); });
	Router.Register(Verb + TEXT(" [str] [str]"), [](const FSimCVArgs& A) { return SpawnActor(A[0], A[1], nullptr); });
	Router.Register(Verb + TEXT(" [str] [float] [float] [float]"), [](const FSimCVArgs& A)
	{
		const FVector Location = VectorFromArgs(A, 1);
		return SpawnActor(A[0], FString(), &Location);
	});
	Router.Register(Verb + TEXT(" [str] [str] [float] [float] [float]"), [](const FSimCVArgs& A)
	{
		const FVector Location = VectorFromArgs(A, 2);
		return SpawnActor(A[0], A[1], &Location);
	}, TEXT("Spawn an actor: class name or /Game/... path (see Config/SimCVRedirects.json), optional name and location"));
}

/** Registers "<verb> /object/[str]/<suffix>" with the actor already resolved. */
void RegisterActorCommand(FSimCVCommandRouter& Router, const FString& Template, TFunction<FSimCVReply(AActor*, const FSimCVArgs&)> Body, const FString& Help)
{
	Router.Register(Template, [Body = MoveTemp(Body)](const FSimCVArgs& Args)
	{
		AActor* Actor = FindActor(GetWorld(), Args[0]);
		return Actor ? Body(Actor, Args) : CannotFind();
	}, Help);
}

FSimCVReply ParseBoolArg(const FString& Text, bool& bOut)
{
	return ParseBool(Text, bOut) ? FSimCVReply::Ok() : FSimCVReply::Error(FString::Printf(TEXT("Expected a boolean, got '%s'"), *Text));
}
}

void SimCV::RegisterObjectCommands(FSimCVCommandRouter& Router)
{
	Router.Register(TEXT("vget /objects"), [](const FSimCVArgs&)
	{
		UWorld* World = GetWorld();
		if (!World)
		{
			return FSimCVReply::Error(TEXT("Cannot get world"));
		}
		FString List;
		for (TActorIterator<AActor> It(World); It; ++It)
		{
			List += It->GetName() + TEXT(" "); // trailing space, as UnrealCV
		}
		return FSimCVReply::Ok(List);
	}, TEXT("Names of all actors"));

	RegisterSpawn(Router, TEXT("vset /objects/spawn"));
	RegisterSpawn(Router, TEXT("vset /objects/spawn_bp_asset"));

	RegisterActorCommand(Router, TEXT("vget /object/[str]/location"), [](AActor* Actor, const FSimCVArgs&)
	{
		return FSimCVReply::Ok(FormatVector(Actor->GetActorLocation()));
	}, TEXT("Location in cm: x y z"));

	RegisterActorCommand(Router, TEXT("vset /object/[str]/location [float] [float] [float]"), [](AActor* Actor, const FSimCVArgs& Args)
	{
		Actor->SetActorLocation(VectorFromArgs(Args, 1), false, nullptr, ETeleportType::TeleportPhysics);
		return FSimCVReply::Ok();
	}, TEXT("Teleport to x y z (cm)"));

	RegisterActorCommand(Router, TEXT("vget /object/[str]/rotation"), [](AActor* Actor, const FSimCVArgs&)
	{
		return FSimCVReply::Ok(FormatRotator(Actor->GetActorRotation()));
	}, TEXT("Rotation in degrees: pitch yaw roll"));

	RegisterActorCommand(Router, TEXT("vset /object/[str]/rotation [float] [float] [float]"), [](AActor* Actor, const FSimCVArgs& Args)
	{
		const FVector PYR = VectorFromArgs(Args, 1);
		Actor->SetActorRotation(FRotator(PYR.X, PYR.Y, PYR.Z), ETeleportType::TeleportPhysics);
		return FSimCVReply::Ok();
	}, TEXT("Set rotation: pitch yaw roll (degrees)"));

	RegisterActorCommand(Router, TEXT("vget /object/[str]/scale"), [](AActor* Actor, const FSimCVArgs&)
	{
		return FSimCVReply::Ok(FormatVector(Actor->GetActorScale3D()));
	}, TEXT("Scale: x y z"));

	RegisterActorCommand(Router, TEXT("vset /object/[str]/scale [float] [float] [float]"), [](AActor* Actor, const FSimCVArgs& Args)
	{
		Actor->SetActorScale3D(VectorFromArgs(Args, 1));
		return FSimCVReply::Ok();
	}, TEXT("Set scale: x y z"));

	RegisterActorCommand(Router, TEXT("vset /object/[str]/name [str]"), [](AActor* Actor, const FSimCVArgs& Args)
	{
		const FString& NewName = Args[1];
		if (Actor->GetName() == NewName)
		{
			return FSimCVReply::Ok(TEXT("The name has already been set"));
		}
		if (!IsValidActorName(NewName))
		{
			return FSimCVReply::Error(FString::Printf(TEXT("Invalid object name '%s'"), *NewName));
		}
		UWorld* World = Actor->GetWorld();
		FreeStaleName(World, NewName);
		if (FindActor(World, NewName) || StaticFindObjectFast(nullptr, Actor->GetOuter(), FName(*NewName)))
		{
			return FSimCVReply::Error(FString::Printf(TEXT("Renaming an object to overwrite an existing object is not allowed: %s"), *NewName));
		}
		Actor->Rename(*NewName);
		return FSimCVReply::Ok();
	}, TEXT("Rename the actor"));

	RegisterActorCommand(Router, TEXT("vset /object/[str]/destroy"), [](AActor* Actor, const FSimCVArgs&)
	{
		Actor->Destroy();
		return FSimCVReply::Ok();
	}, TEXT("Destroy the actor"));

	RegisterActorCommand(Router, TEXT("vset /object/[str]/physics [str]"), [](AActor* Actor, const FSimCVArgs& Args)
	{
		bool bEnable = false;
		FSimCVReply Parsed = ParseBoolArg(Args[1], bEnable);
		if (Parsed.IsError())
		{
			return Parsed;
		}
		// Root primitive if there is one (the usual physics body), otherwise every primitive.
		TArray<UPrimitiveComponent*> Targets;
		if (UPrimitiveComponent* Root = Cast<UPrimitiveComponent>(Actor->GetRootComponent()))
		{
			Targets.Add(Root);
		}
		else
		{
			Actor->GetComponents<UPrimitiveComponent>(Targets);
		}
		if (Targets.Num() == 0)
		{
			return FSimCVReply::Error(TEXT("Object has no primitive component"));
		}
		for (UPrimitiveComponent* Primitive : Targets)
		{
			if (bEnable)
			{
				Primitive->SetMobility(EComponentMobility::Movable);
			}
			Primitive->SetSimulatePhysics(bEnable);
		}
		return FSimCVReply::Ok();
	}, TEXT("Enable/disable physics simulation (true/false/1/0)"));

	RegisterActorCommand(Router, TEXT("vset /object/[str]/collision [str]"), [](AActor* Actor, const FSimCVArgs& Args)
	{
		bool bEnable = false;
		FSimCVReply Parsed = ParseBoolArg(Args[1], bEnable);
		if (!Parsed.IsError())
		{
			Actor->SetActorEnableCollision(bEnable);
		}
		return Parsed;
	}, TEXT("Enable/disable collision (true/false/1/0)"));

	RegisterActorCommand(Router, TEXT("vset /object/[str]/object_mobility [str]"), [](AActor* Actor, const FSimCVArgs& Args)
	{
		bool bMovable = false;
		FSimCVReply Parsed = ParseBoolArg(Args[1], bMovable);
		if (Parsed.IsError())
		{
			return Parsed;
		}
		USceneComponent* Root = Actor->GetRootComponent();
		if (!Root)
		{
			return FSimCVReply::Error(TEXT("Object has no root component"));
		}
		Root->SetMobility(bMovable ? EComponentMobility::Movable : EComponentMobility::Static);
		return FSimCVReply::Ok();
	}, TEXT("true = Movable, false = Static"));

	RegisterActorCommand(Router, TEXT("vget /object/[str]/mobility"), [](AActor* Actor, const FSimCVArgs&)
	{
		const USceneComponent* Root = Actor->GetRootComponent();
		if (!Root)
		{
			return FSimCVReply::Ok(TEXT("Unknown"));
		}
		switch (Root->Mobility)
		{
		case EComponentMobility::Movable: return FSimCVReply::Ok(TEXT("Movable"));
		case EComponentMobility::Static: return FSimCVReply::Ok(TEXT("Static"));
		case EComponentMobility::Stationary: return FSimCVReply::Ok(TEXT("Stationary"));
		default: return FSimCVReply::Ok(TEXT("Unknown"));
		}
	}, TEXT("Static, Stationary or Movable"));

	RegisterActorCommand(Router, TEXT("vget /object/[str]/color"), [](AActor* Actor, const FSimCVArgs&)
	{
		return FSimCVReply::Ok(GetAnnotationColor(Actor).ToString()); // "(R=..,G=..,B=..,A=..)"
	}, TEXT("Object mask colour"));

	RegisterActorCommand(Router, TEXT("vset /object/[str]/color [uint] [uint] [uint]"), [](AActor* Actor, const FSimCVArgs& Args)
	{
		const uint8 R = static_cast<uint8>(FMath::Clamp(FCString::Atoi(*Args[1]), 0, 255));
		const uint8 G = static_cast<uint8>(FMath::Clamp(FCString::Atoi(*Args[2]), 0, 255));
		const uint8 B = static_cast<uint8>(FMath::Clamp(FCString::Atoi(*Args[3]), 0, 255));
		SetAnnotationColor(Actor, FColor(R, G, B, 255));
		return FSimCVReply::Ok();
	}, TEXT("Set object mask colour r g b"));

	RegisterActorCommand(Router, TEXT("vset /object/[str]/show"), [](AActor* Actor, const FSimCVArgs&)
	{
		Actor->SetActorHiddenInGame(false);
		return FSimCVReply::Ok();
	}, TEXT("Show the actor"));

	RegisterActorCommand(Router, TEXT("vset /object/[str]/hide"), [](AActor* Actor, const FSimCVArgs&)
	{
		Actor->SetActorHiddenInGame(true);
		return FSimCVReply::Ok();
	}, TEXT("Hide the actor"));

	RegisterActorCommand(Router, TEXT("vget /object/[str]/uclass_name"), [](AActor* Actor, const FSimCVArgs&)
	{
		return FSimCVReply::Ok(Actor->GetClass()->GetName());
	}, TEXT("Class name"));

	RegisterActorCommand(Router, TEXT("vget /object/[str]/bounds"), [](AActor* Actor, const FSimCVArgs&)
	{
		FVector Origin, Extent;
		Actor->GetActorBounds(false, Origin, Extent);
		const FVector Min = Origin - Extent;
		const FVector Max = Origin + Extent;
		return FSimCVReply::Ok(FString::Printf(TEXT("%.2f %.2f %.2f %.2f %.2f %.2f"), Min.X, Min.Y, Min.Z, Max.X, Max.Y, Max.Z));
	}, TEXT("World bounds: minx miny minz maxx maxy maxz"));
}
