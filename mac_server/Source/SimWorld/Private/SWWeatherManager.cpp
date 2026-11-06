#include "SWWeatherManager.h"

#include "Components/ExponentialHeightFogComponent.h"
#include "Components/LightComponent.h"
#include "Components/SceneComponent.h"
#include "Components/SkyAtmosphereComponent.h"
#include "Engine/DirectionalLight.h"
#include "Engine/ExponentialHeightFog.h"
#include "SWCommon.h"
#include "SWEnvironment.h"

ASWWeatherManager::ASWWeatherManager()
{
	PrimaryActorTick.bCanEverTick = false;
	RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	SetHidden(true); // logic-only actor
}

void ASWWeatherManager::BeginPlay()
{
	Super::BeginPlay();
	const SW::FEnvironment Env = SW::FindOrSpawnEnvironment(GetWorld());
	Sun = Env.Sun;
	Atmosphere = Env.Atmosphere;
	Fog = Env.Fog;

	// Start from what the level shows, so a Get before any Set is truthful.
	if (Env.Sun)
	{
		const FRotator Rotation = Env.Sun->GetActorRotation();
		SunPitch = static_cast<float>(Rotation.Pitch);
		SunYaw = static_cast<float>(FRotator::ClampAxis(Rotation.Yaw));
		if (const ULightComponent* Light = Env.Sun->GetLightComponent())
		{
			SunLux = Light->Intensity;
		}
	}
	if (const UExponentialHeightFogComponent* FogComponent = Env.Fog ? Env.Fog->GetComponent() : nullptr)
	{
		FogDensityValue = FogComponent->FogDensity * FogDensityScale;
		FogDistanceValue = FogComponent->StartDistance;
		FogFalloffValue = FogComponent->FogHeightFalloff;
	}
	if (const USkyAtmosphereComponent* Sky = Env.Atmosphere ? Env.Atmosphere->GetComponent() : nullptr)
	{
		RayleighValue = Sky->RayleighScatteringScale;
		MieValue = Sky->MieScatteringScale;
	}
	const float State[8] = {SunPitch, SunYaw, SunLux, FogDensityValue, FogDistanceValue, FogFalloffValue, RayleighValue, MieValue};
	FMemory::Memcpy(InitialState, State, sizeof(State));
}

void ASWWeatherManager::EndPlay(const EEndPlayReason::Type Reason)
{
	if (Reason == EEndPlayReason::Destroyed)
	{
		const float* S = InitialState;
		SetSunDirection(S[0], S[1]);
		SetSunIntensity(S[2]);
		SetFog(S[3], S[4], S[5]);
		SetAtmosphere(S[6], S[7]);
	}
	Super::EndPlay(Reason);
}

void ASWWeatherManager::SetSunDirection(float Pitch, float Yaw)
{
	SunPitch = FMath::Clamp(Pitch, -89.f, 89.f);
	SunYaw = static_cast<float>(FRotator::ClampAxis(Yaw)); // [0, 360)
	if (ADirectionalLight* Light = Sun.Get())
	{
		SW::EnsureMovable(Light);
		Light->SetActorRotation(FRotator(SunPitch, SunYaw, 0.f));
	}
}

FString ASWWeatherManager::FormatSunRotation() const
{
	// FRotator::ToString style; %f never uses an exponent (client regex P=([-\d.]+)).
	return FString::Printf(TEXT("P=%f Y=%f R=%f"), SunPitch, SunYaw, 0.f);
}

void ASWWeatherManager::GetSunDirection(FString& rotation) const
{
	rotation = FormatSunRotation();
}

void ASWWeatherManager::SetSunIntensity(float Intensity)
{
	SunLux = FMath::Max(0.f, Intensity);
	if (ADirectionalLight* Light = Sun.Get())
	{
		if (ULightComponent* Component = Light->GetLightComponent())
		{
			Component->SetIntensity(SunLux);
		}
	}
}

void ASWWeatherManager::GetSunIntensity(float& SunIntensity) const
{
	SunIntensity = SunLux;
}

void ASWWeatherManager::SetFog(float Density, float Distance, float Falloff)
{
	FogDensityValue = FMath::Max(0.f, Density);
	FogDistanceValue = FMath::Max(0.f, Distance);
	FogFalloffValue = FMath::Max(0.f, Falloff);
	if (UExponentialHeightFogComponent* Component = Fog.IsValid() ? Fog->GetComponent() : nullptr)
	{
		Component->SetFogDensity(FogDensityValue / FogDensityScale);
		Component->SetStartDistance(FogDistanceValue);
		Component->SetFogHeightFalloff(FogFalloffValue);
	}
}

void ASWWeatherManager::GetFog(float& FogDensity, float& FogDistance, float& FogFalloff) const
{
	FogDensity = FogDensityValue;
	FogDistance = FogDistanceValue;
	FogFalloff = FogFalloffValue;
}

void ASWWeatherManager::SetAtmosphere(float Rayleigh, float Mie)
{
	RayleighValue = FMath::Max(0.f, Rayleigh);
	MieValue = FMath::Max(0.f, Mie);
	if (USkyAtmosphereComponent* Sky = Atmosphere.IsValid() ? Atmosphere->GetComponent() : nullptr)
	{
		Sky->SetRayleighScatteringScale(RayleighValue);
		Sky->SetMieScatteringScale(MieValue);
	}
}

void ASWWeatherManager::GetAtmosphere(float& RayleighScatteringScale, float& MieScatteringScale) const
{
	RayleighScatteringScale = RayleighValue;
	MieScatteringScale = MieValue;
}

FString ASWWeatherManager::GetSunDirectionJson() const
{
	return SW::JsonObjectString({{TEXT("rotation"), FormatSunRotation()}});
}

FString ASWWeatherManager::GetSunIntensityJson() const
{
	return SW::JsonObjectString({{TEXT("SunIntensity"), SW::FloatString(SunLux)}});
}

FString ASWWeatherManager::GetFogJson() const
{
	return SW::JsonObjectString({
		{TEXT("FogDensity"), SW::FloatString(FogDensityValue)},
		{TEXT("FogDistance"), SW::FloatString(FogDistanceValue)},
		{TEXT("FogFalloff"), SW::FloatString(FogFalloffValue)},
	});
}

FString ASWWeatherManager::GetAtmosphereJson() const
{
	return SW::JsonObjectString({
		{TEXT("Rayleigh Scattering Scale"), SW::FloatString(RayleighValue)},
		{TEXT("Mie Scattering Scale"), SW::FloatString(MieValue)},
	});
}
