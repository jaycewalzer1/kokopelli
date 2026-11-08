#include "SWCharacterBase.h"

#include "Animation/AnimInstance.h"
#include "Components/CapsuleComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/SkeletalMeshSocket.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/Controller.h"
#include "SWCommon.h"
#include "SWSettings.h"
#include "SWBodyTiers.h"
#include "Engine/StreamableManager.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Components/SkinnedMeshComponent.h"
#include "Engine/SkinnedAsset.h"
#include "GroomAsset.h"
#include "GroomBindingAsset.h"
#include "GroomComponent.h"

ASWCharacterBase::ASWCharacterBase()
{
	PrimaryActorTick.bCanEverTick = true;

	// SPEC 7.9: humanoids spawn at z=600 and fall, pedestrians spawn at z=110 = 20 cm sidewalk + 90.
	GetCapsuleComponent()->InitCapsuleSize(34.f, 90.f);

	// Rotation belongs to the commands, never to a controller or to the velocity.
	bUseControllerRotationYaw = false;
	bUseControllerRotationPitch = false;
	bUseControllerRotationRoll = false;
	AutoPossessAI = EAutoPossessAI::Disabled; // no AIController actors cluttering /objects

	UCharacterMovementComponent* Movement = GetCharacterMovement();
	Movement->bRunPhysicsWithNoController = true; // gravity and input without a controller
	Movement->bOrientRotationToMovement = false;
	Movement->bUseControllerDesiredRotation = false;
	Movement->MaxWalkSpeed = WalkSpeed;
	// Effectively instant start and stop, so distance = speed x time.
	Movement->MaxAcceleration = 100000.f;
	Movement->BrakingDecelerationWalking = 100000.f;
	Movement->GroundFriction = 8.f;
	Movement->MaxStepHeight = 45.f; // 20 cm curbs

	// Bodies are animated even when only a scene capture (never the window) sees them.
	GetMesh()->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
	GetMesh()->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	FadeMesh = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("FadeMesh"));
	FadeMesh->SetupAttachment(GetCapsuleComponent());
	FadeMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	FadeMesh->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
	FadeMesh->SetVisibility(false);
	// MetaHuman faces (Bodies.json face_mesh): a second skinned mesh that follows the body by leader pose.
	FaceMesh = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("FaceMesh"));
	FaceMesh->SetupAttachment(GetMesh());
	FaceMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	FaceMesh->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
	FaceMesh->SetVisibility(false);
	FadeFaceMesh = CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("FadeFaceMesh"));
	FadeFaceMesh->SetupAttachment(FadeMesh);
	FadeFaceMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	FadeFaceMesh->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
	FadeFaceMesh->SetVisibility(false);
}

void ASWCharacterBase::BeginPlay()
{
	Super::BeginPlay();
	SetWalkSpeed(WalkSpeed);
}

void ASWCharacterBase::Destroyed()
{
	// A controller added by EnableController would otherwise outlive its pawn.
	if (AController* OwnController = GetController(); OwnController && !OwnController->IsPlayerController())
	{
		OwnController->UnPossess();
		OwnController->Destroy();
	}
	Super::Destroyed();
}

void ASWCharacterBase::EndPlay(const EEndPlayReason::Type Reason)
{
	if (UWorld* World = GetWorld())
	{
		if (USWBodyTierSubsystem* Tiers = World->GetSubsystem<USWBodyTierSubsystem>())
		{
			Tiers->ReleaseLater(NearHandle);
			Tiers->ReleaseLater(ShownHandle);
		}
	}
	NearHandle.Reset();
	ShownHandle.Reset();
	Super::EndPlay(Reason);
}

void ASWCharacterBase::SetSpeaking(float Seconds)
{
	SpeakTimeLeft = FMath::Max(0.f, Seconds);
}

void ASWCharacterBase::EnableController(bool bEnable)
{
	if (bEnable && !GetController())
	{
		SpawnDefaultController();
	}
	else if (!bEnable && GetController() && !GetController()->IsPlayerController())
	{
		AController* OwnController = GetController();
		OwnController->UnPossess();
		OwnController->Destroy();
	}
}

void ASWCharacterBase::Rotate_Angle(float Duration, float Angle, int32 Direction)
{
	StartRotation(Duration, Angle);
}

void ASWCharacterBase::SetWalkSpeed(float Speed)
{
	WalkSpeed = FMath::Max(0.f, Speed);
	GetCharacterMovement()->MaxWalkSpeed = WalkSpeed;
}

void ASWCharacterBase::StartContinuousMove(const FVector2D& LocalDirection)
{
	Motion = EMotion::Continuous;
	MoveDirection = LocalDirection;
}

void ASWCharacterBase::StartTimedMove(const FVector2D& LocalDirection, float Duration)
{
	if (Duration <= 0.f)
	{
		return;
	}
	Motion = EMotion::Timed;
	MoveDirection = LocalDirection;
	MoveTimeLeft = Duration;
}

bool ASWCharacterBase::SetPathFromString(const FString& Points)
{
	PathIndex = 0;
	return SW::ParsePoints(Points, PathPoints);
}

bool ASWCharacterBase::StartPath()
{
	if (PathPoints.Num() == 0)
	{
		return false;
	}
	PathIndex = 0;
	Motion = EMotion::Path;
	return true;
}

void ASWCharacterBase::StopMotion()
{
	Motion = EMotion::Idle;
	MoveTimeLeft = 0.f;
	// Keep the vertical speed so a falling character keeps falling.
	UCharacterMovementComponent* Movement = GetCharacterMovement();
	Movement->Velocity = FVector(0.0, 0.0, Movement->Velocity.Z);
	ConsumeMovementInputVector();
}

void ASWCharacterBase::StartRotation(float Duration, float Angle)
{
	RotationStartYaw = GetActorRotation().Yaw;
	RotationAngle = Angle;
	RotationElapsed = 0.f;
	RotationDuration = FMath::Max(0.f, Duration) * RotationTimeFraction;
	bRotating = true;
}

// --- Bodies (city/bodies/PLAN.md) ---------------------------------------------------------------

namespace
{
const FName FadeParam(TEXT("BodyFade"));
const FName TintParam(TEXT("Tint"));

bool SupportsDither(const UMeshComponent* Mesh)
{
	if (!Mesh || Mesh->GetNumMaterials() == 0)
	{
		return false;
	}
	for (int32 Slot = 0; Slot < Mesh->GetNumMaterials(); ++Slot)
	{
		float Value = 0.f;
		const UMaterialInterface* Material = Mesh->GetMaterial(Slot);
		if (!Material || !Material->GetScalarParameterValue(FHashedMaterialParameterInfo(FadeParam), Value))
		{
			return false;
		}
	}
	return true;
}
}

void ASWCharacterBase::BuildHumanBody(const FLinearColor& Clothes)
{
	PlaceholderColor = Clothes;
	if (SWBodies::IsLoaded())
	{
		const FString Id = SWBodies::ChooseFor(GetName(), IsAgent());
		FString Error, Warning;
		if (!Id.IsEmpty() && SetBody(Id, Error, Warning))
		{
			return;
		}
		UE_LOG(LogSimWorld, Warning, TEXT("%s: no body from %s (%s); using the placeholder"), *GetName(), *SWBodies::GetPath(),
			Error.IsEmpty() ? TEXT("no default body") : *Error);
		ShowPlaceholder();
		return;
	}

	// No Bodies.json: the older single-mesh setting, else the placeholder.
	const USWSettings* Settings = GetDefault<USWSettings>();
	USkeletalMesh* Mesh = Settings->CharacterMesh.IsNull() ? nullptr : Cast<USkeletalMesh>(Settings->CharacterMesh.TryLoad());
	if (Mesh)
	{
		GetMesh()->SetSkeletalMeshAsset(Mesh);
		GetMesh()->SetRelativeLocationAndRotation(Settings->CharacterMeshOffset, FRotator(0.0, Settings->CharacterMeshYaw, 0.0));
		if (UClass* AnimClass = Settings->CharacterAnimClass.TryLoadClass<UAnimInstance>())
		{
			GetMesh()->SetAnimInstanceClass(AnimClass);
		}
		ShownMesh = Mesh;
		ShownTier = TEXT("near");
		OnBodyChanged();
		return;
	}
	if (!Settings->CharacterMesh.IsNull())
	{
		UE_LOG(LogSimWorld, Warning, TEXT("CharacterMesh '%s' did not load; using the placeholder body"), *Settings->CharacterMesh.ToString());
	}
	ShowPlaceholder();
}

void ASWCharacterBase::ShowPlaceholder()
{
	GetMesh()->SetSkeletalMeshAsset(nullptr);
	FaceMesh->SetLeaderPoseComponent(nullptr);
	FaceMesh->SetSkeletalMeshAsset(nullptr);
	FaceMesh->SetVisibility(false);
	ClearFadeMeshes();
	DestroyParts(Parts);
	PartWarnings.Reset();
	FadeTime = -1.f;
	ShownMesh = nullptr;
	ShownFace = nullptr;
	ShownDef = nullptr;
	ShownTier = TEXT("placeholder");
	if (BodyParts.Num() == 0)
	{
		// Capsule centre is 90 cm above the feet.
		const float HalfHeight = GetCapsuleComponent()->GetUnscaledCapsuleHalfHeight();
		AddBodyPart(ESWShape::Cylinder, FVector(0.0, 0.0, -HalfHeight + 72.0), FVector(42.0, 42.0, 144.0), PlaceholderColor);
		AddBodyPart(ESWShape::Sphere, FVector(0.0, 0.0, -HalfHeight + 160.0), FVector(26.0, 26.0, 30.0), FLinearColor(0.6f, 0.42f, 0.3f));
		AddBodyPart(ESWShape::Box, FVector(15.0, 0.0, -HalfHeight + 160.0), FVector(10.0, 6.0, 6.0), FLinearColor(0.6f, 0.42f, 0.3f));
	}
	OnBodyChanged();
}

ASWCharacterBase::FResolved ASWCharacterBase::ResolveChain(const FSWBodyDef* Def, const FString& TierIfFirst, FString& OutWarning)
{
	TSet<FString> Seen;
	bool bFirst = true;
	for (const FSWBodyDef* Body = Def; Body && !Seen.Contains(Body->Id); Body = SWBodies::Find(Body->Fallback), bFirst = false)
	{
		Seen.Add(Body->Id);
		if (!Body->Mesh.IsEmpty())
		{
			TSharedPtr<FStreamableHandle> Handle = USWBodyTierSubsystem::Streamable().RequestSyncLoad(BodyPaths(Body));
			FResolved Out;
			if (TakeLoaded(Body, Handle, Out))
			{
				Out.Tier = bFirst ? TierIfFirst : FString(TEXT("fallback"));
				return Out;
			}
		}
		OutWarning += Body->FaceMesh.IsEmpty()
			? FString::Printf(TEXT("body '%s': mesh '%s' did not load; "), *Body->Id, *Body->Mesh)
			: FString::Printf(TEXT("body '%s': mesh '%s' or face_mesh '%s' did not load; "), *Body->Id, *Body->Mesh, *Body->FaceMesh);
	}
	return FResolved();
}

bool ASWCharacterBase::HasTieredBody() const
{
	const FSWBodyDef* Def = SWBodies::Find(RequestedBodyId);
	return Def && SWBodies::Find(Def->Far) != nullptr;
}

bool ASWCharacterBase::SetBody(const FString& Id, FString& OutError, FString& OutWarning)
{
	const FSWBodyDef* Def = SWBodies::Find(Id);
	if (!Def)
	{
		OutError = FString::Printf(TEXT("unknown body '%s' (not in %s)"), *Id, *SWBodies::GetPath());
		return false;
	}
	RequestedBodyId = Def->Id;
	if (NearHandle.IsValid())
	{
		if (USWBodyTierSubsystem* Tiers = GetWorld()->GetSubsystem<USWBodyTierSubsystem>())
		{
			Tiers->ReleaseLater(NearHandle);
		}
		NearHandle.Reset();
	}
	// A tiered body starts far (cheap, synchronous); the tier subsystem brings the near one in asynchronously.
	const FSWBodyDef* FarDef = SWBodies::Find(Def->Far);
	bShowingNear = FarDef == nullptr;
	bWantNear = false;
	const FResolved Body = FarDef ? ResolveChain(FarDef, TEXT("far"), OutWarning) : ResolveChain(Def, TEXT("near"), OutWarning);
	if (!Body.Mesh)
	{
		OutWarning += TEXT("using the placeholder");
		UE_LOG(LogSimWorld, Warning, TEXT("%s SetBody %s: %s"), *GetName(), *Id, *OutWarning);
		ShowPlaceholder();
		return true;
	}
	if (!OutWarning.IsEmpty())
	{
		OutWarning += FString::Printf(TEXT("showing '%s'"), *Body.Def->Id);
		UE_LOG(LogSimWorld, Warning, TEXT("%s SetBody %s: %s"), *GetName(), *Id, *OutWarning);
	}
	ShowBody(Body);
	return true;
}

void ASWCharacterBase::SetTierDecision(bool bNear, float Px)
{
	bWantNear = bNear;
	ProjectedPx = Px;
}

void ASWCharacterBase::UpdateTier(float DeltaSeconds)
{
	const FSWBodyDef* NearDef = SWBodies::Find(RequestedBodyId);
	const FSWBodyDef* FarDef = NearDef ? SWBodies::Find(NearDef->Far) : nullptr;
	if (!FarDef || IsFading())
	{
		return;
	}
	USWBodyTierSubsystem* Tiers = GetWorld()->GetSubsystem<USWBodyTierSubsystem>();
	FString Warning;
	if (bWantNear && !bShowingNear)
	{
		if (!NearHandle.IsValid() && !NearDef->Mesh.IsEmpty())
		{
			NearHandle = USWBodyTierSubsystem::Streamable().RequestAsyncLoad(BodyPaths(NearDef), FStreamableDelegate(),
				FStreamableManager::AsyncLoadHighPriority);
		}
		if (NearHandle.IsValid() && NearHandle->IsLoadingInProgress())
		{
			return; // keep showing far until the near body is in memory
		}
		FResolved Body;
		if (TakeLoaded(NearDef, NearHandle, Body))
		{
			Body.Tier = TEXT("near");
		}
		else
		{
			Warning = FString::Printf(TEXT("body '%s': mesh '%s' did not load; "), *NearDef->Id, *NearDef->Mesh);
			Body = ResolveChain(SWBodies::Find(NearDef->Fallback), TEXT("fallback"), Warning);
			Body.Tier = TEXT("fallback");
		}
		bShowingNear = true;
		if (Body.Mesh)
		{
			ShowBody(Body);
		}
		if (!Warning.IsEmpty())
		{
			UE_LOG(LogSimWorld, Warning, TEXT("%s near body: %s"), *GetName(), *Warning);
		}
	}
	else if (!bWantNear && bShowingNear)
	{
		bShowingNear = false;
		const FResolved Body = ResolveChain(FarDef, TEXT("far"), Warning);
		if (Body.Mesh)
		{
			ShowBody(Body);
		}
		if (Tiers && NearHandle.IsValid())
		{
			Tiers->ReleaseLater(NearHandle); // freed release_s after leaving, unless it comes back
		}
		NearHandle.Reset();
	}
}

void ASWCharacterBase::SetupBodyMaterials(USkeletalMeshComponent* Mesh, const FSWBodyDef* Def)
{
	USkeletalMesh* Asset = Mesh->GetSkeletalMeshAsset();
	Mesh->EmptyOverrideMaterials();
	if (!Asset)
	{
		return;
	}
	UMaterialInterface* Override = Def && !Def->Material.IsEmpty() ? LoadObject<UMaterialInterface>(nullptr, *Def->Material) : nullptr;
	if (Def && !Def->Material.IsEmpty() && !Override)
	{
		UE_LOG(LogSimWorld, Warning, TEXT("body '%s': material '%s' did not load"), *Def->Id, *Def->Material);
	}
	static const TArray<FLinearColor> Palette = {
		FLinearColor(0.55f, 0.22f, 0.12f), FLinearColor(0.16f, 0.36f, 0.30f), FLinearColor(0.50f, 0.42f, 0.14f),
		FLinearColor(0.28f, 0.22f, 0.45f), FLinearColor(0.45f, 0.18f, 0.30f), FLinearColor(0.18f, 0.30f, 0.50f),
	};
	const bool bTint = Def && Def->bTint;
	const FLinearColor Tint = Def && Def->bAutoTint ? SW::PickColor(GetName(), Palette) : (Def ? Def->Tint : FLinearColor::White);
	for (int32 Slot = 0; Slot < Mesh->GetNumMaterials(); ++Slot)
	{
		UMaterialInterface* Base = Override ? Override : Mesh->GetMaterial(Slot);
		if (!Base)
		{
			continue;
		}
		UMaterialInstanceDynamic* Material = UMaterialInstanceDynamic::Create(Base, Mesh);
		if (bTint)
		{
			Material->SetVectorParameterValue(TintParam, Tint);
		}
		Mesh->SetMaterial(Slot, Material);
	}
}

TArray<UMeshComponent*> ASWCharacterBase::GetBodySet(bool bOld) const
{
	TArray<UMeshComponent*> Out;
	USkeletalMeshComponent* Body = bOld ? FadeMesh.Get() : GetMesh();
	USkeletalMeshComponent* Face = bOld ? FadeFaceMesh.Get() : FaceMesh.Get();
	if (Body && Body->GetSkeletalMeshAsset())
	{
		Out.Add(Body);
	}
	if (Face && Face->GetSkeletalMeshAsset())
	{
		Out.Add(Face);
	}
	for (UMeshComponent* Part : bOld ? FadeParts : Parts)
	{
		if (Part)
		{
			Out.Add(Part);
		}
	}
	return Out;
}

void ASWCharacterBase::ApplyFade(bool bOld, float Visibility)
{
	// Body, face, grooms and outfit fade together. Each dithers if all its materials have BodyFade; otherwise it
	// cuts at the halfway point, the new set winning ties, so the cut parts never show twice or not at all.
	for (UMeshComponent* Part : GetBodySet(bOld))
	{
		if (SupportsDither(Part))
		{
			Part->SetScalarParameterValueOnMaterials(FadeParam, Visibility);
			Part->SetVisibility(Visibility > 0.001f);
		}
		else
		{
			Part->SetVisibility(bOld ? Visibility > 0.5f : Visibility >= 0.5f);
		}
	}
}

void ASWCharacterBase::SetAnnotationView(bool bClean, TArray<UPrimitiveComponent*>& OutHide)
{
	if (!IsFading())
	{
		return;
	}
	const float Alpha = FMath::Clamp(GetFadeProgress(), 0.f, 1.f);
	const bool bNewWins = Alpha >= 0.5f;
	// Depth, normals and the object mask are world-model controls: one whole body, no dither speckle.
	for (UMeshComponent* Part : GetBodySet(/*bOld*/ bNewWins))
	{
		if (bClean && Part->IsVisible())
		{
			OutHide.Add(Part);
		}
	}
	for (UMeshComponent* Part : GetBodySet(/*bOld*/ !bNewWins))
	{
		if (SupportsDither(Part))
		{
			Part->SetScalarParameterValueOnMaterials(FadeParam, bClean ? 1.f : (bNewWins ? Alpha : 1.f - Alpha));
		}
	}
}

void ASWCharacterBase::DestroyParts(TArray<TObjectPtr<UMeshComponent>>& List)
{
	for (UMeshComponent* Part : List)
	{
		if (Part)
		{
			Part->DestroyComponent();
		}
	}
	List.Reset();
}

void ASWCharacterBase::BuildParts(const FSWBodyDef* Def)
{
	PartWarnings.Reset();
	if (!Def)
	{
		return;
	}
	for (const FSWBodyPart& P : Def->Parts)
	{
		auto Skip = [&](const FString& Why)
		{
			PartWarnings += FString::Printf(TEXT("body '%s' part '%s': %s; skipped. "), *Def->Id, *P.Slot, *Why);
		};
		if (Def->bLow && P.bGroom && P.Geometry == TEXT("strands"))
		{
			Skip(TEXT("strands on a Low body (use cards or a helmet)"));
			continue;
		}
		// Loaded already by the body's handle (BodyPaths); a sync load covers parts added after the request.
		UObject* Asset = FSoftObjectPath(P.Asset).ResolveObject();
		if (!Asset)
		{
			Asset = FSoftObjectPath(P.Asset).TryLoad();
		}
		if (!Asset)
		{
			Skip(FString::Printf(TEXT("'%s' did not load"), *P.Asset));
			continue;
		}
		USceneComponent* Parent = P.bAttachFace && FaceMesh->GetSkeletalMeshAsset() ? static_cast<USceneComponent*>(FaceMesh) : GetMesh();
		const FName Name = MakeUniqueObjectName(this, UMeshComponent::StaticClass(), FName(*FString::Printf(TEXT("BodyPart_%s"), *P.Slot)));
		UMeshComponent* Made = nullptr;
		if (P.bGroom)
		{
			UGroomAsset* Groom = Cast<UGroomAsset>(Asset);
			if (!Groom)
			{
				Skip(FString::Printf(TEXT("'%s' is a %s, not a GroomAsset"), *P.Asset, *Asset->GetClass()->GetName()));
				continue;
			}
			// Far bodies never show strands: the first LOD whose every group is cards or helmet (meshes), else skip.
			int32 ForcedLOD = -1;
			if (Def->bLow)
			{
				for (int32 Lod = 0; Lod < Groom->GetLODCount() && ForcedLOD < 0; ++Lod)
				{
					bool bAllCheap = Groom->GetNumHairGroups() > 0;
					for (int32 Group = 0; Group < Groom->GetNumHairGroups(); ++Group)
					{
						bAllCheap &= Groom->GetGeometryType(Group, Lod) != EGroomGeometryType::Strands;
					}
					ForcedLOD = bAllCheap ? Lod : -1;
				}
				if (ForcedLOD < 0)
				{
					Skip(FString::Printf(TEXT("'%s' has only strands LODs; a Low body needs cards or a helmet"), *P.Asset));
					continue;
				}
			}
			UGroomBindingAsset* Binding = nullptr;
			if (!P.Binding.IsEmpty())
			{
				Binding = Cast<UGroomBindingAsset>(FSoftObjectPath(P.Binding).TryLoad());
				if (!Binding)
				{
					PartWarnings += FString::Printf(TEXT("body '%s' part '%s': binding '%s' did not load; attached rigidly. "),
						*Def->Id, *P.Slot, *P.Binding);
				}
			}
			UGroomComponent* Comp = NewObject<UGroomComponent>(this, Name);
			Comp->SetupAttachment(Parent, P.Socket);
			Comp->SetGroomAsset(Groom, Binding);
			Comp->RegisterComponent();
			if (ForcedLOD >= 0)
			{
				Comp->SetForcedLOD(ForcedLOD);
				Comp->SetEnableSimulation(false); // Low: no hair sim either
			}
			Made = Comp;
		}
		else
		{
			USkinnedAsset* Skinned = Cast<USkinnedAsset>(Asset);
			UClass* CompClass = nullptr;
			if (Cast<USkeletalMesh>(Asset))
			{
				CompClass = USkeletalMeshComponent::StaticClass();
			}
			else if (Skinned)
			{
				// Chaos outfit / cloth assets draw with ChaosClothComponent (plugin module, looked up by name).
				CompClass = FindObject<UClass>(nullptr, TEXT("/Script/ChaosClothAssetEngine.ChaosClothComponent"));
			}
			if (!Skinned || !CompClass)
			{
				Skip(FString::Printf(TEXT("'%s' (%s) is not a skeletal mesh or a loadable outfit asset"), *P.Asset, *Asset->GetClass()->GetName()));
				continue;
			}
			USkinnedMeshComponent* Comp = NewObject<USkinnedMeshComponent>(this, CompClass, Name);
			Comp->SetupAttachment(Parent, P.Socket);
			Comp->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
			Comp->RegisterComponent();
			Comp->SetSkinnedAssetAndUpdate(Skinned);
			// Clothes and cards/helmets follow the body skeleton by bone name (the face does the same).
			Comp->SetLeaderPoseComponent(GetMesh(), /*bForceUpdate*/ true);
			Made = Comp;
		}
		Made->ComponentTags.Add(FName(*P.Slot)); // GetBodyDebug reports it as "slot"
		Made->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Made->SetCastShadow(true);
		if (!P.Material.IsEmpty())
		{
			if (UMaterialInterface* Override = LoadObject<UMaterialInterface>(nullptr, *P.Material))
			{
				for (int32 Slot = 0; Slot < Made->GetNumMaterials(); ++Slot)
				{
					Made->SetMaterial(Slot, UMaterialInstanceDynamic::Create(Override, Made));
				}
			}
			else
			{
				PartWarnings += FString::Printf(TEXT("body '%s' part '%s': material '%s' did not load. "), *Def->Id, *P.Slot, *P.Material);
			}
		}
		Parts.Add(Made);
	}
	if (!PartWarnings.IsEmpty())
	{
		UE_LOG(LogSimWorld, Warning, TEXT("%s: %s"), *GetName(), *PartWarnings);
	}
}

void ASWCharacterBase::ClearFadeMeshes()
{
	DestroyParts(FadeParts);
	FadeFaceMesh->SetLeaderPoseComponent(nullptr);
	FadeFaceMesh->SetSkeletalMeshAsset(nullptr);
	FadeFaceMesh->SetVisibility(false);
	FadeMesh->SetLeaderPoseComponent(nullptr);
	FadeMesh->SetSkeletalMeshAsset(nullptr);
	FadeMesh->SetVisibility(false);
}

TArray<FSoftObjectPath> ASWCharacterBase::BodyPaths(const FSWBodyDef* Def)
{
	TArray<FSoftObjectPath> Paths;
	Paths.Add(FSoftObjectPath(Def->Mesh));
	if (!Def->FaceMesh.IsEmpty())
	{
		Paths.Add(FSoftObjectPath(Def->FaceMesh));
	}
	// Grooms and clothes load and release with their body (the same handle). Missing ones are skipped later.
	for (const FSWBodyPart& Part : Def->Parts)
	{
		Paths.Add(FSoftObjectPath(Part.Asset));
		if (!Part.Binding.IsEmpty())
		{
			Paths.Add(FSoftObjectPath(Part.Binding));
		}
	}
	return Paths;
}

bool ASWCharacterBase::TakeLoaded(const FSWBodyDef* Def, const TSharedPtr<FStreamableHandle>& Handle, FResolved& Out)
{
	if (!Def || !Handle.IsValid())
	{
		return false;
	}
	USkeletalMesh* Mesh = Cast<USkeletalMesh>(FSoftObjectPath(Def->Mesh).ResolveObject());
	USkeletalMesh* Face = Def->FaceMesh.IsEmpty() ? nullptr : Cast<USkeletalMesh>(FSoftObjectPath(Def->FaceMesh).ResolveObject());
	if (!Mesh || (!Def->FaceMesh.IsEmpty() && !Face))
	{
		return false; // a body without its head is worse than the fallback
	}
	Out.Def = Def;
	Out.Mesh = Mesh;
	Out.Face = Face;
	Out.Handle = Handle;
	return true;
}

void ASWCharacterBase::ShowBody(const FResolved& Body)
{
	check(Body.Mesh);
	USkeletalMeshComponent* Mesh = GetMesh();
	USkeletalMesh* Old = ShownMesh;
	const FSWBodyDef* OldDef = ShownDef;
	UWorld* World = GetWorld();
	USWBodyTierSubsystem* Tiers = World ? World->GetSubsystem<USWBodyTierSubsystem>() : nullptr;

	// Crossfade between two bodies on one skeleton: the old one follows the new one's pose (leader pose).
	const bool bFade = Old && Old != Body.Mesh && Old->GetSkeleton() == Body.Mesh->GetSkeleton() && SWBodies::FadeSeconds() > 0.f
		&& HasActorBegunPlay();
	USkeletalMesh* OldFace = ShownFace;
	if (bFade)
	{
		DestroyParts(FadeParts); // a fade still running when the next swap comes
		FadeMesh->SetSkeletalMeshAsset(Old);
		FadeMesh->SetRelativeTransform(Mesh->GetRelativeTransform());
		SetupBodyMaterials(FadeMesh, OldDef);
		FadeMesh->SetLeaderPoseComponent(Mesh);
		FadeMesh->SetVisibility(true);
		if (OldFace)
		{
			// The old face rides the old body's transform but takes the new body's pose (bone names match).
			FadeFaceMesh->SetSkeletalMeshAsset(OldFace);
			SetupBodyMaterials(FadeFaceMesh, OldDef);
			FadeFaceMesh->SetLeaderPoseComponent(Mesh);
			FadeFaceMesh->SetVisibility(true);
		}
		else
		{
			FadeFaceMesh->SetLeaderPoseComponent(nullptr);
			FadeFaceMesh->SetSkeletalMeshAsset(nullptr);
			FadeFaceMesh->SetVisibility(false);
		}
		// The old grooms and clothes go with the old body and face; skinned ones take the new body's pose.
		for (UMeshComponent* Part : Parts)
		{
			if (!Part)
			{
				continue;
			}
			const bool bOnFace = Part->GetAttachParent() == FaceMesh && OldFace;
			Part->AttachToComponent(bOnFace ? static_cast<USceneComponent*>(FadeFaceMesh) : FadeMesh,
				FAttachmentTransformRules::KeepRelativeTransform, Part->GetAttachSocketName());
			if (USkinnedMeshComponent* Skinned = Cast<USkinnedMeshComponent>(Part))
			{
				Skinned->SetLeaderPoseComponent(Mesh);
			}
			FadeParts.Add(Part);
		}
		Parts.Reset();
	}
	else
	{
		DestroyParts(Parts);
	}

	for (UStaticMeshComponent* Part : BodyParts)
	{
		if (Part)
		{
			Part->DestroyComponent();
		}
	}
	BodyParts.Reset();

	Mesh->SetSkeletalMeshAsset(Body.Mesh);
	// A MetaHuman body mesh stops at the neck: size the person by body + face together.
	FBox Box = Body.Mesh->GetImportedBounds().GetBox();
	if (Body.Face)
	{
		Box += Body.Face->GetImportedBounds().GetBox();
	}
	const FBoxSphereBounds Bounds(Box);
	const float Native = Bounds.BoxExtent.Z * 2.f;
	const float Bottom = Bounds.Origin.Z - Bounds.BoxExtent.Z;
	const float Scale = Body.Def && Body.Def->HeightCm > 0.f && Native > 1.f ? Body.Def->HeightCm / Native : 1.f;
	const float HalfHeight = GetCapsuleComponent()->GetUnscaledCapsuleHalfHeight();
	Mesh->SetRelativeScale3D(FVector(Scale));
	Mesh->SetRelativeLocationAndRotation(FVector(0.0, 0.0, -HalfHeight - Bottom * Scale),
		FRotator(0.0, Body.Def ? Body.Def->MeshYaw : -90.0, 0.0));

	UClass* AnimClass = nullptr;
	if (Body.Def && !Body.Def->AnimClass.IsEmpty())
	{
		AnimClass = FSoftClassPath(Body.Def->AnimClass).TryLoadClass<UAnimInstance>();
		if (!AnimClass)
		{
			UE_LOG(LogSimWorld, Warning, TEXT("body '%s': anim_class '%s' did not load; using SWBodyAnimInstance"), *Body.Def->Id, *Body.Def->AnimClass);
		}
	}
	if (!AnimClass)
	{
		AnimClass = USWBodyAnimInstance::StaticClass();
	}
	if (Mesh->GetAnimClass() != AnimClass)
	{
		Mesh->SetAnimInstanceClass(AnimClass);
	}
	SetupBodyMaterials(Mesh, Body.Def);
	Mesh->SetVisibility(true);
	if (Body.Face)
	{
		FaceMesh->SetSkeletalMeshAsset(Body.Face);
		FaceMesh->SetRelativeTransform(FTransform::Identity);
		FaceMesh->SetLeaderPoseComponent(Mesh, /*bForceUpdate*/ true);
		SetupBodyMaterials(FaceMesh, Body.Def);
		FaceMesh->SetVisibility(true);
	}
	else
	{
		FaceMesh->SetLeaderPoseComponent(nullptr);
		FaceMesh->SetSkeletalMeshAsset(nullptr);
		FaceMesh->SetVisibility(false);
	}
	BuildParts(Body.Def);

	if (Tiers && ShownHandle.IsValid() && ShownHandle != Body.Handle && ShownHandle != NearHandle)
	{
		Tiers->ReleaseLater(ShownHandle);
	}
	ShownHandle = Body.Handle;
	ShownMesh = Body.Mesh;
	ShownFace = Body.Face;
	ShownDef = Body.Def;
	ShownTier = Body.Tier;

	const FName Hand = GetHandSocket();
	const USkeletalMeshSocket* Socket = Body.Mesh->FindSocket(Hand);
	BodyAnim.HandBone = Socket ? Socket->BoneName : Hand;

	if (bFade)
	{
		FadeDuration = SWBodies::FadeSeconds();
		FadeTime = FadeHold >= 0.f ? FMath::Clamp(FadeHold, 0.f, 1.f) * FadeDuration : 0.f;
		const float Alpha = FadeTime / FMath::Max(0.001f, FadeDuration);
		ApplyFade(false, Alpha);
		ApplyFade(true, 1.f - Alpha);
	}
	else
	{
		FadeTime = -1.f;
		ClearFadeMeshes();
		ApplyFade(false, 1.f);
	}
	OnBodyChanged();
}

void ASWCharacterBase::UpdateFade(float DeltaSeconds)
{
	if (FadeTime < 0.f)
	{
		return;
	}
	// FadeHold (tests) pins the progress; a hold of 1 or more finishes the fade.
	FadeTime = FadeHold >= 0.f ? FMath::Min(FadeHold, 1.f) * FadeDuration : FadeTime + DeltaSeconds;
	const float Alpha = FMath::Clamp(FadeTime / FMath::Max(0.001f, FadeDuration), 0.f, 1.f);
	ApplyFade(false, Alpha);
	ApplyFade(true, 1.f - Alpha);
	if (Alpha >= 1.f)
	{
		FadeTime = -1.f;
		ClearFadeMeshes();
		ApplyFade(false, 1.f);
	}
}

FString ASWCharacterBase::GetShownBodyId() const
{
	if (!ShownMesh)
	{
		return TEXT("placeholder");
	}
	return ShownDef ? ShownDef->Id : FString(TEXT("settings"));
}

FString ASWCharacterBase::GetBodyTier() const
{
	return ShownMesh ? ShownTier : FString(TEXT("placeholder"));
}

float ASWCharacterBase::GetBodyHeightCm() const
{
	if (const FSWBodyDef* Def = SWBodies::Find(RequestedBodyId); Def && Def->HeightCm > 0.f)
	{
		return Def->HeightCm;
	}
	return ShownDef && ShownDef->HeightCm > 0.f ? ShownDef->HeightCm : 175.f;
}

int32 ASWCharacterBase::CountVisibleBodyMeshes() const
{
	const USkeletalMeshComponent* Mesh = GetMesh();
	return (Mesh->GetSkeletalMeshAsset() && Mesh->IsVisible() ? 1 : 0)
		+ (FadeMesh->GetSkeletalMeshAsset() && FadeMesh->IsVisible() ? 1 : 0);
}

FVector ASWCharacterBase::GetEyeWorldLocation() const
{
	if (!ShownMesh)
	{
		return GetActorTransform().TransformPosition(FVector(12.0, 0.0, 70.0));
	}
	const USkeletalMeshComponent* Mesh = GetMesh();
	FName Socket = ShownDef ? ShownDef->EyeSocket : FName(TEXT("head"));
	if (!Mesh->DoesSocketExist(Socket))
	{
		Socket = TEXT("head");
	}
	const FVector Offset = ShownDef ? ShownDef->EyeOffsetCm : FVector(10.0, 0.0, 8.0);
	return Mesh->GetSocketLocation(Socket) + FRotator(0.0, GetActorRotation().Yaw, 0.0).RotateVector(Offset);
}

FName ASWCharacterBase::GetHandSocket() const
{
	return ShownDef ? ShownDef->HandSocket : FName(TEXT("hand_r"));
}

FVector ASWCharacterBase::GetHandWorldLocation(bool bLeft) const
{
	FName Socket = GetHandSocket();
	if (bLeft)
	{
		FString S = Socket.ToString();
		if (S.EndsWith(TEXT("_r")))
		{
			S[S.Len() - 1] = TEXT('l');
		}
		Socket = FName(*S);
	}
	return GetMesh()->GetSocketLocation(Socket);
}

UStaticMeshComponent* ASWCharacterBase::AddBodyPart(ESWShape Shape, const FVector& Center, const FVector& Size, const FLinearColor& Color)
{
	UStaticMeshComponent* Part = SW::AddShape(this, GetCapsuleComponent(), Shape, Center, Size, Color, false);
	BodyParts.Add(Part);
	return Part;
}

void ASWCharacterBase::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	// Body animation inputs (the anim instance reads these; they outlive mesh swaps).
	const double CurrentYaw = GetActorRotation().Yaw;
	BodyAnim.YawRate = bHaveLastYaw && DeltaSeconds > 0.f ? float(FRotator::NormalizeAxis(CurrentYaw - LastYaw) / DeltaSeconds) : 0.f;
	LastYaw = CurrentYaw;
	bHaveLastYaw = true;
	BodyAnim.Speed = GetVelocity().Size2D();
	SpeakTimeLeft = FMath::Max(0.f, SpeakTimeLeft - DeltaSeconds);
	BodyAnim.bTalking = SpeakTimeLeft > 0.f || bGestureTalking;
	if (BodyAnim.ReachTime >= 0.f)
	{
		BodyAnim.ReachTime += DeltaSeconds;
		if (BodyAnim.ReachTime > 0.9f)
		{
			BodyAnim.ReachTime = -1.f;
		}
	}
	UpdateTier(DeltaSeconds);
	UpdateFade(DeltaSeconds);

	if (bRotating)
	{
		RotationElapsed += DeltaSeconds;
		const double Alpha = RotationDuration > 0.f ? FMath::Min(1.0, RotationElapsed / RotationDuration) : 1.0;
		SetActorRotation(FRotator(0.0, RotationStartYaw + RotationAngle * Alpha, 0.0));
		bRotating = Alpha < 1.0;
	}

	if (Motion == EMotion::Idle || !CanMove())
	{
		return;
	}

	FVector Direction;
	if (Motion == EMotion::Path)
	{
		const FVector Location = GetActorLocation();
		FVector2D ToTarget = PathPoints[PathIndex] - FVector2D(Location.X, Location.Y);
		while (ToTarget.Size() < PathAcceptRadius)
		{
			if (++PathIndex >= PathPoints.Num())
			{
				StopMotion();
				return;
			}
			ToTarget = PathPoints[PathIndex] - FVector2D(Location.X, Location.Y);
		}
		Direction = FVector(ToTarget.GetSafeNormal(), 0.0);
		if (!bRotating)
		{
			const float TargetYaw = static_cast<float>(FMath::RadiansToDegrees(FMath::Atan2(ToTarget.Y, ToTarget.X)));
			const float Yaw = FMath::FixedTurn(static_cast<float>(GetActorRotation().Yaw), TargetYaw, PathTurnRate * DeltaSeconds);
			SetActorRotation(FRotator(0.0, Yaw, 0.0));
		}
	}
	else
	{
		const FRotator YawOnly(0.0, GetActorRotation().Yaw, 0.0);
		Direction = FRotationMatrix(YawOnly).GetUnitAxis(EAxis::X) * MoveDirection.X
			+ FRotationMatrix(YawOnly).GetUnitAxis(EAxis::Y) * MoveDirection.Y;
	}
	AddMovementInput(Direction.GetSafeNormal(), 1.f);

	if (Motion == EMotion::Timed)
	{
		MoveTimeLeft -= DeltaSeconds;
		if (MoveTimeLeft <= 0.f)
		{
			StopMotion();
		}
	}
}
