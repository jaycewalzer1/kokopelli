#pragma once
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MHLocalLibrary.generated.h"

class UMetaHumanCharacter;

UCLASS()
class UMHLocalLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()
public:
	/** Writes the character's current (locally edited) face state as a full face DNA file, using the
	 *  character's own DNA if rigged, else the preview face mesh DNA (same as the editor's debug
	 *  "Save Face State to DNA"). Character must be open for edit. */
	UFUNCTION(BlueprintCallable, Category = "MHLocal")
	static bool WriteFaceStateDNA(UMetaHumanCharacter* Character, const FString& Path);

	/** Marks the character as having final textures so assembly accepts locally synthesized ones. */
	UFUNCTION(BlueprintCallable, Category = "MHLocal")
	static void SetHasHighResolutionTextures(UMetaHumanCharacter* Character, bool bValue);

	UFUNCTION(BlueprintCallable, Category = "MHLocal")
	static bool HasFaceDNA(UMetaHumanCharacter* Character);

	UFUNCTION(BlueprintCallable, Category = "MHLocal")
	static bool HasSynthesizedTextures(UMetaHumanCharacter* Character);

	/** Why assembly is refused (empty if it can build). */
	/** Assemble with the UE Optimized pipeline at Quality (0 Low, 1 Medium, 2 High), with switches the Python
	 *  API doesn't expose: material baking on/off per part (body baking needs the Core Data body textures). */
	UFUNCTION(BlueprintCallable, Category = "MHLocal")
	static FString BuildLocal(UMetaHumanCharacter* Character, int32 Quality, const FString& BuildPath, const FString& CommonPath,
		bool bBakeMaterials, bool bBakeFace, bool bBakeBody, const FString& NameOverride);

	/** Last GPU frame time in ms (RHIGetGPUFrameCycles). */
	UFUNCTION(BlueprintCallable, Category = "MHLocal")
	static float GetGPUFrameMs();

	/** Resource size in bytes (Exclusive or EstimatedTotal) of a loaded object. */
	UFUNCTION(BlueprintCallable, Category = "MHLocal")
	static int64 GetResourceSizeBytes(UObject* Object, bool bEstimatedTotal);

	/** Finish all pending shader compiles and stream every texture/mesh fully in (for renders). */
	UFUNCTION(BlueprintCallable, Category = "MHLocal")
	static void FlushShadersAndStreaming();

	/** Capture Count times, flushing the render thread each time; returns mean wall ms per capture
	 *  (render-thread + GPU bound, since FlushRenderingCommands waits for the GPU work to be submitted and done). */
	UFUNCTION(BlueprintCallable, Category = "MHLocal")
	static float TimeCaptures(class USceneCaptureComponent2D* Capture, int32 Count);

	/** Async-load the given packages (long package names) and return wall ms until all are loaded. */
	UFUNCTION(BlueprintCallable, Category = "MHLocal")
	static float AsyncLoadMs(const TArray<FString>& Packages);

	UFUNCTION(BlueprintCallable, Category = "MHLocal")
	static FString WhyCannotBuild(UMetaHumanCharacter* Character);
};
