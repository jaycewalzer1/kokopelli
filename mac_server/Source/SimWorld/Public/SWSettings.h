#pragma once

#include "CoreMinimal.h"
#include "Engine/DeveloperSettings.h"
#include "UObject/SoftObjectPath.h"
#include "SWSettings.generated.h"

/**
 * [/Script/SimWorld.SWSettings] in DefaultGame.ini.
 *
 * The UE5 mannequin is template content, not engine content, so it is optional: copy
 * Templates/TemplateResources/High/Characters/Content/Mannequins into Content/Characters/Mannequins
 * and point these paths at it. Left empty (or unloadable), characters use a capsule-and-shapes
 * placeholder.
 */
UCLASS(config = Game, defaultconfig, meta = (DisplayName = "SimWorld"))
class SIMWORLD_API USWSettings : public UDeveloperSettings
{
	GENERATED_BODY()

public:
	/** e.g. /Game/Characters/Mannequins/Meshes/SKM_Manny_Simple.SKM_Manny_Simple */
	UPROPERTY(config, EditAnywhere, Category = "Characters", meta = (AllowedClasses = "/Script/Engine.SkeletalMesh"))
	FSoftObjectPath CharacterMesh;

	/** e.g. /Game/Characters/Mannequins/Anims/Unarmed/ABP_Unarmed.ABP_Unarmed_C */
	UPROPERTY(config, EditAnywhere, Category = "Characters", meta = (MetaClass = "/Script/Engine.AnimInstance"))
	FSoftClassPath CharacterAnimClass;

	/** Mesh offset from the capsule centre; the mannequin wants (0, 0, -90) and yaw -90. */
	UPROPERTY(config, EditAnywhere, Category = "Characters")
	FVector CharacterMeshOffset = FVector(0.0, 0.0, -90.0);

	UPROPERTY(config, EditAnywhere, Category = "Characters")
	float CharacterMeshYaw = -90.f;
};
