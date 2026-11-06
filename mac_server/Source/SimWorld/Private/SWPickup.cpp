#include "SWPickup.h"

#include "Components/SceneComponent.h"
#include "SWCommon.h"

ASWPickup::ASWPickup()
{
	PrimaryActorTick.bCanEverTick = false;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	Root->SetMobility(EComponentMobility::Movable);
	RootComponent = Root;
}

void ASWPickup::BeginPlay()
{
	Super::BeginPlay();
	SW::AddShape(this, Root, Shape, FVector(0.0, 0.0, Size.Z / 2.0), Size, Color, true);
}

void ASWPickup::AttachToCarrier(AActor* NewCarrier, const FVector& Offset)
{
	DetachFromActor(FDetachmentTransformRules::KeepWorldTransform);
	SW::EnsureMovable(this);
	// No collision while carried, or the item would block its own carrier's capsule.
	SetActorEnableCollision(false);
	SetActorLocation(NewCarrier->GetActorTransform().TransformPosition(Offset), false, nullptr, ETeleportType::TeleportPhysics);
	SetActorRotation(NewCarrier->GetActorRotation());
	AttachToActor(NewCarrier, FAttachmentTransformRules::KeepWorldTransform);
	Carrier = NewCarrier;
}

void ASWPickup::DetachAt(const FVector& Location)
{
	DetachFromActor(FDetachmentTransformRules::KeepWorldTransform);
	SetActorLocation(Location, false, nullptr, ETeleportType::TeleportPhysics);
	SetActorEnableCollision(true);
	Carrier.Reset();
}

ASWMug::ASWMug()
{
	Size = FVector(9.0, 9.0, 11.0);
	Shape = ESWShape::Cylinder;
	Color = FLinearColor(0.8f, 0.8f, 0.75f);
}

ASWInteractableBox::ASWInteractableBox()
{
	Size = FVector(50.0, 40.0, 35.0);
	Shape = ESWShape::Box;
	Color = FLinearColor(0.55f, 0.33f, 0.12f);
	bHeavy = true;
}
