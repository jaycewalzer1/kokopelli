#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "SWTypes.h"
#include "SWBodies.h"
#include "SWBodyAnimInstance.h"
#include "SWCharacterBase.generated.h"

class UStaticMeshComponent;
class USkeletalMesh;
class USkeletalMeshComponent;
class UMaterialInstanceDynamic;
class UMeshComponent;

/**
 * Shared walking logic for humanoids, pedestrians and the robot dog.
 *
 * A UCharacterMovementComponent keeps the capsule on the ground (gravity, steps, collision),
 * but motion commands drive it deterministically: acceleration and braking are so high that
 * the character is at full speed, or stopped, within one frame. So "walk 1 s at 200 cm/s"
 * moves ~200 cm. Commands only set state and return; Tick does the motion (SPEC 7.1).
 *
 * No controller is needed (bRunPhysicsWithNoController); EnableController adds the engine's
 * default AI controller on request, as SimWorld does for the robot dog.
 */
UCLASS(Abstract)
class SIMWORLD_API ASWCharacterBase : public ACharacter
{
	GENERATED_BODY()

public:
	ASWCharacterBase();

	virtual void Tick(float DeltaSeconds) override;

	/** Possess with (true) or release and destroy (false) the default AI controller (SPEC 2.4). */
	UFUNCTION(BlueprintCallable, Category = "SimWorld")
	void EnableController(bool bEnable);

	/** Turn by Angle degrees (signed; + is clockwise seen from above) over Duration seconds.
	 *  The third client argument repeats the sign and is ignored. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld")
	void Rotate_Angle(float Duration, float Angle, int32 Direction);

	/** Talking gesture for Seconds (<= 0 stops it). Agents and residents; see city/bodies/ANIMATION.md. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|Body")
	void SetSpeaking(float Seconds);

	// --- Bodies (city/bodies/PLAN.md) -------------------------------------------------------
	/** Shows body Id (Bodies.json). False (OutError set) only for an id Bodies.json doesn't know; an unloadable
	 *  mesh walks the fallback chain, then the placeholder, and OutWarning says so. */
	bool SetBody(const FString& Id, FString& OutError, FString& OutWarning);
	/** Id of the body actually shown ("placeholder" if none), the one asked for, and its tier. */
	FString GetShownBodyId() const;
	const FString& GetRequestedBodyId() const { return RequestedBodyId; }
	/** "near" | "far" | "fallback" | "placeholder" */
	FString GetBodyTier() const;
	bool HasBodyMesh() const { return ShownMesh != nullptr; }
	bool HasTieredBody() const;
	bool WantsNear() const { return bWantNear; }
	float GetProjectedPx() const { return ProjectedPx; }
	float GetBodyHeightCm() const;
	/** Called by USWBodyTierSubsystem each frame. */
	void SetTierDecision(bool bNear, float Px);
	/** 0..1 while a near/far crossfade runs, else 0. */
	float GetFadeProgress() const { return FadeTime >= 0.f ? FadeTime / FMath::Max(0.001f, FadeDuration) : 0.f; }
	bool IsFading() const { return FadeTime >= 0.f; }
	/** Number of body meshes currently drawn (1 normally, 2 during a crossfade). */
	int32 CountVisibleBodyMeshes() const;
	/** Annotation captures (depth, normal, object mask; SimCV OnAnnotationCapture): while bClean, a crossfade shows
	 *  exactly one whole body (the new one once fade >= 0.5, else the old one): the other set goes to OutHide (left
	 *  out of that capture only) and the winner's dither is set to fully opaque; false restores the dither. No
	 *  visibility changes, so no render state is recreated between the lit and the control captures. */
	void SetAnnotationView(bool bClean, TArray<UPrimitiveComponent*>& OutHide);
	/** Test hook: >= 0 pins the crossfade at this progress (0..1) whenever one runs; < 0 lets it run. */
	void HoldFade(float Progress) { FadeHold = Progress; }
	float GetFadeHold() const { return FadeHold; }
	/** Groom/outfit components of the shown body (Bodies.json grooms + outfit), and of the old body mid-fade. */
	const TArray<TObjectPtr<UMeshComponent>>& GetBodyParts() const { return Parts; }
	const TArray<TObjectPtr<UMeshComponent>>& GetFadeBodyParts() const { return FadeParts; }
	/** Warnings from the last time parts were built (missing asset, strands on a Low body, ...). */
	const FString& GetPartWarnings() const { return PartWarnings; }
	/** Body, face and parts of the shown body (bOld = false) or of the body fading out (true); only ones with an asset. */
	TArray<UMeshComponent*> GetBodySet(bool bOld) const;
	/** World position of the eyes: eye socket (or head) + the body's eye offset; placeholder: capsule + EyeOffset. */
	FVector GetEyeWorldLocation() const;
	FName GetHandSocket() const;
	FVector GetHandWorldLocation(bool bLeft) const;
	FSWBodyAnimState& GetBodyAnimState() { return BodyAnim; }
	USkeletalMeshComponent* GetFadeMesh() const { return FadeMesh; }
	/** MetaHuman face of the shown body (leader-posed to GetMesh()); no asset when the body has no face_mesh. */
	USkeletalMeshComponent* GetFaceMesh() const { return FaceMesh; }
	USkeletalMeshComponent* GetFadeFaceMesh() const { return FadeFaceMesh; }
	virtual bool IsAgent() const { return false; }

	float GetWalkSpeed() const { return WalkSpeed; }
	void SetWalkSpeed(float Speed);
	bool IsMoving() const { return Motion != EMotion::Idle; }

protected:
	enum class EMotion : uint8
	{
		Idle,
		Continuous, // until stopped
		Timed,      // for MoveTimeLeft seconds
		Path,       // through PathPoints, then stop
	};

	virtual void BeginPlay() override;
	virtual void Destroyed() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

	/** Hook after the shown body changes (cameras hide it, held items re-seat). */
	virtual void OnBodyChanged() {}

	/** Walk along LocalDirection (x = forward, y = right) until StopMotion. */
	void StartContinuousMove(const FVector2D& LocalDirection = FVector2D(1.0, 0.0));
	void StartTimedMove(const FVector2D& LocalDirection, float Duration);
	/** Walk the stored PathPoints in order, facing each one. */
	bool StartPath();
	void StopMotion();
	void StartRotation(float Duration, float Angle);
	/** Parses "x,y;x,y" into PathPoints. */
	bool SetPathFromString(const FString& Points);

	/** Movement commands are ignored while this is false (sitting, in a vehicle, gesturing). */
	virtual bool CanMove() const { return true; }

	/**
	 * Human look shared by agents and pedestrians: the configured skeletal mesh (USWSettings), or
	 * a placeholder of body, head and a nose that shows the facing direction.
	 */
	void BuildHumanBody(const FLinearColor& Clothes);

	/** Adds a visible placeholder part attached to the capsule (no collision; the capsule collides). */
	UStaticMeshComponent* AddBodyPart(ESWShape Shape, const FVector& Center, const FVector& Size, const FLinearColor& Color);
	/** Placeholder parts, removed when a body mesh is shown. */
	UPROPERTY(Transient)
	TArray<TObjectPtr<UStaticMeshComponent>> BodyParts;

	/** Old body drawn in the new body's pose (leader pose) while it dithers out. */
	UPROPERTY(VisibleAnywhere, Category = "SimWorld")
	TObjectPtr<USkeletalMeshComponent> FadeMesh;

	/** Face of the shown body (Bodies.json face_mesh), attached to the body mesh, leader pose = body. */
	UPROPERTY(VisibleAnywhere, Category = "SimWorld")
	TObjectPtr<USkeletalMeshComponent> FaceMesh;

	/** Face of the old body while it dithers out (attached to FadeMesh, posed by the new body). */
	UPROPERTY(VisibleAnywhere, Category = "SimWorld")
	TObjectPtr<USkeletalMeshComponent> FadeFaceMesh;

	/** Grooms and outfit of the shown body, attached to GetMesh() / FaceMesh. */
	UPROPERTY(Transient)
	TArray<TObjectPtr<UMeshComponent>> Parts;

	/** Grooms and outfit of the old body while it dithers out (re-attached to FadeMesh / FadeFaceMesh). */
	UPROPERTY(Transient)
	TArray<TObjectPtr<UMeshComponent>> FadeParts;

	FSWBodyAnimState BodyAnim;
	float SpeakTimeLeft = 0.f;
	bool bGestureTalking = false;

	float WalkSpeed = 150.f;
	/** Fraction of a commanded rotation's duration actually used, so the client's equal sleep always sees the final yaw. */
	static constexpr float RotationTimeFraction = 0.75f;
	static constexpr float PathAcceptRadius = 30.f;
	static constexpr float PathTurnRate = 540.f; // deg/s while following a path

private:
	struct FResolved
	{
		const FSWBodyDef* Def = nullptr;
		USkeletalMesh* Mesh = nullptr;
		USkeletalMesh* Face = nullptr;
		FString Tier;
		TSharedPtr<struct FStreamableHandle> Handle;
	};
	/** Def's mesh, else its fallback chain (sync loads). Tier "fallback" if not Def itself. */
	FResolved ResolveChain(const FSWBodyDef* Def, const FString& TierIfFirst, FString& OutWarning);
	void ShowBody(const FResolved& Body);
	void ShowPlaceholder();
	void UpdateTier(float DeltaSeconds);
	void UpdateFade(float DeltaSeconds);
	/** Shows the shown (bOld false) or old (true) body set at Visibility 0..1: dithered where the materials have
	 *  BodyFade, else a clean cut (the new set wins at >= 0.5, the old one at > 0.5, so exactly one shows). */
	void ApplyFade(bool bOld, float Visibility);
	void SetupBodyMaterials(USkeletalMeshComponent* Mesh, const FSWBodyDef* Def);
	/** Creates Def's groom/outfit components on the shown body (GetMesh()/FaceMesh); skips (and notes) any that fail. */
	void BuildParts(const FSWBodyDef* Def);
	void DestroyParts(TArray<TObjectPtr<UMeshComponent>>& List);

	FLinearColor PlaceholderColor = FLinearColor::Gray;
	FString RequestedBodyId;
	const FSWBodyDef* ShownDef = nullptr;
	FString ShownTier;
	UPROPERTY(Transient)
	TObjectPtr<USkeletalMesh> ShownMesh;
	UPROPERTY(Transient)
	TObjectPtr<USkeletalMesh> ShownFace;
	/** Loads Def's mesh (+ face) from a handle; false if any of them is missing. */
	static bool TakeLoaded(const FSWBodyDef* Def, const TSharedPtr<struct FStreamableHandle>& Handle, FResolved& Out);
	static TArray<FSoftObjectPath> BodyPaths(const FSWBodyDef* Def);
	void ClearFadeMeshes();
	TSharedPtr<struct FStreamableHandle> ShownHandle;
	TSharedPtr<struct FStreamableHandle> NearHandle; // async request for the near (High) mesh
	FString NearHandlePath;
	bool bWantNear = false;
	bool bShowingNear = true;
	float ProjectedPx = 0.f;
	float FadeTime = -1.f;
	float FadeDuration = 0.4f;
	float FadeHold = -1.f;
	FString PartWarnings;
	double LastYaw = 0.0;
	bool bHaveLastYaw = false;

	EMotion Motion = EMotion::Idle;
	FVector2D MoveDirection = FVector2D(1.0, 0.0);
	float MoveTimeLeft = 0.f;

	TArray<FVector2D> PathPoints;
	int32 PathIndex = 0;

	bool bRotating = false;
	double RotationStartYaw = 0.0;
	double RotationAngle = 0.0;
	float RotationElapsed = 0.f;
	float RotationDuration = 0.f;
};
