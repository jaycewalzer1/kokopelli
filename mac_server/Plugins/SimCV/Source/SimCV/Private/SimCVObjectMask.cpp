#include "SimCVCameraComponent.h"

#include "Components/MeshComponent.h"
#include "Components/SkinnedMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "SimCVLog.h"
#include "SimCVSettings.h"
#include "SimCVWorld.h"

/*
 * Object mask without any project assets: for one capture, every visible mesh is drawn with a
 * dynamic instance of a plain opaque material whose base colour is its actor's annotation colour,
 * and the capture reads the GBuffer base colour (no lighting, no tonemapping). Materials are
 * restored right after. UnrealCV instead adds a parallel "annotation" primitive per mesh, which
 * is faster per frame but much more code.
 */

UMaterialInstanceDynamic* USimCVCameraComponent::GetAnnotationMaterial(const FColor& Color, bool bSkinned)
{
	const USimCVSettings* Settings = GetDefault<USimCVSettings>();
	UMaterialInterface* Skinned = nullptr;
	if (bSkinned && !Settings->SkeletalAnnotationMaterial.IsNull())
	{
		static TWeakObjectPtr<UMaterialInterface> Cached;
		static bool bTried = false;
		if (!bTried)
		{
			bTried = true;
			Cached = Cast<UMaterialInterface>(Settings->SkeletalAnnotationMaterial.TryLoad());
			if (!Cached.IsValid())
			{
				UE_LOG(LogSimCV, Warning, TEXT("SkeletalAnnotationMaterial '%s' could not be loaded; skinned meshes use AnnotationMaterial"),
					*Settings->SkeletalAnnotationMaterial.ToString());
			}
		}
		Skinned = Cached.Get();
	}
	// Separate cache entries for the skinned material (top bit of the alpha byte is free: colours are opaque).
	const uint32 Key = Color.ToPackedARGB() ^ (Skinned ? 0x01000000u : 0u);
	if (const TObjectPtr<UMaterialInstanceDynamic>* Existing = AnnotationMaterials.Find(Key))
	{
		return *Existing;
	}
	UMaterialInterface* Base = Skinned ? Skinned : Cast<UMaterialInterface>(Settings->AnnotationMaterial.TryLoad());
	if (!Base)
	{
		UE_LOG(LogSimCV, Error, TEXT("AnnotationMaterial '%s' could not be loaded"), *Settings->AnnotationMaterial.ToString());
		return nullptr;
	}
	UMaterialInstanceDynamic* Material = UMaterialInstanceDynamic::Create(Base, this);
	// FLinearColor(FColor) linearises the sRGB value; the sRGB colour target re-encodes it on write.
	Material->SetVectorParameterValue(Settings->AnnotationColorParameter, FLinearColor(Color));
	AnnotationMaterials.Add(Key, Material);
	return Material;
}

bool USimCVCameraComponent::CaptureObjectMask(TArray<FColor>& OutPixels)
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return false;
	}

	// Fading bodies show exactly one whole body in the mask (never the dithered pair).
	const SimCV::FAnnotationCaptureScope Clean(this);

	struct FSavedMesh
	{
		TWeakObjectPtr<UMeshComponent> Mesh;
		TArray<UMaterialInterface*> Materials;
	};
	TArray<FSavedMesh> Saved;
	TArray<TWeakObjectPtr<UPrimitiveComponent>> ShowOnly;

	for (TActorIterator<AActor> It(World); It; ++It)
	{
		AActor* Actor = *It;
		if (Actor->IsHidden() || Actor == GetOwner())
		{
			continue;
		}
		UMaterialInstanceDynamic* Material = GetAnnotationMaterial(SimCV::GetAnnotationColor(Actor));
		if (!Material)
		{
			return false;
		}
		TInlineComponentArray<UMeshComponent*> Meshes(Actor);
		for (UMeshComponent* Mesh : Meshes)
		{
			if (!Mesh->IsRegistered() || !Mesh->IsVisible() || Clean.Hides(Mesh))
			{
				continue;
			}
			// Anything that isn't a static mesh (skinned bodies and their clothes, grooms) takes the skinned
			// annotation material, which carries the skeletal and hair-strands usage flags.
			UMaterialInstanceDynamic* MeshMaterial = !Mesh->IsA<UStaticMeshComponent>()
				? GetAnnotationMaterial(SimCV::GetAnnotationColor(Actor), true) : Material;
			FSavedMesh& Entry = Saved.AddDefaulted_GetRef();
			Entry.Mesh = Mesh;
			for (int32 Slot = 0; Slot < Mesh->GetNumMaterials(); ++Slot)
			{
				Entry.Materials.Add(Mesh->GetMaterial(Slot));
				Mesh->SetMaterial(Slot, MeshMaterial);
			}
			ShowOnly.Add(Mesh);
		}
	}

	// Material swaps only reach the renderer at end of frame; push them now so this capture sees them.
	World->SendAllEndOfFrameUpdates();

	// Show-only list keeps landscape/sky/fog (no annotation colour) out: background stays black.
	const ESceneCapturePrimitiveRenderMode PreviousMode = PrimitiveRenderMode;
	PrimitiveRenderMode = ESceneCapturePrimitiveRenderMode::PRM_UseShowOnlyList;
	ShowOnlyComponents = ShowOnly;

	Capture(ESceneCaptureSource::SCS_BaseColor, false);
	const bool bOk = ReadColor(OutPixels); // flushes rendering, so restoring below is safe

	ShowOnlyComponents.Reset();
	PrimitiveRenderMode = PreviousMode;
	for (const FSavedMesh& Entry : Saved)
	{
		if (UMeshComponent* Mesh = Entry.Mesh.Get())
		{
			for (int32 Slot = 0; Slot < Entry.Materials.Num(); ++Slot)
			{
				Mesh->SetMaterial(Slot, Entry.Materials[Slot]);
			}
		}
	}
	World->SendAllEndOfFrameUpdates();

	if (bOk)
	{
		for (FColor& Pixel : OutPixels)
		{
			Pixel.A = 255;
		}
	}
	return bOk;
}
