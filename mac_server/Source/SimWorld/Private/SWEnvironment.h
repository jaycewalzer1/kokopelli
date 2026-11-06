#pragma once

#include "CoreMinimal.h"

class ADirectionalLight;
class AExponentialHeightFog;
class ASkyAtmosphere;
class ASkyLight;
class UWorld;

/**
 * The flat default level (SPEC 4.2 [choice]): a large floor at z = 0, a sun, sky atmosphere,
 * real-time sky light and height fog. Existing actors of each kind are reused, so a map that
 * already has them keeps its own.
 */
namespace SW
{
	struct FEnvironment
	{
		ADirectionalLight* Sun = nullptr;
		ASkyAtmosphere* Atmosphere = nullptr;
		ASkyLight* SkyLight = nullptr;
		AExponentialHeightFog* Fog = nullptr;
	};

	/** Finds each environment actor, spawning the missing ones. */
	FEnvironment FindOrSpawnEnvironment(UWorld* World);

	/** Spawns the ground ("Floor", the permanent actor that keeps /objects non-empty) unless present. */
	void EnsureFloor(UWorld* World);

	/** Half the floor's side, cm. demo_city_1 spans about -43000..65000. */
	constexpr double FloorHalfSizeCm = 200000.0;
	constexpr TCHAR FloorName[] = TEXT("Floor");
}
