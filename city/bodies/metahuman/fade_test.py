"""Check the BodyFade crossfade: render mara High at BodyFade 1 / 0.5 / 0 and report material-attribute use."""
import os, sys, json, unreal
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('MH_BODIES', 'mara')
quit_after = os.environ.pop('MH_QUIT', None)
import render_bodies as rb  # noqa: E402  (main() already ran for MH_BODIES; we reuse its helpers)
info = {}
for p in ['/Game/Characters/Bodies/Common/Lookdev_UHM/Skin/Materials/M_skin_unified_UI', '/Game/Characters/Bodies/Common/Lookdev_UHM/Skin/Materials/M_skin_unified_baked']:
    m = unreal.load_asset(p)
    info[p] = {'use_material_attributes': m.get_editor_property('use_material_attributes'),
               'opacity_mask_clip': m.get_editor_property('opacity_mask_clip_value'),
               'mask_input': str(unreal.MaterialEditingLibrary.get_material_property_input_node(m, unreal.MaterialProperty.MP_OPACITY_MASK))}
cap, rt = rb.stage()
a = rb.spawn_body(rb.body_bp('mara', 'High'), (0, 0, 0), rb.YAW)
rb.fov(cap, 40)
rb.look_at(cap, (540, 0, 95), (0, 0, 85))
for v in (1.0, 0.5, 0.0):
    for c in a.get_components_by_class(unreal.SkeletalMeshComponent):
        c.set_scalar_parameter_value_on_materials('BodyFade', v)
    rb.shoot(cap, rt, f'fadetest_{v}')
json.dump(info, open(os.path.join(rb.OUT, 'fadetest.json'), 'w'), indent=1)
unreal.log_warning(f'[MH] fadetest {info}')
if quit_after:
    unreal.SystemLibrary.quit_editor()
