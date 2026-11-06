#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SWWeatherManager.generated.h"

class ADirectionalLight;
class AExponentialHeightFog;
class ASkyAtmosphere;

/**
 * /Game/Weather/BP_WeatherManager, spawned as GEN_WeatherManager (SPEC 6.7). Drives the level's
 * sun, sky atmosphere and height fog, spawning any that are missing.
 *
 * Every Get returns exactly what the matching Set stored (round trip), in the client's units:
 *   sun direction  pitch/yaw degrees, yaw kept in [0, 360)
 *   sun intensity  directional light lux
 *   fog            density 0..100 (x 0.001 = UE FogDensity), start distance cm, height falloff
 *   atmosphere     UE Rayleigh / Mie scattering scales
 *
 * The client parses the getters' JSON by exact keys ("rotation", "Rayleigh Scattering Scale"),
 * which UFUNCTION parameter names cannot spell, so the Get*Json functions build the replies and
 * SimWorldModule.cpp routes "vbp <name> Get..." to them. The UFUNCTION getters stay for Blueprint
 * and for lower-case vbp calls.
 */
UCLASS()
class SIMWORLD_API ASWWeatherManager : public AActor
{
	GENERATED_BODY()

public:
	ASWWeatherManager();

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Weather")
	void SetSunDirection(float Pitch, float Yaw);

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Weather")
	void GetSunDirection(FString& rotation) const;

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Weather")
	void SetSunIntensity(float Intensity);

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Weather")
	void GetSunIntensity(float& SunIntensity) const;

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Weather")
	void SetFog(float Density, float Distance, float Falloff);

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Weather")
	void GetFog(float& FogDensity, float& FogDistance, float& FogFalloff) const;

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Weather")
	void SetAtmosphere(float Rayleigh, float Mie);

	UFUNCTION(BlueprintCallable, Category = "SimWorld|Weather")
	void GetAtmosphere(float& RayleighScatteringScale, float& MieScatteringScale) const;

	// Exact-key JSON replies (see class comment).
	FString GetSunDirectionJson() const;
	FString GetSunIntensityJson() const;
	FString GetFogJson() const;
	FString GetAtmosphereJson() const;

	/** Client fog density units per UE FogDensity unit (density 20 = UE 0.02, the engine default). */
	static constexpr float FogDensityScale = 1000.f;

protected:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

private:
	FString FormatSunRotation() const;

	TWeakObjectPtr<ADirectionalLight> Sun;
	TWeakObjectPtr<ASkyAtmosphere> Atmosphere;
	TWeakObjectPtr<AExponentialHeightFog> Fog;

	// Stored in client units; initialised from the level in BeginPlay.
	float SunPitch = -40.f;
	float SunYaw = 30.f;
	float SunLux = 10.f;
	float FogDensityValue = 20.f;
	float FogDistanceValue = 0.f;
	float FogFalloffValue = 0.2f;
	float RayleighValue = 0.0331f;
	float MieValue = 0.003996f;

	// The weather found at BeginPlay, put back on destroy: the sky outlives the manager.
	float InitialState[8] = {};
};
