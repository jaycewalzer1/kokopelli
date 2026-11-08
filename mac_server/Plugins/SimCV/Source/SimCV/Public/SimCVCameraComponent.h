#pragma once

#include "CoreMinimal.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Math/Float16Color.h"
#include "SimCVCameraComponent.generated.h"

class UMaterialInstanceDynamic;
class UTextureRenderTarget2D;

/** Broadcast around every annotation capture (depth, normal, object mask; never lit): bBegin true right before,
 *  false right after the pixels are read. On begin, game code may add components to OutHide: they are left out of
 *  this one capture (the camera's hidden list, so no render state is recreated), and it may change material
 *  parameters, which it restores on end. Used so a dithered crossfade shows as exactly one whole body in the
 *  control passes (city/bodies, wave 2b). */
DECLARE_MULTICAST_DELEGATE_ThreeParams(FSimCVAnnotationCapture, UWorld* /*World*/, bool /*bBegin*/, TArray<UPrimitiveComponent*>& /*OutHide*/);

/**
 * An UnrealCV camera ("/camera/<id>/..."). Any actor carrying one is listed by vget /cameras;
 * ids are positions in that list, with the player-view camera always at 0.
 * Captures are on demand (CaptureScene + ReadPixels), never every frame.
 */
UCLASS(ClassGroup = (SimCV), meta = (BlueprintSpawnableComponent))
class SIMCV_API USimCVCameraComponent : public USceneCaptureComponent2D
{
	GENERATED_BODY()

public:
	USimCVCameraComponent();

	UFUNCTION(BlueprintCallable, Category = "SimCV")
	void SetFilmSize(int32 Width, int32 Height);

	int32 GetFilmWidth() const { return FilmWidth; }
	int32 GetFilmHeight() const { return FilmHeight; }

	/** BGRA, alpha forced to 255. */
	bool CaptureLit(TArray<FColor>& OutPixels);
	/** Scene depth in cm (plane depth along the view axis), row-major, top row first. */
	bool CaptureDepth(TArray<float>& OutDepth);
	/** World-space normals mapped from [-1,1] to [0,255]. */
	bool CaptureNormal(TArray<FColor>& OutPixels);
	/** Every visible mesh drawn in its actor's annotation colour (see vset /object/[str]/color). */
	bool CaptureObjectMask(TArray<FColor>& OutPixels);

	/** See FSimCVAnnotationCapture. */
	static FSimCVAnnotationCapture OnAnnotationCapture;

	/** Moves this camera to the first player's view point. */
	void SyncToPlayerView();

	/** Camera 0 follows the player view like UnrealCV's pawn-attached sensor. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "SimCV")
	bool bFollowPlayerView = false;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "SimCV", meta = (ClampMin = 1))
	int32 FilmWidth = 640;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "SimCV", meta = (ClampMin = 1))
	int32 FilmHeight = 480;

protected:
	virtual void OnRegister() override;
	virtual void OnUnregister() override;

private:
	void Capture(ESceneCaptureSource Source, bool bFloatTarget);
	bool ReadColor(TArray<FColor>& Out) const;
	bool ReadFloat(TArray<FFloat16Color>& Out) const;
	UTextureRenderTarget2D* EnsureTarget(bool bFloatTarget);
	UMaterialInstanceDynamic* GetAnnotationMaterial(const FColor& Color, bool bSkinned = false);

	UPROPERTY(Transient)
	TObjectPtr<UTextureRenderTarget2D> ColorTarget;

	UPROPERTY(Transient)
	TObjectPtr<UTextureRenderTarget2D> FloatTarget;

	UPROPERTY(Transient)
	TMap<uint32, TObjectPtr<UMaterialInstanceDynamic>> AnnotationMaterials;
};
