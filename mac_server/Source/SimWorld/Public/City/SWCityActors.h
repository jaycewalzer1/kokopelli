#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SWCityActors.generated.h"

class FJsonObject;
class FSWMeshBuilder;
class UInstancedStaticMeshComponent;
class UStaticMesh;
class UStaticMeshComponent;

/**
 * Solarpunk city ("Garden Village + Commons", ~/Desktop/kokopelli/city/world.json), see docs/CITY.md.
 *
 * Every class takes its world.json element via `vbp <name> Configure <json>` (the trailing FString
 * takes the rest of the line). The builder (city/ue/build_city.py) adds converted coordinates
 * (fields ending in _cm: UE X = east, Y = south, cm) plus a few derived fields. Configure may be
 * called again; it replaces the previous geometry.
 *
 * Geometry is one runtime static mesh per actor (one section per material+tint) plus instanced
 * primitives for foliage and small repeated pieces, so draw calls stay low.
 */
UCLASS(Abstract)
class SIMWORLD_API ASWCityActor : public AActor
{
	GENERATED_BODY()

public:
	ASWCityActor();

	UFUNCTION(BlueprintCallable, Category = "SimWorld|City")
	void Configure(const FString& Json);

	/** {"tris": n, "instances": n, "components": n, "ok": bool, "error": "..."} for the last Configure. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|City")
	void GetBuildInfo(FString& Info);

	/** Foliage etc. buckets: one instanced component per (prim, material, tint). */
	struct FInstanceBucket
	{
		uint8 Prim = 0;
		uint8 Mat = 0;
		FLinearColor Tint;
		bool bShadow = true;
		double CullCm = 0.0;
		TArray<FTransform> Xf;
	};
	struct FInstances
	{
		TArray<FInstanceBucket> Buckets;
		void Add(uint8 Prim, uint8 Mat, const FLinearColor& Tint, const FTransform& Xf, bool bShadow = true, double CullCm = 0.0);
	};

protected:
	/** Builds geometry from J (already parsed). Positions given to helpers are actor-local cm. */
	virtual bool Build(const TSharedPtr<FJsonObject>& J, FString& Error) { return true; }

	/** World cm -> actor local (actors are never rotated except furniture/places). */
	FVector L(double X, double Y, double Z = 0.0) const { return FVector(X, Y, Z) - Origin; }
	FVector2D L2(const FVector2D& P) const { return P - FVector2D(Origin.X, Origin.Y); }

	UStaticMeshComponent* AddMesh(const FSWMeshBuilder& B, bool bShadow = true);
	void AddInstances(const FInstances& Inst);
	void AddCollisionBox(const FVector& Min, const FVector& Max);
	void ClearBuilt();

	UPROPERTY(VisibleAnywhere, Category = "SimWorld")
	TObjectPtr<USceneComponent> Root;

	UPROPERTY(Transient)
	TArray<TObjectPtr<UActorComponent>> Built;

	FVector Origin = FVector::ZeroVector;
	int32 Tris = 0;
	int32 InstanceCount = 0;
	bool bOk = false;
	FString LastError;
	uint32 Seed = 1;
	/** JSON "gi": false keeps this actor's geometry out of Lumen's scene (far landscape: GI cost without visible benefit). */
	bool bGI = true;
};

/** Frame timing for perf checks: `vbp CITY_manager GetFrameStats`. Ticks even when paused. */
UCLASS()
class SIMWORLD_API ASWCityManager : public AActor
{
	GENERATED_BODY()

public:
	ASWCityManager();
	virtual void Tick(float DeltaSeconds) override;

	/** Averages over the frames since the last ResetFrameStats (ms) + city totals. */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|City")
	void GetFrameStats(FString& Stats);

	UFUNCTION(BlueprintCallable, Category = "SimWorld|City")
	void ResetFrameStats();

	/** Live look tuning (vibe pass): {"cloud": {"<scalar param>": v, ...}, "sun_pitch": deg, "sun_intensity": lux,
	 *  "saturation": s}. Values are not saved: bake the chosen ones into SWEnvironment.cpp. Returns the cloud
	 *  material's current values of the named params (pass {"cloud": {"Name": null}} to only read). */
	UFUNCTION(BlueprintCallable, Category = "SimWorld|City")
	void Look(const FString& Json, FString& Result);

private:
	int32 Frames = 0;
	double SumDelta = 0, SumGame = 0, SumRender = 0, SumGpu = 0, MaxDelta = 0;
};

/** Ground slabs: grass base, meadow/mulch/paving patches. {"slabs":[{"rect_cm"|"poly_cm","z0","z1","mat","tint"}]} */
UCLASS()
class SIMWORLD_API ASWCityGround : public ASWCityActor
{
	GENERATED_BODY()
protected:
	virtual bool Build(const TSharedPtr<FJsonObject>& J, FString& Error) override;
};

/** One lane: permeable stone with moss joints, kerb strips, optional water runnel down the middle. */
UCLASS()
class SIMWORLD_API ASWCityLane : public ASWCityActor
{
	GENERATED_BODY()
protected:
	virtual bool Build(const TSharedPtr<FJsonObject>& J, FString& Error) override;
};

/** Polyline path: "trail" (gravel ribbon + stone edging) or "boardwalk" (timber deck on posts with rails). */
UCLASS()
class SIMWORLD_API ASWCityPath : public ASWCityActor
{
	GENERATED_BODY()
protected:
	virtual bool Build(const TSharedPtr<FJsonObject>& J, FString& Error) override;
};

/** Water: "creek" (centerline ribbon, banks, stones, reeds), "pond" (ellipse, beach, swim dock, lilies). */
UCLASS()
class SIMWORLD_API ASWCityWater : public ASWCityActor
{
	GENERATED_BODY()
protected:
	virtual bool Build(const TSharedPtr<FJsonObject>& J, FString& Error) override;
};

/** A group of trees/shrubs: {"trees":[[x_cm,y_cm,species,scale],...]}; species names in docs/CITY.md. */
UCLASS()
class SIMWORLD_API ASWCityTrees : public ASWCityActor
{
	GENERATED_BODY()
public:
	/** Adds one procedural tree (trunk, limbs, clustered canopy) at local Base. */
	static void AddTree(FInstances& Out, const FString& Species, const FVector& Base, double Scale, uint32 Seed); // "<species>@far" = 2-instance distant tree
	static void AddShrub(FInstances& Out, const FVector& Base, double Radius, const FLinearColor& Tint, uint32 Seed, double CullCm = 0.0);
protected:
	virtual bool Build(const TSharedPtr<FJsonObject>& J, FString& Error) override;
};

/** Street furniture item by "type": lantern_post, bench, bike_rack, outdoor_gym_station, mural_wall, wayfinding_totem, water_fountain. */
UCLASS()
class SIMWORLD_API ASWStreetFurniture : public ASWCityActor
{
	GENERATED_BODY()
protected:
	virtual bool Build(const TSharedPtr<FJsonObject>& J, FString& Error) override;
};

/** Place marker dressing by category (cafe tables + umbrellas, market stalls, planters + sign...). */
UCLASS()
class SIMWORLD_API ASWCityPlace : public ASWCityActor
{
	GENERATED_BODY()
protected:
	virtual bool Build(const TSharedPtr<FJsonObject>& J, FString& Error) override;
};

/** Open spaces: courtyard, amphitheater, chess_garden, playground, village_green, plots, food_forest. */
UCLASS()
class SIMWORLD_API ASWCityOpenSpace : public ASWCityActor
{
	GENERATED_BODY()
protected:
	virtual bool Build(const TSharedPtr<FJsonObject>& J, FString& Error) override;
};

/**
 * Buildings: courtyard-block bars (stepped terraces, facade bands by material, balconies with planters
 * and cascading greenery, shopfronts with awnings, green roof + PV + canopy-walk deck + rooftop feature)
 * and the civic ones by id (market_hall, library, bathhouse, willow_school, mobility_hub, greenhouse).
 */
UCLASS()
class SIMWORLD_API ASWCityBuilding : public ASWCityActor
{
	GENERATED_BODY()
protected:
	virtual bool Build(const TSharedPtr<FJsonObject>& J, FString& Error) override;
};

/** Sky bridge at the canopy-walk level: deck, under-arch, railings, planters with cascading plants. */
UCLASS()
class SIMWORLD_API ASWSkyBridge : public ASWCityActor
{
	GENERATED_BODY()
protected:
	virtual bool Build(const TSharedPtr<FJsonObject>& J, FString& Error) override;
};

/** Canopy landing: timber stair/elevator tower with woven bamboo screen, top deck and planted roof. */
UCLASS()
class SIMWORLD_API ASWCanopyLanding : public ASWCityActor
{
	GENERATED_BODY()
protected:
	virtual bool Build(const TSharedPtr<FJsonObject>& J, FString& Error) override;
};
