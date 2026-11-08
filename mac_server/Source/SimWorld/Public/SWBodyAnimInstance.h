#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimInstance.h"
#include "Animation/AnimInstanceProxy.h"
#include "SWBodyAnimInstance.generated.h"

class UAnimSequence;
class ASWCharacterBase;

/**
 * What the body should be doing, written by the character (game thread) and read by the animation.
 * It lives on the character, not on the anim instance, so a mesh swap (near/far tier, SetBody) keeps the
 * walk phase and every blend weight: the new mesh continues the pose instead of restarting it.
 */
USTRUCT()
struct FSWBodyAnimState
{
	GENERATED_BODY()

	// Inputs (character -> animation)
	float Speed = 0.f;           // ground speed, cm/s
	float YawRate = 0.f;         // deg/s, signed
	bool bSitting = false;
	bool bTalking = false;
	int32 Carry = 0;             // 0 none, 1 light (right hand), 2 heavy (both hands)
	float ReachTime = -1.f;      // seconds since a PickUp started, < 0 when not reaching
	FVector ReachTarget = FVector::ZeroVector; // actor space, cm
	FName HandBone = TEXT("hand_r");

	// Outputs kept across mesh swaps (animation -> character)
	float LocoPhase = 0.f;       // 0..1 normalised cycle position of walk/run
	float TurnPhase = 0.f;
	float MoveAlpha = 0.f;
	float RunAlpha = 0.f;
	float TurnAlpha = 0.f;
	float SitAlpha = 0.f;
	float TalkAlpha = 0.f;
	float CarryAlpha = 0.f;
	float Time = 0.f;
};

/** Measured once per clip: cycle length and the ground speed its feet imply (no foot sliding at that speed). */
struct FSWClipInfo
{
	float Length = 1.f;
	float Speed = 0.f;
	bool bMeasured = false;
};

struct FSWBodyAnimProxy : public FAnimInstanceProxy
{
	FSWBodyAnimProxy() = default;
	explicit FSWBodyAnimProxy(UAnimInstance* Instance) : FAnimInstanceProxy(Instance) {}

	virtual void PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds) override;
	virtual bool Evaluate(FPoseContext& Output) override;

	FSWBodyAnimState State;
	FTransform ComponentToActor = FTransform::Identity;
	TObjectPtr<UAnimSequence> Idle;
	TObjectPtr<UAnimSequence> Walk;
	TObjectPtr<UAnimSequence> Run;
	FSWClipInfo* WalkInfo = nullptr;
	FSWClipInfo* RunInfo = nullptr;

private:
	void Sample(UAnimSequence* Sequence, float Time, FPoseContext& Out) const;
	void Measure(UAnimSequence* Sequence, FSWClipInfo& Info, const FBoneContainer& Bones) const;
};

/**
 * One shared animation for every body (city/bodies/ANIMATION.md): idle / walk / run blended by ground speed
 * with play rate matched to the clip's measured stride (no foot sliding), stepping in place while turning,
 * and procedural layers for sit, pick-up reach, carry (hands IK'd to the object) and a light talking gesture.
 * Everything is found by bone name (pelvis, spine chain up to neck_01, thigh/calf/foot, upperarm/lowerarm/hand,
 * head), which UE5 Manny/Quinn and MetaHuman bodies share, so it runs on either skeleton without an anim graph.
 */
UCLASS(Transient, Blueprintable)
class SIMWORLD_API USWBodyAnimInstance : public UAnimInstance
{
	GENERATED_BODY()

public:
	UPROPERTY(EditDefaultsOnly, Category = "Body")
	TSoftObjectPtr<UAnimSequence> IdleClip;

	UPROPERTY(EditDefaultsOnly, Category = "Body")
	TSoftObjectPtr<UAnimSequence> WalkClip;

	UPROPERTY(EditDefaultsOnly, Category = "Body")
	TSoftObjectPtr<UAnimSequence> RunClip;

	USWBodyAnimInstance();

	/** Measured clip speeds (cm/s), for logs and tests. */
	float GetWalkClipSpeed() const { return WalkInfo.Speed; }
	float GetRunClipSpeed() const { return RunInfo.Speed; }

protected:
	virtual FAnimInstanceProxy* CreateAnimInstanceProxy() override;
	virtual void DestroyAnimInstanceProxy(FAnimInstanceProxy* InProxy) override;
	virtual void NativeInitializeAnimation() override;
	virtual void NativeUpdateAnimation(float DeltaSeconds) override;

private:
	friend struct FSWBodyAnimProxy;

	UPROPERTY(Transient)
	TObjectPtr<UAnimSequence> IdleSeq;
	UPROPERTY(Transient)
	TObjectPtr<UAnimSequence> WalkSeq;
	UPROPERTY(Transient)
	TObjectPtr<UAnimSequence> RunSeq;

	FSWClipInfo WalkInfo;
	FSWClipInfo RunInfo;
	FSWBodyAnimState Snapshot;
	FTransform ComponentToActor = FTransform::Identity;
};
