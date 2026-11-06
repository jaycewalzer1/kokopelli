"""Author the realism pilot's materials headlessly (city/realism/): Tools/look/realism_author.sh runs this as
UnrealEditor -run=pythonscript. Imports Tools/look/realism_tex.py's output (env RL_TEX_DIR) into /Game/Realism/Textures
and builds /Game/Realism/Materials/M_*_Real from realism_hlsl.py: WorldPosition + VertexNormalWS + TexCoord + params +
texture objects -> one Custom HLSL node -> outputs. Never touches /Game/Solarpunk. Re-runnable.
"""
import os
import sys

import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
import realism_hlsl
importlib.reload(realism_hlsl)

MEL = unreal.MaterialEditingLibrary
EAL = unreal.EditorAssetLibrary
TOOLS = unreal.AssetToolsHelpers.get_asset_tools()
TEX_DIR = os.environ.get("RL_TEX_DIR", "")
TEX_PATH = "/Game/Realism/Textures"
MAT_PATH = "/Game/Realism/Materials"
NOISE = "/Game/Solarpunk/Textures/T_SP_Noise"
ONLY = [s for s in os.environ.get("RL_ONLY", "").split(",") if s]


def log(msg):
    unreal.log_warning("[RL] " + msg)


def import_textures():
    names = sorted(f[:-4] for f in os.listdir(TEX_DIR) if f.startswith("T_R_") and f.endswith(".png"))
    tasks = []
    for name in names:
        t = unreal.AssetImportTask()
        t.filename = os.path.join(TEX_DIR, name + ".png")
        t.destination_path = TEX_PATH
        t.destination_name = name
        t.automated = True
        t.replace_existing = True
        t.save = False
        tasks.append(t)
    TOOLS.import_asset_tasks(tasks)
    for name in names:
        tex = unreal.load_asset(f"{TEX_PATH}/{name}")
        colour = name.endswith("_C")
        tex.set_editor_property("srgb", colour)
        tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_DEFAULT)
        tex.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_WORLD)
        EAL.save_loaded_asset(tex)
        log(f"texture {name} ok")


def custom_output(name, typ):
    o = unreal.CustomOutput()
    o.set_editor_property("output_name", name)
    o.set_editor_property("output_type", typ)
    return o


def custom_input(name):
    i = unreal.CustomInput()
    i.set_editor_property("input_name", name)
    return i


def build(name):
    texset, shading, two_sided, masked, wired = realism_hlsl.SPEC[name]
    code, scale_default = realism_hlsl.BODIES[name]
    path = f"{MAT_PATH}/{name}"
    if EAL.does_asset_exist(path):
        EAL.delete_asset(path)
    mat = TOOLS.create_asset(name, MAT_PATH, unreal.Material, unreal.MaterialFactoryNew())
    mat.set_editor_property("tangent_space_normal", False)
    mat.set_editor_property("two_sided", two_sided)
    mat.set_editor_property("used_with_instanced_static_meshes", True)
    if shading == "foliage":
        mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_TWO_SIDED_FOLIAGE)
    if masked:
        mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
        mat.set_editor_property("opacity_mask_clip_value", 0.35)

    X = -900

    def expr(cls, y, x=X):
        return MEL.create_material_expression(mat, cls, x, y)

    pos = expr(unreal.MaterialExpressionWorldPosition, -500)
    nrm = expr(unreal.MaterialExpressionVertexNormalWS, -400)
    uv = expr(unreal.MaterialExpressionTextureCoordinate, -300)
    tint = expr(unreal.MaterialExpressionVectorParameter, -200)
    tint.set_editor_property("parameter_name", "Tint")
    tint.set_editor_property("default_value", unreal.LinearColor(1, 1, 1, 1))
    scale = expr(unreal.MaterialExpressionScalarParameter, -100)
    scale.set_editor_property("parameter_name", "Scale")
    scale.set_editor_property("default_value", scale_default)
    steel = expr(unreal.MaterialExpressionScalarParameter, 0)
    steel.set_editor_property("parameter_name", "Steel")
    steel.set_editor_property("default_value", 0.0)
    texs = {}
    for k, (inp, path_, sampler) in enumerate([
            ("Tc", f"{TEX_PATH}/T_R_{texset}_C", unreal.MaterialSamplerType.SAMPLERTYPE_COLOR),
            ("Td", f"{TEX_PATH}/T_R_{texset}_D", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR),
            ("Tn", NOISE, unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)]):
        e = expr(unreal.MaterialExpressionTextureObject, 100 + 100 * k)
        e.set_editor_property("texture", unreal.load_asset(path_))
        e.set_editor_property("sampler_type", sampler)
        texs[inp] = e

    cust = expr(unreal.MaterialExpressionCustom, 0, -400)
    cust.set_editor_property("description", name)
    cust.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    in_names = ["P", "N", "UV", "Tint", "Scale", "Steel", "Tc", "Td", "Tn"]
    cust.set_editor_property("inputs", [custom_input(n) for n in in_names])
    F1, F3 = unreal.CustomMaterialOutputType.CMOT_FLOAT1, unreal.CustomMaterialOutputType.CMOT_FLOAT3
    cust.set_editor_property("additional_outputs", [
        custom_output("Rough", F1), custom_output("Nrm", F3), custom_output("Metal", F1),
        custom_output("SSS", F3), custom_output("Spec", F1), custom_output("Opac", F1)])
    cust.set_editor_property("code", realism_hlsl.PRELUDE + code)

    src = {"P": pos, "N": nrm, "UV": uv, "Tint": tint, "Scale": scale, "Steel": steel, **texs}
    for n in in_names:
        if not MEL.connect_material_expressions(src[n], "", cust, n):
            log(f"{name}: FAILED to connect input {n}")

    MP = unreal.MaterialProperty
    targets = {"Rough": MP.MP_ROUGHNESS, "Nrm": MP.MP_NORMAL, "Metal": MP.MP_METALLIC, "SSS": MP.MP_SUBSURFACE_COLOR,
               "Spec": MP.MP_SPECULAR, "Opac": MP.MP_OPACITY_MASK}
    if not MEL.connect_material_property(cust, "", MP.MP_BASE_COLOR):
        log(f"{name}: FAILED base colour")
    for o in wired:
        if not MEL.connect_material_property(cust, o, targets[o]):
            log(f"{name}: FAILED output {o}")

    MEL.recompile_material(mat)
    EAL.save_loaded_asset(mat)
    log(f"material {name} built")


def main():
    unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous(["/Game/Solarpunk", "/Game/Realism"], True)
    if TEX_DIR:
        import_textures()
    for name in realism_hlsl.SPEC:
        if ONLY and name not in ONLY:
            continue
        try:
            build(name)
        except Exception as e:
            log(f"{name}: EXCEPTION {e!r}")


main()
