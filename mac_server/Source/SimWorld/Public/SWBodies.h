#pragma once

#include "CoreMinimal.h"

class USkeletalMesh;

/**
 * Bodies.json (city/bodies/PLAN.md, "Interface" + "Near/far bodies, revised").
 *
 *   Config/Bodies.json, or -bodies=<path> on the command line (like -cvredirects).
 *
 * Top level: default_agent, default_resident, actors {actor name -> body id}, bodies {id -> body},
 *            near_px (28), far_px (near_px - 6), max_near (3), fade_s (0.4), release_s (30), capture_w/h (832x480).
 * Body:      mesh, face_mesh (optional, leader-posed to mesh), anim_class, eye_socket, hand_socket, height_cm, fallback, far (body id of the Low twin),
 *            optional: eye_offset_cm [fwd,right,up] (actor frame, added to the socket), mesh_yaw (-90),
 *            material (override for every slot), tint ([r,g,b] 0..1 or "auto" = per-actor colour),
 *            grooms [part...] (hair, eyebrows, beard, mustache: UGroomAsset + optional binding, or a skinned mesh
 *            for hair cards / helmets), outfit [part...] or one part (clothing skeletal meshes or Chaos outfit assets).
 * Part:      {"slot": "hair", "groom": path, "binding": path, "geometry": "strands"|"cards"|"helmet", "attach": "face"|"body",
 *             "socket": bone} or {"slot": "outfit", "mesh": path, "attach": "body", "material": override}; a plain string
 *            is a mesh path. Parts load and release with their body, follow it (leader pose / groom binding), fade
 *            with it and carry the person's one object id. A part that doesn't load is skipped with a warning. A Low
 *            body (some body's "far", or "tier": "low") never shows strands: a groom shows its first cards/helmet LOD,
 *            or is skipped.
 *
 * Game thread only.
 */
struct FSWBodyPart
{
	FString Slot;                 // hair, eyebrows, beard, mustache, outfit, ...
	bool bGroom = false;          // UGroomAsset (else a skinned asset: skeletal mesh or Chaos outfit)
	FString Asset;
	FString Binding;              // optional UGroomBindingAsset
	FString Geometry;             // grooms: strands | cards | helmet ("" = whatever the asset has)
	bool bAttachFace = false;     // grooms default to the face, outfits to the body
	FName Socket;                 // optional attach bone/socket
	FString Material;             // optional override for every slot
};

struct FSWBodyDef
{
	FString Id;
	FString Mesh;
	/** Optional second mesh drawn in the body's pose (leader pose): a MetaHuman face. Both must load or the body falls back. */
	FString FaceMesh;
	FString AnimClass;
	FName EyeSocket = TEXT("head");
	FName HandSocket = TEXT("hand_r");
	float HeightCm = 0.f; // 0 = native mesh size
	FString Fallback;
	FString Far;
	FVector EyeOffsetCm = FVector::ZeroVector;
	float MeshYaw = -90.f;
	FString Material;
	bool bTint = false;
	bool bAutoTint = false;
	FLinearColor Tint = FLinearColor::White;
	/** Hair, brows, beard (grooms) then clothes (outfit), in Bodies.json order. */
	TArray<FSWBodyPart> Parts;
	/** Far (Low) body: grooms never show strands. */
	bool bLow = false;
};

namespace SWBodies
{
	/** (Re)loads the file. Returns false (and keeps an empty registry) if it is missing or invalid. */
	bool Load();
	bool IsLoaded();
	FString GetPath();

	const FSWBodyDef* Find(const FString& Id);
	/** Body id for an actor by name: actors[name], else default_agent / default_resident. Empty if none. */
	FString ChooseFor(const FString& ActorName, bool bAgent);

	float NearPx();
	float FarPx();
	int32 MaxNear();
	float FadeSeconds();
	float ReleaseSeconds();
	FIntPoint CaptureSize();
}
