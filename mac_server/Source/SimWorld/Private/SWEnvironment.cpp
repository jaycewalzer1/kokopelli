#include "SWEnvironment.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/ExponentialHeightFogComponent.h"
#include "Components/SkyAtmosphereComponent.h"
#include "Components/SkyLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/DirectionalLight.h"
#include "Engine/ExponentialHeightFog.h"
#include "Engine/PostProcessVolume.h"
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
		// Late-afternoon sun FROM the southwest (world.json: x east, y south == UE +X, +Y). The light points
		// toward the northeast, i.e. direction (+X, -Y): yaw -45. Pitch -18 = sun 18 deg above the horizon.
		const FTransform Transform(FRotator(-18.0, -45.0, 0.0), FVector(0.0, 0.0, 1000.0));
		Env.Sun = SpawnDeferred<ADirectionalLight>(World, TEXT("SWSun"), Transform);
		if (UDirectionalLightComponent* Light = Cast<UDirectionalLightComponent>(Env.Sun->GetLightComponent()))
		{
			Light->SetMobility(EComponentMobility::Movable); // no baked lighting in this project
			Light->SetIntensity(14.f);                       // lux
			Light->SetAtmosphereSunLight(true);
			// Golden key. The sun colour also tints the whole sky, which greys it; SkyLuminanceFactor
			// below puts the blue back.
			Light->SetLightColor(FLinearColor(1.0f, 0.84f, 0.65f));
			Light->SetLightSourceAngle(1.2f);                 // slightly soft shadow edges
			Light->SetVolumetricScatteringIntensity(0.f);
		}
		Env.Sun->FinishSpawning(Transform);
		// FinishSpawning composes the transform with the light component's default relative rotation
		// (pitch about -46), so the sun ended up ~46 deg steeper than asked. Set it explicitly.
		Env.Sun->SetActorRotation(Transform.Rotator());
	}

	Env.Atmosphere = FindFirst<ASkyAtmosphere>(World);
	if (!Env.Atmosphere)
	{
		const FTransform Transform(FVector::ZeroVector);
		Env.Atmosphere = SpawnDeferred<ASkyAtmosphere>(World, TEXT("SWSkyAtmosphere"), Transform);
		if (USkyAtmosphereComponent* Sky = Env.Atmosphere->GetComponent())
		{
			// A touch more Mie haze than Earth default: golden glow around the low sun, soft distance.
			Sky->SetMieScatteringScale(0.005f);
			Sky->SetSkyLuminanceFactor(FLinearColor(0.75f, 1.0f, 1.5f));  // Ghibli cerulean despite the warm sun
			Sky->SetMieAnisotropy(0.8f);
			Sky->SetAerialPespectiveViewDistanceScale(1.5f);
		}
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
			Light->SetIntensity(0.9f);
			Light->bLowerHemisphereIsBlack = false;          // ground bounce instead of black undersides
			Light->SetLowerHemisphereColor(FLinearColor(0.10f, 0.11f, 0.06f));
		}
		Env.SkyLight->FinishSpawning(Transform);
	}

	Env.Fog = FindFirst<AExponentialHeightFog>(World);
	if (!Env.Fog)
	{
		const FTransform Transform(FVector::ZeroVector);
		Env.Fog = SpawnDeferred<AExponentialHeightFog>(World, TEXT("SWFog"), Transform);
		if (UExponentialHeightFogComponent* Fog = Env.Fog->GetComponent())
		{
			// Thin warm valley haze that only reads past ~50 m: depth without greying the near city.
			Fog->SetFogDensity(0.005f);
			Fog->SetFogHeightFalloff(0.12f);
			Fog->SetStartDistance(4000.f);
			Fog->SetFogMaxOpacity(0.85f);
			Fog->SetFogInscatteringColor(FLinearColor(0.16f, 0.22f, 0.32f));
			Fog->SetDirectionalInscatteringColor(FLinearColor(0.60f, 0.42f, 0.22f));
			Fog->SetDirectionalInscatteringExponent(6.f);
			Fog->SetVolumetricFog(false);
		}
		Env.Fog->FinishSpawning(Transform);
	}

	// Unbound post-process "look": gentle bloom, slight warmth and saturation, soft vignette.
	// Exposure stays with the SimCV camera (LitExposureEV100 in DefaultGame.ini overrides it per capture).
	if (!FindFirst<APostProcessVolume>(World))
	{
		const FTransform Transform(FVector::ZeroVector);
		APostProcessVolume* PP = SpawnDeferred<APostProcessVolume>(World, TEXT("SWLook"), Transform);
		PP->bUnbound = true;
		PP->Priority = -1.f;                                  // any map-authored volume wins
		FPostProcessSettings& S = PP->Settings;
		S.bOverride_BloomIntensity = true;            S.BloomIntensity = 0.45f;
		S.bOverride_BloomThreshold = true;            S.BloomThreshold = 1.0f;
		S.bOverride_ColorSaturation = true;           S.ColorSaturation = FVector4(1.1f, 1.1f, 1.1f, 1.f);
		S.bOverride_ColorContrast = true;             S.ColorContrast = FVector4(1.0f, 1.0f, 1.0f, 0.97f);
		S.bOverride_ColorGain = true;                 S.ColorGain = FVector4(1.06f, 1.0f, 0.89f, 1.f);         // golden hour warmth
		S.bOverride_ColorGainShadows = true;          S.ColorGainShadows = FVector4(0.95f, 1.0f, 1.08f, 1.f); // cool shadows
		S.bOverride_ColorGainHighlights = true;       S.ColorGainHighlights = FVector4(1.07f, 1.0f, 0.88f, 1.f); // warm highlights
		S.bOverride_VignetteIntensity = true;         S.VignetteIntensity = 0.3f;
		S.bOverride_LumenSkylightLeaking = true;      S.LumenSkylightLeaking = 0.03f; // softer, airier shadows
		S.bOverride_SceneFringeIntensity = true;      S.SceneFringeIntensity = 0.f;
		PP->FinishSpawning(Transform);
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
