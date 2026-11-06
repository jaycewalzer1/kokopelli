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

	/** Relative to the project Config directory. */
	UPROPERTY(config, EditAnywhere, Category = "Server")
	FString RedirectsFile = TEXT("SimCVRedirects.json");

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
