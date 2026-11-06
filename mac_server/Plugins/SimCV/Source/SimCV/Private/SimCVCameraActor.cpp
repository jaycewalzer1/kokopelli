#include "SimCVCameraActor.h"

#include "SimCVCameraComponent.h"

ASimCVCameraActor::ASimCVCameraActor()
{
	PrimaryActorTick.bCanEverTick = false;
	Camera = CreateDefaultSubobject<USimCVCameraComponent>(TEXT("SimCVCamera"));
	RootComponent = Camera;
}
