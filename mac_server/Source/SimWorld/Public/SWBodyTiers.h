#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "SWBodyTiers.generated.h"

struct FStreamableHandle;
class UPrimitiveComponent;
struct FStreamableManager;

/**
 * Near/far body tiers (city/bodies/PLAN.md, "Near/far bodies, revised").
 *
 * Each frame: for every person whose body has a "far" twin, the tallest it appears in any active SimCV camera
 * (agent eyes, capture cameras, the player view; never its own eyes), as pixels at the world-model capture size
 * (832x480 by default; horizontal FOV from the camera). Above near_px it wants the near body, below far_px the far
 * one, in between it keeps what it has (hysteresis). At most max_near people are near, tallest first.
 * Also owns the asset handles: near meshes load asynchronously and are released release_s after nobody shows them.
 */
UCLASS()
class SIMWORLD_API USWBodyTierSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;
	virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;

	static FStreamableManager& Streamable();
	/** Keeps Handle (and its assets) loaded for release_s more seconds, then lets go. */
	void ReleaseLater(TSharedPtr<FStreamableHandle> Handle);
	int32 NumPendingReleases() const { return Pending.Num(); }

private:
	struct FPendingRelease
	{
		TSharedPtr<FStreamableHandle> Handle;
		double When = 0.0;
	};
	TArray<FPendingRelease> Pending;
	/** SimCV annotation captures: fading people show one whole body in depth / normals / object mask. */
	void OnAnnotationCapture(UWorld* CaptureWorld, bool bBegin, TArray<UPrimitiveComponent*>& OutHide);
	FDelegateHandle AnnotationHandle;
};
