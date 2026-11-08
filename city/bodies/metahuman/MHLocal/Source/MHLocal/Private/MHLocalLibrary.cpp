#include "MHLocalLibrary.h"
#include "MetaHumanCharacter.h"
#include "MetaHumanCharacterEditorSubsystem.h"
#include "MetaHumanCharacterIdentity.h"
#include "DNAUtils.h"
#include "DNAReader.h"
#include "SkelMeshDNAUtils.h"
#include "Engine/SkeletalMesh.h"
#include "Editor.h"
#include "RHI.h"
#include "ShaderCompiler.h"
#include "ContentStreaming.h"
#include "RenderingThread.h"
#include "Components/SceneCaptureComponent2D.h"
#include "UObject/UObjectGlobals.h"
#include "HAL/PlatformTime.h"
#include "MetaHumanTypes.h"
#include "MetaHumanCollectionPipeline.h"
#include "MetaHumanCharacterPaletteProjectSettings.h"
#include "MetaHumanDefaultEditorPipelineBase.h"
#include "Subsystem/MetaHumanCharacterBuild.h"

bool UMHLocalLibrary::WriteFaceStateDNA(UMetaHumanCharacter* Character, const FString& Path)
{
	if (!Character) return false;
	UMetaHumanCharacterEditorSubsystem* Sub = GEditor->GetEditorSubsystem<UMetaHumanCharacterEditorSubsystem>();
	if (!Sub || !Sub->IsObjectAddedForEditing(Character)) return false;
	TSharedPtr<IDNAReader> Out;
	if (Character->HasFaceDNA())
	{
		TArray<uint8> Buf = Character->GetFaceDNABuffer();
		TSharedPtr<IDNAReader> R = ReadDNAFromBuffer(&Buf);
		if (R) Out = Sub->GetFaceState(Character)->StateToDna(R->Unwrap());
	}
	else
	{
		const USkeletalMesh* Mesh = Sub->GetFaceEditMesh(Character);
		TSharedPtr<IDNAReader> R = USkelMeshDNAUtils::GetDNAReader(const_cast<USkeletalMesh*>(Mesh));
		if (R) Out = Sub->GetFaceState(Character)->StateToDna(R->Unwrap());
	}
	if (!Out) return false;
	WriteDNAToFile(Out.Get(), EDNADataLayer::All, Path);
	return true;
}

void UMHLocalLibrary::SetHasHighResolutionTextures(UMetaHumanCharacter* Character, bool bValue)
{
	if (Character) { Character->SetHasHighResolutionTextures(bValue); Character->MarkPackageDirty(); }
}

bool UMHLocalLibrary::HasFaceDNA(UMetaHumanCharacter* Character) { return Character && Character->HasFaceDNA(); }
bool UMHLocalLibrary::HasSynthesizedTextures(UMetaHumanCharacter* Character) { return Character && Character->HasSynthesizedTextures(); }

FString UMHLocalLibrary::WhyCannotBuild(UMetaHumanCharacter* Character)
{
	if (!Character) return TEXT("null");
	UMetaHumanCharacterEditorSubsystem* Sub = GEditor->GetEditorSubsystem<UMetaHumanCharacterEditorSubsystem>();
	FText Msg;
	return Sub->CanBuildMetaHuman(Character, Msg) ? FString() : Msg.ToString();
}

FString UMHLocalLibrary::BuildLocal(UMetaHumanCharacter* Character, int32 Quality, const FString& BuildPath, const FString& CommonPath,
	bool bBakeMaterials, bool bBakeFace, bool bBakeBody, const FString& NameOverride)
{
	if (!Character) return TEXT("null character");
	UMetaHumanCharacterEditorSubsystem* Sub = GEditor->GetEditorSubsystem<UMetaHumanCharacterEditorSubsystem>();
	const UMetaHumanCharacterPaletteProjectSettings* Settings = GetDefault<UMetaHumanCharacterPaletteProjectSettings>();
	const EMetaHumanQualityLevel Q = (EMetaHumanQualityLevel)FMath::Clamp(Quality, 0, 2);
	const TSoftClassPtr<UMetaHumanCollectionPipeline>* Found = Settings->DefaultCharacterLegacyPipelines.Find(Q);
	if (!Found || Found->IsNull()) return TEXT("no default optimized pipeline for quality");
	UClass* Cls = Found->LoadSynchronous();
	if (!Cls) return TEXT("pipeline class failed to load");
	UMetaHumanCollectionPipeline* Pipeline = NewObject<UMetaHumanCollectionPipeline>(Character, Cls);
	UMetaHumanDefaultEditorPipelineBase* Ed = Cast<UMetaHumanDefaultEditorPipelineBase>(Pipeline->GetMutableEditorPipeline());
	if (!Ed) return TEXT("editor pipeline is not a UMetaHumanDefaultEditorPipelineBase");
	Ed->bBakeMaterials = bBakeMaterials;
	if (!bBakeFace) Ed->MaterialBakingOptions.FaceBakingOptions.BakingSettings.Reset();
	if (!bBakeBody) Ed->MaterialBakingOptions.BodyBakingOptions.BakingSettings.Reset();
	FMetaHumanCharacterEditorBuildParameters P;
	P.PipelineType = EMetaHumanDefaultPipelineType::Optimized;
	P.PipelineQuality = Q;
	P.AbsoluteBuildPath = BuildPath;
	P.CommonFolderPath = CommonPath;
	P.NameOverride = NameOverride;
	P.bEnableWardrobeItemValidation = false;
	P.PipelineOverride = Pipeline;
	Sub->BuildMetaHuman(Character, P);
	return FString::Printf(TEXT("ok pipeline=%s"), *Cls->GetPathName());
}

float UMHLocalLibrary::GetGPUFrameMs()
{
	return (float)FPlatformTime::ToMilliseconds(RHIGetGPUFrameCycles());
}

int64 UMHLocalLibrary::GetResourceSizeBytes(UObject* Object, bool bEstimatedTotal)
{
	return Object ? (int64)Object->GetResourceSizeBytes(bEstimatedTotal ? EResourceSizeMode::EstimatedTotal : EResourceSizeMode::Exclusive) : 0;
}

void UMHLocalLibrary::FlushShadersAndStreaming()
{
	if (GShaderCompilingManager) GShaderCompilingManager->FinishAllCompilation();
	IStreamingManager::Get().StreamAllResources(5.0f);
	FlushRenderingCommands();
}

float UMHLocalLibrary::TimeCaptures(USceneCaptureComponent2D* Capture, int32 Count)
{
	if (!Capture || Count <= 0) return -1.f;
	Capture->CaptureScene();
	FlushRenderingCommands();
	const double T0 = FPlatformTime::Seconds();
	for (int32 i = 0; i < Count; ++i)
	{
		Capture->CaptureScene();
		FlushRenderingCommands();
	}
	return (float)((FPlatformTime::Seconds() - T0) * 1000.0 / Count);
}

float UMHLocalLibrary::AsyncLoadMs(const TArray<FString>& Packages)
{
	const double T0 = FPlatformTime::Seconds();
	int32 Pending = Packages.Num();
	for (const FString& P : Packages)
	{
		LoadPackageAsync(P, FLoadPackageAsyncDelegate::CreateLambda(
			[&Pending](const FName&, UPackage*, EAsyncLoadingResult::Type) { --Pending; }));
	}
	while (Pending > 0) { FlushAsyncLoading(); }
	return (float)((FPlatformTime::Seconds() - T0) * 1000.0);
}
