#include "SWBodyTiers.h"

#include "Engine/StreamableManager.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "SimCVCameraComponent.h"
#include "SWBodies.h"
#include "SWCharacterBase.h"
#include "UObject/UObjectIterator.h"

FStreamableManager& USWBodyTierSubsystem::Streamable()
{
	static FStreamableManager Manager;
	return Manager;
}

bool USWBodyTierSubsystem::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
	return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

TStatId USWBodyTierSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(USWBodyTierSubsystem, STATGROUP_Tickables);
}

void USWBodyTierSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	AnnotationHandle = USimCVCameraComponent::OnAnnotationCapture.AddUObject(this, &USWBodyTierSubsystem::OnAnnotationCapture);
}

void USWBodyTierSubsystem::Deinitialize()
{
	USimCVCameraComponent::OnAnnotationCapture.Remove(AnnotationHandle);
	Super::Deinitialize();
}

void USWBodyTierSubsystem::OnAnnotationCapture(UWorld* CaptureWorld, bool bBegin, TArray<UPrimitiveComponent*>& OutHide)
{
	if (CaptureWorld != GetWorld())
	{
		return;
	}
	// Only the lit pass dithers a crossfade; depth, normals and the mask are controls and must not see speckle.
	for (TActorIterator<ASWCharacterBase> It(CaptureWorld); It; ++It)
	{
		It->SetAnnotationView(bBegin, OutHide);
	}
}

void USWBodyTierSubsystem::ReleaseLater(TSharedPtr<FStreamableHandle> Handle)
{
	if (Handle.IsValid())
	{
		Pending.Add({Handle, FPlatformTime::Seconds() + SWBodies::ReleaseSeconds()});
	}
}

void USWBodyTierSubsystem::Tick(float DeltaTime)
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return;
	}

	// Delayed releases. Wall clock, so a paused world still frees memory.
	const double Now = FPlatformTime::Seconds();
	for (int32 Index = Pending.Num() - 1; Index >= 0; --Index)
	{
		if (Now >= Pending[Index].When)
		{
			if (Pending[Index].Handle.IsValid())
			{
				Pending[Index].Handle->ReleaseHandle();
			}
			Pending.RemoveAtSwap(Index);
		}
	}

	// Active cameras.
	struct FCam
	{
		FTransform Transform;
		float Focal = 1.f;
		const AActor* Owner = nullptr;
	};
	TArray<FCam> Cams;
	const FIntPoint Size = SWBodies::CaptureSize();
	for (TObjectIterator<USimCVCameraComponent> It; It; ++It)
	{
		USimCVCameraComponent* Camera = *It;
		if (!Camera->IsRegistered() || Camera->GetWorld() != World)
		{
			continue;
		}
		if (Camera->bFollowPlayerView)
		{
			Camera->SyncToPlayerView();
		}
		FCam& Cam = Cams.AddDefaulted_GetRef();
		Cam.Transform = Camera->GetComponentTransform();
		Cam.Focal = (Size.X * 0.5f) / FMath::Tan(FMath::DegreesToRadians(FMath::Clamp(Camera->FOVAngle, 1.f, 170.f) * 0.5f));
		Cam.Owner = Camera->GetOwner();
	}

	// Projected heights, then hysteresis, then the cap (tallest first).
	struct FCandidate
	{
		ASWCharacterBase* Person;
		float Px;
		bool bWant;
	};
	TArray<FCandidate> People;
	for (TActorIterator<ASWCharacterBase> It(World); It; ++It)
	{
		ASWCharacterBase* Person = *It;
		if (!Person->HasTieredBody() || Person->IsHidden())
		{
			continue;
		}
		const float Height = Person->GetBodyHeightCm();
		const FVector Feet = Person->GetActorLocation() - FVector(0.0, 0.0, 90.0);
		const FVector Centre = Feet + FVector(0.0, 0.0, Height * 0.5f);
		float Best = 0.f;
		for (const FCam& Cam : Cams)
		{
			if (Cam.Owner == Person)
			{
				continue; // one's own eyes never see one's own body
			}
			const FVector Local = Cam.Transform.InverseTransformPositionNoScale(Centre);
			if (Local.X < 20.0)
			{
				continue; // behind or at the lens
			}
			const float Px = Height / Local.X * Cam.Focal;
			const float X = Local.Y / Local.X * Cam.Focal;
			const float Y = Local.Z / Local.X * Cam.Focal;
			if (FMath::Abs(X) > Size.X * 0.5f + Px * 0.25f || FMath::Abs(Y) > Size.Y * 0.5f + Px * 0.5f)
			{
				continue; // out of frame
			}
			Best = FMath::Max(Best, Px);
		}
		const bool bWant = Person->WantsNear() ? Best >= SWBodies::FarPx() : Best > SWBodies::NearPx();
		People.Add({Person, Best, bWant});
	}
	People.Sort([](const FCandidate& A, const FCandidate& B) { return A.Px > B.Px; });
	int32 Near = 0;
	const int32 MaxNear = SWBodies::MaxNear();
	for (FCandidate& Candidate : People)
	{
		const bool bNear = Candidate.bWant && Near < MaxNear;
		Near += bNear ? 1 : 0;
		Candidate.Person->SetTierDecision(bNear, Candidate.Px);
	}
}
