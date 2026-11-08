#include "SWBodyAnimInstance.h"

#include "Animation/AnimNodeBase.h"
#include "Animation/AnimSequence.h"
#include "Animation/AnimationPoseData.h"
#include "AnimationRuntime.h"
#include "BonePose.h"
#include "Components/SkeletalMeshComponent.h"
#include "SWCharacterBase.h"
#include "SWCommon.h"
#include "TwoBoneIK.h"

/*
 * Why a native proxy instead of an AnimGraph: the graph can't be authored reproducibly from scripts, and the
 * same code has to drive Manny/Quinn now and MetaHuman bodies later. FAnimInstanceProxy::Evaluate is the
 * engine's own "native evaluation" hook (UAnimSingleNodeInstance uses it); returning true skips the graph.
 */

namespace
{
constexpr float DefaultWalkSpeed = 150.f; // until a clip is measured
constexpr float DefaultRunSpeed = 380.f;
constexpr float ReachSeconds = 0.9f;
constexpr float SeatHeight = 45.f;

float Approach(float Value, float Target, float Seconds, float DeltaSeconds)
{
	return Seconds <= 0.f ? Target : FMath::FInterpConstantTo(Value, Target, DeltaSeconds, 1.f / Seconds);
}

FCompactPoseBoneIndex FindBone(const FBoneContainer& Bones, FName Name)
{
	const int32 Index = Name.IsNone() ? INDEX_NONE : Bones.GetPoseBoneIndexForBoneName(Name);
	return Index == INDEX_NONE ? FCompactPoseBoneIndex(INDEX_NONE) : Bones.MakeCompactPoseIndex(FMeshPoseBoneIndex(Index));
}

FName MirrorName(FName Name)
{
	FString S = Name.ToString();
	if (S.EndsWith(TEXT("_r"))) { S[S.Len() - 1] = TEXT('l'); }
	else if (S.EndsWith(TEXT("_l"))) { S[S.Len() - 1] = TEXT('r'); }
	return FName(*S);
}

using FCS = FCSPose<FCompactPose>;

void SetCS(FCS& CS, FCompactPoseBoneIndex Bone, const FTransform& T)
{
	const FBoneTransform One(Bone, T);
	CS.SafeSetCSBoneTransforms(MakeArrayView(&One, 1));
}

void RotateCS(FCS& CS, FCompactPoseBoneIndex Bone, const FQuat& Q)
{
	if (Bone.GetInt() == INDEX_NONE) { return; }
	FTransform T = CS.GetComponentSpaceTransform(Bone);
	T.SetRotation((Q * T.GetRotation()).GetNormalized());
	SetCS(CS, Bone, T);
}

/** Two-bone IK of A-B-C toward Target (component space), blended by moving the target from the current end. */
void SolveLimb(FCS& CS, FCompactPoseBoneIndex A, FCompactPoseBoneIndex B, FCompactPoseBoneIndex C,
	const FVector& Target, const FVector& Pole, float Alpha)
{
	if (Alpha <= KINDA_SMALL_NUMBER || A.GetInt() == INDEX_NONE || B.GetInt() == INDEX_NONE || C.GetInt() == INDEX_NONE)
	{
		return;
	}
	FTransform TA = CS.GetComponentSpaceTransform(A);
	FTransform TB = CS.GetComponentSpaceTransform(B);
	FTransform TC = CS.GetComponentSpaceTransform(C);
	const FQuat EndRotation = TC.GetRotation();
	const FVector Effector = FMath::Lerp(TC.GetLocation(), Target, FMath::Clamp(Alpha, 0.f, 1.f));
	AnimationCore::SolveTwoBoneIK(TA, TB, TC, Pole, Effector, false, 1.0, 1.0);
	TC.SetRotation(EndRotation); // hand/foot keeps its orientation
	SetCS(CS, A, TA);
	SetCS(CS, B, TB);
	SetCS(CS, C, TC);
}
}

// --- Anim instance (game thread) ----------------------------------------------------------------

USWBodyAnimInstance::USWBodyAnimInstance()
{
	IdleClip = TSoftObjectPtr<UAnimSequence>(FSoftObjectPath(TEXT("/Game/Characters/Mannequins/Anims/Unarmed/MM_Idle.MM_Idle")));
	WalkClip = TSoftObjectPtr<UAnimSequence>(FSoftObjectPath(TEXT("/Game/Characters/Mannequins/Anims/Unarmed/Walk/MF_Unarmed_Walk_Fwd.MF_Unarmed_Walk_Fwd")));
	RunClip = TSoftObjectPtr<UAnimSequence>(FSoftObjectPath(TEXT("/Game/Characters/Mannequins/Anims/Unarmed/Jog/MF_Unarmed_Jog_Fwd.MF_Unarmed_Jog_Fwd")));
}

FAnimInstanceProxy* USWBodyAnimInstance::CreateAnimInstanceProxy()
{
	return new FSWBodyAnimProxy(this);
}

void USWBodyAnimInstance::DestroyAnimInstanceProxy(FAnimInstanceProxy* InProxy)
{
	delete InProxy;
}

void USWBodyAnimInstance::NativeInitializeAnimation()
{
	Super::NativeInitializeAnimation();
	IdleSeq = IdleClip.LoadSynchronous();
	WalkSeq = WalkClip.LoadSynchronous();
	RunSeq = RunClip.LoadSynchronous();
	if (!IdleSeq || !WalkSeq || !RunSeq)
	{
		UE_LOG(LogSimWorld, Warning, TEXT("SWBodyAnimInstance: missing clip(s) idle=%d walk=%d run=%d; missing ones hold the reference pose"),
			IdleSeq != nullptr, WalkSeq != nullptr, RunSeq != nullptr);
	}
}

void USWBodyAnimInstance::NativeUpdateAnimation(float DeltaSeconds)
{
	Super::NativeUpdateAnimation(DeltaSeconds);
	USkeletalMeshComponent* Mesh = GetSkelMeshComponent();
	ASWCharacterBase* Character = Mesh ? Cast<ASWCharacterBase>(Mesh->GetOwner()) : nullptr;
	if (!Character)
	{
		return;
	}
	ComponentToActor = Mesh->GetRelativeTransform();
	const float Scale = ComponentToActor.GetScale3D().Z;
	FSWBodyAnimState& S = Character->GetBodyAnimState();
	const float Dt = FMath::Max(0.f, DeltaSeconds);

	// Stride-matched locomotion: the cycle advances by distance walked / distance one cycle covers.
	const float WalkSpeed = (WalkInfo.bMeasured && WalkInfo.Speed > 10.f ? WalkInfo.Speed : DefaultWalkSpeed) * Scale;
	const float RunSpeed = (RunInfo.bMeasured && RunInfo.Speed > 10.f ? RunInfo.Speed : DefaultRunSpeed) * Scale;
	const float WalkLen = WalkSeq ? WalkSeq->GetPlayLength() : 1.f;
	const float RunLen = RunSeq ? RunSeq->GetPlayLength() : 1.f;
	const float RunStart = WalkSpeed * 1.25f;
	const float RunTarget = RunSpeed > RunStart ? FMath::Clamp((S.Speed - RunStart) / (RunSpeed - RunStart), 0.f, 1.f) : 0.f;
	S.RunAlpha = Approach(S.RunAlpha, RunTarget, 0.25f, Dt);
	S.MoveAlpha = Approach(S.MoveAlpha, S.Speed > 5.f ? 1.f : 0.f, 0.15f, Dt);
	const float CycleDistance = FMath::Max(1.f, FMath::Lerp(WalkSpeed * WalkLen, RunSpeed * RunLen, S.RunAlpha));
	S.LocoPhase = FMath::Fmod(S.LocoPhase + S.Speed * Dt / CycleDistance, 1.f);

	// Turning in place: step the walk cycle at a rate set by the yaw speed.
	const bool bTurning = S.Speed < 10.f && FMath::Abs(S.YawRate) > 15.f && !S.bSitting;
	S.TurnAlpha = Approach(S.TurnAlpha, bTurning ? 0.7f : 0.f, 0.15f, Dt);
	const float TurnRate = FMath::Clamp(FMath::Abs(S.YawRate) / 90.f, 0.6f, 1.6f);
	S.TurnPhase = FMath::Fmod(S.TurnPhase + (S.TurnAlpha > 0.01f ? TurnRate * Dt / FMath::Max(0.1f, WalkLen) : 0.f), 1.f);

	S.SitAlpha = Approach(S.SitAlpha, S.bSitting ? 1.f : 0.f, 0.6f, Dt);
	S.TalkAlpha = Approach(S.TalkAlpha, S.bTalking ? 1.f : 0.f, 0.3f, Dt);
	S.CarryAlpha = Approach(S.CarryAlpha, S.Carry > 0 ? 1.f : 0.f, 0.3f, Dt);
	S.Time += Dt;
	Snapshot = S;
}

// --- Proxy (worker thread) -----------------------------------------------------------------------

void FSWBodyAnimProxy::PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds)
{
	FAnimInstanceProxy::PreUpdate(InAnimInstance, DeltaSeconds);
	USWBodyAnimInstance* Instance = CastChecked<USWBodyAnimInstance>(InAnimInstance);
	State = Instance->Snapshot;
	ComponentToActor = Instance->ComponentToActor;
	Idle = Instance->IdleSeq;
	Walk = Instance->WalkSeq;
	Run = Instance->RunSeq;
	WalkInfo = &Instance->WalkInfo;
	RunInfo = &Instance->RunInfo;
}

void FSWBodyAnimProxy::Sample(UAnimSequence* Sequence, float Time, FPoseContext& Out) const
{
	if (!Sequence)
	{
		Out.ResetToRefPose();
		return;
	}
	const float Length = FMath::Max(0.001f, Sequence->GetPlayLength());
	FAnimationPoseData Data(Out);
	Sequence->GetAnimationPose(Data, FAnimExtractContext(double(FMath::Fmod(FMath::Max(0.f, Time), Length)), false, {}, true));
	// Root lock: the capsule does the moving, so any root motion in the clip is discarded.
	const FCompactPoseBoneIndex Root(0);
	Out.Pose[Root] = Out.Pose.GetRefPose(Root);
}

void FSWBodyAnimProxy::Measure(UAnimSequence* Sequence, FSWClipInfo& Info, const FBoneContainer& Bones) const
{
	Info.bMeasured = true;
	if (!Sequence)
	{
		return;
	}
	Info.Length = FMath::Max(0.01f, Sequence->GetPlayLength());
	const FCompactPoseBoneIndex Feet[2] = {FindBone(Bones, TEXT("foot_l")), FindBone(Bones, TEXT("foot_r"))};
	if (Feet[0].GetInt() == INDEX_NONE || Feet[1].GetInt() == INDEX_NONE)
	{
		return;
	}
	constexpr int32 N = 60;
	TArray<FVector> Positions[2];
	FCompactPose Pose;
	Pose.SetBoneContainer(&Bones);
	FBlendedCurve Curve;
	UE::Anim::FStackAttributeContainer Attributes;
	for (int32 Frame = 0; Frame <= N; ++Frame)
	{
		FAnimationPoseData Data(Pose, Curve, Attributes);
		Sequence->GetAnimationPose(Data, FAnimExtractContext(double(Info.Length * Frame / N), false, {}, true));
		Pose[FCompactPoseBoneIndex(0)] = Pose.GetRefPose(FCompactPoseBoneIndex(0));
		FCS CS;
		CS.InitPose(Pose);
		for (int32 Foot = 0; Foot < 2; ++Foot)
		{
			Positions[Foot].Add(CS.GetComponentSpaceTransform(Feet[Foot]).GetLocation());
		}
	}
	// A planted foot slides backward under a root-locked body at exactly the ground speed.
	TArray<float> Speeds;
	const float Dt = Info.Length / N;
	for (int32 Foot = 0; Foot < 2; ++Foot)
	{
		float MinZ = TNumericLimits<float>::Max();
		for (const FVector& P : Positions[Foot]) { MinZ = FMath::Min(MinZ, float(P.Z)); }
		for (int32 Frame = 0; Frame < N; ++Frame)
		{
			if (Positions[Foot][Frame].Z < MinZ + 3.f && Positions[Foot][Frame + 1].Z < MinZ + 3.f)
			{
				// Horizontal speed only, so it holds whichever way the mesh faces.
				Speeds.Add(float((Positions[Foot][Frame + 1] - Positions[Foot][Frame]).Size2D()) / Dt);
			}
		}
	}
	if (Speeds.Num() > 4)
	{
		Speeds.Sort();
		Info.Speed = FMath::Max(0.f, Speeds[Speeds.Num() / 2]);
	}
	UE_LOG(LogSimWorld, Display, TEXT("Body clip %s: %.2f s, stride speed %.0f cm/s (mesh units, %d stance samples)"),
		*Sequence->GetName(), Info.Length, Info.Speed, Speeds.Num());
}

bool FSWBodyAnimProxy::Evaluate(FPoseContext& Output)
{
	const FBoneContainer& Bones = Output.Pose.GetBoneContainer();
	if (WalkInfo && !WalkInfo->bMeasured) { Measure(Walk, *WalkInfo, Bones); }
	if (RunInfo && !RunInfo->bMeasured) { Measure(Run, *RunInfo, Bones); }
	const FSWBodyAnimState& S = State;

	// 1. Clips: idle, walk/run at the shared phase, walk again as stepping-in-place for turns.
	Sample(Idle, S.Time, Output);
	if (S.MoveAlpha > 0.f || S.TurnAlpha > 0.f)
	{
		FPoseContext Loco(Output);
		const float WalkLen = Walk ? Walk->GetPlayLength() : 1.f;
		const float RunLen = Run ? Run->GetPlayLength() : 1.f;
		if (S.MoveAlpha > 0.f)
		{
			Sample(Walk, S.LocoPhase * WalkLen, Loco);
			if (S.RunAlpha > 0.f)
			{
				FPoseContext RunPose(Output);
				Sample(Run, S.LocoPhase * RunLen, RunPose);
				FPoseContext Mixed(Output);
				FAnimationPoseData MixedData(Mixed);
				FAnimationRuntime::BlendTwoPosesTogether(FAnimationPoseData(RunPose), FAnimationPoseData(Loco), S.RunAlpha, MixedData);
				Loco.Pose.CopyBonesFrom(Mixed.Pose);
			}
		}
		else
		{
			Sample(Walk, S.TurnPhase * WalkLen, Loco);
		}
		const float Weight = S.MoveAlpha > 0.f ? S.MoveAlpha : S.TurnAlpha;
		FPoseContext Mixed(Output);
		FAnimationPoseData MixedData(Mixed);
		FAnimationRuntime::BlendTwoPosesTogether(FAnimationPoseData(Loco), FAnimationPoseData(Output), Weight, MixedData);
		Output.Pose.CopyBonesFrom(Mixed.Pose);
		Output.Curve.CopyFrom(Mixed.Curve);
	}

	// 2. Procedural layers in component space. Targets are written in actor space (cm, +X forward,
	//    feet at FeetZ) and converted, so they hold for any mesh scale / yaw.
	const float ReachT = S.ReachTime >= 0.f ? FMath::Clamp(S.ReachTime / ReachSeconds, 0.f, 1.f) : 1.f;
	const float Reach = S.ReachTime >= 0.f ? FMath::Sin(PI * ReachT) : 0.f;
	if (S.SitAlpha <= 0.f && Reach <= 0.f && S.CarryAlpha <= 0.f && S.TalkAlpha <= 0.f)
	{
		return true;
	}
	const FTransform& C2A = ComponentToActor;
	auto ToCS = [&C2A](const FVector& ActorPoint) { return C2A.InverseTransformPosition(ActorPoint); };
	auto ToActor = [&C2A](const FVector& CSPoint) { return C2A.TransformPosition(CSPoint); };
	const FVector ForwardCS = C2A.InverseTransformVectorNoScale(FVector::ForwardVector).GetSafeNormal();
	const FVector RightCS = C2A.InverseTransformVectorNoScale(FVector::RightVector).GetSafeNormal();
	const FVector UpCS = C2A.InverseTransformVectorNoScale(FVector::UpVector).GetSafeNormal();
	// Sign that makes a rotation about Right tip Up toward Forward (a forward bow).
	const float BowSign = (FQuat(RightCS, 0.1).RotateVector(UpCS) | ForwardCS) > 0.0 ? 1.f : -1.f;

	const FCompactPoseBoneIndex Pelvis = FindBone(Bones, TEXT("pelvis"));
	const FCompactPoseBoneIndex Head = FindBone(Bones, TEXT("head"));
	FCompactPoseBoneIndex Neck = FindBone(Bones, TEXT("neck_01"));
	const FName HandR = S.HandBone.IsNone() ? FName(TEXT("hand_r")) : S.HandBone;
	const FName HandL = MirrorName(HandR);
	struct FLimb { FCompactPoseBoneIndex A, B, C; };
	auto MakeLimb = [&Bones](FName End)
	{
		FLimb L;
		L.C = FindBone(Bones, End);
		L.B = L.C.GetInt() != INDEX_NONE ? Bones.GetParentBoneIndex(L.C) : FCompactPoseBoneIndex(INDEX_NONE);
		L.A = L.B.GetInt() != INDEX_NONE ? Bones.GetParentBoneIndex(L.B) : FCompactPoseBoneIndex(INDEX_NONE);
		return L;
	};
	const FLimb LegL = MakeLimb(TEXT("foot_l"));
	const FLimb LegR = MakeLimb(TEXT("foot_r"));
	const FLimb ArmR = MakeLimb(HandR);
	const FLimb ArmL = MakeLimb(HandL);
	TArray<FCompactPoseBoneIndex> Spine; // pelvis (excluded) .. below the neck
	if (Neck.GetInt() != INDEX_NONE && Pelvis.GetInt() != INDEX_NONE)
	{
		for (FCompactPoseBoneIndex B = Bones.GetParentBoneIndex(Neck); B.GetInt() != INDEX_NONE && B != Pelvis; B = Bones.GetParentBoneIndex(B))
		{
			Spine.Insert(B, 0);
		}
	}

	FCS CS;
	CS.InitPose(Output.Pose);
	const FVector FootL0 = LegL.C.GetInt() != INDEX_NONE ? CS.GetComponentSpaceTransform(LegL.C).GetLocation() : FVector::ZeroVector;
	const FVector FootR0 = LegR.C.GetInt() != INDEX_NONE ? CS.GetComponentSpaceTransform(LegR.C).GetLocation() : FVector::ZeroVector;
	const float FeetZ = -90.f; // capsule half height: feet sit on the capsule bottom

	// Pelvis: down onto a 45 cm seat when sitting, into a squat when reaching.
	if (Pelvis.GetInt() != INDEX_NONE && (S.SitAlpha > 0.f || Reach > 0.f))
	{
		FTransform P = CS.GetComponentSpaceTransform(Pelvis);
		const FVector Pa = ToActor(P.GetLocation());
		const FVector Seated(Pa.X - 14.f, Pa.Y, FeetZ + SeatHeight + 10.f);
		FVector Target = FMath::Lerp(Pa, Seated, S.SitAlpha);
		Target += FVector(-10.f, 0.f, -38.f) * Reach * (1.f - S.SitAlpha);
		P.SetLocation(ToCS(Target));
		SetCS(CS, Pelvis, P);
	}
	// Spine: bow forward to reach down.
	if (Reach > 0.f && Spine.Num() > 0)
	{
		const float Angle = FMath::DegreesToRadians(60.f) * Reach * (1.f - S.SitAlpha) / Spine.Num();
		for (const FCompactPoseBoneIndex& B : Spine)
		{
			RotateCS(CS, B, FQuat(RightCS, BowSign * Angle));
		}
	}
	// Legs: feet stay planted (squat) or move forward under the knees (seated).
	if (S.SitAlpha > 0.f || Reach > 0.f)
	{
		const FVector SitShift = ToCS(FVector(36.f, 0.f, 0.f)) - ToCS(FVector::ZeroVector);
		for (const FLimb* Leg : {&LegL, &LegR})
		{
			if (Leg->C.GetInt() == INDEX_NONE) { continue; }
			const FVector Foot0 = Leg == &LegL ? FootL0 : FootR0;
			const FVector Target = Foot0 + SitShift * S.SitAlpha;
			const FVector Knee = CS.GetComponentSpaceTransform(Leg->B).GetLocation();
			SolveLimb(CS, Leg->A, Leg->B, Leg->C, Target, Knee + ForwardCS * 60.f, 1.f);
		}
	}

	// Arms. Each layer moves the hands from wherever the previous layer left them.
	const float PelvisZ = Pelvis.GetInt() != INDEX_NONE ? ToActor(CS.GetComponentSpaceTransform(Pelvis).GetLocation()).Z : FeetZ + 95.f;
	auto ArmTo = [&](const FLimb& Arm, const FVector& ActorTarget, float Side, float Alpha)
	{
		if (Arm.A.GetInt() == INDEX_NONE) { return; }
		const FVector Shoulder = ToActor(CS.GetComponentSpaceTransform(Arm.A).GetLocation());
		const FVector Pole = Shoulder + FVector(-30.f, 35.f * Side, -45.f);
		SolveLimb(CS, Arm.A, Arm.B, Arm.C, ToCS(ActorTarget), ToCS(Pole), Alpha);
	};
	const float Free = 1.f - S.CarryAlpha;
	if (S.SitAlpha > 0.f && LegL.B.GetInt() != INDEX_NONE)
	{
		// Seated, hands rest on the thighs.
		for (int32 Side = 0; Side < 2; ++Side)
		{
			const FLimb& Leg = Side == 0 ? LegR : LegL;
			const FVector Hip = ToActor(CS.GetComponentSpaceTransform(Leg.A).GetLocation());
			const FVector Knee = ToActor(CS.GetComponentSpaceTransform(Leg.B).GetLocation());
			const FVector Rest = FMath::Lerp(Hip, Knee, 0.7f) + FVector(0.f, 0.f, 9.f);
			ArmTo(Side == 0 ? ArmR : ArmL, Rest, Side == 0 ? 1.f : -1.f, S.SitAlpha * Free * (1.f - S.TalkAlpha * (Side == 0 ? 1.f : 0.5f)));
		}
	}
	if (S.TalkAlpha > 0.f)
	{
		// A light conversational gesture: right hand in front of the chest, drifting; left hand lower.
		const float W = 2.f * PI * 0.6f;
		const FVector Right(26.f, 20.f + 4.f * FMath::Sin(W * S.Time), PelvisZ + 28.f + 7.f * FMath::Sin(1.3f * W * S.Time + 1.f));
		const FVector Left(22.f, -19.f, PelvisZ + 18.f + 3.f * FMath::Sin(0.8f * W * S.Time + 2.f));
		ArmTo(ArmR, Right, 1.f, S.TalkAlpha * Free);
		ArmTo(ArmL, Left, -1.f, S.TalkAlpha * Free * 0.6f);
		RotateCS(CS, Head, FQuat(RightCS, BowSign * FMath::DegreesToRadians(3.f) * FMath::Sin(1.7f * W * S.Time) * S.TalkAlpha));
	}
	if (S.CarryAlpha > 0.f)
	{
		if (S.Carry == 2)
		{
			const FVector Box(40.f, 0.f, PelvisZ + 12.f);
			ArmTo(ArmR, Box + FVector(0.f, 24.f, 0.f), 1.f, S.CarryAlpha);
			ArmTo(ArmL, Box + FVector(0.f, -24.f, 0.f), -1.f, S.CarryAlpha);
		}
		else
		{
			ArmTo(ArmR, FVector(34.f, 16.f, PelvisZ + 22.f), 1.f, S.CarryAlpha); // forearm forward, cup at waist
		}
	}
	if (Reach > 0.f)
	{
		const FVector Item = S.ReachTarget + FVector(0.f, 0.f, 6.f);
		if (S.Carry == 2 || ReachT < 0.5f) // heavy items (and the way down) use both hands for a box
		{
			ArmTo(ArmR, Item + FVector(0.f, 20.f, 0.f), 1.f, Reach);
			ArmTo(ArmL, Item + FVector(0.f, -20.f, 0.f), -1.f, Reach * (S.Carry == 2 ? 1.f : 0.3f));
		}
		else
		{
			ArmTo(ArmR, Item, 1.f, Reach);
		}
	}

	FCS::ConvertComponentPosesToLocalPoses(MoveTemp(CS), Output.Pose);
	return true;
}
