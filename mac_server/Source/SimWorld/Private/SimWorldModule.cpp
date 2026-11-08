#include "Modules/ModuleManager.h"
#include "SimCVCommandRouter.h"
#include "SimCVModule.h"
#include "SWCommon.h"
#include "SWHumanoid.h"
#include "SWBodies.h"
#include "SWPedestrian.h"
#include "SWBodyTiers.h"
#include "SWPickup.h"
#include "SimCVCameraComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkinnedAsset.h"
#include "GroomAsset.h"
#include "GroomComponent.h"
#include "Materials/MaterialInterface.h"
#include "Dom/JsonObject.h"
#include "EngineUtils.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "SWUEManager.h"
#include "SWWeatherManager.h"

/*
 * Exact-key JSON replies for the vbp calls whose reply the client parses by key.
 *
 * The plugin's generic vbp names each JSON key after the UFUNCTION's output parameter. That can't
 * spell "Rayleigh Scattering Scale" (spaces), and in non-editor builds FName does not preserve
 * case, so a parameter "rotation" can come back as "Rotation" if the engine registered that
 * spelling first. These routes are registered after the plugin's, so they win (later routes are
 * matched first); they call the same C++ functions and write the keys as literal strings.
 * Other spellings of the function name (e.g. "sitdown") still reach the generic path.
 */
namespace
{
FString SuccessString(bool bValue)
{
	return bValue ? TEXT("true") : TEXT("false"); // SPEC 6.1: lower-case strings
}

template <typename T>
void AddRoute(FSimCVCommandRouter& Router, const TCHAR* Function, bool bTakesArg,
	TFunction<TArray<TPair<FString, FString>>(T* Target, const FString& Arg)> Body)
{
	const FString Template = FString::Printf(TEXT("vbp [str] %s%s"), Function, bTakesArg ? TEXT(" [str]") : TEXT(""));
	const FString FunctionName = Function;
	Router.Register(Template, [Body = MoveTemp(Body), FunctionName](const FSimCVArgs& Args)
	{
		AActor* Actor = SW::FindActorByName(SW::GetGameWorld(), Args[0]);
		if (!Actor)
		{
			return FSimCVReply::Error(FString::Printf(TEXT("Can not find actor with id '%s'"), *Args[0]));
		}
		T* Target = Cast<T>(Actor);
		if (!Target)
		{
			return FSimCVReply::Error(FString::Printf(TEXT("Can not find function '%s' on '%s'"), *FunctionName, *Actor->GetName()));
		}
		return FSimCVReply::Ok(SW::JsonObjectString(Body(Target, Args.Num() > 1 ? Args[1] : FString())));
	}, FString::Printf(TEXT("SimWorld: %s with exact JSON keys"), Function));
}

FString JsonString(const TSharedRef<FJsonObject>& Json)
{
	FString Out;
	const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer = TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Out);
	FJsonSerializer::Serialize(Json, Writer);
	return Out;
}

TArray<TSharedPtr<FJsonValue>> JsonVector(const FVector& V)
{
	return {MakeShared<FJsonValueNumber>(V.X), MakeShared<FJsonValueNumber>(V.Y), MakeShared<FJsonValueNumber>(V.Z)};
}

ASWCharacterBase* FindPerson(const FString& Name, FString& OutError)
{
	AActor* Actor = SW::FindActorByName(SW::GetGameWorld(), Name);
	ASWCharacterBase* Person = Cast<ASWCharacterBase>(Actor);
	if (!Actor)
	{
		OutError = FString::Printf(TEXT("Can not find actor with id '%s'"), *Name);
	}
	else if (!Person || (!Person->IsA<ASWHumanoid>() && !Person->IsA<ASWPedestrian>()))
	{
		OutError = FString::Printf(TEXT("'%s' has no human body"), *Name);
		Person = nullptr;
	}
	return Person;
}

void BodyFields(ASWCharacterBase* Person, const TSharedRef<FJsonObject>& Json)
{
	Json->SetStringField(TEXT("body"), Person->GetShownBodyId());
	Json->SetStringField(TEXT("tier"), Person->GetBodyTier());
	Json->SetStringField(TEXT("requested"), Person->GetRequestedBodyId());
}

/** city/bodies/PLAN.md: SetBody / GetBody, plus GetBodyDebug and vget /bodies for tests and capture sidecars. */
void RegisterBodyRoutes(FSimCVCommandRouter& Router)
{
	Router.Register(TEXT("vbp [str] SetBody [str]"), [](const FSimCVArgs& Args)
	{
		FString Error, Warning;
		ASWCharacterBase* Person = FindPerson(Args[0], Error);
		if (!Person || !Person->SetBody(Args[1], Error, Warning))
		{
			return FSimCVReply::Error(Error);
		}
		const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
		Json->SetBoolField(TEXT("ok"), true);
		BodyFields(Person, Json);
		if (!Warning.IsEmpty())
		{
			Json->SetStringField(TEXT("warning"), Warning);
		}
		if (!Person->GetPartWarnings().IsEmpty())
		{
			// Separate key: a missing groom or outfit piece is not a body fallback (the body still shows).
			Json->SetStringField(TEXT("part_warnings"), Person->GetPartWarnings());
		}
		return FSimCVReply::Ok(JsonString(Json));
	}, TEXT("Bodies: show body <id> from Bodies.json (fallback chain, then placeholder)"));

	Router.Register(TEXT("vbp [str] HoldFade [str]"), [](const FSimCVArgs& Args)
	{
		FString Error;
		ASWCharacterBase* Person = FindPerson(Args[0], Error);
		if (!Person)
		{
			return FSimCVReply::Error(Error);
		}
		Person->HoldFade(FCString::Atof(*Args[1]));
		const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
		Json->SetNumberField(TEXT("fade_hold"), Person->GetFadeHold());
		Json->SetBoolField(TEXT("fading"), Person->IsFading());
		return FSimCVReply::Ok(JsonString(Json));
	}, TEXT("Bodies (tests): pin a near/far crossfade at progress 0..1 whenever one runs; -1 releases"));

	Router.Register(TEXT("vbp [str] GetBody"), [](const FSimCVArgs& Args)
	{
		FString Error;
		ASWCharacterBase* Person = FindPerson(Args[0], Error);
		if (!Person)
		{
			return FSimCVReply::Error(Error);
		}
		const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
		BodyFields(Person, Json);
		return FSimCVReply::Ok(JsonString(Json));
	}, TEXT("Bodies: {body, tier, requested}"));

	Router.Register(TEXT("vbp [str] GetBodyDebug"), [](const FSimCVArgs& Args)
	{
		FString Error;
		ASWCharacterBase* Person = FindPerson(Args[0], Error);
		if (!Person)
		{
			return FSimCVReply::Error(Error);
		}
		const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
		BodyFields(Person, Json);
		const FSWBodyAnimState& S = Person->GetBodyAnimState();
		const FVector Feet = Person->GetActorLocation() - FVector(0.0, 0.0, 90.0);
		Json->SetNumberField(TEXT("px"), Person->GetProjectedPx());
		Json->SetBoolField(TEXT("want_near"), Person->WantsNear());
		Json->SetBoolField(TEXT("fading"), Person->IsFading());
		Json->SetNumberField(TEXT("fade"), Person->GetFadeProgress());
		Json->SetNumberField(TEXT("visible_meshes"), Person->CountVisibleBodyMeshes());
		Json->SetNumberField(TEXT("fade_hold"), Person->GetFadeHold());
		// Grooms and outfit (Bodies.json parts): one entry per component, shown body then the one fading out.
		TArray<TSharedPtr<FJsonValue>> PartList;
		for (int32 Old = 0; Old < 2; ++Old)
		{
			for (UMeshComponent* Part : Old ? Person->GetFadeBodyParts() : Person->GetBodyParts())
			{
				if (!Part)
				{
					continue;
				}
				const TSharedRef<FJsonObject> One = MakeShared<FJsonObject>();
				One->SetStringField(TEXT("name"), Part->GetName());
				One->SetStringField(TEXT("slot"), Part->ComponentTags.Num() ? Part->ComponentTags[0].ToString() : FString());
				One->SetStringField(TEXT("class"), Part->GetClass()->GetName());
				One->SetBoolField(TEXT("old"), Old != 0);
				One->SetBoolField(TEXT("visible"), Part->IsVisible());
				const USceneComponent* Parent = Part->GetAttachParent();
				One->SetStringField(TEXT("parent"), Parent == Person->GetMesh() ? TEXT("body") : Parent == Person->GetFaceMesh() ? TEXT("face")
					: Parent == Person->GetFadeMesh() ? TEXT("fade_body") : Parent == Person->GetFadeFaceMesh() ? TEXT("fade_face")
					: Parent ? *Parent->GetName() : TEXT(""));
				FString Asset;
				int32 ForcedLod = -1;
				if (const USkinnedMeshComponent* Skinned = Cast<USkinnedMeshComponent>(Part))
				{
					Asset = Skinned->GetSkinnedAsset() ? Skinned->GetSkinnedAsset()->GetPathName() : FString();
					One->SetBoolField(TEXT("follows_body"), Skinned->LeaderPoseComponent.Get() == Person->GetMesh());
				}
				else if (const UGroomComponent* Groom = Cast<UGroomComponent>(Part))
				{
					Asset = Groom->GroomAsset ? Groom->GroomAsset->GetPathName() : FString();
					ForcedLod = Groom->GetForcedLOD();
				}
				One->SetStringField(TEXT("asset"), Asset);
				One->SetNumberField(TEXT("forced_lod"), ForcedLod);
				float Fade = 1.f;
				const UMaterialInterface* Material = Part->GetNumMaterials() > 0 ? Part->GetMaterial(0) : nullptr;
				One->SetBoolField(TEXT("dither"), Material && Material->GetScalarParameterValue(FHashedMaterialParameterInfo(TEXT("BodyFade")), Fade));
				One->SetNumberField(TEXT("body_fade"), Fade);
				PartList.Add(MakeShared<FJsonValueObject>(One));
			}
		}
		Json->SetArrayField(TEXT("parts"), PartList);
		Json->SetStringField(TEXT("part_warnings"), Person->GetPartWarnings());
		Json->SetNumberField(TEXT("phase"), S.LocoPhase);
		Json->SetNumberField(TEXT("time"), S.Time);
		Json->SetNumberField(TEXT("move_alpha"), S.MoveAlpha);
		Json->SetNumberField(TEXT("sit_alpha"), S.SitAlpha);
		Json->SetNumberField(TEXT("talk_alpha"), S.TalkAlpha);
		Json->SetNumberField(TEXT("carry_alpha"), S.CarryAlpha);
		Json->SetNumberField(TEXT("height_cm"), Person->GetBodyHeightCm());
		Json->SetArrayField(TEXT("feet"), JsonVector(Feet));
		Json->SetArrayField(TEXT("eye"), JsonVector(Person->GetEyeWorldLocation()));
		Json->SetArrayField(TEXT("hand"), JsonVector(Person->GetHandWorldLocation(false)));
		Json->SetStringField(TEXT("hand_socket"), Person->GetHandSocket().ToString());
		USkeletalMeshComponent* Mesh = Person->GetMesh();
		Json->SetStringField(TEXT("mesh"), Mesh->GetSkeletalMeshAsset() ? Mesh->GetSkeletalMeshAsset()->GetPathName() : FString());
		Json->SetStringField(TEXT("anim_class"), Mesh->GetAnimClass() ? Mesh->GetAnimClass()->GetPathName() : FString());
		USkeletalMeshComponent* Face = Person->GetFaceMesh();
		Json->SetStringField(TEXT("face_mesh"), Face->GetSkeletalMeshAsset() ? Face->GetSkeletalMeshAsset()->GetPathName() : FString());
		Json->SetBoolField(TEXT("face_visible"), Face->GetSkeletalMeshAsset() && Face->IsVisible());
		Json->SetBoolField(TEXT("face_follows_body"), Face->LeaderPoseComponent.Get() == Mesh);
		Json->SetNumberField(TEXT("mesh_scale"), Mesh->GetRelativeScale3D().Z);
		if (const USWBodyAnimInstance* Anim = Cast<USWBodyAnimInstance>(Mesh->GetAnimInstance()))
		{
			Json->SetNumberField(TEXT("walk_clip_speed"), Anim->GetWalkClipSpeed());
			Json->SetNumberField(TEXT("run_clip_speed"), Anim->GetRunClipSpeed());
		}
		if (const ASWHumanoid* Agent = Cast<ASWHumanoid>(Person))
		{
			Json->SetArrayField(TEXT("camera"), JsonVector(Agent->GetCamera()->GetComponentLocation()));
			Json->SetBoolField(TEXT("camera_follows_eyes"), Agent->IsCameraFollowingEyes());
			if (const ASWPickup* Item = Agent->GetHeld())
			{
				Json->SetStringField(TEXT("held"), Item->GetName());
				Json->SetBoolField(TEXT("held_on_hand"), Agent->IsHeldOnHand());
				const USceneComponent* Root = Item->GetRootComponent();
				Json->SetStringField(TEXT("held_parent"), Root && Root->GetAttachParent() ? Root->GetAttachParent()->GetName() : FString());
				Json->SetStringField(TEXT("held_socket"), Root ? Root->GetAttachSocketName().ToString() : FString());
				Json->SetArrayField(TEXT("held_location"), JsonVector(Item->GetActorLocation()));
			}
		}
		return FSimCVReply::Ok(JsonString(Json));
	}, TEXT("Bodies: tier, projected px, fade, pose phase, eye/camera/hand positions (tests)"));

	Router.Register(TEXT("vget /bodies"), [](const FSimCVArgs&)
	{
		const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
		if (UWorld* World = SW::GetGameWorld())
		{
			for (TActorIterator<ASWCharacterBase> It(World); It; ++It)
			{
				FString Error;
				if (!FindPerson(It->GetName(), Error))
				{
					continue;
				}
				const TSharedRef<FJsonObject> One = MakeShared<FJsonObject>();
				BodyFields(*It, One);
				One->SetNumberField(TEXT("px"), It->GetProjectedPx());
				One->SetBoolField(TEXT("fading"), It->IsFading());
				Json->SetObjectField(It->GetName(), One);
			}
		}
		return FSimCVReply::Ok(JsonString(Json));
	}, TEXT("Bodies: {actor: {body, tier, requested, px, fading}} for capture sidecars"));
}

void RegisterJsonRoutes(FSimCVCommandRouter& Router)
{
	using FFields = TArray<TPair<FString, FString>>;

	AddRoute<ASWUEManager>(Router, TEXT("GetInformation"), false, [](ASWUEManager* Manager, const FString&)
	{
		return Manager->GetInformationFields();
	});

	AddRoute<ASWHumanoid>(Router, TEXT("GetCollisionNum"), false, [](ASWHumanoid* Agent, const FString&)
	{
		int32 Human = 0, Object = 0, Building = 0, Vehicle = 0;
		Agent->GetCollisionNum(Human, Object, Building, Vehicle);
		// Integer strings: the client does int() on them.
		return FFields{
			{TEXT("HumanCollision"), FString::FromInt(Human)},
			{TEXT("ObjectCollision"), FString::FromInt(Object)},
			{TEXT("BuildingCollision"), FString::FromInt(Building)},
			{TEXT("VehicleCollision"), FString::FromInt(Vehicle)},
		};
	});

	auto SuccessRoute = [&Router](const TCHAR* Function, bool bTakesArg, TFunction<void(ASWHumanoid*, const FString&, bool&)> Call)
	{
		AddRoute<ASWHumanoid>(Router, Function, bTakesArg, [Call = MoveTemp(Call)](ASWHumanoid* Agent, const FString& Arg)
		{
			bool bSuccess = false;
			Call(Agent, Arg, bSuccess);
			return FFields{{TEXT("Success"), SuccessString(bSuccess)}};
		});
	};
	SuccessRoute(TEXT("SitDown"), false, [](ASWHumanoid* Agent, const FString&, bool& bOut) { Agent->SitDown(bOut); });
	SuccessRoute(TEXT("StandUp"), false, [](ASWHumanoid* Agent, const FString&, bool& bOut) { Agent->StandUp(bOut); });
	SuccessRoute(TEXT("DropOff"), false, [](ASWHumanoid* Agent, const FString&, bool& bOut) { Agent->DropOff(bOut); });
	SuccessRoute(TEXT("PickUp"), true, [](ASWHumanoid* Agent, const FString& Arg, bool& bOut) { Agent->PickUp(Arg, bOut); });
	SuccessRoute(TEXT("EnterVehicle"), true, [](ASWHumanoid* Agent, const FString& Arg, bool& bOut) { Agent->EnterVehicle(Arg, bOut); });
	SuccessRoute(TEXT("ExitVehicle"), true, [](ASWHumanoid* Agent, const FString& Arg, bool& bOut) { Agent->ExitVehicle(Arg, bOut); });

	auto WeatherRoute = [&Router](const TCHAR* Function, FString (ASWWeatherManager::*Json)() const)
	{
		// The weather JSON is built by the manager itself; wrap it as a single pass-through.
		const FString Template = FString::Printf(TEXT("vbp [str] %s"), Function);
		Router.Register(Template, [Json](const FSimCVArgs& Args)
		{
			ASWWeatherManager* Manager = Cast<ASWWeatherManager>(SW::FindActorByName(SW::GetGameWorld(), Args[0]));
			if (!Manager)
			{
				return FSimCVReply::Error(FString::Printf(TEXT("Can not find weather manager '%s'"), *Args[0]));
			}
			return FSimCVReply::Ok((Manager->*Json)());
		}, FString::Printf(TEXT("SimWorld: %s with exact JSON keys"), Function));
	};
	WeatherRoute(TEXT("GetSunDirection"), &ASWWeatherManager::GetSunDirectionJson);
	WeatherRoute(TEXT("GetSunIntensity"), &ASWWeatherManager::GetSunIntensityJson);
	WeatherRoute(TEXT("GetFog"), &ASWWeatherManager::GetFogJson);
	WeatherRoute(TEXT("GetAtmosphere"), &ASWWeatherManager::GetAtmosphereJson);
}
}

class FSimWorldModule : public FDefaultGameModuleImpl
{
public:
	virtual void StartupModule() override
	{
		// Loads SimCV first if needed; its built-in routes are registered in its StartupModule.
		RegisterJsonRoutes(FSimCVModule::Get().GetRouter());
		RegisterBodyRoutes(FSimCVModule::Get().GetRouter());
	}
};

IMPLEMENT_PRIMARY_GAME_MODULE(FSimWorldModule, SimWorld, "SimWorld");
