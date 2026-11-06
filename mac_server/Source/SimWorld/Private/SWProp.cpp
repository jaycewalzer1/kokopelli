#include "SWProp.h"

#include "Components/SceneComponent.h"
#include "Components/StaticMeshComponent.h"
#include "SWCommon.h"

namespace
{
// Street elements sit at z=20 (sidewalk top) in progen_world.json, also where no sidewalk exists.
// Extending them 20 cm below the pivot hides the gap; on a sidewalk the extra part is buried.
constexpr double ElementSinkCm = 20.0;

// Road geometry before the (0.95, 0.9, 1) node scale; see ASWRoad in SWProp.h.
constexpr double RoadScaleX = 0.95;
constexpr double RoadScaleY = 0.9;
constexpr double SegmentLengthCm = 20000.0;
constexpr double RoadHalfWidthCm = 2700.0 / RoadScaleY;   // edge at +-2700 after scale
constexpr double AsphaltHalfWidthCm = 1170.0 / RoadScaleY; // lanes at +-300, sidewalk starts at +-1170
constexpr double SidewalkHeightCm = 20.0;
constexpr double AsphaltThicknessCm = 2.0;                // top at z=+1, just above the floor
}

ASWProp::ASWProp()
{
	PrimaryActorTick.bCanEverTick = false;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	Root->SetMobility(EComponentMobility::Movable); // generate_world switches it to Static afterwards
	RootComponent = Root;
}

void ASWProp::BeginPlay()
{
	Super::BeginPlay();
	// Spawned actors already carry their final name here (SimCV passes it in the spawn params).
	const FSWPropInfo* Info = SW::FindPropInfo(GetName(), GetKind());
	bSeat = Info && Info->bSeat;
	const FVector Size = Info ? FVector(Info->SizeX, Info->SizeY, Info->SizeZ) : GetDefaultSize();
	BuildPlaceholder(Info, Size);
}

void ASWProp::BuildPlaceholder(const FSWPropInfo* Info, const FVector& Size)
{
	const ESWShape Shape = Info ? Info->Shape : ESWShape::Box;
	const FLinearColor Color = SW::CategoryColor(Info ? Info->Category : ESWPropCategory::StreetFurniture);
	const bool bSink = Shape == ESWShape::Box || Shape == ESWShape::Cylinder;
	const double Bottom = bSink ? -ElementSinkCm : 0.0;
	const double Height = Size.Z - Bottom;
	SW::AddShape(this, Root, Shape, FVector(0.0, 0.0, Bottom + Height / 2.0), FVector(Size.X, Size.Y, Height), Color, true);
}

void ASWBuilding::BuildPlaceholder(const FSWPropInfo* Info, const FVector& Size)
{
	static const TArray<FLinearColor> Facades = {
		FLinearColor(0.45f, 0.40f, 0.36f),
		FLinearColor(0.32f, 0.33f, 0.36f),
		FLinearColor(0.55f, 0.47f, 0.35f),
		FLinearColor(0.38f, 0.30f, 0.28f),
		FLinearColor(0.50f, 0.50f, 0.48f),
	};
	// Same asset, same facade colour; different assets vary so neighbours stay distinguishable.
	const FLinearColor Color = SW::PickColor(Info ? Info->Key : GetName(), Facades);
	SW::AddShape(this, Root, ESWShape::Box, FVector(0.0, 0.0, Size.Z / 2.0), Size, Color, true);
}

void ASWTree::BuildPlaceholder(const FSWPropInfo* Info, const FVector& Size)
{
	const double TrunkDiameter = FMath::Clamp(0.05 * FMath::Min(Size.X, Size.Y), 25.0, 60.0);
	const double TrunkTop = 0.45 * Size.Z;
	SW::AddShape(this, Root, ESWShape::Cylinder, FVector(0.0, 0.0, (TrunkTop - ElementSinkCm) / 2.0),
		FVector(TrunkDiameter, TrunkDiameter, TrunkTop + ElementSinkCm), FLinearColor(0.12f, 0.07f, 0.03f), true);

	// Canopy is visual only, so agents and pedestrians can walk under it.
	const FVector Canopy(0.85 * Size.X, 0.85 * Size.Y, 0.65 * Size.Z);
	SW::AddShape(this, Root, ESWShape::Sphere, FVector(0.0, 0.0, Size.Z - Canopy.Z / 2.0), Canopy,
		SW::CategoryColor(ESWPropCategory::Vegetation), false);
}

FVector ASWRoad::GetDefaultSize() const
{
	return FVector(SegmentLengthCm / RoadScaleX, 2.0 * RoadHalfWidthCm, SidewalkHeightCm);
}

void ASWRoad::BuildPlaceholder(const FSWPropInfo* Info, const FVector& Size)
{
	const double Length = Size.X;
	SW::AddShape(this, Root, ESWShape::Box, FVector(0.0, 0.0, AsphaltThicknessCm / 2.0 - 1.0),
		FVector(Length, 2.0 * AsphaltHalfWidthCm, AsphaltThicknessCm), SW::CategoryColor(ESWPropCategory::Road), true);

	// Sidewalks end one road half-width before each segment end so they don't cross the
	// perpendicular road's asphalt at an intersection.
	const double SidewalkLength = FMath::Max(0.0, (SegmentLengthCm - 2.0 * RoadHalfWidthCm * RoadScaleY) / RoadScaleX);
	const double SidewalkWidth = RoadHalfWidthCm - AsphaltHalfWidthCm;
	const double SidewalkCentre = AsphaltHalfWidthCm + SidewalkWidth / 2.0;
	for (const double Side : {-1.0, 1.0})
	{
		SW::AddShape(this, Root, ESWShape::Box, FVector(0.0, Side * SidewalkCentre, SidewalkHeightCm / 2.0),
			FVector(SidewalkLength, SidewalkWidth, SidewalkHeightCm), FLinearColor(0.35f, 0.35f, 0.33f), true);
	}
}
