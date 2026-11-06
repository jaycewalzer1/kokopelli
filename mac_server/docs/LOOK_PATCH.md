# Solarpunk look patch: lighting and mood

Apply to the main project (`~/Desktop/kokopelli/mac_server`) with
`patch -p1 < <this diff>` from the project root, or by hand. Two files: `Source/SimWorld/Private/SWEnvironment.cpp` and
`Config/DefaultGame.ini`. Rebuild with `scripts/build.sh editor`. The materials need no code. They are plain assets in
`Content/Solarpunk`.

## What it does

* **Sun:** late afternoon, 18 deg above the horizon, shining FROM the southwest. world.json uses x = east and y = south,
  which is UE +X and +Y. A sun in the southwest sits at (-X, +Y), so its light travels toward the northeast, (+X, -Y).
  That is yaw -45, and pitch -18 because negative pitch points down. The rotation is FRotator(-18, -45, 0). Light colour
  is golden (1, 0.84, 0.65), intensity is 14 lux and the source angle is 1.2 deg for soft edges.
* **Bug fix, which changes the old look too:** `FinishSpawning(Transform)` composes the spawn transform with the
  DirectionalLight component's default relative rotation, pitch about -46. The sun therefore always sat about 46 deg
  steeper than the code said. The old (-40, 30) was really about -86, almost straight overhead. I measured -64 for a
  requested -18 via `vget /object/SWSun/rotation`. The patch calls `SetActorRotation` after FinishSpawning.
* **Sky:** a little more Mie scattering (0.005), anisotropy 0.8 for the golden glow around the sun, and aerial
  perspective x1.5. `SkyLuminanceFactor` is (0.75, 1, 1.5): the warm sun colour also tints the whole atmosphere and
  turns it grey, and this restores a Ghibli cerulean.
* **Sky light:** real-time capture is kept, intensity 0.9, and the lower hemisphere is dark olive instead of black.
* **Height fog:** thin (density 0.005, falloff 0.12) and starts at 40 m. Blue-grey inscattering plus warm directional
  inscattering toward the sun. Volumetric fog is off.
* **Post-process:** a new unbound `APostProcessVolume` "SWLook" with priority -1, so a map volume wins. Bloom 0.45, saturation 1.1,
  global gain (1.06, 1, 0.89), cooler shadows, warmer highlights, vignette 0.3, Lumen skylight leaking 0.03.
  Verified: world PPVs DO reach SimCV lit captures (a magenta SceneColorTint test turned the capture magenta).
* **Exposure:** `LitExposureEV100` goes from -2.0 to -1.3. The camera keeps manual exposure, and +0.7 EV makes up for
  the real low sun putting less light on the ground than the old near-overhead one.

Weather API note: `ASWWeatherManager::SetSunDirection` uses SetActorRotation, so it was never affected by the spawn bug.
Clients that called it got the angle they asked for. Only the spawn default was wrong.

## Exact diff

```diff
--- a/Source/SimWorld/Private/SWEnvironment.cpp
+++ b/Source/SimWorld/Private/SWEnvironment.cpp
@@ -7,6 +7,7 @@
 #include "Components/StaticMeshComponent.h"
 #include "Engine/DirectionalLight.h"
 #include "Engine/ExponentialHeightFog.h"
+#include "Engine/PostProcessVolume.h"
 #include "Engine/SkyLight.h"
 #include "Engine/StaticMeshActor.h"
 #include "Engine/World.h"
@@ -46,15 +47,25 @@
 	Env.Sun = FindFirst<ADirectionalLight>(World);
 	if (!Env.Sun)
 	{
-		const FTransform Transform(FRotator(-40.0, 30.0, 0.0), FVector(0.0, 0.0, 1000.0));
+		// Late-afternoon sun FROM the southwest (world.json: x east, y south == UE +X, +Y). The light points
+		// toward the northeast, i.e. direction (+X, -Y): yaw -45. Pitch -18 = sun 18 deg above the horizon.
+		const FTransform Transform(FRotator(-18.0, -45.0, 0.0), FVector(0.0, 0.0, 1000.0));
 		Env.Sun = SpawnDeferred<ADirectionalLight>(World, TEXT("SWSun"), Transform);
 		if (UDirectionalLightComponent* Light = Cast<UDirectionalLightComponent>(Env.Sun->GetLightComponent()))
 		{
 			Light->SetMobility(EComponentMobility::Movable); // no baked lighting in this project
-			Light->SetIntensity(10.f);                       // lux
+			Light->SetIntensity(14.f);                       // lux
 			Light->SetAtmosphereSunLight(true);
+			// Golden key. The sun colour also tints the whole sky, which greys it; SkyLuminanceFactor
+			// below puts the blue back.
+			Light->SetLightColor(FLinearColor(1.0f, 0.84f, 0.65f));
+			Light->SetLightSourceAngle(1.2f);                 // slightly soft shadow edges
+			Light->SetVolumetricScatteringIntensity(0.f);
 		}
 		Env.Sun->FinishSpawning(Transform);
+		// FinishSpawning composes the transform with the light component's default relative rotation
+		// (pitch about -46), so the sun ended up ~46 deg steeper than asked. Set it explicitly.
+		Env.Sun->SetActorRotation(Transform.Rotator());
 	}
 
 	Env.Atmosphere = FindFirst<ASkyAtmosphere>(World);
@@ -62,6 +73,14 @@
 	{
 		const FTransform Transform(FVector::ZeroVector);
 		Env.Atmosphere = SpawnDeferred<ASkyAtmosphere>(World, TEXT("SWSkyAtmosphere"), Transform);
+		if (USkyAtmosphereComponent* Sky = Env.Atmosphere->GetComponent())
+		{
+			// A touch more Mie haze than Earth default: golden glow around the low sun, soft distance.
+			Sky->SetMieScatteringScale(0.005f);
+			Sky->SetSkyLuminanceFactor(FLinearColor(0.75f, 1.0f, 1.5f));  // Ghibli cerulean despite the warm sun
+			Sky->SetMieAnisotropy(0.8f);
+			Sky->SetAerialPespectiveViewDistanceScale(1.5f);
+		}
 		Env.Atmosphere->FinishSpawning(Transform);
 	}
 
@@ -75,6 +94,9 @@
 			// Real-time capture of the atmosphere, so ambient light follows the sun (and goes dark with it).
 			Light->SetMobility(EComponentMobility::Movable);
 			Light->SetRealTimeCapture(true);
+			Light->SetIntensity(0.9f);
+			Light->bLowerHemisphereIsBlack = false;          // ground bounce instead of black undersides
+			Light->SetLowerHemisphereColor(FLinearColor(0.10f, 0.11f, 0.06f));
 		}
 		Env.SkyLight->FinishSpawning(Transform);
 	}
@@ -84,8 +106,42 @@
 	{
 		const FTransform Transform(FVector::ZeroVector);
 		Env.Fog = SpawnDeferred<AExponentialHeightFog>(World, TEXT("SWFog"), Transform);
+		if (UExponentialHeightFogComponent* Fog = Env.Fog->GetComponent())
+		{
+			// Thin warm valley haze that only reads past ~50 m: depth without greying the near city.
+			Fog->SetFogDensity(0.005f);
+			Fog->SetFogHeightFalloff(0.12f);
+			Fog->SetStartDistance(4000.f);
+			Fog->SetFogMaxOpacity(0.85f);
+			Fog->SetFogInscatteringColor(FLinearColor(0.16f, 0.22f, 0.32f));
+			Fog->SetDirectionalInscatteringColor(FLinearColor(0.60f, 0.42f, 0.22f));
+			Fog->SetDirectionalInscatteringExponent(6.f);
+			Fog->SetVolumetricFog(false);
+		}
 		Env.Fog->FinishSpawning(Transform);
 	}
+
+	// Unbound post-process "look": gentle bloom, slight warmth and saturation, soft vignette.
+	// Exposure stays with the SimCV camera (LitExposureEV100 in DefaultGame.ini overrides it per capture).
+	if (!FindFirst<APostProcessVolume>(World))
+	{
+		const FTransform Transform(FVector::ZeroVector);
+		APostProcessVolume* PP = SpawnDeferred<APostProcessVolume>(World, TEXT("SWLook"), Transform);
+		PP->bUnbound = true;
+		PP->Priority = -1.f;                                  // any map-authored volume wins
+		FPostProcessSettings& S = PP->Settings;
+		S.bOverride_BloomIntensity = true;            S.BloomIntensity = 0.45f;
+		S.bOverride_BloomThreshold = true;            S.BloomThreshold = 1.0f;
+		S.bOverride_ColorSaturation = true;           S.ColorSaturation = FVector4(1.1f, 1.1f, 1.1f, 1.f);
+		S.bOverride_ColorContrast = true;             S.ColorContrast = FVector4(1.0f, 1.0f, 1.0f, 0.97f);
+		S.bOverride_ColorGain = true;                 S.ColorGain = FVector4(1.06f, 1.0f, 0.89f, 1.f);         // golden hour warmth
+		S.bOverride_ColorGainShadows = true;          S.ColorGainShadows = FVector4(0.95f, 1.0f, 1.08f, 1.f); // cool shadows
+		S.bOverride_ColorGainHighlights = true;       S.ColorGainHighlights = FVector4(1.07f, 1.0f, 0.88f, 1.f); // warm highlights
+		S.bOverride_VignetteIntensity = true;         S.VignetteIntensity = 0.3f;
+		S.bOverride_LumenSkylightLeaking = true;      S.LumenSkylightLeaking = 0.03f; // softer, airier shadows
+		S.bOverride_SceneFringeIntensity = true;      S.SceneFringeIntensity = 0.f;
+		PP->FinishSpawning(Transform);
+	}
 	return Env;
 }
 
--- a/Config/DefaultGame.ini
+++ b/Config/DefaultGame.ini
@@ -20,7 +20,8 @@
 MaxRequestsPerTick=1024
 TickBudgetMs=30.0
 LingerMs=4.0
-LitExposureEV100=-2.0
+; Solarpunk look: tuned for the 14 lux, 18 deg late-afternoon sun in SWEnvironment.cpp (was -2.0).
+LitExposureEV100=-1.3
 RedirectsFile=SimCVRedirects.json
 DefaultWidth=640
 DefaultHeight=480
```
