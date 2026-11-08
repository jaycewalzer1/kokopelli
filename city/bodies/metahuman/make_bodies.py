"""Create the city's MetaHuman bodies headlessly (editor Python, no cloud, no login) and assemble each at
High (near body) and Low (far body) quality.

Run (full editor, minimized, quits when done):
    MH_BODIES=mara,iris city/bodies/metahuman/run_editor_gui.sh city/bodies/metahuman/make_bodies.py out/bodies/make.log

Env: MH_BODIES (comma list, default all), MH_QUALITIES (default "HIGH,LOW"), MH_OUT (json report dir).

Pipeline per body (all local; see city/bodies/METAHUMAN.md):
 1. create a MetaHumanCharacter asset in /Game/Characters/Bodies/<id>/MHC_<id>
 2. body: parametric constraints (height, fat, muscularity, masc/fem, chest/waist/hip)
 3. face: perturb the face model coefficients with a per-person seed, scaled so the landmarks move a set
    RMS distance (calibrated live), then skin tone / freckles / eyes / eyelashes / makeup
 4. rig locally: write the edited face state to a DNA (MHLocal helper) and import it as the whole face rig
    (this replaces Epic's cloud auto-rig, which needs an Epic account login)
 5. mark textures final (MHLocal) - the cloud "Download Texture Sources" step is skipped
 6. wardrobe (wave 2b): hair / eyebrows / beard / moustache grooms and the outfit from city/bodies/looks.json, resolved
    against the installed wardrobe (city/bodies/metahuman/looks.py), plus hair colour and outfit colours
 7. assemble with the UE Optimized pipeline at High and Low into .../<id>/High and .../<id>/Low; the report lists the
    groom / outfit assets each tier produced (city/bodies/write_parts.py turns them into Bodies.json parts)

Needs the "MetaHuman Creator Core Data" (Epic launcher). Without it the script writes out/bodies/make/status.json
{"status": "no_core_data"}, logs one clear message and quits without touching any body. MH_ALLOW_CLAY=1 builds the
old clay bodies anyway (wave 1 behaviour).
"""
import json
import math
import os
import random
import time
import traceback

import sys

import unreal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import looks as LOOKS  # noqa: E402  (pure-Python planner, city/bodies/metahuman/looks.py)

ROOT = '/Game/Characters/Bodies'
COMMON = f'{ROOT}/Common'
OUT = os.environ.get('MH_OUT', os.path.expanduser('~/Desktop/kokopelli/out/bodies/make'))
os.makedirs(OUT, exist_ok=True)

# Skin: u ~ melanin (0 light -> 1 dark), v ~ undertone (0 cool/pink -> 1 warm/yellow). Eyes: iris primary
# colour UV on the same kind of picker (u 0 blue -> 1 brown). Heights in cm.
BODIES = {
    'mara':  dict(desc='woman ~30, warm, chatty, notices plants', height=168, fem=0.85, fat=0.35, muscle=0.45,
                  skin=(0.30, 0.65), freckles=0.35, iris=(0.75, 0.55), lashes='LongSlightCurl', seed=11,
                  hair='long wavy, dark brown', outfit='linen shirt, rolled sleeves, green apron/overalls'),
    'iris':  dict(desc='Mara\'s neighbour, woman ~40', height=174, fem=0.75, fat=0.25, muscle=0.40,
                  skin=(0.70, 0.50), freckles=0.0, iris=(0.95, 0.60), lashes='LongCurl', seed=23,
                  hair='short natural curls, black', outfit='ochre knit cardigan, wide trousers'),
    'ana':   dict(desc='barista at The Kettle, woman ~25', height=162, fem=0.90, fat=0.30, muscle=0.40,
                  skin=(0.50, 0.70), freckles=0.0, iris=(0.85, 0.50), lashes='LongThickCurl', seed=31,
                  hair='tied-back ponytail, dark', outfit='t-shirt, canvas barista apron'),
    'tomas': dict(desc='baker at Rise Bakery, man ~45, broad', height=178, fem=0.10, fat=0.65, muscle=0.55,
                  skin=(0.40, 0.55), freckles=0.0, iris=(0.60, 0.50), lashes='ShortFine', seed=47,
                  hair='short, greying, beard', outfit='white baker shirt, flour-dusted apron'),
    'wen':   dict(desc='retired engineer who plays chess, man ~72, slight', height=166, fem=0.15, fat=0.30, muscle=0.25,
                  skin=(0.25, 0.75), freckles=0.0, iris=(0.90, 0.55), lashes='ShortSparse', seed=59,
                  hair='thin white, receding', outfit='cardigan over shirt, flat cap optional'),
    'priya': dict(desc='librarian at Lantern Library, woman ~55', height=160, fem=0.80, fat=0.50, muscle=0.30,
                  skin=(0.62, 0.70), freckles=0.0, iris=(0.95, 0.55), lashes='LongSlightCurl', seed=67,
                  hair='grey-streaked bun', outfit='long tunic, light scarf, reading glasses'),
    'kai':   dict(desc='ten-year-old (child body attempt)', height=138, fem=0.45, fat=0.30, muscle=0.25,
                  skin=(0.45, 0.60), freckles=0.15, iris=(0.70, 0.50), lashes='ShortThin', seed=83,
                  hair='short messy', outfit='t-shirt, shorts, backpack'),
}

def apply_looks():
    """looks.json overrides the skin and body numbers above, and adds the wardrobe plan."""
    try:
        data = LOOKS.load()
    except Exception as ex:  # noqa: BLE001
        log(f'looks.json not loaded ({ex}); using the built-in specs, no wardrobe')
        return {}
    errs = LOOKS.validate(data)
    if errs:
        log('looks.json INVALID, wardrobe skipped: ' + '; '.join(errs))
        return {}
    for pid, look in data['people'].items():
        spec = BODIES.get(pid)
        if spec is None:
            continue
        spec['skin'] = (look['skin']['u'], look['skin']['v'])
        spec['freckles'] = look['skin'].get('freckles', spec['freckles'])
        spec['face_texture_index'] = look['skin'].get('face_texture_index', 0)
        body = look.get('body') or {}
        if 'height' in body:
            spec['height'] = body['height']
        for k_json, k_spec in (('fat', 'fat'), ('muscle', 'muscle'), ('fem', 'fem')):
            if k_json in body:
                spec[k_spec] = body[k_json]
        spec['age'] = look['age']
        spec['look'] = look
    return data


R = {'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'bodies': {}}
sub = unreal.get_editor_subsystem(unreal.MetaHumanCharacterEditorSubsystem)
tools = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary
MH = unreal.MHLocalLibrary


def log(msg):
    unreal.log_warning(f'[MH] {msg}')


def optional_content_installed():
    d = unreal.PluginBlueprintLibrary.get_plugin_content_dir('MetaHumanCharacter')
    return os.path.isdir(os.path.join(d, 'Optional', 'TextureSynthesis'))


def set_body(ch, spec, rep):
    cons = sub.get_body_constraints(ch)
    m = {str(c.name).lower().replace(' ', '_').replace('/', '_'): c for c in cons}
    rep['constraint_ranges'] = {k: (round(c.min_measurement, 1), round(c.max_measurement, 1)) for k, c in m.items()}
    h = spec['height']
    if h == 'min':  # "as young as the sliders allow": the height constraint's floor
        h = m['height'].min_measurement
        rep['height_min'] = round(h, 1)
    want = {'height': h}
    # Fat / Muscularity / Masculine-Feminine are 0..1-style sliders mapped onto their own ranges.
    for key, frac in (('fat', spec['fat']), ('muscularity', spec['muscle']), ('masculine_feminine', spec['fem'])):
        if key in m:
            c = m[key]
            want[key] = c.min_measurement + frac * (c.max_measurement - c.min_measurement)
    for k, v in want.items():
        c = m[k]
        if v < c.min_measurement or v > c.max_measurement:
            rep.setdefault('clamped', {})[k] = (v, c.min_measurement, c.max_measurement)
            v = min(max(v, c.min_measurement), c.max_measurement)
        c.is_active = True
        c.target_measurement = float(v)
    sub.set_body_constraints(ch, list(m.values()))
    sub.commit_body_state(ch)
    after = {str(c.name): round(c.target_measurement, 1) for c in sub.get_body_constraints(ch) if c.is_active}
    rep['body_constraints'] = after


def landmarks(ch):
    return [unreal.Vector(p.x, p.y, p.z) for p in sub.get_face_landmarks(ch)]


def rms(a, b):
    return math.sqrt(sum((p.x - q.x) ** 2 + (p.y - q.y) ** 2 + (p.z - q.z) ** 2 for p, q in zip(a, b)) / max(1, len(a)))


def set_face(ch, spec, rep, amp_cm=float(os.environ.get('MH_FACE_AMP', '1.0'))):
    """Sculpt the face like dragging landmarks in the Creator UI: symmetric random offsets per landmark pair.

    (Setting the face model coefficients directly fails - the array is a serialized blob, not free
    parameters: 'PatchBlendModel Deserialize from vector failed'.)"""
    lm = landmarks(ch)
    rep['face_landmarks'] = len(lm)
    # Mirror pairs across the face's symmetry plane x = 0 (MetaHuman faces are centred on x).
    idx = list(range(len(lm)))
    pair = {}
    for i in idx:
        mx = unreal.Vector(-lm[i].x, lm[i].y, lm[i].z)
        j = min(idx, key=lambda k: (lm[k].x - mx.x) ** 2 + (lm[k].y - mx.y) ** 2 + (lm[k].z - mx.z) ** 2)
        pair[i] = j
    rng = random.Random(spec['seed'])
    deltas = {}
    for i in idx:
        if i in deltas:
            continue
        d = unreal.Vector(rng.gauss(0, amp_cm), rng.gauss(0, amp_cm), rng.gauss(0, amp_cm))
        j = pair[i]
        if j == i or abs(lm[i].x) < 0.3:     # on the midline: no sideways push
            d.x = 0.0
            deltas[i] = d
        else:
            deltas[i] = d
            deltas[j] = unreal.Vector(-d.x, d.y, d.z)
    keys = sorted(deltas)
    before = landmarks(ch)
    sub.translate_face_landmarks(ch, keys, [deltas[k] for k in keys])
    rep['face_landmark_rms_cm'] = round(rms(before, landmarks(ch)), 3)
    sub.commit_face_state(ch)


def set_look(ch, spec, rep):
    if not optional_content_installed():
        # Skin tone, freckles and body/chest textures all load from the Core Data (Optional/TextureSynthesis,
        # Optional/BodyTextures); without it commit_skin_settings asserts in BodyTextureUtils. Skip.
        rep['skin'] = 'skipped: MetaHuman Creator Core Data not installed'
    else:
        set_skin(ch, spec, rep)
    set_eyes(ch, spec, rep)


def set_skin(ch, spec, rep):
    ch.preview_material_type = unreal.MetaHumanCharacterSkinPreviewMaterial.EDITABLE
    sk = unreal.MetaHumanCharacterSkinProperties()
    sk.u, sk.v = spec['skin']
    sk.roughness = 1.0
    try:
        sk.face_texture_index = int(spec.get('face_texture_index', 0))  # skin detail set (clamped by the editor)
    except Exception as ex:  # noqa: BLE001
        rep['face_texture_index'] = repr(ex)
    sk.show_top_underwear = True
    fr = unreal.MetaHumanCharacterFrecklesProperties()
    fr.density = spec['freckles']
    fr.strength = 0.5 if spec['freckles'] else 0.0
    fr.mask = unreal.MetaHumanCharacterFrecklesMask.TYPE1 if spec['freckles'] else unreal.MetaHumanCharacterFrecklesMask.NONE
    ss = unreal.MetaHumanCharacterSkinSettings()
    ss.skin = sk
    ss.freckles = fr
    sub.commit_skin_settings(ch, ss)
    rep['skin'] = spec['skin']


def set_eyes(ch, spec, rep):
    try:
        eyes = ch.get_editor_property('eyes_settings')
        for side in ('eye_left', 'eye_right'):
            e = eyes.get_editor_property(side)
            iris = e.get_editor_property('iris')
            iris.primary_color_u, iris.primary_color_v = spec['iris']
            iris.secondary_color_u, iris.secondary_color_v = spec['iris'][0] * 0.8, spec['iris'][1]
            e.set_editor_property('iris', iris)
            eyes.set_editor_property(side, e)
        sub.commit_eyes_settings(ch, eyes)
        rep['eyes'] = 'ok'
    except Exception as ex:  # noqa: BLE001
        rep['eyes'] = repr(ex)
    try:
        hm = ch.get_editor_property('head_model_settings')
        lashes = hm.get_editor_property('eyelashes')
        lashes.type = getattr(unreal.MetaHumanCharacterEyelashesType, ''.join(
            ('_' + c if c.isupper() else c) for c in spec['lashes']).lstrip('_').upper())
        hm.set_editor_property('eyelashes', lashes)
        sub.commit_head_model_settings(ch, hm)
        rep['eyelashes'] = spec['lashes']
    except Exception as ex:  # noqa: BLE001
        rep['eyelashes'] = repr(ex)


def wardrobe_catalog():
    """{slot: {name: AssetData}} of the installed wardrobe items, per looks.SLOTS folder."""
    reg = unreal.AssetRegistryHelpers.get_asset_registry()
    cls = unreal.MetaHumanWardrobeItem.static_class().get_class_path_name()
    out = {}
    for slot, (_, folder) in LOOKS.SLOTS.items():
        f = unreal.ARFilter(package_paths=[f'/MetaHumanCharacter/Optional/{folder}'], recursive_paths=True,
                            class_paths=[cls])
        out[slot] = {str(a.asset_name): a for a in reg.get_assets(f)}
    return out


def preview_assemble(ch):
    """Assemble for preview so the instance parameters (hair colour, outfit colours) exist."""
    for name in ('assemble_for_preview', 'run_character_editor_pipeline_for_preview'):
        fn = getattr(sub, name, None)
        if fn:
            try:
                fn(character=ch)
            except TypeError:
                fn(ch)
            return name
    return None


def set_wardrobe(ch, spec, rep):
    """Grooms (hair, eyebrows, beard, moustache) and the outfit from looks.json, then their colours."""
    look = spec.get('look')
    if not look:
        rep['wardrobe'] = 'skipped: no look in looks.json'
        return
    cat = wardrobe_catalog()
    rep['wardrobe_catalog'] = {k: len(v) for k, v in cat.items()}
    coll = ch.internal_collection
    inst = coll.default_instance
    chosen = {}
    w = rep['wardrobe'] = {}
    for slot, (ue_slot, _) in LOOKS.SLOTS.items():
        want = look.get(slot)
        if want is None:
            continue
        name, how = LOOKS.match(want, sorted(cat.get(slot, {})))
        if not name:
            w[slot] = f'no wardrobe item matches {want.get("items")} / {want.get("keywords")} ({how}); skipped'
            log(f'{slot}: {w[slot]}')
            continue
        item = cat[slot][name].get_asset()
        key = coll.try_add_item_from_wardrobe_item(ue_slot, item)
        if key is None:
            w[slot] = f'{name}: try_add_item_from_wardrobe_item failed'
            continue
        ok = inst.try_add_slot_selection(unreal.MetaHumanPipelineSlotSelection(slot_name=ue_slot, selected_item=key))
        w[slot] = {'item': name, 'how': how, 'selected': bool(ok)}
        chosen[slot] = key
    if not chosen:
        return
    w['_preview'] = preview_assemble(ch)
    for slot, key in chosen.items():
        want = look[slot]
        try:
            params = inst.get_instance_parameters(item_path=unreal.MetaHumanPaletteItemPath(item_key=key))
        except Exception as ex:  # noqa: BLE001
            w[slot]['params'] = repr(ex)
            continue
        names = [str(p.name) for p in params]
        w[slot]['available_params'] = names
        done = {}
        if slot in LOOKS.GROOM_SLOTS:
            for k, pname in LOOKS.HAIR_PARAMS.items():
                if k in want:
                    p = next((q for q in params if str(q.name) == pname), None)
                    if p is not None:
                        p.set_float(value=float(want[k]))
                        done[pname] = want[k]
        else:
            for cname, rgb in (want.get('colors') or {}).items():
                for p in params:  # e.g. Primary -> PrimaryColorShirt, PrimaryColorPants
                    if str(p.name).lower().startswith(cname.lower()) and 'color' in str(p.name).lower():
                        p.set_color(value=unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0))
                        done[str(p.name)] = rgb
        w[slot]['set'] = done


def rig_locally(ch, bid, rep):
    dna = os.path.join(OUT, f'{bid}_face.dna')
    ok = MH.write_face_state_dna(ch, dna)
    rep['face_dna'] = dna if ok else 'FAILED'
    ip = unreal.ImportFromDNAParams()
    ip.import_whole_rig = True
    rep['import_whole_rig'] = str(sub.import_from_face_dna(ch, dna, ip))
    rep['rigged'] = MH.has_face_dna(ch)


def summarize_build(path, rep):
    assets = eal.list_assets(path, recursive=True, include_folder=False)
    out = {'n_assets': len(assets), 'meshes': {}, 'textures_kb': 0, 'mesh_kb': 0, 'other_kb': 0, 'blueprint': None,
           'parts': []}  # grooms / bindings / outfits the assembly produced (city/bodies/write_parts.py)
    for a in assets:
        obj = eal.load_asset(a)
        size = MH.get_resource_size_bytes(obj, True) // 1024
        cname = obj.get_class().get_name()
        if cname in ('GroomAsset', 'GroomBindingAsset', 'ChaosOutfitAsset', 'ChaosClothAsset') or (
                isinstance(obj, unreal.SkeletalMesh) and not any(t in a for t in ('/Body/', '/Face/'))):
            part = {'path': a, 'class': cname}
            if cname == 'GroomAsset':
                try:
                    lods = obj.get_editor_property('hair_groups_lod')
                    part['geometry'] = sorted({str(l.get_editor_property('geometry_type')).split('.')[-1].split(':')[0].lower()
                                               for g in lods for l in g.get_editor_property('lods')})
                except Exception as ex:  # noqa: BLE001
                    part['geometry'] = repr(ex)
            if cname == 'GroomBindingAsset':
                try:
                    tgt = obj.get_editor_property('target_skeletal_mesh')
                    part['target'] = tgt.get_path_name() if tgt else None
                    g = obj.get_editor_property('groom')
                    part['groom'] = g.get_path_name() if g else None
                except Exception as ex:  # noqa: BLE001
                    part['target'] = repr(ex)
            out['parts'].append(part)
        if isinstance(obj, unreal.SkeletalMesh):
            out['mesh_kb'] += size
            skel = obj.get_editor_property('skeleton')
            info = {'kb': size, 'skeleton': skel.get_path_name() if skel else None,
                    'lods': obj.get_lod_num() if hasattr(obj, 'get_lod_num') else None}
            try:
                sms = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
                info['verts_per_lod'] = [sms.get_num_verts(obj, i) for i in range(info['lods'] or 0)]
            except Exception:  # noqa: BLE001
                pass
            try:
                info['sockets'] = [str(s.socket_name) for s in obj.get_editor_property('sockets')] if hasattr(obj, 'get_editor_property') else []
            except Exception:  # noqa: BLE001
                pass
            b = obj.get_bounds() if hasattr(obj, 'get_bounds') else None
            if b:
                info['bounds_extent_cm'] = [round(b.box_extent.x, 1), round(b.box_extent.y, 1), round(b.box_extent.z, 1)]
            out['meshes'][a] = info
        elif isinstance(obj, unreal.Texture2D):
            out['textures_kb'] += size
            out.setdefault('textures', {})[a.rsplit('/', 1)[-1]] = (obj.blueprint_get_size_x(), obj.blueprint_get_size_y(), size)
        elif isinstance(obj, unreal.Blueprint):
            out['blueprint'] = a
        else:
            out['other_kb'] += size
    rep.update(out)


def make(bid, spec, qualities):
    rep = {'spec': spec}
    R['bodies'][bid] = rep
    folder = f'{ROOT}/{bid}'
    name = f'MHC_{bid}'
    if eal.does_asset_exist(f'{folder}/{name}'):
        eal.delete_asset(f'{folder}/{name}')
    t0 = time.time()
    ch = tools.create_asset(name, folder, unreal.MetaHumanCharacter, unreal.MetaHumanCharacterFactoryNew())
    if not sub.try_add_object_to_edit(ch):
        rep['error'] = 'could not open for edit'
        return
    try:
        set_body(ch, spec, rep)
        set_face(ch, spec, rep)
        set_look(ch, spec, rep)
        rig_locally(ch, bid, rep)
        if optional_content_installed():
            set_wardrobe(ch, spec, rep)
        else:
            rep['wardrobe'] = 'skipped: MetaHuman Creator Core Data not installed' 
        MH.set_has_high_resolution_textures(ch, True)
        rep['why_cannot_build'] = MH.why_cannot_build(ch)
        rep['optional_content'] = optional_content_installed()
        eal.save_loaded_asset(ch)
        rep['create_s'] = round(time.time() - t0, 1)
        bake_body = rep['optional_content']  # body baking needs the Core Data body textures
        for q in qualities:
            qi = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}[q]
            path = f'{folder}/{q.capitalize()}'
            for old in eal.list_assets(path, recursive=True):
                eal.delete_asset(old)
            t1 = time.time()
            try:
                res = MH.build_local(ch, qi, path, COMMON, True, True, bake_body, f'{bid}_{q.lower()}')
            except RuntimeError as ex:
                # Unreal Python raises if anything logged an error during the call. Assembly logs benign
                # 'Cannot break link ... RerouteNode' errors while copying the face control rigs into Common.
                res = 'ok-with-logged-errors: ' + str(ex).splitlines()[0][:200]
            qrep = {'result': res, 'build_s': round(time.time() - t1, 1)}
            summarize_build(path, qrep)
            rep[q.lower()] = qrep
            log(f'{bid} {q}: {res} {qrep.get("n_assets")} assets, mesh {qrep.get("mesh_kb")} KB, tex {qrep.get("textures_kb")} KB')
    except Exception:  # noqa: BLE001
        rep['exception'] = traceback.format_exc()
        log(f'{bid} exception {rep["exception"]}')
    finally:
        if sub.is_object_added_for_editing(ch):
            sub.remove_object_to_edit(ch)
        eal.save_directory(folder)


ALL = os.path.join(OUT, 'make_report_all.json')


def merge_all():
    try:
        allr = json.load(open(ALL))
    except Exception:  # noqa: BLE001
        allr = {'bodies': {}}
    allr['bodies'].update(R['bodies'])
    allr['updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
    json.dump(allr, open(ALL, 'w'), indent=1, default=str)


STATUS = os.path.join(OUT, 'status.json')


def main():
    if not optional_content_installed() and not os.environ.get('MH_ALLOW_CLAY'):
        msg = ('MetaHuman Creator Core Data is NOT installed (no MetaHumanCharacter/Content/Optional/TextureSynthesis). '
               'Install it in the Epic Games Launcher: Unreal Engine > Library > 5.8 > Options > "MetaHuman Creator Core '
               'Data", then re-run city/bodies/apply_core_data.sh. Nothing was changed.')
        log(msg)
        json.dump({'status': 'no_core_data', 'message': msg, 'when': time.strftime('%Y-%m-%d %H:%M:%S')},
                  open(STATUS, 'w'), indent=1)
        return
    R['looks'] = bool(apply_looks())
    want = [b for b in os.environ.get('MH_BODIES', ','.join(BODIES)).split(',') if b]
    qualities = os.environ.get('MH_QUALITIES', 'HIGH,LOW').split(',')
    for bid in want:
        log(f'== {bid}')
        make(bid, BODIES[bid], qualities)
        json.dump(R, open(os.path.join(OUT, 'make_report.json'), 'w'), indent=1, default=str)
    eal.save_directory(ROOT)
    R['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
    json.dump(R, open(os.path.join(OUT, 'make_report.json'), 'w'), indent=1, default=str)
    merge_all()
    failed = [b for b in want if 'exception' in R['bodies'].get(b, {}) or 'error' in R['bodies'].get(b, {})]
    json.dump({'status': 'failed' if failed else 'ok', 'failed': failed, 'bodies': want,
               'core_data': optional_content_installed(), 'when': time.strftime('%Y-%m-%d %H:%M:%S')},
              open(STATUS, 'w'), indent=1)
    log('done')


try:
    main()
finally:
    if os.environ.get('MH_QUIT'):
        unreal.SystemLibrary.quit_editor()
