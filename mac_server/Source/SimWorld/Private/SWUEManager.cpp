#include "SWUEManager.h"

#include "Components/SceneComponent.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "SWCommon.h"
#include "SWPedestrian.h"
#include "SWTrafficLight.h"
#include "SWVehicle.h"

namespace
{
// Client naming (communicator.py get_*_name).
const TCHAR* VehiclePrefix = TEXT("GEN_BP_Vehicle_");
const TCHAR* PedestrianPrefix = TEXT("GEN_BP_Pedestrian_");
const TCHAR* SignalPrefix = TEXT("GEN_BP_TrafficSignal_");
const TCHAR* AgentPrefix = TEXT("GEN_BP_Humanoid_");
const TCHAR* ScooterPrefix = TEXT("GEN_BP_Scooter_");

void AppendEntry(FString& Out, const FString& Entry)
{
	if (!Out.IsEmpty())
	{
		Out += TEXT("\n");
	}
	Out += Entry;
}

/** "name,a,b,..." entries split on ';' and ','. */
TArray<TArray<FString>> SplitEntries(const FString& Text)
{
	TArray<FString> Entries;
	Text.TrimStartAndEnd().TrimQuotes().ParseIntoArray(Entries, TEXT(";"));
	TArray<TArray<FString>> Out;
	for (const FString& Entry : Entries)
	{
		TArray<FString> Fields;
		Entry.ParseIntoArray(Fields, TEXT(","));
		for (FString& Field : Fields)
		{
			Field.TrimStartAndEndInline();
		}
		if (Fields.Num() > 0)
		{
			Out.Add(MoveTemp(Fields));
		}
	}
	return Out;
}

bool ParseFloat(const FString& Text, float& Out)
{
	return LexTryParseString(Out, *Text);
}

/** One scan: name -> actor for names starting with Prefix. */
TMap<FName, AActor*> ActorsWithPrefix(UWorld* World, const TCHAR* Prefix)
{
	TMap<FName, AActor*> Found;
	for (TActorIterator<AActor> It(World); It; ++It)
	{
		if (It->GetName().StartsWith(Prefix, ESearchCase::IgnoreCase))
		{
			Found.Add(It->GetFName(), *It);
		}
	}
	return Found;
}
}

ASWUEManager::ASWUEManager()
{
	PrimaryActorTick.bCanEverTick = false;
	RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	SetHidden(true); // logic-only actor
}

TArray<TPair<FString, FString>> ASWUEManager::GetInformationFields() const
{
	FString Loc[4]; // vehicles, pedestrians, agents, scooters
	FString Rot[4];
	FString LStates;
	const TCHAR* Prefixes[4] = {VehiclePrefix, PedestrianPrefix, AgentPrefix, ScooterPrefix};

	for (TActorIterator<AActor> It(GetWorld()); It; ++It)
	{
		AActor* Actor = *It;
		const FString Name = Actor->GetName();
		if (!Name.StartsWith(TEXT("GEN_BP_"), ESearchCase::IgnoreCase))
		{
			continue;
		}
		if (Name.StartsWith(SignalPrefix, ESearchCase::IgnoreCase))
		{
			if (const ASWTrafficLight* Light = Cast<ASWTrafficLight>(Actor))
			{
				// Client regex: name(true|false)(true|false)(\d+\.\d+), so the time needs its decimal point.
				AppendEntry(LStates, FString::Printf(TEXT("%s%s%s%s"), *Name,
					Light->IsVehicleGreen() ? TEXT("true") : TEXT("false"),
					Light->IsPedestrianWalk() ? TEXT("true") : TEXT("false"),
					*SW::FloatString(Light->GetLeftTime())));
			}
			continue;
		}
		for (int32 Group = 0; Group < 4; ++Group)
		{
			if (Name.StartsWith(Prefixes[Group], ESearchCase::IgnoreCase))
			{
				AppendEntry(Loc[Group], Name + Actor->GetActorLocation().ToString());
				AppendEntry(Rot[Group], Name + Actor->GetActorRotation().ToString());
				break;
			}
		}
	}

	return {
		{TEXT("VLocations"), Loc[0]}, {TEXT("VRotations"), Rot[0]},
		{TEXT("PLocations"), Loc[1]}, {TEXT("PRotations"), Rot[1]},
		{TEXT("LStates"), LStates},
		{TEXT("ALocations"), Loc[2]}, {TEXT("ARotations"), Rot[2]},
		{TEXT("SLocations"), Loc[3]}, {TEXT("SRotations"), Rot[3]},
	};
}

void ASWUEManager::GetInformation(FString& VLocations, FString& VRotations, FString& PLocations, FString& PRotations, FString& LStates,
	FString& ALocations, FString& ARotations, FString& SLocations, FString& SRotations) const
{
	const TArray<TPair<FString, FString>> Fields = GetInformationFields();
	FString* Outs[9] = {&VLocations, &VRotations, &PLocations, &PRotations, &LStates, &ALocations, &ARotations, &SLocations, &SRotations};
	for (int32 Index = 0; Index < 9; ++Index)
	{
		*Outs[Index] = Fields[Index].Value;
	}
}

void ASWUEManager::UpdateObjects()
{
}

void ASWUEManager::VSetState(const FString& States)
{
	const TArray<TArray<FString>> Entries = SplitEntries(States);
	if (Entries.Num() == 0)
	{
		return;
	}
	// Vehicles and scooters are both ASWVehicle; one scan serves the whole batch.
	TMap<FName, AActor*> Candidates = ActorsWithPrefix(GetWorld(), TEXT("GEN_BP_"));
	for (const TArray<FString>& Fields : Entries)
	{
		float Throttle = 0.f, Brake = 0.f, Steering = 0.f;
		if (Fields.Num() < 4 || !ParseFloat(Fields[1], Throttle) || !ParseFloat(Fields[2], Brake) || !ParseFloat(Fields[3], Steering))
		{
			continue;
		}
		AActor** Found = Candidates.Find(FName(*Fields[0], FNAME_Find));
		ASWVehicle* Vehicle = Found ? Cast<ASWVehicle>(*Found) : Cast<ASWVehicle>(SW::FindActorByName(GetWorld(), Fields[0]));
		if (Vehicle)
		{
			Vehicle->SetState(Throttle, Brake, Steering);
		}
	}
}

void ASWUEManager::PSetState(const FString& States)
{
	for (const TArray<FString>& Fields : SplitEntries(States))
	{
		float State = 0.f;
		ASWPedestrian* Pedestrian = Fields.Num() >= 2 && ParseFloat(Fields[1], State)
			? Cast<ASWPedestrian>(SW::FindActorByName(GetWorld(), Fields[0]))
			: nullptr;
		if (!Pedestrian)
		{
			continue;
		}
		if (State == 0.f)
		{
			Pedestrian->StopPedestrian();
			continue;
		}
		if (State != 1.f)
		{
			Pedestrian->SetMaxSpeed(FMath::Abs(State));
		}
		Pedestrian->MoveForward();
	}
}
