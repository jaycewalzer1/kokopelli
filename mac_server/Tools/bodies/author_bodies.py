"""Author the shared body assets headlessly (editor Python, run by author.sh). Idempotent: recreates each asset.

  /Game/Characters/Anim/M_BodyStandIn  masked material: Tint (vector), BodyFade (scalar 0..1 -> DitherTemporalAA
                                       opacity mask) for the near/far crossfade. Used by the stand-ins and the
                                       manny fallback. MetaHuman materials need the same BodyFade input (ANIMATION.md).
  /Game/Characters/Anim/M_BodyAnnotation  object_mask material for skinned meshes (SimCV SkeletalAnnotationMaterial).
  /Game/Characters/Anim/ABP_Body       template Animation Blueprint (no skeleton), parent /Script/SimWorld.SWBodyAnimInstance.
                                       The pose is built natively (FSWBodyAnimProxy::Evaluate), the graph stays empty.
  /Game/Characters/Anim/IK_Mannequin_Body  IK Rig with retarget chains on SK_Mannequin, the source side of the
                                       IK Retargeter for MetaHuman skeletons (ANIMATION.md, wave 2).
"""
import unreal

DIR = "/Game/Characters/Anim"
EAL = unreal.EditorAssetLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()
MEL = unreal.MaterialEditingLibrary


def log(msg):
    unreal.log("[BODIES] " + msg)


def fresh(name, cls, factory):
    path = f"{DIR}/{name}"
    if EAL.does_asset_exist(path):
        EAL.delete_asset(path)
    asset = AT.create_asset(name, DIR, cls, factory)
    if not asset:
        raise RuntimeError("could not create " + path)
    return asset


def material():
    m = fresh("M_BodyStandIn", unreal.Material, unreal.MaterialFactoryNew())
    m.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
    m.set_editor_property("used_with_skeletal_mesh", True)
    tint = MEL.create_material_expression(m, unreal.MaterialExpressionVectorParameter, -500, -100)
    tint.set_editor_property("parameter_name", "Tint")
    tint.set_editor_property("default_value", unreal.LinearColor(0.5, 0.5, 0.5, 1.0))
    MEL.connect_material_property(tint, "", unreal.MaterialProperty.MP_BASE_COLOR)
    rough = MEL.create_material_expression(m, unreal.MaterialExpressionConstant, -500, 100)
    rough.set_editor_property("r", 0.6)
    MEL.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    fade = MEL.create_material_expression(m, unreal.MaterialExpressionScalarParameter, -700, 300)
    fade.set_editor_property("parameter_name", "BodyFade")
    fade.set_editor_property("default_value", 1.0)
    dither = MEL.create_material_expression(m, unreal.MaterialExpressionMaterialFunctionCall, -400, 300)
    dither.set_material_function(unreal.load_asset("/Engine/Functions/Engine_MaterialFunctions02/Utility/DitherTemporalAA"))
    if not any(MEL.connect_material_expressions(fade, "", dither, name) for name in ("Alpha Threshold", "AlphaThreshold", "Alpha")):
        raise RuntimeError("DitherTemporalAA input not found")
    MEL.connect_material_property(dither, "", unreal.MaterialProperty.MP_OPACITY_MASK)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m)
    log("M_BodyStandIn ok")


def annotation():
    """object_mask material for skinned meshes and grooms: BaseColor = Color, like BasicShapeMaterial, plus the
    skeletal and hair-strands usages."""
    m = fresh("M_BodyAnnotation", unreal.Material, unreal.MaterialFactoryNew())
    m.set_editor_property("used_with_skeletal_mesh", True)
    # grooms (Bodies.json "grooms") get the same annotation material in the object mask (wave 2b)
    m.set_editor_property("used_with_hair_strands", True)
    color = MEL.create_material_expression(m, unreal.MaterialExpressionVectorParameter, -400, 0)
    color.set_editor_property("parameter_name", "Color")
    color.set_editor_property("default_value", unreal.LinearColor(1.0, 1.0, 1.0, 1.0))
    MEL.connect_material_property(color, "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m)
    log("M_BodyAnnotation ok")


def anim_blueprint():
    parent = unreal.load_class(None, "/Script/SimWorld.SWBodyAnimInstance")
    if not parent:
        raise RuntimeError("SWBodyAnimInstance not found: build the editor target first")
    f = unreal.AnimBlueprintFactory()
    f.set_editor_property("parent_class", parent)
    templ = False
    try:
        f.set_editor_property("template", True)  # skeleton-agnostic: plays on Manny and MetaHuman meshes
        templ = True
    except Exception as e:  # older engines: bind to the mannequin skeleton instead
        log(f"no template ABPs ({e}); binding to SK_Mannequin")
        f.set_editor_property("target_skeleton", unreal.load_asset("/Game/Characters/Mannequins/Meshes/SK_Mannequin"))
    abp = fresh("ABP_Body", unreal.AnimBlueprint, f)
    unreal.BlueprintEditorLibrary.compile_blueprint(abp)
    EAL.save_loaded_asset(abp)
    log(f"ABP_Body ok (template={templ})")


CHAINS = [  # (name, start, end, goal)
    ("Root", "root", "root", None),
    ("Spine", "spine_01", "spine_05", None),  # MetaHuman has 5; Manny's chain ends at spine_05 as well in UE5
    ("Neck", "neck_01", "neck_02", None),
    ("Head", "head", "head", None),
    ("LeftClavicle", "clavicle_l", "clavicle_l", None),
    ("RightClavicle", "clavicle_r", "clavicle_r", None),
    ("LeftArm", "upperarm_l", "hand_l", "hand_l"),
    ("RightArm", "upperarm_r", "hand_r", "hand_r"),
    ("LeftLeg", "thigh_l", "ball_l", "foot_l"),
    ("RightLeg", "thigh_r", "ball_r", "foot_r"),
]


def ik_rig():
    mesh = unreal.load_asset("/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple")
    rig = fresh("IK_Mannequin_Body", unreal.IKRigDefinition, unreal.IKRigDefinitionFactory())
    ctrl = unreal.IKRigController.get_controller(rig)
    ctrl.set_skeletal_mesh(mesh)
    ctrl.set_retarget_root("pelvis")
    names = {str(n) for n in [mesh.get_bone_name(i) for i in range(mesh.get_num_bones())]} if hasattr(mesh, "get_num_bones") else None
    for name, start, end, goal in CHAINS:
        if names is not None and (start not in names or end not in names):
            # Manny's spine stops at spine_05 only on the UE5 skeleton; fall back to whatever exists
            if name == "Spine":
                end = "spine_05" if "spine_05" in names else "spine_03"
            if name == "Neck" and "neck_02" not in names:
                end = "neck_01"
        goal_name = ""
        if goal:
            goal_name = str(ctrl.add_new_goal(goal + "_goal", goal))
        ctrl.add_retarget_chain(name, start, end, goal_name)
    EAL.save_loaded_asset(rig)
    log("IK_Mannequin_Body ok")


import os
for step in [s for s in (material, annotation, anim_blueprint, ik_rig) if not os.environ.get("BODIES_ONLY") or s.__name__ in os.environ["BODIES_ONLY"]]:
    try:
        step()
    except Exception as e:
        log(f"FAILED {step.__name__}: {e}")
