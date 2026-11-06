#pragma once

#include "CoreMinimal.h"
#include "Engine/DeveloperSettings.h"
#include "UObject/SoftObjectPath.h"
#include "SimCVSettings.generated.h"

/** [/Script/SimCV.SimCVSettings] in DefaultGame.ini. Command line overrides: -cvport= -cvbind= -cvredirects= */
UCLASS(config = Game, defaultconfig, meta = (DisplayName = "SimCV"))
class SIMCV_API USimCVSettings : public UDeveloperSettings
{
	GENERATED_BODY()

public:
	UPROPERTY(config, EditAnywhere, Category = "Server", meta = (ClampMin = 1, ClampMax = 65535))
	int32 Port = 9000;

	UPROPERTY(config, EditAnywhere, Category = "Server")
	FString BindAddress = TEXT("127.0.0.1");

	UPROPERTY(config, EditAnywhere, Category = "Server", meta = (ClampMin = 1))
	int32 MaxRequestsPerTick = 1024;

	/** Stop starting new requests in a frame once this much time has been spent. */
	UPROPERTY(config, EditAnywhere, Category = "Server", meta = (ClampMin = 1))
	float TickBudgetMs = 30.f;

	/**
	 * After handling a request, keep waiting this long for the next one before ending the frame.
	 * Clients send one request at a time, so without this a burst runs at one request per frame.
	 */
	UPROPERTY(config, EditAnywhere, Category = "Server", meta = (ClampMin = 0))
	float LingerMs = 4.f;

	/** Relative to the project Config directory. */
	UPROPERTY(config, EditAnywhere, Category = "Server")
	FString RedirectsFile = TEXT("SimCVRedirects.json");

	/**
	 * Fixed exposure compensation (stops, higher = brighter) for lit captures. Auto exposure would
	 * undo weather changes, and on-demand captures never get the frames it needs to adapt.
	 * -2 suits the 10 lux default sun.
	 */
	UPROPERTY(config, EditAnywhere, Category = "Camera")
	float LitExposureEV100 = -2.f;

	UPROPERTY(config, EditAnywhere, Category = "Camera", meta = (ClampMin = 1))
	int32 DefaultWidth = 640;

	UPROPERTY(config, EditAnywhere, Category = "Camera", meta = (ClampMin = 1))
	int32 DefaultHeight = 480;

	UPROPERTY(config, EditAnywhere, Category = "Camera", meta = (ClampMin = 1, ClampMax = 170))
	float DefaultFOV = 90.f;

	/** Opaque material with a vector parameter used as base colour; object_mask renders every mesh with it. */
	UPROPERTY(config, EditAnywhere, Category = "Camera", meta = (AllowedClasses = "/Script/Engine.MaterialInterface"))
	FSoftObjectPath AnnotationMaterial = FSoftObjectPath(TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"));

	UPROPERTY(config, EditAnywhere, Category = "Camera")
	FName AnnotationColorParameter = TEXT("Color");
};
