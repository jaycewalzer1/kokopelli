#include "Modules/ModuleManager.h"
#include "SimCVCommandRouter.h"
#include "SimCVModule.h"
#include "SWCommon.h"
#include "SWHumanoid.h"
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
	}
};

IMPLEMENT_PRIMARY_GAME_MODULE(FSimWorldModule, SimWorld, "SimWorld");
