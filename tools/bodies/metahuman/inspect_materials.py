"""List each body mesh's material slots, their base material, blend mode override and whether BodyFade is visible."""
import json, os, unreal
eal = unreal.EditorAssetLibrary
out = {}
for tier in ('High', 'Low'):
    for a in eal.list_assets(f'/Game/Characters/Bodies/mara/{tier}', recursive=True):
        o = eal.load_asset(a)
        if isinstance(o, unreal.SkeletalMesh):
            rows = []
            for m in o.get_editor_property('materials'):
                mi = m.get_editor_property('material_interface')
                if not mi:
                    rows.append(None); continue
                base = mi.get_base_material()
                ov = None
                if isinstance(mi, unreal.MaterialInstance):
                    bpo = mi.get_editor_property('base_property_overrides')
                    ov = (bpo.get_editor_property('override_blend_mode'), str(bpo.get_editor_property('blend_mode')))
                fade = unreal.MaterialEditingLibrary.get_scalar_parameter_names(base) if hasattr(unreal.MaterialEditingLibrary, 'get_scalar_parameter_names') else []
                rows.append({'slot': str(m.get_editor_property('material_slot_name')), 'mi': mi.get_path_name(), 'base': base.get_path_name(),
                             'base_blend': str(base.get_editor_property('blend_mode')), 'override': ov, 'has_BodyFade': 'BodyFade' in [str(x) for x in fade]})
            out[a] = rows
json.dump(out, open(os.path.expanduser('~/Desktop/kokopelli/out/bodies/make/materials_mara.json'), 'w'), indent=1)
unreal.log_warning('[MH] inspect done')
if os.environ.get('MH_QUIT'):
    unreal.SystemLibrary.quit_editor()
