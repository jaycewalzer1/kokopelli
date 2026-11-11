"""Render each assembled body (front + 3/4, High and Low) and measure cost, in the bodies scratch project.

    MH_BODIES=mara,iris tools/bodies/metahuman/run_editor_gui.sh tools/bodies/metahuman/render_bodies.py out/bodies/render.log

Writes PNGs to out/bodies/renders/wave1/ and costs to out/bodies/renders/wave1/costs.json.
Costs measured here (editor, uncooked, M4 Max):
  - async load ms of each tier's blueprint package from a cold editor (first touch in this session)
  - capture ms at 1280x720 for an empty stage, then with 1 / 3 / 8 copies of a body, High and Low,
    at a near distance (3 m) and an aerial distance (40 m). FlushRenderingCommands per capture, so this
    is render-thread + GPU wall time per frame, not a pure GPU timer.
"""
import json
import os
import traceback

import unreal

ROOT = '/Game/Characters/Bodies'
OUT = os.path.expanduser('~/Desktop/kokopelli/out/bodies/renders/wave1')
os.makedirs(OUT, exist_ok=True)
MH = unreal.MHLocalLibrary
eal = unreal.EditorAssetLibrary
ell = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
R = {'costs': {}, 'notes': []}


def log(m):
    unreal.log_warning(f'[MH] {m}')


def world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()


def spawn(cls, loc, rot=(0, 0, 0)):
    """rot = (pitch, yaw, roll) in degrees. (unreal.Rotator's positional order is roll, pitch, yaw.)"""
    return ell.spawn_actor_from_class(cls, unreal.Vector(*loc), unreal.Rotator(roll=rot[2], pitch=rot[0], yaw=rot[1]))


def stage():
    unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    floor = spawn(unreal.StaticMeshActor, (0, 0, 0))
    floor.static_mesh_component.set_static_mesh(unreal.load_asset('/Engine/BasicShapes/Plane.Plane'))
    floor.set_actor_scale3d(unreal.Vector(200, 200, 1))
    mat = unreal.load_asset('/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial')
    floor.static_mesh_component.set_material(0, mat)
    sun = spawn(unreal.DirectionalLight, (0, 0, 500), (-40, -35, 0))
    sun.light_component.set_intensity(6.0)
    sun.light_component.set_editor_property('atmosphere_sun_light', True)
    spawn(unreal.SkyAtmosphere, (0, 0, 0))
    sky = spawn(unreal.SkyLight, (0, 0, 300))
    sky.light_component.set_editor_property('real_time_capture', True)
    sky.light_component.set_intensity(1.2)
    # soft key from the front so faces read
    key = spawn(unreal.RectLight, (250, -120, 190), (-12, 155, 0))
    key.light_component.set_intensity(18.0)
    key.light_component.set_editor_property('source_width', 120)
    key.light_component.set_editor_property('source_height', 120)
    ppv = spawn(unreal.PostProcessVolume, (0, 0, 0))
    ppv.set_editor_property('unbound', True)
    s = ppv.settings
    s.set_editor_property('override_auto_exposure_method', True)
    s.set_editor_property('auto_exposure_method', unreal.AutoExposureMethod.AEM_MANUAL)
    s.set_editor_property('override_auto_exposure_bias', True)
    s.set_editor_property('auto_exposure_bias', 11.0)
    ppv.set_editor_property('settings', s)
    cap = spawn(unreal.SceneCapture2D, (300, 0, 160))
    rt = unreal.RenderingLibrary.create_render_target2d(world(), 1280, 720, unreal.TextureRenderTargetFormat.RTF_RGBA8_SRGB)
    c = cap.capture_component2d
    c.set_editor_property('texture_target', rt)
    c.set_editor_property('capture_source', unreal.SceneCaptureSource.SCS_FINAL_TONE_CURVE_HDR)
    c.set_editor_property('capture_every_frame', False)
    c.set_editor_property('fov_angle', 30.0)
    return cap, rt


def look_at(cap, eye, target):
    rot = unreal.MathLibrary.find_look_at_rotation(unreal.Vector(*eye), unreal.Vector(*target))
    cap.set_actor_location_and_rotation(unreal.Vector(*eye), rot, False, False)


def shoot(cap, rt, name):
    MH.flush_shaders_and_streaming()
    for _ in range(3):  # let Lumen / TSR history settle
        cap.capture_component2d.capture_scene()
    MH.flush_shaders_and_streaming()
    cap.capture_component2d.capture_scene()
    unreal.RenderingLibrary.export_render_target(world(), rt, OUT, name + '.png')
    log(f'wrote {name}')


YAW = -90.0  # assembled MetaHuman blueprints face +Y; turn them to face the +X cameras


def fov(cap, deg):
    cap.capture_component2d.set_editor_property('fov_angle', float(deg))


def dep_memory(pkg):
    """Sum resource sizes of everything the body blueprint pulls in (recursive hard deps under /Game),
    split into body-owned vs the shared Common folder. Uncompressed-ish estimates, all mips resident."""
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    opts = unreal.AssetRegistryDependencyOptions(include_soft_package_references=False, include_hard_package_references=True)
    seen, todo = set(), [pkg]
    while todo:
        p = todo.pop()
        if p in seen or not p.startswith('/Game'):
            continue
        seen.add(p)
        todo += [str(d) for d in (ar.get_dependencies(p, opts) or [])]
    own = common = tex = mesh = 0
    for p in seen:
        for ad in ar.get_assets_by_package_name(p):
            obj = ad.get_asset()
            b = MH.get_resource_size_bytes(obj, True)
            if isinstance(obj, unreal.Texture):
                tex += b
            elif isinstance(obj, unreal.SkeletalMesh):
                mesh += b
            if '/Common/' in p:
                common += b
            else:
                own += b
    mb = lambda x: round(x / 2 ** 20, 1)
    return {'packages': len(seen), 'own_mb': mb(own), 'common_mb': mb(common), 'textures_mb': mb(tex), 'skeletal_mesh_mb': mb(mesh)}


WANT_BONES = ('root', 'pelvis', 'head', 'neck_01', 'hand_r', 'hand_l', 'FACIAL_C_FacialRoot', 'FACIAL_L_Eye', 'FACIAL_R_Eye')


def ref_pos(c, bone):
    """Component-space reference-pose position of a bone (compose local ref transforms up the parent chain)."""
    chain = []
    b = bone
    while b and str(b) != 'None':
        chain.append(b)
        b = c.get_parent_bone(b)
    t = unreal.Transform()
    for name in reversed(chain):
        local = c.get_ref_pose_transform(c.get_bone_index(name))
        t = local.multiply(t) if hasattr(local, 'multiply') else local * t
    p = t.translation
    return [round(p.x, 1), round(p.y, 1), round(p.z, 1)]


def rig_info(actor):
    out = {}
    zmax = -1e9
    for c in actor.get_components_by_class(unreal.SkeletalMeshComponent):
        mesh = c.get_skeletal_mesh_asset() if hasattr(c, 'get_skeletal_mesh_asset') else c.skeletal_mesh
        if not mesh:
            continue
        n = c.get_num_bones()
        names = [str(c.get_bone_name(i)) for i in range(n)]
        info = {'mesh': mesh.get_path_name(), 'bones': n,
                'skeleton': mesh.get_editor_property('skeleton').get_path_name(),
                'sockets': [str(x) for x in c.get_all_socket_names()][:0] or None,
                'ref_pose_cm': {b: ref_pos(c, b) for b in WANT_BONES if b in names}}
        out[str(c.get_name())] = info
        o, e, _ = unreal.SystemLibrary.get_component_bounds(c)
        zmax = max(zmax, o.z + e.z)
    out['top_z_cm'] = round(zmax, 1)
    return out


def body_bp(bid, tier):
    assets = eal.list_assets(f'{ROOT}/{bid}/{tier}', recursive=True, include_folder=False)
    bps = [a for a in assets if a.split('/')[-1].split('.')[0].startswith('BP_')]
    return bps[0] if bps else None


def spawn_body(bp_path, loc, yaw):
    bp = eal.load_asset(bp_path)
    cls = bp.generated_class() if hasattr(bp, 'generated_class') else unreal.load_class(None, bp_path + '_C')
    return spawn(cls, loc, (0, yaw, 0))


def main():
    want = [b for b in os.environ.get('MH_BODIES', 'mara,iris,ana,tomas,wen,priya,kai').split(',') if b]
    cap, rt = stage()
    try:
        rep = json.load(open(os.path.expanduser('~/Desktop/kokopelli/out/bodies/make/make_report_all.json')))
        for b, v in rep['bodies'].items():
            R['costs'].setdefault(b, {})['height_cm'] = v['spec']['height']
    except Exception:  # noqa: BLE001
        pass
    MH.flush_shaders_and_streaming()
    for bid in want:
        for tier in ('High', 'Low'):
            bp = body_bp(bid, tier)
            if not bp:
                R['notes'].append(f'{bid} {tier}: no blueprint')
                continue
            pkg = bp.split('.')[0]
            ms = MH.async_load_ms([pkg])
            R['costs'].setdefault(bid, {})[f'{tier.lower()}_async_load_ms'] = round(ms, 1)
            R['costs'][bid][f'{tier.lower()}_memory'] = dep_memory(pkg)
            a = spawn_body(bp, (0, 0, 0), YAW)
            R['costs'][bid][f'{tier.lower()}_rig'] = rig_info(a)
            h = R['costs'][bid].get('height_cm') or 170
            for _ in range(2):   # warm-up: first captures of a fresh actor still show the streaming/guide texture
                MH.flush_shaders_and_streaming()
                for _ in range(8):
                    cap.capture_component2d.capture_scene()
            fov(cap, 40)
            look_at(cap, (540, 0, h * 0.55), (0, 0, h * 0.5))         # front, full body
            shoot(cap, rt, f'{bid}_{tier.lower()}_front')
            look_at(cap, (380, -380, h * 0.6), (0, 0, h * 0.5))       # 3/4, full body
            shoot(cap, rt, f'{bid}_{tier.lower()}_34')
            fov(cap, 20)
            look_at(cap, (110, -70, h * 0.93), (0, 0, h * 0.91))      # 3/4 head close-up
            shoot(cap, rt, f'{bid}_{tier.lower()}_head')
            if bid == want[0] and tier == 'High':   # crossfade check: BodyFade 0.5 via MIDs, like the server does
                for c in a.get_components_by_class(unreal.SkeletalMeshComponent):
                    c.set_scalar_parameter_value_on_materials('BodyFade', 0.5)
                fov(cap, 40)
                look_at(cap, (540, 0, h * 0.55), (0, 0, h * 0.5))
                shoot(cap, rt, f'{bid}_high_fade050')
            if tier == 'Low':
                fov(cap, 40)
                look_at(cap, (2600, -1500, 1400), (0, 0, 80))          # ~33 m, aerial-ish: how the far body reads
                shoot(cap, rt, f'{bid}_low_far')
            ell.destroy_actor(a)
    # cost: N copies of the first available body
    first = next((b for b in want if body_bp(b, 'High')), None)
    if first:
        perf = {}
        for dist_name, eye, tgt in (('near_4m', (450, 0, 160), (-100, 0, 100)), ('aerial_40m', (2800, 2800, 1800), (0, 0, 0))):
            look_at(cap, eye, tgt)
            MH.flush_shaders_and_streaming()
            for tier in ('High', 'Low'):
                for n in (1, 3, 8, 16):
                    base = MH.time_captures(cap.capture_component2d, 60)
                    actors = [spawn_body(body_bp(first, tier), (-(i % 4) * 70, (i // 4) * 80 - 40 * (n // 4), 0), YAW) for i in range(n)]
                    MH.flush_shaders_and_streaming()
                    with_b = MH.time_captures(cap.capture_component2d, 60)
                    perf[f'{dist_name}_{tier.lower()}_x{n}'] = {'empty_ms': round(base, 2), 'with_ms': round(with_b, 2), 'delta_ms': round(with_b - base, 2)}
                    for a in actors:
                        ell.destroy_actor(a)
        R['perf'] = perf
        R['perf_body'] = first
    json.dump(R, open(os.path.join(OUT, 'costs.json'), 'w'), indent=1)
    log('render done')


try:
    main()
except Exception:  # noqa: BLE001
    log(traceback.format_exc())
    R['exception'] = traceback.format_exc()
    json.dump(R, open(os.path.join(OUT, 'costs.json'), 'w'), indent=1)
finally:
    if os.environ.get('MH_QUIT'):
        unreal.SystemLibrary.quit_editor()
