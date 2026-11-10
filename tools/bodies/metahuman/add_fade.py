"""Give every master material the assembled bodies use a dithered fade, for the near/far crossfade.

    tools/bodies/metahuman/run_editor_gui.sh tools/bodies/metahuman/add_fade.py out/bodies/add_fade.log

Each base Material reached from a body blueprint under /Game/Characters/Bodies gets a scalar parameter
`BodyFade` (default 1 = fully visible, 0 = gone)  (plain parameter; agent B's server sets it with
SetScalarParameterValueOnMaterials, i.e. dynamic material instances; USE_CPD switches it to Custom Primitive Data
index 0 instead, which avoids the instances):

Opaque materials become Masked with OpacityMask = DitherTemporalAA(BodyFade); already-masked ones get
their mask multiplied by it; translucent ones get Opacity multiplied by BodyFade. Idempotent (skips
materials that already have the parameter). Only the copies in /Game/Characters/Bodies/Common are edited,
never the plugin's originals.
"""
import json
import os
import traceback

import unreal

ROOT = '/Game/Characters/Bodies'
OUT = os.path.expanduser('~/Desktop/kokopelli/out/bodies/make')
MEL = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
R = {'edited': [], 'skipped': [], 'errors': []}


def log(m):
    unreal.log_warning(f'[MH] {m}')


def base_materials():
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    opts = unreal.AssetRegistryDependencyOptions(include_soft_package_references=False, include_hard_package_references=True)
    bps = [a.split('.')[0] for a in eal.list_assets(ROOT, recursive=True) if a.rsplit('/', 1)[-1].startswith('BP_')]
    seen, todo, mats = set(), list(bps), set()
    while todo:
        p = todo.pop()
        if p in seen or not p.startswith('/Game'):
            continue
        seen.add(p)
        todo += [str(d) for d in (ar.get_dependencies(p, opts) or [])]
        for ad in ar.get_assets_by_package_name(p):
            if str(ad.asset_class_path.asset_name) == 'Material':
                mats.add(str(ad.package_name))
    return sorted(m for m in mats if m.startswith(ROOT))


# Agent B's server sets the value with SetScalarParameterValueOnMaterials (dynamic material instances), which a
# custom-primitive-data parameter would ignore, so CPD is off. Flip to True if the server switches to CPD.
USE_CPD = False


def fix_existing(mat):
    changed = False
    for e in MEL.get_material_expressions(mat):
        if isinstance(e, unreal.MaterialExpressionScalarParameter) and str(e.get_editor_property('parameter_name')) == 'BodyFade':
            if e.get_editor_property('use_custom_primitive_data') != USE_CPD:
                e.set_editor_property('use_custom_primitive_data', USE_CPD)
                changed = True
    if changed:
        MEL.recompile_material(mat)
        eal.save_loaded_asset(mat)
    return changed


def has_fade(mat):
    return any(isinstance(e, unreal.MaterialExpressionScalarParameter) and str(e.get_editor_property('parameter_name')) == 'BodyFade'
               for e in MEL.get_material_expressions(mat) if e) if hasattr(MEL, 'get_material_expressions') else False


DITHER_FN = '/Engine/Functions/Engine_MaterialFunctions02/Utility/DitherTemporalAA.DitherTemporalAA'


def dither(mat):
    d = MEL.create_material_expression(mat, unreal.MaterialExpressionMaterialFunctionCall, -700, 900)
    d.set_editor_property('material_function', unreal.load_asset(DITHER_FN))
    return d


def fade_param(mat):
    for e in MEL.get_material_expressions(mat):
        if isinstance(e, unreal.MaterialExpressionScalarParameter) and str(e.get_editor_property('parameter_name')) == 'BodyFade':
            return e
    return None


ATTR_TAG = 'BodyFade attributes'


def out_name(mat, prop):
    f = getattr(MEL, 'get_material_property_input_node_output_name', None)
    return f(mat, prop) if f else ''


def add_attribute_fade(mat, p):
    """Materials that use Material Attributes ignore the plain OpacityMask pin. Re-make the attributes:
    Break(old) -> Make(..., OpacityMask = old.OpacityMask * Dither(BodyFade)) -> MaterialAttributes."""
    if any(isinstance(e, unreal.MaterialExpressionMakeMaterialAttributes) and e.get_editor_property('desc') == ATTR_TAG
           for e in MEL.get_material_expressions(mat)):
        return False
    old = MEL.get_material_property_input_node(mat, unreal.MaterialProperty.MP_MATERIAL_ATTRIBUTES)
    if not old:
        return False
    old_out = out_name(mat, unreal.MaterialProperty.MP_MATERIAL_ATTRIBUTES)
    brk = MEL.create_material_expression(mat, unreal.MaterialExpressionBreakMaterialAttributes, -400, 1200)
    MEL.connect_material_expressions(old, old_out, brk, 'Attr')
    mk = MEL.create_material_expression(mat, unreal.MaterialExpressionMakeMaterialAttributes, -100, 1200)
    mk.set_editor_property('desc', ATTR_TAG)
    pins = ['BaseColor', 'Metallic', 'Specular', 'Roughness', 'Anisotropy', 'EmissiveColor', 'Opacity', 'Normal',
            'Tangent', 'WorldPositionOffset', 'SubsurfaceColor', 'ClearCoat', 'ClearCoatRoughness', 'AmbientOcclusion',
            'Refraction', 'CustomizedUVs0', 'CustomizedUVs1', 'CustomizedUVs2', 'CustomizedUVs3', 'CustomizedUVs4',
            'CustomizedUVs5', 'CustomizedUVs6', 'CustomizedUVs7', 'PixelDepthOffset', 'ShadingModel', 'Displacement']
    missed = []
    for pin in pins:
        if not MEL.connect_material_expressions(brk, pin, mk, pin):
            missed.append(pin)
    d = dither(mat)
    MEL.connect_material_expressions(p, '', d, 'Alpha Threshold')
    mul = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, -250, 1400)
    MEL.connect_material_expressions(brk, 'OpacityMask', mul, 'A')
    MEL.connect_material_expressions(d, '', mul, 'B')
    MEL.connect_material_expressions(mul, '', mk, 'OpacityMask')
    MEL.connect_material_property(mk, '', unreal.MaterialProperty.MP_MATERIAL_ATTRIBUTES)
    if mat.get_editor_property('blend_mode') == unreal.BlendMode.BLEND_OPAQUE:
        mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_MASKED)
    R.setdefault('attribute_pins_missed', {})[mat.get_path_name()] = missed
    return True


def add(mat):
    if has_fade(mat):
        fixed = fix_existing(mat)
        attr = False
        if mat.get_editor_property('use_material_attributes') and mat.get_editor_property('blend_mode') != unreal.BlendMode.BLEND_TRANSLUCENT:
            attr = add_attribute_fade(mat, fade_param(mat))
            if attr:
                MEL.recompile_material(mat)
                eal.save_loaded_asset(mat)
                log(f'fade attributes: {mat.get_path_name()}')
        R['skipped'].append((mat.get_path_name(), f'already has BodyFade; cpd fixed={fixed}; attributes added={attr}'))
        return
    p = MEL.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -900, 900)
    p.set_editor_property('parameter_name', 'BodyFade')
    p.set_editor_property('default_value', 1.0)
    p.set_editor_property('use_custom_primitive_data', USE_CPD)
    blend = mat.get_editor_property('blend_mode')
    if blend == unreal.BlendMode.BLEND_OPAQUE:
        d = dither(mat)
        MEL.connect_material_expressions(p, '', d, 'Alpha Threshold')
        mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_MASKED)
        MEL.connect_material_property(d, '', unreal.MaterialProperty.MP_OPACITY_MASK)
        kind = 'opaque->masked'
    elif blend == unreal.BlendMode.BLEND_MASKED:
        old = MEL.get_material_property_input_node(mat, unreal.MaterialProperty.MP_OPACITY_MASK)
        d = dither(mat)
        MEL.connect_material_expressions(p, '', d, 'Alpha Threshold')
        if old:
            m = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, -500, 900)
            MEL.connect_material_expressions(old, MEL.get_material_property_input_node_output_name(mat, unreal.MaterialProperty.MP_OPACITY_MASK) if hasattr(MEL, 'get_material_property_input_node_output_name') else '', m, 'A')
            MEL.connect_material_expressions(d, '', m, 'B')
            MEL.connect_material_property(m, '', unreal.MaterialProperty.MP_OPACITY_MASK)
        else:
            MEL.connect_material_property(d, '', unreal.MaterialProperty.MP_OPACITY_MASK)
        kind = 'masked*fade'
    else:
        old = MEL.get_material_property_input_node(mat, unreal.MaterialProperty.MP_OPACITY)
        m = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, -500, 900)
        if old:
            MEL.connect_material_expressions(old, '', m, 'A')
        else:
            m.set_editor_property('const_a', 1.0)
        MEL.connect_material_expressions(p, '', m, 'B')
        MEL.connect_material_property(m, '', unreal.MaterialProperty.MP_OPACITY)
        kind = 'translucent*fade'
    MEL.recompile_material(mat)
    eal.save_loaded_asset(mat)
    R['edited'].append((mat.get_path_name(), kind))
    log(f'fade {kind}: {mat.get_path_name()}')


try:
    for path in base_materials():
        try:
            add(eal.load_asset(path))
        except Exception:  # noqa: BLE001
            R['errors'].append((path, traceback.format_exc()[-400:]))
    json.dump(R, open(os.path.join(OUT, 'add_fade.json'), 'w'), indent=1)
    log(f"fade done: {len(R['edited'])} edited, {len(R['skipped'])} skipped, {len(R['errors'])} errors")
finally:
    if os.environ.get('MH_QUIT'):
        unreal.SystemLibrary.quit_editor()
