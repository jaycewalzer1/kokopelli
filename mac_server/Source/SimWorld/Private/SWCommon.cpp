#include "SWCommon.h"

#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

DEFINE_LOG_CATEGORY(LogSimWorld);

namespace
{
const FSWPropInfo GPropTable[] =
{
#include "SWPropTable.inl"
};

const TCHAR* ShapePath(ESWShape Shape)
{
	switch (Shape)
	{
	case ESWShape::Cylinder: return TEXT("/Engine/BasicShapes/Cylinder.Cylinder");
	case ESWShape::Sphere: return TEXT("/Engine/BasicShapes/Sphere.Sphere");
	case ESWShape::Cone: return TEXT("/Engine/BasicShapes/Cone.Cone");
	default: return TEXT("/Engine/BasicShapes/Cube.Cube");
	}
}

const TCHAR* BaseMaterialPath = TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial");
const FName ColorParameter(TEXT("Color"));

bool IsWordChar(TCHAR Ch)
{
	return FChar::IsAlnum(Ch);
}
}

UStaticMesh* SW::GetShapeMesh(ESWShape Shape)
{
	static UStaticMesh* Meshes[4] = {nullptr, nullptr, nullptr, nullptr};
	UStaticMesh*& Mesh = Meshes[static_cast<int32>(Shape)];
	if (!Mesh)
	{
		Mesh = LoadObject<UStaticMesh>(nullptr, ShapePath(Shape));
		if (Mesh)
		{
			Mesh->AddToRoot(); // engine content, needed for the whole session
		}
		else
		{
			UE_LOG(LogSimWorld, Error, TEXT("Could not load %s (is /Engine/BasicShapes cooked?)"), ShapePath(Shape));
		}
	}
	return Mesh;
}

UMaterialInstanceDynamic* SW::MakeColorMaterial(UObject* Outer, const FLinearColor& Color)
{
	static UMaterialInterface* Base = nullptr;
	if (!Base)
	{
		Base = LoadObject<UMaterialInterface>(nullptr, BaseMaterialPath);
		if (!Base)
		{
			UE_LOG(LogSimWorld, Error, TEXT("Could not load %s"), BaseMaterialPath);
			return nullptr;
		}
		Base->AddToRoot();
	}
	UMaterialInstanceDynamic* Material = UMaterialInstanceDynamic::Create(Base, Outer);
	Material->SetVectorParameterValue(ColorParameter, Color);
	return Material;
}

void SW::SetShapeColor(UStaticMeshComponent* Shape, const FLinearColor& Color)
{
	if (!Shape)
	{
		return;
	}
	// The object_mask capture swaps materials temporarily and restores them, so look the MID up each time.
	if (UMaterialInstanceDynamic* Material = Cast<UMaterialInstanceDynamic>(Shape->GetMaterial(0)))
	{
		Material->SetVectorParameterValue(ColorParameter, Color);
	}
	else
	{
		Shape->SetMaterial(0, MakeColorMaterial(Shape, Color));
	}
}

UStaticMeshComponent* SW::AddShape(AActor* Owner, USceneComponent* Parent, ESWShape Shape, const FVector& Center,
	const FVector& Size, const FLinearColor& Color, bool bCollision)
{
	UStaticMeshComponent* Mesh = NewObject<UStaticMeshComponent>(Owner);
	Mesh->SetMobility(EComponentMobility::Movable);
	Mesh->SetupAttachment(Parent);
	Mesh->SetRelativeLocation(Center);
	Mesh->SetRelativeScale3D(Size / 100.0);
	Mesh->SetStaticMesh(GetShapeMesh(Shape));
	Mesh->SetMaterial(0, MakeColorMaterial(Mesh, Color));
	Mesh->SetCollisionProfileName(bCollision ? TEXT("BlockAllDynamic") : TEXT("NoCollision"));
	Mesh->SetGenerateOverlapEvents(false);
	Mesh->RegisterComponent();
	Owner->AddInstanceComponent(Mesh);
	return Mesh;
}

UWorld* SW::GetGameWorld()
{
	if (!GEngine)
	{
		return nullptr;
	}
	UWorld* Fallback = nullptr;
	for (const FWorldContext& Context : GEngine->GetWorldContexts())
	{
		if (Context.WorldType == EWorldType::Game || Context.WorldType == EWorldType::PIE)
		{
			return Context.World();
		}
		if (Context.WorldType == EWorldType::Editor)
		{
			Fallback = Context.World();
		}
	}
	return Fallback;
}

AActor* SW::FindActorByName(UWorld* World, const FString& Name)
{
	const FName Key(*Name, FNAME_Find);
	if (!World || Key == NAME_None)
	{
		return nullptr;
	}
	for (TActorIterator<AActor> It(World); It; ++It)
	{
		if (It->GetFName() == Key && IsValid(*It))
		{
			return *It;
		}
	}
	return nullptr;
}

float SW::DistanceToActor(const FVector& Point, const AActor* Target)
{
	const FBox Box = Target->GetComponentsBoundingBox(/*bNonColliding=*/true);
	if (!Box.IsValid)
	{
		return FVector::Dist(Point, Target->GetActorLocation());
	}
	return FMath::Sqrt(Box.ComputeSquaredDistanceToPoint(Point));
}

void SW::EnsureMovable(AActor* Actor)
{
	USceneComponent* Root = Actor ? Actor->GetRootComponent() : nullptr;
	if (Root && Root->Mobility != EComponentMobility::Movable)
	{
		Root->SetMobility(EComponentMobility::Movable);
	}
}

bool SW::ParsePoints(const FString& Text, TArray<FVector2D>& OutPoints)
{
	OutPoints.Reset();
	TArray<FString> Pieces;
	Text.TrimStartAndEnd().TrimQuotes().ParseIntoArray(Pieces, TEXT(";"));
	for (FString Piece : Pieces)
	{
		Piece.ReplaceInline(TEXT("("), TEXT(""));
		Piece.ReplaceInline(TEXT(")"), TEXT(""));
		TArray<FString> Coords;
		Piece.ParseIntoArray(Coords, TEXT(","));
		if (Coords.Num() < 2)
		{
			continue;
		}
		double XY[2] = {0.0, 0.0};
		bool bOk = true;
		for (int32 Index = 0; Index < 2; ++Index)
		{
			FString Value = Coords[Index].TrimStartAndEnd();
			int32 Equals = INDEX_NONE;
			if (Value.FindChar(TEXT('='), Equals))
			{
				Value.RightChopInline(Equals + 1);
			}
			bOk &= LexTryParseString(XY[Index], *Value);
		}
		if (bOk)
		{
			OutPoints.Emplace(XY[0], XY[1]);
		}
	}
	return OutPoints.Num() > 0;
}

FString SW::FloatString(double Value)
{
	return FString::Printf(TEXT("%f"), Value);
}

FString SW::JsonObjectString(const TArray<TPair<FString, FString>>& Fields)
{
	const TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
	for (const TPair<FString, FString>& Field : Fields)
	{
		Json->SetStringField(Field.Key, Field.Value);
	}
	FString Out;
	const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
	FJsonSerializer::Serialize(Json, Writer);
	return Out;
}

FLinearColor SW::PickColor(const FString& Name, const TArray<FLinearColor>& Palette)
{
	check(Palette.Num() > 0);
	return Palette[FCrc::StrCrc32(*Name.ToLower()) % Palette.Num()];
}

const FSWPropInfo* SW::FindPropInfo(const FString& Name, ESWPropKind Kind)
{
	const FString Lower = Name.ToLower();
	const FSWPropInfo* Best = nullptr;
	int32 BestLen = 0;
	for (const FSWPropInfo& Info : GPropTable)
	{
		if (Info.Kind != Kind)
		{
			continue;
		}
		const FString Key = FString(Info.Key).ToLower();
		if (Key.Len() <= BestLen)
		{
			continue;
		}
		// Whole-token match so "BP_Building_10" does not claim "GEN_BP_Building_101_C_3".
		for (int32 At = Lower.Find(Key); At != INDEX_NONE; At = Lower.Find(Key, ESearchCase::CaseSensitive, ESearchDir::FromStart, At + 1))
		{
			const int32 End = At + Key.Len();
			const bool bStartOk = At == 0 || !IsWordChar(Lower[At - 1]);
			const bool bEndOk = End == Lower.Len() || !IsWordChar(Lower[End]);
			if (bStartOk && bEndOk)
			{
				Best = &Info;
				BestLen = Key.Len();
				break;
			}
		}
	}
	return Best;
}

FLinearColor SW::CategoryColor(ESWPropCategory Category)
{
	// Lit placeholder colours (linear). Distinct per group; the object_mask colours are separate (vset .../color).
	switch (Category)
	{
	case ESWPropCategory::Building: return FLinearColor(0.45f, 0.40f, 0.36f);
	case ESWPropCategory::Vegetation: return FLinearColor(0.08f, 0.32f, 0.06f);
	case ESWPropCategory::Road: return FLinearColor(0.04f, 0.04f, 0.045f);
	case ESWPropCategory::StreetFurniture: return FLinearColor(0.85f, 0.65f, 0.02f);
	case ESWPropCategory::Furniture: return FLinearColor(0.45f, 0.08f, 0.06f);
	case ESWPropCategory::Trash: return FLinearColor(0.15f, 0.22f, 0.15f);
	case ESWPropCategory::Box: return FLinearColor(0.55f, 0.33f, 0.12f);
	case ESWPropCategory::Can: return FLinearColor(0.7f, 0.7f, 0.75f);
	case ESWPropCategory::Table: return FLinearColor(0.35f, 0.2f, 0.08f);
	case ESWPropCategory::RoadBlocker: return FLinearColor(0.9f, 0.3f, 0.02f);
	case ESWPropCategory::Scooter: return FLinearColor(0.05f, 0.15f, 0.7f);
	default: return FLinearColor::Gray;
	}
}
