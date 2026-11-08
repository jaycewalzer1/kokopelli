"""M6: realistic bodies (city/bodies/PLAN.md, city/bodies/ANIMATION.md).

Bodies come from Config/Bodies.json, chosen by actor name; `vbp <actor> SetBody <id>` / `GetBody`.
Each person has a near (High) and far (Low) body; the tier follows its on-screen height in any active
camera (near above near_px, far below far_px, at most max_near near), with a short crossfade.

Wave 1 runs on stand-ins: `standin_near` (Quinn) / `standin_far` (Manny), and `test_missing*` bodies whose
meshes don't exist, for the fallback chain. Against tests/mock_server.py only the reply-shape tests run;
the rest need the UE server and skip.

    SIMCV_PORT=9004 ~/Desktop/kokopelli/simworld/.venv/bin/python -I -m pytest mac_server/tests -m m6
"""
import json
import time
from io import BytesIO

import numpy as np
import pytest

from conftest import req, wait_until

AGENT = '/Game/TrafficSystem/Pedestrian/Base_User_Agent.Base_User_Agent_C'
PEDESTRIAN = '/Game/TrafficSystem/Pedestrian/Base_Pedestrian.Base_Pedestrian_C'
MUG = '/Game/InteractableAsset/Cup/BP_Mug.BP_Mug_C'
COUCH = '/Game/CityDatabase/blueprints/BP_Couch.BP_Couch_C'
TIERS = ('near', 'far', 'fallback', 'placeholder')

# Projected-height thresholds from Config/Bodies.json, for a 170 cm stand-in seen by a 90 deg camera at 832 px:
# focal = 416 px, so near below 170*416/28 = 25.3 m, far beyond 170*416/22 = 32.1 m.
FOCAL = 416.0
NEAR_PX, FAR_PX = 28.0, 22.0


def j(ucv, cmd):
    r = req(ucv, cmd)
    assert isinstance(r, str) and not r.startswith('error'), f'{cmd} -> {r!r}'
    return json.loads(r)


def spawn(ucv, name, path, x, y, z=110, yaw=0):
    assert req(ucv, f'vset /objects/spawn_bp_asset {path} {name}') == name
    req(ucv, f'vset /object/{name}/location {x} {y} {z}')
    req(ucv, f'vset /object/{name}/rotation 0 {yaw} 0')
    return name


def needs_ue(ucv, name):
    r = req(ucv, f'vbp {name} GetBodyDebug')
    if isinstance(r, str) and 'mock server' in r:
        pytest.skip('needs the UE server (mock has no bodies in motion)')
    return json.loads(r)


def debug(ucv, name):
    return j(ucv, f'vbp {name} GetBodyDebug')


def look_from(ucv, x, y, z, yaw=0.0, pitch=0.0):
    req(ucv, 'vset /camera/0/fov 90')
    req(ucv, f'vset /camera/0/location {x} {y} {z}')
    req(ucv, f'vset /camera/0/rotation {pitch} {yaw} 0')


# --------------------------------------------------------------------------- interface (mock + UE)
@pytest.mark.m6
def test_default_body_by_actor_name(world):
    """PLAN Interface: GEN_BP_Humanoid_0 -> mara, a pedestrian -> default_resident; GetBody reply shape."""
    ucv, _ = world
    spawn(ucv, 'GEN_BP_Humanoid_0', AGENT, 0, 0, 300)
    spawn(ucv, 'GEN_BP_Pedestrian_Body0', PEDESTRIAN, 300, 0)
    time.sleep(0.5)
    a = j(ucv, 'vbp GEN_BP_Humanoid_0 GetBody')
    p = j(ucv, 'vbp GEN_BP_Pedestrian_Body0 GetBody')
    assert set(a) >= {'body', 'tier', 'requested'} and a['requested'] == 'mara' and a['tier'] in TIERS
    assert p['requested'] == 'ana' and p['tier'] in TIERS
    assert a['body'] != 'placeholder', 'the manny fallback must load at least'


@pytest.mark.m6
def test_set_body_reply(world):
    """PLAN Interface: SetBody -> {"ok": true, "body": id, ...}; a tiered body starts far."""
    ucv, _ = world
    spawn(ucv, 'GEN_BP_Pedestrian_Body0', PEDESTRIAN, 300, 0)
    r = j(ucv, 'vbp GEN_BP_Pedestrian_Body0 SetBody standin_near')
    assert r['ok'] is True and r['requested'] == 'standin_near'
    assert (r['body'], r['tier']) in (('standin_far', 'far'), ('standin_near', 'near'))
    g = j(ucv, 'vbp GEN_BP_Pedestrian_Body0 GetBody')
    assert g['requested'] == 'standin_near' and g['tier'] in ('near', 'far')


@pytest.mark.m6
def test_unknown_body_is_error_and_keeps_body(world):
    """PLAN Interface: an id Bodies.json doesn't know is an error naming it; the body stays."""
    ucv, _ = world
    spawn(ucv, 'GEN_BP_Pedestrian_Body0', PEDESTRIAN, 300, 0)
    before = j(ucv, 'vbp GEN_BP_Pedestrian_Body0 GetBody')
    r = req(ucv, 'vbp GEN_BP_Pedestrian_Body0 SetBody no_such_body')
    assert r.startswith('error') and 'no_such_body' in r
    assert j(ucv, 'vbp GEN_BP_Pedestrian_Body0 GetBody') == before


@pytest.mark.m6
def test_fallback_chain_on_missing_asset(world):
    """PLAN: unloadable mesh -> fallback chain (tier "fallback", warning names the asset), then placeholder."""
    ucv, _ = world
    spawn(ucv, 'GEN_BP_Pedestrian_Body0', PEDESTRIAN, 300, 0)
    r = j(ucv, 'vbp GEN_BP_Pedestrian_Body0 SetBody test_missing')
    assert r['ok'] is True and r['body'] == 'manny' and r['tier'] == 'fallback'
    assert 'SKM_Missing' in r.get('warning', '')
    r = j(ucv, 'vbp GEN_BP_Pedestrian_Body0 SetBody test_missing_all')
    assert r['ok'] is True and r['body'] == 'placeholder' and r['tier'] == 'placeholder'
    assert 'SKM_AlsoMissing' in r['warning']


@pytest.mark.m6
def test_body_commands_reject_non_humans(world):
    """Bodies only exist on agents and residents."""
    ucv, _ = world
    spawn(ucv, 'GEN_BP_Tree_Body0', '/Game/CityDatabase/blueprints/BP_Tree1.BP_Tree1_C', 0, 900, 0)
    assert req(ucv, 'vbp GEN_BP_Tree_Body0 GetBody').startswith('error')
    assert req(ucv, 'vbp GEN_BP_Tree_Body0 SetBody manny').startswith('error')


@pytest.mark.m6
def test_vget_bodies_lists_people(world):
    """`vget /bodies`: {actor: {body, tier, ...}} for capture sidecars (tier per person per frame)."""
    ucv, _ = world
    spawn(ucv, 'GEN_BP_Pedestrian_Body0', PEDESTRIAN, 300, 0)
    spawn(ucv, 'GEN_BP_Pedestrian_Body1', PEDESTRIAN, 600, 0)
    allb = json.loads(req(ucv, 'vget /bodies'))
    for n in ('GEN_BP_Pedestrian_Body0', 'GEN_BP_Pedestrian_Body1'):
        assert allb[n]['tier'] in TIERS and 'body' in allb[n]


# --------------------------------------------------------------------------- UE only
@pytest.mark.m6
def test_capsule_and_speed_unchanged_with_body(world):
    """Invariant: the body is visual only. Capsule lands at z~92 and 1.5 s at 200 cm/s covers ~300 cm."""
    ucv, comm = world
    name = spawn(ucv, 'GEN_BP_Humanoid_0', AGENT, 0, 0, 600)
    needs_ue(ucv, name)
    j(ucv, f'vbp {name} SetBody manny')
    assert wait_until(lambda: abs(float(req(ucv, f'vget /object/{name}/location').split()[2]) - 92) < 5, timeout=5)
    req(ucv, f'vbp {name} SetMaxSpeed 200')
    p0 = np.array([float(v) for v in req(ucv, f'vget /object/{name}/location').split()])
    req(ucv, f'vbp {name} MoveForward')
    time.sleep(1.5)
    req(ucv, f'vbp {name} StopAgent')
    time.sleep(0.5)
    p1 = np.array([float(v) for v in req(ucv, f'vget /object/{name}/location').split()])
    assert 230 < np.linalg.norm(p1[:2] - p0[:2]) < 380


@pytest.mark.m6
def test_eye_camera_at_body_eye_height(world):
    """Invariant: the agent camera sits at the body's eye socket (~93% of height_cm above the feet) and drops
    with the head when sitting."""
    ucv, _ = world
    name = spawn(ucv, 'GEN_BP_Humanoid_0', AGENT, 0, 0, 300)
    needs_ue(ucv, name)
    j(ucv, f'vbp {name} SetBody manny')
    time.sleep(1.5)
    d = debug(ucv, name)
    cam = np.array([float(v) for v in req(ucv, 'vget /camera/1/location').split()])
    height = d['height_cm']
    eye_h = cam[2] - d['feet'][2]
    assert d['camera_follows_eyes'] is True
    assert np.linalg.norm(cam - np.array(d['eye'])) < 3, 'camera 1 is not at the eye socket'
    assert 0.88 * height < eye_h < 0.97 * height, (eye_h, height)
    # sit on a couch: the eyes come down with the head
    spawn(ucv, 'GEN_BP_Couch_Body0', COUCH, -70, 0, 0)
    time.sleep(0.3)
    assert json.loads(req(ucv, f'vbp {name} SitDown'))['Success'] == 'true'
    time.sleep(1.5)
    sat = float(req(ucv, 'vget /camera/1/location').split()[2]) - d['feet'][2]
    assert sat < eye_h - 25, (sat, eye_h)
    req(ucv, f'vbp {name} StandUp')


@pytest.mark.m6
def test_pick_up_attaches_to_hand_socket(world):
    """Invariant: a carried object rides the hand socket (after the reach), follows the walk, drops at the feet."""
    ucv, _ = world
    name = spawn(ucv, 'GEN_BP_Humanoid_0', AGENT, 0, 0, 300)
    needs_ue(ucv, name)
    j(ucv, f'vbp {name} SetBody manny')
    time.sleep(1.5)
    spawn(ucv, 'BP_Mug_C_1', MUG, 60, 10, 0)
    time.sleep(0.3)
    assert json.loads(req(ucv, f'vbp {name} PickUp BP_Mug_C_1'))['Success'] == 'true'
    time.sleep(1.5)
    d = debug(ucv, name)
    assert d['held'] == 'BP_Mug_C_1' and d['held_on_hand'] is True
    assert d['held_socket'] == d['hand_socket'] and d['held_parent'], d
    assert np.linalg.norm(np.array(d['held_location']) - np.array(d['hand'])) < 20
    req(ucv, f'vbp {name} SetMaxSpeed 200')
    req(ucv, f'vbp {name} MoveForward')
    time.sleep(1.0)
    req(ucv, f'vbp {name} StopAgent')
    time.sleep(0.5)
    d = debug(ucv, name)
    assert np.linalg.norm(np.array(d['held_location']) - np.array(d['hand'])) < 20, 'mug left the hand while walking'
    assert json.loads(req(ucv, f'vbp {name} DropOff'))['Success'] == 'true'
    mug = np.array([float(v) for v in req(ucv, 'vget /object/BP_Mug_C_1/location').split()])
    assert abs(mug[2] - d['feet'][2]) < 5, 'dropped mug should stand at the feet'


def mask_colors(ucv, cam=0):
    img = ucv.get_image(cam, 'object_mask')[:, :, ::-1]  # BGR -> RGB
    return img


@pytest.mark.m6
def test_body_is_one_object_in_mask_and_depth(world):
    """Invariant: the body shows in object_mask as exactly its actor colour, and in depth at its distance."""
    ucv, _ = world
    name = spawn(ucv, 'GEN_BP_Pedestrian_Body0', PEDESTRIAN, 400, 0)
    needs_ue(ucv, name)
    j(ucv, f'vbp {name} SetBody manny')
    ucv.set_color(name, (255, 0, 255))
    ucv.set_camera_resolution(0, (320, 240))
    look_from(ucv, 0, 0, 100)
    time.sleep(1.0)

    def person_mask():
        m = mask_colors(ucv).reshape(-1, 3).astype(int)
        return m, (np.abs(m - [255, 0, 255]).max(axis=1) <= 3)
    # editor-game builds compile the skinned annotation shader on first use (then it's cached): allow for that
    wait_until(lambda: person_mask()[1].mean() > 0.01, timeout=20, interval=1.0)
    m, person = person_mask()
    assert person.mean() > 0.01, f'only {person.mean():.3%} person pixels'
    # every pixel that is neither background, floor nor the person would be a second id on the body
    floor = m[-1]  # bottom row centre is floor
    other = ~person & (m.sum(axis=1) > 0) & (np.abs(m - floor).max(axis=1) > 3)
    assert other.mean() < 0.002, f'{other.mean():.3%} pixels of other ids'
    d = np.load(BytesIO(req(ucv, 'vget /camera/0/depth npy')))
    centre = d[90:150, 150:170]
    assert np.median(centre) < 450, f'depth at the body {np.median(centre):.0f} cm'


def tier_of(ucv, name):
    return j(ucv, f'vbp {name} GetBody')['tier']


@pytest.mark.m6
def test_tier_switch_by_projected_height_with_hysteresis(world):
    """Near above 28 px, far below 22 px (832x480 units), keep the current tier in between."""
    ucv, _ = world
    name = spawn(ucv, 'GEN_BP_Pedestrian_Body0', PEDESTRIAN, 0, 0)
    needs_ue(ucv, name)
    j(ucv, f'vbp {name} SetBody standin_near')

    def at(dist):  # camera dist cm in front of the person, looking at it
        look_from(ucv, -dist, 0, 100)
        time.sleep(1.2)  # async load + 0.4 s fade
        return tier_of(ucv, name)

    assert at(2000) == 'near'                    # 35 px
    assert at(2900) == 'near'                    # 24 px: inside the band, stays near
    assert at(3600) == 'far'                     # 20 px
    assert at(2900) == 'far'                     # band again: stays far
    assert at(2000) == 'near'
    px = debug(ucv, name)['px']
    assert abs(px - 170 / 2000 * FOCAL) < 3, px
    look_from(ucv, 2000, 0, 100)                 # camera past the person, looking away: not seen
    time.sleep(1.2)
    assert tier_of(ucv, name) == 'far'


@pytest.mark.m6
def test_max_near_cap_tallest_first(world):
    """At most max_near (3) people are near; the ones that look tallest win."""
    ucv, _ = world
    names = []
    for i, dist in enumerate((800, 1000, 1200, 1400, 1600)):
        names.append(spawn(ucv, f'GEN_BP_Pedestrian_Body{i}', PEDESTRIAN, dist, (i - 2) * 150))
    needs_ue(ucv, names[0])
    for n in names:
        j(ucv, f'vbp {n} SetBody standin_near')
    look_from(ucv, 0, 0, 100)
    time.sleep(2.0)
    tiers = [tier_of(ucv, n) for n in names]
    assert tiers == ['near', 'near', 'near', 'far', 'far'], tiers


def warm_mask_shaders(ucv, name, bodies, colour, dist=600):
    """Uncooked editor games compile a mesh's annotation shader on its first mask capture and draw nothing until
    then (cooked builds ship them). Show each body once, close up, until it appears in the mask."""
    look_from(ucv, -dist, 0, 100)
    for body in bodies:
        j(ucv, f'vbp {name} HoldFade 1')         # any fade completes at once
        j(ucv, f'vbp {name} SetBody {body}')
        wait_until(lambda: person_px(mask_colors(ucv), colour).sum() > 20, timeout=30, interval=0.5)
    j(ucv, f'vbp {name} HoldFade -1')


@pytest.mark.m6
def test_fade_completes_with_one_mesh_and_constant_seg_id(world):
    """The crossfade draws both bodies for ~0.4 s, both in the person's one mask colour, then exactly one."""
    ucv, _ = world
    name = spawn(ucv, 'GEN_BP_Pedestrian_Body0', PEDESTRIAN, 0, 0)
    needs_ue(ucv, name)
    ucv.set_color(name, (0, 255, 255))
    ucv.set_camera_resolution(0, (160, 120))
    warm_mask_shaders(ucv, name, ('standin_far', 'test_parts_missing'), (0, 255, 255))
    j(ucv, f'vbp {name} SetBody standin_near')
    look_from(ucv, -4000, 0, 100)
    time.sleep(1.2)
    assert tier_of(ucv, name) == 'far'
    look_from(ucv, -1500, 0, 100)                # switch to near now
    seen_two, colours = False, set()
    end = time.time() + 1.5
    while time.time() < end:
        d = debug(ucv, name)
        seen_two |= d['visible_meshes'] == 2
        m = mask_colors(ucv).reshape(-1, 3)
        person = (np.abs(m.astype(int) - [0, 255, 255]).max(axis=1) <= 3)
        if person.any():
            colours.add(tuple(m[person][0]))
        assert person.mean() > 0.0005, ('person vanished from the mask during the fade', d['fade'], int(person.sum()))
    d = debug(ucv, name)
    assert d['tier'] == 'near' and d['fading'] is False and d['visible_meshes'] == 1, d
    assert seen_two, 'never saw both meshes during the crossfade'
    assert len(colours) == 1


@pytest.mark.m6
def test_pose_continues_across_tier_swap(world):
    """The walk phase and anim clock live on the actor: a swap neither restarts nor stalls the cycle."""
    ucv, _ = world
    name = spawn(ucv, 'GEN_BP_Pedestrian_Body0', PEDESTRIAN, 0, -700, yaw=90)
    needs_ue(ucv, name)
    j(ucv, f'vbp {name} SetBody standin_near')
    look_from(ucv, -4000, 0, 100)
    time.sleep(1.2)
    req(ucv, f'vbp {name} SetMaxSpeed 150')
    req(ucv, f'vbp {name} MoveForward')          # walks across the view (+y)
    time.sleep(1.0)

    def sample():
        d = debug(ucv, name)
        return time.time(), d['time'], d['phase'], d['tier']

    def rate(a, b):  # phase cycles per second, unwrapped (<1 cycle between samples)
        return ((b[2] - a[2]) % 1.0) / (b[0] - a[0])

    s0 = sample(); time.sleep(0.4); s1 = sample()
    assert s1[3] == 'far'
    look_from(ucv, -1500, 0, 100)                # swap to near while walking
    time.sleep(0.25)
    s2 = sample(); time.sleep(0.4); s3 = sample()
    req(ucv, f'vbp {name} StopPedestrian')
    assert s3[3] == 'near'
    assert s0[1] < s1[1] < s2[1] < s3[1], 'anim clock restarted'
    before, after = rate(s0, s1), rate(s2, s3)
    assert before > 0.1 and abs(after - before) / before < 0.3, (before, after)


# --------------------------------------------------------------------------- wave 2: MetaHuman bodies
METAHUMANS = {'mara': 168, 'iris': 174, 'ana': 162, 'tomas': 178, 'wen': 166, 'priya': 160, 'kai': 138}


def metahuman_or_skip(ucv, name, body):
    r = j(ucv, f'vbp {name} SetBody {body}')
    if r['tier'] in ('fallback', 'placeholder'):
        pytest.skip(f'{body} MetaHuman not in this build (shows {r["body"]}); run city/bodies/migrate_bodies.sh')
    return r


@pytest.mark.m6
def test_metahuman_face_follows_body_near_and_far(world):
    """Wave 2: a MetaHuman is body + face_mesh; the face is leader-posed to the body at both tiers, the person
    is sized to height_cm by body + face together, and the near/far crossfade carries the face along."""
    ucv, _ = world
    name = spawn(ucv, 'GEN_BP_Pedestrian_Body0', PEDESTRIAN, 0, 0)
    needs_ue(ucv, name)
    metahuman_or_skip(ucv, name, 'priya')
    look_from(ucv, -6000, 0, 100)                # 11 px: far
    time.sleep(1.0)
    d = debug(ucv, name)
    assert d['tier'] == 'far' and d['body'] == 'priya_low', d
    assert '/Low/' in d['face_mesh'] and d['face_visible'] and d['face_follows_body'], d
    assert abs(d['mesh_scale'] - 1.0) < 0.05, 'MetaHumans are authored at real size; body+face bounds give ~1'
    look_from(ucv, -500, 0, 100)                 # 140 px: near
    assert wait_until(lambda: (lambda x: x['tier'] == 'near' and not x['fading'])(debug(ucv, name)), timeout=15)
    d = debug(ucv, name)
    assert d['body'] == 'priya' and '/High/' in d['face_mesh'] and d['face_visible'] and d['face_follows_body'], d
    assert d['visible_meshes'] == 1


@pytest.mark.m6
def test_metahuman_eye_height_and_bodies_json(world):
    """Wave 2: every person id maps to a High/Low MetaHuman pair with a face; the agent eye camera sits at
    head + [8,0,6] cm, i.e. ~94% of the body height (A measured 157.8 cm for mara's 168 cm)."""
    import pathlib
    cfg = json.loads((pathlib.Path(__file__).resolve().parents[1] / 'Config' / 'Bodies.json').read_text())
    for pid, h in METAHUMANS.items():
        near, far = cfg['bodies'][pid], cfg['bodies'][pid + '_low']
        assert near['far'] == pid + '_low' and near['face_mesh'] and far['face_mesh'], pid
        # kai: 'as young as the sliders allow' may move him to the height floor (~135) after Core Data (write_parts.py)
        ok_h = 134 <= near['height_cm'] <= h if pid == 'kai' else near['height_cm'] == h
        assert ok_h and near['height_cm'] == far['height_cm'] and near['fallback'] and far['fallback'], pid
        assert '/High/' in near['mesh'] and '/Low/' in far['mesh'], pid
    ucv, _ = world
    name = spawn(ucv, 'GEN_BP_Humanoid_0', AGENT, 0, 0, 300)
    needs_ue(ucv, name)
    metahuman_or_skip(ucv, name, 'mara')
    time.sleep(1.5)
    d = debug(ucv, name)
    eye_h = d['eye'][2] - d['feet'][2]
    assert 0.90 * 168 < eye_h < 0.97 * 168, eye_h
    assert d['camera_follows_eyes'] and np.linalg.norm(np.array(d['camera']) - np.array(d['eye'])) < 3


# --------------------------------------------------------------------------- wave 2b: clean controls mid-fade
def person_px(mask, colour):
    return np.abs(mask.astype(int) - colour).max(axis=2) <= 3


def isolated(person):
    """Person pixels with no 4-neighbour of the same id: the signature of a dither pattern."""
    p = np.pad(person, 1)
    nb = p[:-2, 1:-1].astype(int) + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]
    return int((person & (nb == 0)).sum())


def tiny_holes(person, max_px=3):
    """Enclosed background specks of at most max_px pixels: what a dither leaves inside a silhouette (natural
    gaps, e.g. between an arm and the thigh, are bigger)."""
    from scipy import ndimage
    holes = ndimage.binary_fill_holes(person) & ~person
    lab, n = ndimage.label(holes)
    sizes = np.bincount(lab.ravel())[1:]
    return int((sizes <= max_px).sum())


def start_held_fade(ucv, name, body, progress, colour):
    """Far first, then a near camera, with the crossfade pinned at `progress` (HoldFade)."""
    j(ucv, f'vbp {name} SetBody {body}')
    ucv.set_color(name, colour)
    ucv.set_camera_resolution(0, (640, 480))
    look_from(ucv, -6000, 0, 100)                # 12 px: far
    assert wait_until(lambda: (lambda d: d['tier'] == 'far' and not d['fading'])(debug(ucv, name)), timeout=10)
    j(ucv, f'vbp {name} HoldFade {progress}')
    look_from(ucv, -600, 0, 100)                 # 118 px: near, the fade starts and stays pinned
    assert wait_until(lambda: debug(ucv, name)['fading'], timeout=15), 'crossfade never started'


def controls(ucv, colour):
    m = mask_colors(ucv)
    person = person_px(m, colour)
    d = np.load(BytesIO(req(ucv, 'vget /camera/0/depth npy')))
    return m, person, d


def speckle_stats(person, d):
    """see_through: pixels inside the silhouette (one pixel in from its edge, where mask and depth may disagree
    by anti-aliasing) whose depth is the background behind the body, i.e. holes in the depth control."""
    from scipy import ndimage
    med = float(np.median(d[person])) if person.any() else 0.0
    inner = ndimage.binary_erosion(person)
    return {'area': int(person.sum()), 'isolated': isolated(person), 'tiny_holes': tiny_holes(person),
            'see_through': int((d[inner] > med + 150).sum()), 'depth_median': med}


def shown_alone(ucv, name, body):
    """Controls of one body with no fade running (the reference silhouette)."""
    j(ucv, f'vbp {name} SetBody {body}')
    assert wait_until(lambda: (lambda d: d['body'] == body and not d['fading'])(debug(ucv, name)), timeout=10)
    time.sleep(0.2)


@pytest.mark.m6
def test_fade_controls_have_no_speckle(world):
    """Wave 2b: mid-fade only the lit pass dithers. Depth and the object mask show exactly one whole body: the old
    (far, Manny) one below fade 0.5, the new (near, Quinn) one from 0.5 on. At fade 0.25, 0.5 and 0.75 the mask
    has no isolated pixels, no more tiny holes than that body alone, the same area as that body alone (+-3%), and
    depth is solid at the body everywhere inside the silhouette. After each capture the lit dither is back."""
    ucv, _ = world
    name = spawn(ucv, 'GEN_BP_Pedestrian_Body0', PEDESTRIAN, 0, 0, yaw=180)
    needs_ue(ucv, name)
    colour = (255, 0, 255)
    ucv.set_color(name, colour)
    ucv.set_camera_resolution(0, (640, 480))
    look_from(ucv, -600, 0, 100)                 # 118 px at 832: near
    j(ucv, f'vbp {name} HoldFade -1')
    # references: Quinn alone (test_parts_missing = Quinn + M_BodyStandIn, untiered), Manny alone (standin_far)
    shown_alone(ucv, name, 'test_parts_missing')
    # the editor game compiles the skinned annotation shader on first use
    wait_until(lambda: person_px(mask_colors(ucv), colour).sum() > 200, timeout=20, interval=1.0)
    ref = {}
    for body in ('test_parts_missing', 'standin_far'):
        shown_alone(ucv, name, body)
        _, person, d = controls(ucv, colour)
        ref[body] = speckle_stats(person, d)
        assert ref[body]['area'] > 800 and ref[body]['isolated'] <= 2, (body, ref[body])
    # standin_near starts on its far twin (standin_far, same mesh: no fade), then goes near with the fade pinned
    j(ucv, f'vbp {name} HoldFade 0.25')
    j(ucv, f'vbp {name} SetBody standin_near')
    assert wait_until(lambda: debug(ucv, name)['fading'], timeout=15), 'crossfade never started'
    for p in (0.25, 0.5, 0.75):
        j(ucv, f'vbp {name} HoldFade {p}')
        time.sleep(0.3)
        dbg = debug(ucv, name)
        assert dbg['fading'] and abs(dbg['fade'] - p) < 0.01 and dbg['visible_meshes'] == 2, dbg
        _, person, d = controls(ucv, colour)
        st = speckle_stats(person, d)
        want = ref['test_parts_missing' if p >= 0.5 else 'standin_far']
        other = ref['standin_far' if p >= 0.5 else 'test_parts_missing']
        assert st['isolated'] <= 2, f'fade {p}: {st} (dither speckle in the seg control)'
        assert st['tiny_holes'] <= want['tiny_holes'] + 3, f'fade {p}: {st} vs alone {want}'
        # one whole body: the right one's area (idle breathing moves it a few %), nearer it than the other one's
        assert st['area'] == pytest.approx(want['area'], rel=0.05), f'fade {p}: {st} vs alone {want} (not one whole body)'
        assert abs(st['area'] - want['area']) < abs(st['area'] - other['area']), f'fade {p}: {st} looks like the other body {other}'
        assert 500 < st['depth_median'] < 700 and st['see_through'] <= 2, f'fade {p}: depth {st}'
        assert debug(ucv, name)['visible_meshes'] == 2, 'lit pass lost the crossfade after an annotation capture'
    j(ucv, f'vbp {name} HoldFade -1')
    assert wait_until(lambda: not debug(ucv, name)['fading'], timeout=5)


@pytest.mark.m6
def test_fade_mask_has_one_id_and_no_extra_colours(world):
    """Wave 2b: during a held fade the mask holds the person's one id and nothing else on the body."""
    ucv, _ = world
    name = spawn(ucv, 'GEN_BP_Pedestrian_Body0', PEDESTRIAN, 0, 0, yaw=180)
    needs_ue(ucv, name)
    colour = (0, 255, 255)
    start_held_fade(ucv, name, 'standin_near', 0.5, colour)
    wait_until(lambda: person_px(mask_colors(ucv), colour).sum() > 200, timeout=20, interval=1.0)
    m, person, _ = controls(ucv, colour)
    ys, xs = np.nonzero(person)
    box = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1].reshape(-1, 3).astype(int)
    floor = m[-1, m.shape[1] // 2].astype(int)
    other = (np.abs(box - colour).max(axis=1) > 3) & (box.sum(axis=1) > 0) & (np.abs(box - floor).max(axis=1) > 3)
    assert other.mean() < 0.01, f'{other.mean():.2%} of the person box has another id'
    j(ucv, f'vbp {name} HoldFade -1')


# --------------------------------------------------------------------------- wave 2b: grooms and outfits
def slot_names(d, old=False):
    return sorted(p['slot'] for p in d['parts'] if p['old'] == old)


@pytest.mark.m6
def test_parts_in_bodies_json_low_never_strands():
    """Bodies.json: every Low (far) body's grooms are cards or helmets, never declared strands, except the
    deliberate test_parts_low case the server must skip."""
    import pathlib
    cfg = json.loads((pathlib.Path(__file__).resolve().parents[1] / 'Config' / 'Bodies.json').read_text())
    lows = {b['far'] for b in cfg['bodies'].values() if b.get('far')}
    for bid in lows:
        for g in cfg['bodies'][bid].get('grooms', []):
            if bid != 'test_parts_low':
                assert isinstance(g, dict) and g.get('geometry') in ('cards', 'helmet'), (bid, g)
    for bid, b in cfg['bodies'].items():
        for part in b.get('grooms', []) + (b['outfit'] if isinstance(b.get('outfit'), list) else [b['outfit']] if b.get('outfit') else []):
            assert isinstance(part, (str, dict)), (bid, part)


@pytest.mark.m6
def test_parts_load_with_tier_and_follow_body(world):
    """Wave 2b: grooms and outfit come with their tier. Far (Low): the helmet groom at its forced non-strands LOD
    and the outfit; the strands-only hair and the declared-strands brows are skipped with warnings. Near (High):
    the strands hair and the outfit; a missing groom and a non-groom asset are skipped. The body shows throughout,
    and clothes follow the body by leader pose."""
    ucv, _ = world
    name = spawn(ucv, 'GEN_BP_Pedestrian_Body0', PEDESTRIAN, 0, 0, yaw=180)
    needs_ue(ucv, name)
    look_from(ucv, -6000, 0, 100)
    r = j(ucv, f'vbp {name} SetBody test_parts')
    assert r['tier'] == 'far' and r['body'] == 'test_parts_low', r
    assert 'strands' in r.get('part_warnings', ''), r
    d = debug(ucv, name)
    assert slot_names(d) == ['hair_helmet', 'outfit'], d['parts']
    for p in d['parts']:
        assert p['parent'] == 'body' and p['visible'], p
        if p['slot'] == 'hair_helmet':
            assert p['class'] == 'GroomComponent' and p['forced_lod'] == 0 and 'GA_StandinHairHelmet' in p['asset'], p
        if p['slot'] == 'outfit':
            assert p['follows_body'] and 'SKM_Quinn' in p['asset'] and p['dither'], p
    look_from(ucv, -600, 0, 100)
    assert wait_until(lambda: (lambda x: x['tier'] == 'near' and not x['fading'])(debug(ucv, name)), timeout=15)
    d = debug(ucv, name)
    assert d['body'] == 'test_parts' and d['tier'] == 'near'
    assert slot_names(d) == ['hair', 'outfit'], d['parts']
    hair = next(p for p in d['parts'] if p['slot'] == 'hair')
    assert hair['class'] == 'GroomComponent' and hair['forced_lod'] == -1 and hair['visible'], hair
    assert 'GA_Missing' in d['part_warnings'] and 'not a GroomAsset' in d['part_warnings'], d['part_warnings']
    assert not [p for p in d['parts'] if p['old']], 'old parts left after the fade'


@pytest.mark.m6
def test_parts_fade_with_body_and_carry_the_seg_id(world):
    """Wave 2b: mid-fade the old parts ride the old body (fade_body), the new ones the new body; at 0.5 exactly one
    set of non-dithering parts is drawn; the mask holds only the person's id (grooms and clothes included), with
    no speckle."""
    ucv, _ = world
    name = spawn(ucv, 'GEN_BP_Pedestrian_Body0', PEDESTRIAN, 0, 0, yaw=180)
    needs_ue(ucv, name)
    colour = (255, 128, 0)
    start_held_fade(ucv, name, 'test_parts', 0.5, colour)
    d = debug(ucv, name)
    old = [p for p in d['parts'] if p['old']]
    new = [p for p in d['parts'] if not p['old']]
    assert old and new, d['parts']
    assert all(p['parent'] == 'fade_body' for p in old) and all(p['parent'] == 'body' for p in new), d['parts']
    for p in old + new:
        if p['class'] == 'GroomComponent':    # no BodyFade on the hair material: a cut at 0.5, new set wins
            assert p['visible'] == (not p['old']), p
        else:
            assert p['dither'] and p['visible'], p
            assert p['body_fade'] == pytest.approx(0.5, abs=0.01), p
    wait_until(lambda: person_px(mask_colors(ucv), colour).sum() > 200, timeout=20, interval=1.0)
    m, person, depth = controls(ucv, colour)
    st = speckle_stats(person, depth)
    assert st['isolated'] <= 2 and st['tiny_holes'] <= 2 and st['see_through'] <= 2, st
    ys, xs = np.nonzero(person)
    box = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1].reshape(-1, 3).astype(int)
    floor = m[-1, m.shape[1] // 2].astype(int)
    other = (np.abs(box - colour).max(axis=1) > 3) & (box.sum(axis=1) > 0) & (np.abs(box - floor).max(axis=1) > 3)
    assert other.mean() < 0.01, f'{other.mean():.2%} of the person box has another id (a part without the annotation material?)'
    j(ucv, f'vbp {name} HoldFade -1')
    assert wait_until(lambda: (lambda x: not x['fading'] and not [p for p in x['parts'] if p['old']])(debug(ucv, name)), timeout=5)


@pytest.mark.m6
def test_missing_parts_skip_and_body_still_shows(world):
    """Wave 2b: a body whose groom and outfit don't exist shows anyway (its own tier, no fallback), with warnings."""
    ucv, _ = world
    name = spawn(ucv, 'GEN_BP_Pedestrian_Body0', PEDESTRIAN, 400, 0)
    needs_ue(ucv, name)
    r = j(ucv, f'vbp {name} SetBody test_parts_missing')
    assert r['body'] == 'test_parts_missing' and r['tier'] == 'near', r
    assert 'GA_Missing' in r['part_warnings'] and 'SKM_MissingOutfit' in r['part_warnings'], r
    d = debug(ucv, name)
    assert d['parts'] == [] and d['visible_meshes'] == 1


@pytest.mark.m6
def test_agent_eye_camera_hides_own_parts(world):
    """Wave 2b: the agent's eye camera doesn't see its own hair or collar (parts are hidden like the face)."""
    ucv, _ = world
    name = spawn(ucv, 'GEN_BP_Humanoid_0', AGENT, 0, 0, 300)
    needs_ue(ucv, name)
    j(ucv, f'vbp {name} SetBody test_parts_missing')   # body only: reference view
    j(ucv, f'vbp {name} SetBody test_parts')            # starts far: helmet + outfit on the body
    time.sleep(1.5)
    d = debug(ucv, name)
    assert d['parts'], d
    ucv.set_color(name, (255, 0, 255))
    ucv.set_camera_resolution(1, (320, 240))
    req(ucv, 'vset /camera/1/rotation -60 0 0')        # look down at own chest
    time.sleep(0.5)
    img = ucv.get_image(1, 'object_mask')[:, :, ::-1]
    own = person_px(img, (255, 0, 255))
    assert own.mean() < 0.002, f'{own.mean():.2%} of the eye view is the agent itself'
