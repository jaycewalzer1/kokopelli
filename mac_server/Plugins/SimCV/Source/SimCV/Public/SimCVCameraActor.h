#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SimCVCameraActor.generated.h"

class USimCVCameraComponent;

/** Free-standing camera, spawned by vset /cameras/spawn and for the player-view camera 0. */
UCLASS()
class SIMCV_API ASimCVCameraActor : public AActor
{
	GENERATED_BODY()

public:
	ASimCVCameraActor();

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "SimCV")
	TObjectPtr<USimCVCameraComponent> Camera;
};
