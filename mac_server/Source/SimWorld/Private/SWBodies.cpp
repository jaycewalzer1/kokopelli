#include "SWBodies.h"

#include "Dom/JsonObject.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "SWCommon.h"

namespace
{
struct FRegistry
{
	bool bLoaded = false;
	FString Path;
	FString DefaultAgent;
	FString DefaultResident;
	TMap<FString, FString> Actors; // FString keys compare case-insensitively, like actor names
	TMap<FString, FSWBodyDef> Bodies;
	float NearPx = 28.f;
	float FarPx = 22.f;
	int32 MaxNear = 3;
	float FadeSeconds = 0.4f;
	float ReleaseSeconds = 30.f;
	FIntPoint Capture = FIntPoint(832, 480);
};

FRegistry GRegistry;
bool GTriedLoad = false;

FRegistry& Get()
{
	if (!GTriedLoad)
	{
		SWBodies::Load();
	}
	return GRegistry;
}

FVector ReadVector(const TSharedPtr<FJsonObject>& Obj, const TCHAR* Key, const FVector& Default)
{
	const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
	if (Obj->TryGetArrayField(Key, Values) && Values->Num() == 3)
	{
		return FVector((*Values)[0]->AsNumber(), (*Values)[1]->AsNumber(), (*Values)[2]->AsNumber());
	}
	return Default;
}

/** One part from a JSON value (object, or a plain string = skinned mesh path). False if it names no asset. */
bool ReadPart(const TSharedPtr<FJsonValue>& Value, bool bGroomList, int32 Index, FSWBodyPart& Out)
{
	FString Text;
	if (Value.IsValid() && Value->TryGetString(Text))
	{
		Out.Asset = Text;
		Out.bGroom = false;
		Out.Slot = bGroomList ? FString::Printf(TEXT("groom%d"), Index) : TEXT("outfit");
		Out.bAttachFace = false;
		return !Text.IsEmpty();
	}
	const TSharedPtr<FJsonObject>* Obj = nullptr;
	if (!Value.IsValid() || !Value->TryGetObject(Obj))
	{
		return false;
	}
	FString S;
	if ((*Obj)->TryGetStringField(TEXT("groom"), S))
	{
		Out.bGroom = true;
		Out.Asset = S;
	}
	else if ((*Obj)->TryGetStringField(TEXT("mesh"), S) || (*Obj)->TryGetStringField(TEXT("asset"), S))
	{
		Out.bGroom = false;
		Out.Asset = S;
	}
	(*Obj)->TryGetStringField(TEXT("binding"), Out.Binding);
	(*Obj)->TryGetStringField(TEXT("geometry"), Out.Geometry);
	Out.Geometry = Out.Geometry.ToLower();
	(*Obj)->TryGetStringField(TEXT("material"), Out.Material);
	if (!(*Obj)->TryGetStringField(TEXT("slot"), Out.Slot))
	{
		Out.Slot = bGroomList ? FString::Printf(TEXT("groom%d"), Index) : TEXT("outfit");
	}
	// Hair/brows/beard ride the head (face mesh); clothes ride the body.
	Out.bAttachFace = bGroomList;
	if ((*Obj)->TryGetStringField(TEXT("attach"), S))
	{
		Out.bAttachFace = S.Equals(TEXT("face"), ESearchCase::IgnoreCase);
	}
	if ((*Obj)->TryGetStringField(TEXT("socket"), S))
	{
		Out.Socket = FName(*S);
	}
	return !Out.Asset.IsEmpty();
}

void ReadParts(const TSharedPtr<FJsonObject>& Obj, const TCHAR* Key, bool bGroomList, FSWBodyDef& Def)
{
	const TArray<TSharedPtr<FJsonValue>>* List = nullptr;
	TArray<TSharedPtr<FJsonValue>> Single;
	if (!Obj->TryGetArrayField(Key, List))
	{
		const TSharedPtr<FJsonValue> One = Obj->TryGetField(Key);
		if (!One.IsValid() || One->IsNull())
		{
			return;
		}
		Single.Add(One);
		List = &Single;
	}
	for (int32 Index = 0; Index < List->Num(); ++Index)
	{
		FSWBodyPart Part;
		if (ReadPart((*List)[Index], bGroomList, Index, Part))
		{
			Def.Parts.Add(Part);
		}
		else
		{
			UE_LOG(LogSimWorld, Warning, TEXT("Bodies: body '%s' %s[%d] names no asset; ignored"), *Def.Id, Key, Index);
		}
	}
}
}

bool SWBodies::Load()
{
	GTriedLoad = true;
	FRegistry& R = GRegistry;
	R = FRegistry();

	FString Path;
	if (!FParse::Value(FCommandLine::Get(), TEXT("bodies="), Path))
	{
		Path = FPaths::Combine(FPaths::ProjectConfigDir(), TEXT("Bodies.json"));
	}
	R.Path = Path;

	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		UE_LOG(LogSimWorld, Log, TEXT("Bodies: no %s; characters use the placeholder (or SWSettings.CharacterMesh)"), *Path);
		return false;
	}
	TSharedPtr<FJsonObject> Root;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
	{
		UE_LOG(LogSimWorld, Error, TEXT("Bodies: %s is not valid JSON; characters use the placeholder"), *Path);
		return false;
	}

	Root->TryGetStringField(TEXT("default_agent"), R.DefaultAgent);
	Root->TryGetStringField(TEXT("default_resident"), R.DefaultResident);
	double Number = 0.0;
	if (Root->TryGetNumberField(TEXT("near_px"), Number)) { R.NearPx = Number; R.FarPx = Number - 6.0; }
	if (Root->TryGetNumberField(TEXT("far_px"), Number)) { R.FarPx = Number; }
	if (Root->TryGetNumberField(TEXT("max_near"), Number)) { R.MaxNear = FMath::Max(0, int32(Number)); }
	if (Root->TryGetNumberField(TEXT("fade_s"), Number)) { R.FadeSeconds = FMath::Max(0.0, Number); }
	if (Root->TryGetNumberField(TEXT("release_s"), Number)) { R.ReleaseSeconds = FMath::Max(0.0, Number); }
	const TArray<TSharedPtr<FJsonValue>>* Capture = nullptr;
	if (Root->TryGetArrayField(TEXT("capture_size"), Capture) && Capture->Num() == 2)
	{
		R.Capture = FIntPoint(FMath::Max(1, int32((*Capture)[0]->AsNumber())), FMath::Max(1, int32((*Capture)[1]->AsNumber())));
	}

	const TSharedPtr<FJsonObject>* Actors = nullptr;
	if (Root->TryGetObjectField(TEXT("actors"), Actors))
	{
		for (const auto& Pair : (*Actors)->Values)
		{
			FString Id;
			if (Pair.Value.IsValid() && Pair.Value->TryGetString(Id))
			{
				R.Actors.Add(FString(*Pair.Key), Id);
			}
		}
	}

	const TSharedPtr<FJsonObject>* Bodies = nullptr;
	if (Root->TryGetObjectField(TEXT("bodies"), Bodies))
	{
		for (const auto& Pair : (*Bodies)->Values)
		{
			const TSharedPtr<FJsonObject>* Obj = nullptr;
			if (!Pair.Value.IsValid() || !Pair.Value->TryGetObject(Obj))
			{
				continue;
			}
			FSWBodyDef Def;
			Def.Id = FString(*Pair.Key);
			FString S;
			(*Obj)->TryGetStringField(TEXT("mesh"), Def.Mesh);
			(*Obj)->TryGetStringField(TEXT("face_mesh"), Def.FaceMesh);
			(*Obj)->TryGetStringField(TEXT("anim_class"), Def.AnimClass);
			if ((*Obj)->TryGetStringField(TEXT("eye_socket"), S)) { Def.EyeSocket = FName(*S); }
			if ((*Obj)->TryGetStringField(TEXT("hand_socket"), S)) { Def.HandSocket = FName(*S); }
			if ((*Obj)->TryGetNumberField(TEXT("height_cm"), Number)) { Def.HeightCm = Number; }
			(*Obj)->TryGetStringField(TEXT("fallback"), Def.Fallback);
			(*Obj)->TryGetStringField(TEXT("far"), Def.Far);
			Def.EyeOffsetCm = ReadVector(*Obj, TEXT("eye_offset_cm"), FVector::ZeroVector);
			if ((*Obj)->TryGetNumberField(TEXT("mesh_yaw"), Number)) { Def.MeshYaw = Number; }
			(*Obj)->TryGetStringField(TEXT("material"), Def.Material);
			if ((*Obj)->TryGetStringField(TEXT("tint"), S) && S.Equals(TEXT("auto"), ESearchCase::IgnoreCase))
			{
				Def.bTint = Def.bAutoTint = true;
			}
			else if ((*Obj)->HasField(TEXT("tint")))
			{
				const FVector T = ReadVector(*Obj, TEXT("tint"), FVector::OneVector);
				Def.bTint = true;
				Def.Tint = FLinearColor(T.X, T.Y, T.Z);
			}
			ReadParts(*Obj, TEXT("grooms"), true, Def);
			ReadParts(*Obj, TEXT("outfit"), false, Def);
			if ((*Obj)->TryGetStringField(TEXT("tier"), S))
			{
				Def.bLow = S.Equals(TEXT("low"), ESearchCase::IgnoreCase) || S.Equals(TEXT("far"), ESearchCase::IgnoreCase);
			}
			R.Bodies.Add(Def.Id, Def);
		}
	}
	// A body some other body names as its "far" twin is a Low body.
	for (const auto& Pair : R.Bodies)
	{
		if (FSWBodyDef* Far = Pair.Value.Far.IsEmpty() ? nullptr : R.Bodies.Find(Pair.Value.Far))
		{
			Far->bLow = true;
		}
	}
	R.bLoaded = true;
	UE_LOG(LogSimWorld, Display, TEXT("Bodies: %d bodies, %d actor mappings from %s (near %.0f px / far %.0f px, max_near %d)"),
		R.Bodies.Num(), R.Actors.Num(), *Path, R.NearPx, R.FarPx, R.MaxNear);
	return true;
}

bool SWBodies::IsLoaded() { return Get().bLoaded; }
FString SWBodies::GetPath() { return Get().Path; }

const FSWBodyDef* SWBodies::Find(const FString& Id)
{
	return Id.IsEmpty() ? nullptr : Get().Bodies.Find(Id);
}

FString SWBodies::ChooseFor(const FString& ActorName, bool bAgent)
{
	const FRegistry& R = Get();
	if (const FString* Mapped = R.Actors.Find(ActorName))
	{
		return *Mapped;
	}
	return bAgent ? R.DefaultAgent : R.DefaultResident;
}

float SWBodies::NearPx() { return Get().NearPx; }
float SWBodies::FarPx() { return Get().FarPx; }
int32 SWBodies::MaxNear() { return Get().MaxNear; }
float SWBodies::FadeSeconds() { return Get().FadeSeconds; }
float SWBodies::ReleaseSeconds() { return Get().ReleaseSeconds; }
FIntPoint SWBodies::CaptureSize() { return Get().Capture; }
