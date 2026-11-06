#include "SWEnvironment.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/ExponentialHeightFogComponent.h"
#include "Components/SkyAtmosphereComponent.h"
#include "Components/SkyLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/DirectionalLight.h"
#include "Engine/ExponentialHeightFog.h"
#include "Engine/SkyLight.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "SWCommon.h"

namespace
{
template <typename T>
T* FindFirst(UWorld* World)
{
	TActorIterator<T> It(World);
	return It ? *It : nullptr;
}

/** Spawn with construction deferred: native components are registered, but BeginPlay waits for FinishSpawning. */
template <typename T>
T* SpawnDeferred(UWorld* World, const TCHAR* Name, const FTransform& Transform)
{
	FActorSpawnParameters Params;
	Params.Name = FName(Name);
	Params.NameMode = FActorSpawnParameters::ESpawnActorNameMode::Requested; // made unique if taken
	Params.bDeferConstruction = true;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	return World->SpawnActor<T>(T::StaticClass(), Transform, Params);
}
}

SW::FEnvironment SW::FindOrSpawnEnvironment(UWorld* World)
{
	FEnvironment Env;
	if (!World)
	{
		return Env;
	}

	Env.Sun = FindFirst<ADirectionalLight>(World);
	if (!Env.Sun)
	{
		const FTransform Transform(FRotator(-40.0, 30.0, 0.0), FVector(0.0, 0.0, 1000.0));
		Env.Sun = SpawnDeferred<ADirectionalLight>(World, TEXT("SWSun"), Transform);
		if (UDirectionalLightComponent* Light = Cast<UDirectionalLightComponent>(Env.Sun->GetLightComponent()))
		{
			Light->SetMobility(EComponentMobility::Movable); // no baked lighting in this project
			Light->SetIntensity(10.f);                       // lux
			Light->SetAtmosphereSunLight(true);
		}
		Env.Sun->FinishSpawning(Transform);
	}

	Env.Atmosphere = FindFirst<ASkyAtmosphere>(World);
	if (!Env.Atmosphere)
	{
		const FTransform Transform(FVector::ZeroVector);
		Env.Atmosphere = SpawnDeferred<ASkyAtmosphere>(World, TEXT("SWSkyAtmosphere"), Transform);
		Env.Atmosphere->FinishSpawning(Transform);
	}

	Env.SkyLight = FindFirst<ASkyLight>(World);
	if (!Env.SkyLight)
	{
		const FTransform Transform(FVector(0.0, 0.0, 500.0));
		Env.SkyLight = SpawnDeferred<ASkyLight>(World, TEXT("SWSkyLight"), Transform);
		if (USkyLightComponent* Light = Env.SkyLight->GetLightComponent())
		{
			// Real-time capture of the atmosphere, so ambient light follows the sun (and goes dark with it).
			Light->SetMobility(EComponentMobility::Movable);
			Light->SetRealTimeCapture(true);
		}
		Env.SkyLight->FinishSpawning(Transform);
	}

	Env.Fog = FindFirst<AExponentialHeightFog>(World);
	if (!Env.Fog)
	{
		const FTransform Transform(FVector::ZeroVector);
		Env.Fog = SpawnDeferred<AExponentialHeightFog>(World, TEXT("SWFog"), Transform);
		Env.Fog->FinishSpawning(Transform);
	}
	return Env;
}

void SW::EnsureFloor(UWorld* World)
{
	if (!World || FindActorByName(World, FloorName))
	{
		return;
	}
	// A 1 m thick slab (thick so characters falling from z=600 never tunnel), top face at z = 0.
	const FTransform Transform(FRotator::ZeroRotator, FVector(0.0, 0.0, -50.0), FVector(2.0 * FloorHalfSizeCm / 100.0, 2.0 * FloorHalfSizeCm / 100.0, 1.0));
	FActorSpawnParameters Params;
	Params.Name = FName(FloorName);
	Params.NameMode = FActorSpawnParameters::ESpawnActorNameMode::Requested;
	Params.bDeferConstruction = true;
	AStaticMeshActor* Floor = World->SpawnActor<AStaticMeshActor>(AStaticMeshActor::StaticClass(), Transform, Params);
	if (!Floor)
	{
		UE_LOG(LogSimWorld, Error, TEXT("Could not spawn the floor"));
		return;
	}
	UStaticMeshComponent* Mesh = Floor->GetStaticMeshComponent();
	// Movable: static meshes can't change their mesh once registered. Lumen handles movable fine.
	Mesh->SetMobility(EComponentMobility::Movable);
	Mesh->SetStaticMesh(GetShapeMesh(ESWShape::Box));
	Mesh->SetMaterial(0, MakeColorMaterial(Mesh, FLinearColor(0.12f, 0.13f, 0.1f)));
	Mesh->SetCollisionProfileName(TEXT("BlockAll"));
	Floor->FinishSpawning(Transform);
}
