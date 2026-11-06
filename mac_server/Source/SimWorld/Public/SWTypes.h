#pragma once

#include "CoreMinimal.h"

/** Engine basic shape used for a placeholder part (/Engine/BasicShapes, all 100 cm, pivot at centre). */
enum class ESWShape : uint8
{
	Box,
	Cylinder,
	Sphere,
	Cone,
};

/** Which ASWProp subclass an entry of the size table belongs to. */
enum class ESWPropKind : uint8
{
	Building,
	Tree,
	Road,
	Small,
};

/** Colour groups of simworld's ue_assets.json, used for the lit placeholder colours. */
enum class ESWPropCategory : uint8
{
	Building,
	Vegetation,
	Road,
	StreetFurniture,
	Furniture,
	Trash,
	Box,
	Can,
	Table,
	RoadBlocker,
	Scooter,
};

/** One row of the generated table in Private/SWPropTable.inl. */
struct FSWPropInfo
{
	const TCHAR* Key; // asset name without "_C", e.g. "BP_Building_64"
	ESWPropKind Kind;
	ESWShape Shape;
	ESWPropCategory Category;
	float SizeX;
	float SizeY;
	float SizeZ;
	bool bSeat;
};
