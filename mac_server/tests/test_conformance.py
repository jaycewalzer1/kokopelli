"""SimWorld UnrealCV server conformance suite.

Drives the server through the REAL simworld client classes
(simworld.communicator.UnrealCV / Communicator / WeatherManager /
TrafficController) wherever possible and through raw sockets for the wire
protocol. See docs/SPEC.md for the requirement each test checks (the SPEC
section is given in each docstring).

Run (from anywhere outside the simworld package dir):
    SIMCV_PORT=9000 ~/Desktop/kokopelli/simworld/.venv/bin/python -I -m pytest \
        ~/Desktop/kokopelli/mac_server/tests -m "m0 or m1"
"""
import json
import math
import os
import re
import struct
import threading
import time
import warnings
from io import BytesIO
from types import SimpleNamespace

import numpy as np
import pytest

from conftest import HOST, MAGIC, PORT, purge, req, reset_counters, wait_until

SIMWORLD_ROOT = os.path.expanduser('~/Desktop/kokopelli/simworld')
DATA = os.path.join(SIMWORLD_ROOT, 'data')
DEMO_CITY = os.path.join(DATA, 'example_city', 'demo_city_1')

TREE = '/Game/CityDatabase/blueprints/BP_Tree1.BP_Tree1_C'
AGENT = '/Game/TrafficSystem/Pedestrian/Base_User_Agent.Base_User_Agent_C'
PEDESTRIAN = '/Game/TrafficSystem/Pedestrian/Base_Pedestrian.Base_Pedestrian_C'
UE_MANAGER = '/Game/TrafficSystem/UE_Manager.UE_Manager_C'
WEATHER = '/Game/Weather/BP_WeatherManager.BP_WeatherManager_C'
SCOOTER = '/Game/ScooterAssets/Blueprints/BP_Scooter_Pawn.BP_Scooter_Pawn_C'
DOG = '/Game/Robot_Dog/Blueprint/BP_SpotRobot.BP_SpotRobot_C'
MUG = '/Game/InteractableAsset/Cup/BP_Mug.BP_Mug_C'
BOX = '/Game/InteractableAsset/Box/BP_Interactable_Box.BP_Interactable_Box_C'
CAR_INTERACT = '/Game/Interactable_Vehicle/Blueprint/BP_VehicleBase_Destruction.BP_VehicleBase_Destruction_C'
DEFAULT_CHAR = '/Game/Human_Avatar/DefaultCharacter/Blueprint/BP_Default_Character.BP_Default_Character_C'
TRAFFIC_LIGHT = '/Game/city_props/BP/props/street_light/BP_street_light.BP_street_light_C'
PED_LIGHT = '/Game/city_props/BP/props/street_light/BP_street_light_ped.BP_street_light_ped_C'
VEHICLES = [f'/Game/TrafficSystem/Vehicle/Vehicle{i}.Vehicle{i}_C' for i in range(1, 6)]

NON_CITY_PREFABS = [UE_MANAGER, AGENT, PEDESTRIAN, *VEHICLES, TRAFFIC_LIGHT, PED_LIGHT, SCOOTER,
                    WEATHER, DOG, DEFAULT_CHAR, BOX, MUG, CAR_INTERACT]


def city_prefabs():
    with open(os.path.join(DATA, 'ue_assets.json')) as f:
        d = json.load(f)
    return sorted({v['asset_path'] for k, v in d.items() if k != 'colors'})


def is_error(reply):
    if isinstance(reply, bytes):
        return reply[:5].lower() == b'error'
    return isinstance(reply, str) and reply.lstrip().lower().startswith('error')


def angle_diff(a, b):
    """Signed smallest difference a-b in degrees."""
    return (a - b + 180.0) % 360.0 - 180.0


def loc(ucv, name):
    return ucv.get_location(name)


def yaw(ucv, name):
    return float(ucv.get_orientation(name)[1])


# ==========================================================================
# M0 - wire protocol, handshake, objects, camera png        (SPEC sections 1-3)
# ==========================================================================
@pytest.mark.m0
def test_handshake_bytes(raw):
    """SPEC 1.2: first frame is magic C1 83 2B 9E, LE uint32 size, payload 'connected...'."""
    c = raw()
    hdr = c.recv_exact(8)
    assert hdr[:4] == b'\xc1\x83\x2b\x9e', f'magic bytes {hdr[:4]!r}'
    size = struct.unpack('<I', hdr[4:])[0]
    payload = c.recv_exact(size)
    assert payload.startswith(b'connected'), payload


@pytest.mark.m0
def test_request_id_echoed_verbatim(raw):
    """SPEC 1.3: reply id equals request id, ids need not start at 0 or be contiguous."""
    c = raw()
    c.recv_frame()
    for rid in (41, 7, 123456):
        body = c.request(rid, 'vget /objects')
        assert not is_error(body)


@pytest.mark.m0
def test_pipelined_requests_answered_in_order(raw):
    """SPEC 1.4: N requests sent back-to-back get N replies in send order, errors included."""
    c = raw()
    c.recv_frame()
    cmds = []
    for i in range(30):
        cmds.append(['vget /objects', 'vget /camera/0/location', 'vbogus /nothing', 'vget /object/__nope__/location'][i % 4])
    for i, cmd in enumerate(cmds):
        c.send_frame(b'%d:%s' % (100 + i, cmd.encode()))
    for i, cmd in enumerate(cmds):
        body = c.reply(100 + i)
        if 'bogus' in cmd or '__nope__' in cmd:
            assert is_error(body), (cmd, body)


@pytest.mark.m0
def test_fragmented_frame(raw):
    """SPEC 1.1: TCP is a stream; a frame split across writes must still be parsed."""
    c = raw()
    c.recv_frame()
    payload = b'5:vget /objects'
    frame = struct.pack('<II', MAGIC, len(payload)) + payload
    for i in range(0, len(frame), 3):
        c.sock.sendall(frame[i:i + 3])
        time.sleep(0.01)
    assert not is_error(c.reply(5))


@pytest.mark.m0
def test_reconnect_after_close(raw):
    """SPEC 1.6: server accepts a new client after the previous one disconnects."""
    for _ in range(3):
        c = raw()
        assert c.recv_frame().startswith(b'connected')
        assert not is_error(c.request(1, 'vget /objects'))
        c.close()
        time.sleep(0.3)


@pytest.mark.m0
def test_second_client_does_not_break_first(raw):
    """SPEC 1.6: a second concurrent connection must not disturb the first one."""
    a = raw()
    a.recv_frame()
    b = raw(timeout=2.0)
    try:
        b.recv_frame()  # allowed either way; real UnrealCV refuses it
    except Exception:
        pass
    assert not is_error(a.request(9, 'vget /objects'))


@pytest.mark.m0
def test_simworld_client_connects_without_capability_warnings(holder):
    """SPEC 1.7: `vget /unrealcv/commands` lists templates so unrealcv emits no UserWarning
    for any command simworld sends."""
    holder.drop()
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter('always')
        ucv = holder.get()
    cap = [w for w in rec if issubclass(w.category, UserWarning)]
    assert not cap, [str(w.message) for w in cap]
    client = ucv.client
    assert client._command_capabilities_available, 'server did not return a usable command list'
    samples = [
        'vset /objects/spawn_bp_asset /Game/A.A_C N', 'vset /objects/spawn /Game/A.A_C N',
        'vset /action/clean_garbage', 'vset /object/N/location 1.0 -2 3e-05',
        'vset /object/N/rotation 0 90.0 0', 'vset /object/N/scale 1 1 1', 'vset /object/N/color 255 0 0',
        'vbp N EnableController True', 'vset /object/N/physics False', 'vset /object/N/collision True',
        'vset /object/N/object_mobility True', 'vset /action/set_fixed_frame_rate 30',
        'vset /action/game/pause', 'vset /action/game/resume', 'vset /action/tick_intervel 0.05',
        'vset /action/tick', 'vset /object/N/destroy', 'vget /objects', 'vset /object/N/name M',
        'vbp N GetCollisionNum', 'vget /object/N/location', 'vget /object/N/rotation',
        'vbp N SetState 1 0 0', 'vbp N MakeUTurn', 'vbp M VSetState a,1,0,0;b,0,1,0', 'vbp M PSetState a,1',
        'vbp N StopPedestrian', 'vbp N MoveForward', 'vbp N Rotate_Angle 1 -30 -1', 'vbp N SetMaxSpeed 200',
        'vbp N MovementSimulation', 'vbp N SetWaypoints 1,2;3,4', 'vbp N SwitchVehicleFrontGreen',
        'vbp N SetPedestrianWalk', 'vbp N SetDuration 10 2 30', 'vbp M GetInformation', 'vbp M UpdateObjects',
        'vbp I AddVehicleSignal S', 'vbp I AddPedSignal S', 'vbp I StartSimulation',
        'vbp D Move_Speed 200 1 0', 'vbp D lookup', 'vbp D lookdown', 'vbp N TurnAround 1 90 1',
        'vbp N StopAgent', 'vbp N StepForward 2 0', 'vbp N SitDown', 'vbp N StandUp', 'vbp N GetOnScooter',
        'vbp S GetOffScooter', 'vbp N PickUp O', 'vbp N DropOff', 'vbp N EnterVehicle V', 'vbp N ExitVehicle V',
        'vbp N Discussion 0', 'vbp N Arguing 1', 'vbp N Listening', 'vbp N Wave2Dog', 'vbp N Directing',
        'vbp N StopAction', 'vbp N SetPath 1,2;3,4', 'vbp N FollowPath', 'vget /cameras',
        'vget /camera/1/location', 'vget /camera/1/rotation', 'vget /camera/1/fov', 'vget /camera/1/size',
        'vset /camera/1/location 0 0 0', 'vset /camera/1/rotation 0 0 0', 'vset /camera/1/fov 90',
        'vset /camera/1/size 320 240', 'vget /camera/1/lit png', 'vget /camera/1/depth npy',
        'vget /camera/1/object_mask png', 'vget /camera/1/lit bmp', 'vget /camera/1/lit /tmp/x.png',
        'vbp W SetSunDirection 30 10', 'vbp W GetSunDirection', 'vbp W SetSunIntensity 5',
        'vbp W GetSunIntensity', 'vbp W SetFog 1 2 3', 'vbp W GetFog', 'vbp W SetAtmosphere 1 2',
        'vbp W GetAtmosphere', 'vrun setres 640x480w', 'vrun Editor.AsyncSkinnedAssetCompilation 2',
    ]
    missing = [s for s in samples if not any(client._matches_command_template(s, t)
                                             for t in client._supported_command_templates)]
    assert not missing, f'commands not covered by any template: {missing}'


@pytest.mark.m0
def test_vrun_replies(ucv):
    """SPEC 2.1: vrun console commands always get a reply (client sends them async)."""
    assert req(ucv, 'vrun setres 640x480w') is not None
    assert req(ucv, 'vrun Editor.AsyncSkinnedAssetCompilation 2') is not None


@pytest.mark.m0
def test_objects_list(ucv):
    """SPEC 2.2: `vget /objects` is a non-empty space-separated list (clear_env crashes on empty)."""
    raw = req(ucv, 'vget /objects')
    assert isinstance(raw, str) and not is_error(raw)
    names = ucv.get_objects()
    assert len(names) >= 1
    assert all(n and not re.search(r'\s', n) for n in names)


@pytest.mark.m0
def test_spawn_and_transform_roundtrip(world):
    """SPEC 2.3/2.4: spawn_bp_asset, location (cm), rotation in pitch-yaw-roll order, scale."""
    ucv, _ = world
    assert not is_error(req(ucv, f'vset /objects/spawn_bp_asset {TREE} CT_Tree'))
    assert 'CT_Tree' in ucv.get_objects()
    ucv.set_location((12.5, -30, 40), 'CT_Tree')
    ucv.set_orientation((10, 45, -5), 'CT_Tree')
    ucv.set_scale((2, 0.5, 1.25), 'CT_Tree')
    np.testing.assert_allclose(ucv.get_location('CT_Tree'), [12.5, -30, 40], atol=0.01)
    np.testing.assert_allclose(ucv.get_orientation('CT_Tree'), [10, 45, -5], atol=0.01)
    np.testing.assert_allclose([float(x) for x in req(ucv, 'vget /object/CT_Tree/scale').split()], [2, 0.5, 1.25], atol=1e-3)


@pytest.mark.m0
def test_numeric_token_formats(world):
    """SPEC 2.4: Python str(float) may emit ints, negatives and scientific notation."""
    ucv, _ = world
    req(ucv, f'vset /objects/spawn_bp_asset {TREE} CT_Num')
    req(ucv, 'vset /object/CT_Num/location 1e-05 -2.5E+02 3')
    np.testing.assert_allclose(ucv.get_location('CT_Num'), [0, -250, 3], atol=0.01)
    ucv.set_location((np.float64(0.1), np.int64(7), -0.0), 'CT_Num')
    np.testing.assert_allclose(ucv.get_location('CT_Num'), [0.1, 7, 0], atol=0.01)


@pytest.mark.m0
def test_names_case_insensitive(world):
    """SPEC 2.3: Communicator.clear_env destroys LOWER-CASED names, so lookup is case-insensitive."""
    ucv, _ = world
    req(ucv, f'vset /objects/spawn_bp_asset {TREE} CT_CaseTree')
    ucv.set_location((1, 2, 3), 'ct_casetree')
    np.testing.assert_allclose(ucv.get_location('CT_CASETREE'), [1, 2, 3], atol=0.01)
    assert 'CT_CaseTree' in ucv.get_objects(), 'listing must keep the original spelling'
    ucv.destroy('ct_casetree')
    assert 'CT_CaseTree' not in ucv.get_objects()


@pytest.mark.m0
def test_rename_object(world):
    """SPEC 2.3: `vset /object/A/name B` renames in place (used after GetOffScooter)."""
    ucv, _ = world
    req(ucv, f'vset /objects/spawn_bp_asset {TREE} CT_Old')
    ucv.set_location((5, 6, 7), 'CT_Old')
    ucv.set_object_name('CT_Old', 'CT_New')
    objs = list(ucv.get_objects())
    assert 'CT_New' in objs and 'CT_Old' not in objs
    np.testing.assert_allclose(ucv.get_location('CT_New'), [5, 6, 7], atol=0.01)


@pytest.mark.m0
def test_destroy_and_missing_object_errors(world):
    """SPEC 2.5: unknown object -> reply starting with 'error'; get_location then raises."""
    ucv, _ = world
    req(ucv, f'vset /objects/spawn_bp_asset {TREE} CT_Gone')
    ucv.destroy('CT_Gone')
    ucv.clean_garbage()
    assert 'CT_Gone' not in ucv.get_objects()
    assert is_error(req(ucv, 'vget /object/CT_Gone/location'))
    assert is_error(req(ucv, 'vset /object/CT_Gone/location 1 2 3'))
    with pytest.raises(ValueError):
        ucv.get_location('CT_Gone')


@pytest.mark.m0
def test_flag_setters_accept_python_bools(world):
    """SPEC 2.4: collision/physics/object_mobility/EnableController receive 'True'/'False'."""
    ucv, _ = world
    req(ucv, f'vset /objects/spawn_bp_asset {TREE} CT_Flags')
    for tok in ('True', 'False', 'true', 'false', '1', '0'):
        for prop in ('collision', 'physics', 'object_mobility'):
            r = req(ucv, f'vset /object/CT_Flags/{prop} {tok}')
            assert not is_error(r), (prop, tok, r)
    assert not is_error(req(ucv, 'vset /object/CT_Flags/color 255 128 0'))


@pytest.mark.m0
def test_batch_location_and_rotation(world):
    """SPEC 1.4: request_batch (used by get_location_batch) returns one reply per request."""
    ucv, _ = world
    names = [f'CT_B{i}' for i in range(10)]
    for i, n in enumerate(names):
        req(ucv, f'vset /objects/spawn_bp_asset {TREE} {n}')
        ucv.set_location((i * 100, -i, 0), n)
        ucv.set_orientation((0, i * 10, 0), n)
    locs = ucv.get_location_batch(names)
    rots = ucv.get_orientation_batch(names)
    for i in range(10):
        np.testing.assert_allclose(locs[i], [i * 100, -i, 0], atol=0.01)
        assert abs(angle_diff(rots[i][1], i * 10)) < 0.01


@pytest.mark.m0
def test_camera_list_and_params(ucv):
    """SPEC 3.1: camera 0 exists; location/rotation/fov/size get+set round-trip."""
    cams = ucv.get_cameras()
    assert isinstance(cams, str) and not is_error(cams) and len(cams.split()) >= 1
    ucv.set_camera_location(0, (100, 200, 150))
    ucv.set_camera_rotation(0, (-10, 45, 0))
    ucv.set_camera_fov(0, 75)
    ucv.set_camera_resolution(0, (320, 240))
    np.testing.assert_allclose([float(x) for x in ucv.get_camera_location(0).split()], [100, 200, 150], atol=0.01)
    np.testing.assert_allclose([float(x) for x in ucv.get_camera_rotation(0).split()], [-10, 45, 0], atol=0.01)
    assert abs(float(ucv.get_camera_fov(0)) - 75) < 0.01
    assert [int(float(x)) for x in ucv.get_camera_resolution(0).split()] == [320, 240]
    assert is_error(req(ucv, 'vget /camera/999/location'))


@pytest.mark.m0
def test_camera_png_lit(ucv):
    """SPEC 3.2: `vget /camera/0/lit png` returns an 8-bit RGBA PNG at the camera size."""
    ucv.set_camera_resolution(0, (320, 240))
    res = req(ucv, 'vget /camera/0/lit png')
    assert isinstance(res, bytes), 'image body must not be valid UTF-8'
    assert res[:8] == b'\x89PNG\r\n\x1a\n'
    w, h, depth, ctype = struct.unpack('>IIBB', res[16:26])
    assert (w, h, depth, ctype) == (320, 240, 8, 6), 'expect 8-bit RGBA (color type 6)'
    img = ucv.get_image(0, 'lit')
    assert img.shape == (240, 320, 3) and img.dtype == np.uint8


@pytest.mark.m0
def test_sync_mode_and_tick(ucv):
    """SPEC 2.6: pause/tick/tick_intervel/resume/fixed frame rate are acknowledged."""
    for cmd in ('vset /action/tick_intervel 0.05', 'vset /action/game/pause', 'vset /action/tick',
                'vset /action/tick', 'vset /action/game/resume', 'vset /action/set_fixed_frame_rate 30',
                'vset /action/clean_garbage'):
        assert not is_error(req(ucv, cmd)), cmd
    ucv.set_mode('sync', 0.05)
    ucv.tick()
    ucv.set_mode('async')


@pytest.mark.m0
@pytest.mark.should
def test_throughput(world):
    """SPEC 1.8: >= 200 small requests/s so generate_world (~4.5k requests) is practical."""
    ucv, _ = world
    req(ucv, f'vset /objects/spawn_bp_asset {TREE} CT_Speed')
    t = time.time()
    for i in range(400):
        ucv.set_location((i, 0, 0), 'CT_Speed')
    dt = time.time() - t
    assert dt < 2.0, f'400 vset took {dt:.2f}s'


# ==========================================================================
# M1 - prefab catalog + city generation                    (SPEC sections 4-5)
# ==========================================================================
@pytest.mark.m1
@pytest.mark.parametrize('path', NON_CITY_PREFABS + city_prefabs())
def test_every_prefab_spawns(world, path):
    """SPEC 4: every /Game path the client can spawn must load."""
    ucv, _ = world
    name = 'CT_P_' + path.rsplit('.', 1)[-1]
    r = req(ucv, f'vset /objects/spawn_bp_asset {path} {name}')
    assert not is_error(r), r
    assert name.lower() in [o.lower() for o in ucv.get_objects()]


@pytest.mark.m1
@pytest.mark.should
def test_unknown_prefab_is_error(world):
    """SPEC 2.3: unloadable class -> error reply, nothing spawned."""
    ucv, _ = world
    r = req(ucv, 'vset /objects/spawn_bp_asset /Game/DoesNot/Exist.Exist_C CT_Bad')
    assert is_error(r)
    assert 'CT_Bad' not in ucv.get_objects()


@pytest.mark.m1
def test_duplicate_spawn_name_keeps_single_object(world):
    """SPEC 2.3: spawning an existing name must not create a second object with that name."""
    ucv, _ = world
    req(ucv, f'vset /objects/spawn_bp_asset {TREE} CT_Dup')
    req(ucv, f'vset /objects/spawn_bp_asset {TREE} CT_Dup')
    assert [o.lower() for o in ucv.get_objects()].count('ct_dup') == 1


@pytest.mark.m1
def test_communicator_spawn_object(world):
    """SPEC 5.1: Communicator.spawn_object = spawn + location + rotation + scale + flags."""
    ucv, comm = world
    comm.spawn_object('GEN_BP_Box_1_C', BOX, (1700, -1700, 20), (0, 30, 0))
    np.testing.assert_allclose(ucv.get_location('GEN_BP_Box_1_C'), [1700, -1700, 20], atol=0.5)
    assert abs(angle_diff(yaw(ucv, 'GEN_BP_Box_1_C'), 30)) < 0.5


@pytest.mark.m1
def test_generate_world_demo_city(world):
    """SPEC 5.2: generate_world(demo_city_1) places all 638 nodes at their JSON transforms."""
    ucv, comm = world
    progen = os.path.join(DEMO_CITY, 'progen_world.json')
    assets = os.path.join(DATA, 'ue_assets.json')
    t = time.time()
    ids = comm.generate_world(progen, assets, run_time=True)
    elapsed = time.time() - t
    with open(progen) as f:
        nodes = {n['id']: n for n in json.load(f)['nodes']}
    with open(assets) as f:
        lib = json.load(f)
    # Client data gap: BP_Building_64_C is used by demo_city_1 but missing from
    # ue_assets.json, so generate_world logs an error and skips it (SPEC 4.1).
    nodes = {k: v for k, v in nodes.items() if v['instance_name'] in lib}
    assert ids == set(nodes), f'{len(nodes) - len(ids)} resolvable nodes not generated'
    present = {o.lower() for o in ucv.get_objects()}
    assert all(i.lower() in present for i in nodes)
    rng = np.random.default_rng(0)
    for nid in rng.choice(sorted(nodes), 25, replace=False):
        p = nodes[nid]['properties']
        np.testing.assert_allclose(ucv.get_location(nid), [p['location'][k] for k in 'xyz'], atol=0.5)
        r = ucv.get_orientation(nid)
        assert abs(angle_diff(r[1], p['orientation']['yaw'])) < 0.05
        s = [float(x) for x in req(ucv, f'vget /object/{nid}/scale').split()]
        np.testing.assert_allclose(s, [p['scale'][k] for k in 'xyz'], atol=1e-3)
        col = req(ucv, f'vget /object/{nid}/color')
        want = re.findall(r'\d+', lib['colors'][lib[nodes[nid]['instance_name']]['color']])[:3]
        assert re.findall(r'\d+', col)[:3] == want, (nid, col, want)
    print(f'generate_world: {len(ids)} nodes in {elapsed:.1f}s')


@pytest.mark.m1
def test_clear_env(world):
    """SPEC 5.3: clear_env(keep_roads) destroys GEN_BP_* (and GEN_Road_*) via lower-cased names."""
    ucv, comm = world
    req(ucv, f'vset /objects/spawn_bp_asset /Game/CityDatabase/blueprints/BP_Road1.BP_Road1_C GEN_Road_0')
    req(ucv, f'vset /objects/spawn_bp_asset {TREE} GEN_BP_Tree1_0_1')
    comm.clear_env(keep_roads=True)
    objs = [o.lower() for o in ucv.get_objects()]
    assert 'gen_road_0' in objs and 'gen_bp_tree1_0_1' not in objs
    comm.clear_env(keep_roads=False)
    assert 'gen_road_0' not in [o.lower() for o in ucv.get_objects()]
    assert len(ucv.get_objects()) >= 1, 'level must keep at least one actor'


# ==========================================================================
# M2 - humanoid agent                                       (SPEC 6.1, 6.6)
# ==========================================================================
def spawn_humanoid(ucv, comm, x=0.0, y=0.0, dir_xy=(1, 0), settle=2.0):
    from simworld.agent.humanoid import Humanoid
    from simworld.utils.vector import Vector
    h = Humanoid(Vector(x, y), Vector(*dir_xy))
    comm.spawn_agent(h, None)  # default model path = Base_User_Agent, z = 600
    time.sleep(settle)
    return h, comm.get_humanoid_name(h.id)


def get_info(ucv, comm):
    raw = ucv.get_informations(comm.ue_manager_name)
    return json.loads(raw)


@pytest.mark.m2
def test_humanoid_spawn_adds_camera(world):
    """SPEC 3.1/6.1: each Base_User_Agent adds camera id = humanoid.id + 1."""
    ucv, comm = world
    n0 = len(ucv.get_cameras().split())
    h, name = spawn_humanoid(ucv, comm)
    assert name == 'GEN_BP_Humanoid_0' and name in ucv.get_objects()
    assert len(ucv.get_cameras().split()) == n0 + 1
    assert h.camera_id == 1
    ucv.set_camera_resolution(h.camera_id, (320, 240))
    img = comm.get_camera_observation(h.camera_id, 'lit')
    assert img.shape == (240, 320, 3), 'got the 480x640 zero fallback -> capture failed'
    cam = np.array([float(v) for v in ucv.get_camera_location(h.camera_id).split()])
    assert np.linalg.norm(cam[:2] - loc(ucv, name)[:2]) < 300, 'agent camera must ride with the agent'


@pytest.mark.m2
def test_humanoid_falls_to_ground(world):
    """SPEC 6.1: spawned at z=600 the character falls onto the ground (gravity on)."""
    ucv, comm = world
    _, name = spawn_humanoid(ucv, comm, settle=0.1)
    assert wait_until(lambda: loc(ucv, name)[2] < 300, timeout=5), loc(ucv, name)


@pytest.mark.m2
def test_humanoid_move_forward_and_stop(world):
    """SPEC 6.1: MoveForward walks along +yaw at SetMaxSpeed cm/s until StopAgent."""
    ucv, comm = world
    h, name = spawn_humanoid(ucv, comm)
    comm.humanoid_set_speed(h.id, 200)
    p0 = loc(ucv, name)
    comm.humanoid_move_forward(h.id)
    time.sleep(1.5)
    comm.humanoid_stop(h.id)
    time.sleep(0.7)
    p1 = loc(ucv, name)
    d = p1 - p0
    assert 120 < d[0] < 450 and abs(d[1]) < 60, d
    time.sleep(1.0)
    assert np.linalg.norm(loc(ucv, name)[:2] - p1[:2]) < 15, 'agent kept moving after StopAgent'


@pytest.mark.m2
@pytest.mark.parametrize('direction,sign', [('right', 1), ('left', -1)])
def test_humanoid_rotate(world, direction, sign):
    """SPEC 6.1: TurnAround right = +yaw, left = -yaw, completes within the client's 1 s sleep."""
    ucv, comm = world
    h, name = spawn_humanoid(ucv, comm)
    y0 = yaw(ucv, name)
    comm.humanoid_rotate(h.id, 90, direction)  # sleeps 1 s client-side
    time.sleep(0.3)
    assert abs(angle_diff(yaw(ucv, name), y0 + sign * 90)) < 5


@pytest.mark.m2
@pytest.mark.parametrize('direction,sign', [(0, 1), (1, -1)])
def test_humanoid_step_forward(world, direction, sign):
    """SPEC 6.1: StepForward <duration> <0 fwd|1 back> moves ~speed*duration, returns immediately."""
    ucv, comm = world
    h, name = spawn_humanoid(ucv, comm)
    comm.humanoid_set_speed(h.id, 200)
    p0 = loc(ucv, name)
    t = time.time()
    with ucv.lock:
        ucv.client.request(f'vbp {name} StepForward 1 {direction}')
    assert time.time() - t < 0.5, 'StepForward must not block the reply'
    time.sleep(1.8)
    d = loc(ucv, name) - p0
    assert 80 < sign * d[0] < 350 and abs(d[1]) < 60, d


@pytest.mark.m2
def test_humanoid_teleport(world):
    """SPEC 2.4: vset location on a character teleports it (used by gym reset)."""
    ucv, comm = world
    _, name = spawn_humanoid(ucv, comm)
    ucv.set_location((500, -500, 600), name)
    ucv.set_orientation((0, 90, 0), name)
    time.sleep(1.5)
    p = loc(ucv, name)
    assert np.linalg.norm(p[:2] - [500, -500]) < 20
    assert abs(angle_diff(yaw(ucv, name), 90)) < 2


@pytest.mark.m2
def test_collision_counts(world):
    """SPEC 6.1: GetCollisionNum -> JSON with 4 integer-like fields."""
    ucv, comm = world
    h, _ = spawn_humanoid(ucv, comm)
    counts = comm.get_collision_number(h.id)
    assert len(counts) == 4 and all(isinstance(c, int) and c >= 0 for c in counts)


@pytest.mark.m2
def test_ue_manager_reports_humanoid(world):
    """SPEC 6.6: GetInformation JSON has 9 string fields; ALocations parse via the client regex."""
    ucv, comm = world
    h, name = spawn_humanoid(ucv, comm)
    comm.spawn_ue_manager(UE_MANAGER)
    time.sleep(0.5)
    info = get_info(ucv, comm)
    for k in ('VLocations', 'VRotations', 'PLocations', 'PRotations', 'LStates',
              'ALocations', 'ARotations', 'SLocations', 'SRotations'):
        assert isinstance(info.get(k), str), k
    res = comm.get_position_and_direction(humanoid_ids=[h.id])
    pos, direction = res[('humanoid', h.id)]
    p = loc(ucv, name)
    assert abs(pos.x - p[0]) < 5 and abs(pos.y - p[1]) < 5
    assert abs(angle_diff(direction, yaw(ucv, name))) < 1


@pytest.mark.m2
def test_ue_manager_update_objects_sees_late_spawns(world):
    """SPEC 6.6: actors spawned after the manager appear after UpdateObjects."""
    ucv, comm = world
    comm.spawn_ue_manager(UE_MANAGER)
    h, _ = spawn_humanoid(ucv, comm)
    comm.update_objects()
    time.sleep(0.3)
    assert ('humanoid', h.id) in comm.get_position_and_direction(humanoid_ids=[h.id])


# ==========================================================================
# M3 - vehicles, pedestrians, traffic signals                (SPEC 6.2-6.4)
# ==========================================================================
def ns_agent(i, x, y, dx=1, dy=0, **kw):
    from simworld.utils.vector import Vector
    return SimpleNamespace(id=i, position=Vector(x, y), direction=Vector(dx, dy), **kw)


@pytest.mark.m3
def test_vehicle_throttle_brake(world):
    """SPEC 6.2: SetState throttle drives along +yaw; brake stops; manager VLocations agree."""
    ucv, comm = world
    comm.spawn_vehicles([ns_agent(0, 0, 0, vehicle_reference=VEHICLES[0])])
    comm.spawn_ue_manager(UE_MANAGER)
    name = comm.get_vehicle_name(0)
    time.sleep(1.0)
    p0 = loc(ucv, name)
    comm.update_vehicle(0, 1, 0, 0)
    time.sleep(2.0)
    comm.update_vehicle(0, 0, 1, 0)
    time.sleep(2.5)
    p1 = loc(ucv, name)
    assert p1[0] - p0[0] > 150 and abs(p1[1] - p0[1]) < 150, p1 - p0
    time.sleep(1.0)
    assert np.linalg.norm(loc(ucv, name)[:2] - p1[:2]) < 30, 'vehicle did not stop under brake'
    pos, direction = comm.get_position_and_direction(vehicle_ids=[0])[('vehicle', 0)]
    assert abs(pos.x - p1[0]) < 50 and abs(pos.y - p1[1]) < 50


@pytest.mark.m3
def test_vehicle_batch_state_via_manager(world):
    """SPEC 6.6: VSetState 'name,t,b,s;name,t,b,s' controls several vehicles at once."""
    ucv, comm = world
    comm.spawn_vehicles([ns_agent(0, 0, 0, vehicle_reference=VEHICLES[1]),
                         ns_agent(1, 0, 1500, vehicle_reference=VEHICLES[2])])
    comm.spawn_ue_manager(UE_MANAGER)
    time.sleep(1.0)
    p0 = [loc(ucv, comm.get_vehicle_name(i)) for i in (0, 1)]
    comm.update_vehicles({0: (1, 0, 0), 1: (1, 0, 0)})
    time.sleep(2.0)
    comm.update_vehicles({0: (0, 1, 0), 1: (0, 1, 0)})
    time.sleep(2.0)
    for i in (0, 1):
        assert loc(ucv, comm.get_vehicle_name(i))[0] - p0[i][0] > 150


@pytest.mark.m3
def test_vehicle_u_turn(world):
    """SPEC 6.2: MakeUTurn + SetState(0.05,0,-1) eventually reverses heading (>150 deg)."""
    ucv, comm = world
    comm.spawn_vehicles([ns_agent(0, 0, 0, vehicle_reference=VEHICLES[0])])
    name = comm.get_vehicle_name(0)
    time.sleep(1.0)
    y0 = yaw(ucv, name)
    comm.vehicle_make_u_turn(0)
    comm.update_vehicle(0, 0.05, 0, -1)
    assert wait_until(lambda: abs(angle_diff(yaw(ucv, name), y0)) > 150, timeout=20, interval=0.5)


@pytest.mark.m3
def test_pedestrian_move_rotate_stop(world):
    """SPEC 6.3: Base_Pedestrian SetMaxSpeed/MoveForward/StopPedestrian/Rotate_Angle."""
    ucv, comm = world
    comm.spawn_pedestrians([ns_agent(0, 0, 0)], PEDESTRIAN)
    name = comm.get_pedestrian_name(0)
    time.sleep(1.5)
    comm.set_pedestrian_speed(0, 200)
    p0 = loc(ucv, name)
    comm.pedestrian_move_forward(0)
    time.sleep(1.5)
    comm.pedestrian_stop(0)
    time.sleep(0.7)
    p1 = loc(ucv, name)
    assert 100 < p1[0] - p0[0] < 450, p1 - p0
    y0 = yaw(ucv, name)
    comm.pedestrian_rotate(0, 90, 'right')
    time.sleep(1.5)
    assert abs(angle_diff(yaw(ucv, name), y0 + 90)) < 8


@pytest.mark.m3
def test_traffic_signal_states(world):
    """SPEC 6.4/6.6: LStates '<name>(true|false)(true|false)<float>' and the green->not-green cycle."""
    ucv, comm = world
    sigs = [ns_agent(0, 0, 0, type='both'), ns_agent(1, 500, 0, type='pedestrian')]
    comm.spawn_traffic_signals(sigs, TRAFFIC_LIGHT, PED_LIGHT)
    comm.spawn_ue_manager(UE_MANAGER)
    time.sleep(0.5)
    comm.traffic_signal_set_duration(0, 2, 1, 3)
    comm.traffic_signal_set_duration(1, 2, 1, 3)
    comm.traffic_signal_switch_to(0, 'green')
    time.sleep(0.3)
    st = comm.get_position_and_direction(traffic_signal_ids=[0, 1])
    green, walk, left = st[('traffic_signal', 0)]
    assert green and not walk and 0 < left <= 2.0
    time.sleep(0.6)
    assert comm.get_position_and_direction(traffic_signal_ids=[0])[('traffic_signal', 0)][2] < left
    time.sleep(3.0)
    assert not comm.get_position_and_direction(traffic_signal_ids=[0])[('traffic_signal', 0)][0]
    comm.traffic_signal_switch_to(1, 'pedestrian walk')
    time.sleep(0.3)
    green, walk, left = comm.get_position_and_direction(traffic_signal_ids=[1])[('traffic_signal', 1)]
    assert walk and not green and 0 < left <= 3.0


@pytest.mark.m3
def test_traffic_controller_smoke(world, tmp_path):
    """SPEC 5.4: the real TrafficController runs on demo_city_1 and vehicles move."""
    ucv, comm = world
    from simworld.config import Config
    from simworld.traffic.controller.traffic_controller import TrafficController
    cfg = tmp_path / 'cfg.yaml'
    cfg.write_text(f"traffic:\n  map_path: '{DEMO_CITY}/roads.json'\n  vehicle:\n"
                   f"    model_file_path: '{DATA}/vehicle_types.json'\n")
    config = Config(str(cfg))
    tc = TrafficController(config, 4, 4, f'{DEMO_CITY}/roads.json', 1, 0.2)
    tc.init_communicator(comm)
    tc.spawn_objects_in_unreal_engine()
    comm.spawn_ue_manager(config['simworld.ue_manager_path'])
    time.sleep(1.0)
    start = {v.id: loc(ucv, comm.get_vehicle_name(v.id)) for v in tc.vehicles}
    stop = threading.Event()
    th = threading.Thread(target=tc.simulation, args=(tc.update_states, stop), daemon=True)
    th.start()
    time.sleep(10)
    stop.set()
    th.join(timeout=10)
    moved = [vid for vid, p in start.items()
             if np.linalg.norm(loc(ucv, comm.get_vehicle_name(vid))[:2] - p[:2]) > 100]
    assert moved, 'no vehicle moved during 10 s of simulation'


# ==========================================================================
# M4 - capture modes + weather                              (SPEC 3.2-3.4, 6.7)
# ==========================================================================
@pytest.mark.m4
def test_depth_npy(ucv):
    """SPEC 3.3: depth npy = float (H,W) array, finite, positive, not constant."""
    ucv.set_camera_resolution(0, (160, 120))
    ucv.set_camera_location(0, (0, 0, 300))
    ucv.set_camera_rotation(0, (-20, 0, 0))
    res = req(ucv, 'vget /camera/0/depth npy')
    assert isinstance(res, bytes) and res[:6] == b'\x93NUMPY'
    d = np.load(BytesIO(res))
    assert d.shape == (120, 160) and d.dtype.kind == 'f'
    assert np.isfinite(d).all() and (d > 0).all() and d.max() > d.min()
    img = ucv.get_image(0, 'depth')
    assert img.shape == (120, 160, 3)


@pytest.mark.m4
def test_bmp_and_file_modes(ucv, tmp_path):
    """SPEC 3.2: 'fast' bmp decodes to (H,W,3); filename mode saves a file and returns its path."""
    ucv.set_camera_resolution(0, (161, 97))  # odd width exercises BMP row padding
    res = req(ucv, 'vget /camera/0/lit bmp')
    assert isinstance(res, bytes) and res[:2] == b'BM'
    assert ucv.get_image(0, 'lit', mode='fast').shape == (97, 161, 3)
    path = str(tmp_path / 'cap.png')
    img = ucv.get_image(0, 'lit', mode='file_path', img_path=path)
    assert os.path.exists(path) and img.shape == (97, 161, 3)


@pytest.mark.m4
def test_object_mask_uses_set_color(world):
    """SPEC 3.4: object_mask paints each actor with its `vset /object/X/color` RGB."""
    ucv, _ = world
    req(ucv, 'vset /objects/spawn_bp_asset /Game/CityDatabase/blueprints/BP_Building_01.BP_Building_01_C CT_MaskBldg')
    ucv.set_location((3000, 0, 0), 'CT_MaskBldg')
    ucv.set_scale((3, 3, 3), 'CT_MaskBldg')
    ucv.set_color('CT_MaskBldg', (255, 0, 255))
    ucv.set_camera_resolution(0, (160, 120))
    ucv.set_camera_location(0, (0, 0, 300))
    ucv.set_camera_rotation(0, (0, 0, 0))
    time.sleep(0.5)
    mask = ucv.get_image(0, 'object_mask')[:, :, ::-1]  # client returns BGR -> RGB
    hit = (np.abs(mask.astype(int) - [255, 0, 255]).max(axis=2) <= 3).mean()
    assert hit > 0.01, f'only {hit:.3%} of mask pixels have the object color'


@pytest.mark.m4
def test_weather_roundtrip(world):
    """SPEC 6.7: WeatherManager set/get for sun direction, intensity, fog, atmosphere."""
    ucv, comm = world
    from simworld.weather.weather_manager import WeatherManager
    wm = WeatherManager(comm)
    wm.spawn()
    time.sleep(0.5)
    wm.set_sun_direction(30, 370)
    assert np.allclose(comm.get_sun_direction(wm.name), (30, 10), atol=0.5)
    raw = ucv.get_sun_direction(wm.name)
    assert re.search(r'P=[-\d.]+ Y=[-\d.]+ R=[-\d.]+', json.loads(re.sub(r'[\r\n\t]', '', raw))['rotation'])
    wm.set_sun_intensity(7.5)
    assert abs(comm.get_sun_intensity(wm.name) - 7.5) < 0.01
    wm.set_fog(40, 2000, 1.5)
    assert np.allclose(comm.get_fog(wm.name), (40, 2000, 1.5), atol=0.01)
    wm.set_atmosphere(1.5, 2.0)
    assert np.allclose(comm.get_atmosphere(wm.name), (1.5, 2.0), atol=0.01)


@pytest.mark.m4
@pytest.mark.should
def test_sun_intensity_changes_lit_image(world):
    """SPEC 6.7: lighting changes are visible in lit captures."""
    ucv, comm = world
    from simworld.weather.weather_manager import WeatherManager
    wm = WeatherManager(comm)
    wm.spawn()
    ucv.set_camera_resolution(0, (160, 120))
    ucv.set_camera_location(0, (0, 0, 300))
    ucv.set_camera_rotation(0, (-30, 0, 0))
    wm.set_sun_intensity(0)
    time.sleep(1.0)
    dark = ucv.get_image(0, 'lit').mean()
    wm.set_sun_intensity(10)
    time.sleep(1.0)
    bright = ucv.get_image(0, 'lit').mean()
    assert bright - dark > 5, (dark, bright)


# ==========================================================================
# M5 - actions                                              (SPEC 6.1, 6.5, 6.8)
# ==========================================================================
def success_call(ucv, cmd):
    with ucv.lock:
        r = ucv.client.request(cmd)
    return r, str(json.loads(r)['Success'])


@pytest.mark.m5
def test_sit_stand_return_string_bools(world):
    """SPEC 6.1: SitDown/StandUp reply {"Success":"true"|"false"} (string, lower case)."""
    ucv, comm = world
    _, name = spawn_humanoid(ucv, comm)
    for fn in ('SitDown', 'StandUp'):
        r, s = success_call(ucv, f'vbp {name} {fn}')
        assert s in ('true', 'false'), r
    assert ucv.humanoid_sit_down(name) in (True, False)
    time.sleep(2)
    assert ucv.humanoid_stand_up(name) in (True, False)


@pytest.mark.m5
def test_pick_up_and_drop(world):
    """SPEC 6.1/6.8: PickUp near object -> true and object follows; far -> false; DropOff."""
    ucv, comm = world
    h, name = spawn_humanoid(ucv, comm)
    p = loc(ucv, name)
    comm.spawn_object('BP_Mug_C_1', MUG, (p[0] + 60, p[1], 0), (0, 0, 0))
    comm.spawn_object('BP_Mug_C_2', MUG, (p[0] + 5000, p[1], 0), (0, 0, 0))
    time.sleep(0.5)
    assert ucv.humanoid_pick_up_object(name, 'BP_Mug_C_2') is False
    assert ucv.humanoid_pick_up_object(name, 'BP_Mug_C_1') is True
    time.sleep(2.0)
    m0 = loc(ucv, 'BP_Mug_C_1')
    comm.humanoid_set_speed(h.id, 200)
    comm.humanoid_move_forward(h.id)
    time.sleep(1.0)
    comm.humanoid_stop(h.id)
    time.sleep(0.5)
    assert np.linalg.norm(loc(ucv, 'BP_Mug_C_1')[:2] - m0[:2]) > 80, 'held object did not follow'
    assert ucv.humanoid_drop_object(name) is True


@pytest.mark.m5
def test_heavy_box_pick_up(world):
    """SPEC 6.8: BP_Interactable_Box pick-up replies a Success string."""
    ucv, comm = world
    _, name = spawn_humanoid(ucv, comm)
    p = loc(ucv, name)
    comm.spawn_object('BP_Interactable_Box_C_1', BOX, (p[0] + 70, p[1], 0), (0, 0, 0))
    assert ucv.humanoid_pick_up_object(name, 'BP_Interactable_Box_C_1') in (True, False)
    assert ucv.humanoid_drop_object(name) in (True, False)


@pytest.mark.m5
def test_enter_exit_vehicle(world):
    """SPEC 6.8: EnterVehicle/ExitVehicle on BP_VehicleBase_Destruction."""
    ucv, comm = world
    _, name = spawn_humanoid(ucv, comm)
    p = loc(ucv, name)
    car = 'BP_VehicleBase_Destruction_C_1'
    comm.spawn_object(car, CAR_INTERACT, (p[0] + 100, p[1] + 200, 0), (0, 0, 0))
    time.sleep(0.5)
    assert ucv.humanoid_enter_vehicle(name, car) is True
    time.sleep(3)
    assert np.linalg.norm(loc(ucv, name)[:2] - loc(ucv, car)[:2]) < 300
    assert ucv.humanoid_exit_vehicle(name, car) is True


@pytest.mark.m5
def test_gestures(world):
    """SPEC 6.1: gesture/animation functions are accepted."""
    ucv, comm = world
    _, name = spawn_humanoid(ucv, comm)
    for cmd in ('Discussion 0', 'Discussion 1', 'StopAction', 'Arguing 0', 'Arguing 1', 'StopAction',
                'Listening', 'StopAction', 'Directing', 'Wave2Dog', 'StopAction'):
        assert not is_error(req(ucv, f'vbp {name} {cmd}')), cmd
        time.sleep(0.2)


@pytest.mark.m5
def test_scooter_cycle(world):
    """SPEC 6.5: GetOnScooter removes the humanoid; scooter drives; GetOffScooter spawns a
    Base_User_Agent_C_* that the client renames back to GEN_BP_Humanoid_<id>."""
    ucv, comm = world
    from simworld.agent.scooter import Scooter
    from simworld.utils.vector import Vector
    h, name = spawn_humanoid(ucv, comm, 0, 0, (0, 1))
    sc = Scooter(Vector(100, 0), Vector(0, 1))
    comm.spawn_scooter(sc, SCOOTER)
    sname = comm.get_scooter_name(sc.id)
    time.sleep(1.0)
    comm.humanoid_get_on_scooter(h.id)
    time.sleep(2.0)
    assert name.lower() not in [o.lower() for o in ucv.get_objects()], 'rider actor should be gone'
    s0 = loc(ucv, sname)
    comm.set_scooter_attributes(sc.id, 1, 0, 0)
    time.sleep(2.0)
    comm.set_scooter_attributes(sc.id, 0, 1, 0)
    time.sleep(1.5)
    assert np.linalg.norm(loc(ucv, sname)[:2] - s0[:2]) > 80, 'scooter did not move'
    comm.humanoid_get_off_scooter(h.id, sc.id)
    time.sleep(0.5)
    assert name in ucv.get_objects()
    assert np.linalg.norm(loc(ucv, name)[:2] - loc(ucv, sname)[:2]) < 300


@pytest.mark.m5
def test_robot_dog(world):
    """SPEC 6.9: BP_SpotRobot Move_Speed / Rotate_Angle / lookup / lookdown, owns a camera."""
    ucv, comm = world
    n0 = len(ucv.get_cameras().split())
    ucv.spawn_bp_asset(DOG, 'Demo_Robot')
    ucv.set_location((0, 0, 20), 'Demo_Robot')
    ucv.enable_controller('Demo_Robot', True)
    time.sleep(1.0)
    assert len(ucv.get_cameras().split()) == n0 + 1
    p0 = loc(ucv, 'Demo_Robot')
    y0 = yaw(ucv, 'Demo_Robot')
    ucv.dog_move('Demo_Robot', [200, 1, 0])  # sleeps 1 s
    time.sleep(0.7)
    assert 80 < loc(ucv, 'Demo_Robot')[0] - p0[0] < 400
    ucv.dog_rotate('Demo_Robot', [0.7, 90, 1])
    time.sleep(0.7)
    assert abs(angle_diff(yaw(ucv, 'Demo_Robot'), y0 + 90)) < 10
    assert not is_error(req(ucv, 'vbp Demo_Robot lookup'))
    assert not is_error(req(ucv, 'vbp Demo_Robot lookdown'))


@pytest.mark.m5
@pytest.mark.should
def test_pedestrian_waypoints(world):
    """SPEC 6.3: SetWaypoints 'x,y;x,y' + MovementSimulation walks the polyline."""
    ucv, comm = world
    from simworld.utils.vector import Vector
    comm.spawn_pedestrians([ns_agent(0, 0, 0)], PEDESTRIAN)
    time.sleep(1.5)
    comm.set_pedestrian_speed(0, 200)
    comm.p_set_waypoints(0, [Vector(500, 0), Vector(500, 500)])
    ucv.p_movement_simulation(comm.get_pedestrian_name(0))
    name = comm.get_pedestrian_name(0)
    assert wait_until(lambda: np.linalg.norm(loc(ucv, name)[:2] - [500, 500]) < 150, timeout=15, interval=0.5)


@pytest.mark.m5
@pytest.mark.should
def test_humanoid_set_follow_path(world):
    """SPEC 6.1: SetPath 'x,y;x,y' + FollowPath walks the polyline."""
    ucv, comm = world
    h, name = spawn_humanoid(ucv, comm)
    comm.humanoid_set_speed(h.id, 200)
    ucv.humanoid_set_path(name, '400,0;400,400')
    ucv.humanoid_follow_path(name)
    assert wait_until(lambda: np.linalg.norm(loc(ucv, name)[:2] - [400, 400]) < 150, timeout=15, interval=0.5)
