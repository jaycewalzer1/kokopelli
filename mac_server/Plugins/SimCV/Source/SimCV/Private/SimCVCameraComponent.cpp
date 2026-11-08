#include "SimCVCameraComponent.h"

#include "Engine/TextureRenderTarget2D.h"
#include "Engine/World.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "SimCVSettings.h"
#include "SimCVWorld.h"
#include "TextureResource.h"

FSimCVAnnotationCapture USimCVCameraComponent::OnAnnotationCapture;

namespace SimCV
{
/** Brackets an annotation capture with OnAnnotationCapture (begin/end): what the game hides goes on the camera's
 *  hidden list for this capture only, and other component changes are pushed to the renderer first. */
FAnnotationCaptureScope::FAnnotationCaptureScope(USimCVCameraComponent* InCamera)
	: Camera(InCamera), World(InCamera ? InCamera->GetWorld() : nullptr)
{
	if (!World || !USimCVCameraComponent::OnAnnotationCapture.IsBound())
	{
		return;
	}
	bActive = true;
	USimCVCameraComponent::OnAnnotationCapture.Broadcast(World, true, Hidden);
	for (UPrimitiveComponent* Component : Hidden)
	{
		if (Component && !Camera->HiddenComponents.Contains(Component))
		{
			Camera->HiddenComponents.Add(Component);
			Added.Add(Component);
		}
	}
	World->SendAllEndOfFrameUpdates();
}

FAnnotationCaptureScope::~FAnnotationCaptureScope()
{
	if (!bActive)
	{
		return;
	}
	for (UPrimitiveComponent* Component : Added)
	{
		Camera->HiddenComponents.Remove(Component);
	}
	TArray<UPrimitiveComponent*> Unused;
	USimCVCameraComponent::OnAnnotationCapture.Broadcast(World, false, Unused);
	World->SendAllEndOfFrameUpdates();
}
}

USimCVCameraComponent::USimCVCameraComponent()
{
	bCaptureEveryFrame = false;
	bCaptureOnMovement = false;
	// Keeps eye adaptation and temporal history between on-demand captures.
	bAlwaysPersistRenderingState = true;
	CaptureSource = ESceneCaptureSource::SCS_FinalColorLDR;
	FOVAngle = 90.f;

	PostProcessSettings.bOverride_AutoExposureMethod = true;
	PostProcessSettings.AutoExposureMethod = AEM_Manual;
	PostProcessSettings.bOverride_AutoExposureApplyPhysicalCameraExposure = true;
	PostProcessSettings.AutoExposureApplyPhysicalCameraExposure = false;
	PostProcessSettings.bOverride_AutoExposureBias = true;
	PostProcessSettings.AutoExposureBias = GetDefault<USimCVSettings>()->LitExposureEV100;
	PostProcessBlendWeight = 1.f;
}

void USimCVCameraComponent::OnRegister()
{
	Super::OnRegister();
	if (GetWorld() && GetWorld()->IsGameWorld())
	{
		SimCV::RegisterCamera(this);
	}
}

void USimCVCameraComponent::OnUnregister()
{
	SimCV::UnregisterCamera(this);
	Super::OnUnregister();
}

void USimCVCameraComponent::SetFilmSize(int32 Width, int32 Height)
{
	FilmWidth = FMath::Clamp(Width, 1, 8192);
	FilmHeight = FMath::Clamp(Height, 1, 8192);
}

void USimCVCameraComponent::SyncToPlayerView()
{
	APlayerController* PC = SimCV::GetPlayerController(GetWorld());
	if (!PC)
	{
		return;
	}
	// Computed directly rather than from the camera manager, whose cached view only updates
	// next frame; a "vset rotation" followed by "vget lit" in the same frame must agree.
	FVector Location;
	FRotator Rotation;
	if (const APawn* Pawn = PC->GetPawn())
	{
		Location = Pawn->GetPawnViewLocation();
		Rotation = PC->GetControlRotation();
	}
	else
	{
		PC->GetPlayerViewPoint(Location, Rotation);
	}
	SetWorldLocationAndRotation(Location, Rotation);
}

UTextureRenderTarget2D* USimCVCameraComponent::EnsureTarget(bool bFloatTarget)
{
	TObjectPtr<UTextureRenderTarget2D>& Target = bFloatTarget ? FloatTarget : ColorTarget;
	if (!Target)
	{
		Target = NewObject<UTextureRenderTarget2D>(this);
	}
	if (Target->SizeX != FilmWidth || Target->SizeY != FilmHeight || !Target->GameThread_GetRenderTargetResource())
	{
		// Same formats as UnrealCV: 8-bit sRGB BGRA for colour, linear fp16 RGBA for depth/normals.
		Target->InitCustomFormat(FilmWidth, FilmHeight, bFloatTarget ? PF_FloatRGBA : PF_B8G8R8A8, /*bForceLinearGamma=*/bFloatTarget);
	}
	return Target;
}

void USimCVCameraComponent::Capture(ESceneCaptureSource Source, bool bFloatTarget)
{
	if (bFollowPlayerView)
	{
		SyncToPlayerView();
	}
	TextureTarget = EnsureTarget(bFloatTarget);
	CaptureSource = Source;
	CaptureScene(); // enqueues the render; ReadPixels below flushes it
}

bool USimCVCameraComponent::ReadColor(TArray<FColor>& Out) const
{
	FTextureRenderTargetResource* Resource = TextureTarget ? TextureTarget->GameThread_GetRenderTargetResource() : nullptr;
	return Resource && Resource->ReadPixels(Out) && Out.Num() == FilmWidth * FilmHeight;
}

bool USimCVCameraComponent::ReadFloat(TArray<FFloat16Color>& Out) const
{
	FTextureRenderTargetResource* Resource = TextureTarget ? TextureTarget->GameThread_GetRenderTargetResource() : nullptr;
	return Resource && Resource->ReadFloat16Pixels(Out) && Out.Num() == FilmWidth * FilmHeight;
}

bool USimCVCameraComponent::CaptureLit(TArray<FColor>& OutPixels)
{
	Capture(ESceneCaptureSource::SCS_FinalColorLDR, false);
	if (!ReadColor(OutPixels))
	{
		return false;
	}
	for (FColor& Pixel : OutPixels)
	{
		Pixel.A = 255;
	}
	return true;
}

bool USimCVCameraComponent::CaptureDepth(TArray<float>& OutDepth)
{
	const SimCV::FAnnotationCaptureScope Clean(this);
	Capture(ESceneCaptureSource::SCS_SceneDepth, true);
	TArray<FFloat16Color> Raw;
	if (!ReadFloat(Raw))
	{
		return false;
	}
	OutDepth.SetNumUninitialized(Raw.Num());
	for (int32 Index = 0; Index < Raw.Num(); ++Index)
	{
		OutDepth[Index] = Raw[Index].R.GetFloat();
	}
	return true;
}

bool USimCVCameraComponent::CaptureNormal(TArray<FColor>& OutPixels)
{
	const SimCV::FAnnotationCaptureScope Clean(this);
	Capture(ESceneCaptureSource::SCS_Normal, true);
	TArray<FFloat16Color> Raw;
	if (!ReadFloat(Raw))
	{
		return false;
	}
	auto ToByte = [](const FFloat16& Component)
	{
		return static_cast<uint8>(FMath::Clamp(FMath::RoundToInt((Component.GetFloat() * 0.5f + 0.5f) * 255.f), 0, 255));
	};
	OutPixels.SetNumUninitialized(Raw.Num());
	for (int32 Index = 0; Index < Raw.Num(); ++Index)
	{
		OutPixels[Index] = FColor(ToByte(Raw[Index].R), ToByte(Raw[Index].G), ToByte(Raw[Index].B), 255);
	}
	return true;
}
