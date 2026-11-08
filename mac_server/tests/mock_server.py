#!/usr/bin/env python3
"""Pure-Python mock of the SimWorld UnrealCV server (stdlib only).

Speaks the exact UnrealCV wire protocol described in docs/SPEC.md section 1
and implements enough state for the M0 and M1 conformance tests:

* handshake, id echo, pipelined requests, `vget /unrealcv/commands`
* object registry (spawn / location / rotation / scale / color / flags /
  rename / destroy) with case-insensitive name lookup
* cameras (camera 0 = level camera) returning tiny valid RGBA PNG, BMP, NPY
* `vrun`, `/action/*` acknowledgements

It does NOT simulate anything: every `vbp` call returns an error string so
that M2+ tests fail fast instead of hanging. Exception: the body commands
(`vbp <actor> SetBody <id>`, `GetBody`, `vget /bodies`; city/bodies/PLAN.md), which
follow Config/Bodies.json with the same reply shapes as the UE server. A mesh counts
as loadable when its .uasset exists under Content/; the tier is "far" for a body
with a Low twin (the mock has no cameras), "fallback" after a fallback step. The point of this file is to
validate the conformance tests themselves, not to replace the UE server.

Usage:
    python3 mock_server.py [--host 127.0.0.1] [--port 9000] [--assets PATH] [-v]
Port defaults to $SIMCV_PORT, then 9000.
"""
import argparse
import json
import math
import os
import re
import socket
import struct
import sys
import threading
import zlib
from array import array

MAGIC = 0x9E2B83C1
HDR = struct.Struct('<II')

# Non-city prefabs referenced by simworld code, configs and notebooks.
KNOWN_PREFABS = [
    '/Game/TrafficSystem/UE_Manager.UE_Manager_C',
    '/Game/TrafficSystem/Pedestrian/Base_User_Agent.Base_User_Agent_C',
    '/Game/TrafficSystem/Pedestrian/Base_Pedestrian.Base_Pedestrian_C',
    '/Game/TrafficSystem/Vehicle/Vehicle1.Vehicle1_C',
    '/Game/TrafficSystem/Vehicle/Vehicle2.Vehicle2_C',
    '/Game/TrafficSystem/Vehicle/Vehicle3.Vehicle3_C',
    '/Game/TrafficSystem/Vehicle/Vehicle4.Vehicle4_C',
    '/Game/TrafficSystem/Vehicle/Vehicle5.Vehicle5_C',
    '/Game/city_props/BP/props/street_light/BP_street_light.BP_street_light_C',
    '/Game/city_props/BP/props/street_light/BP_street_light_ped.BP_street_light_ped_C',
    '/Game/ScooterAssets/Blueprints/BP_Scooter_Pawn.BP_Scooter_Pawn_C',
    '/Game/Weather/BP_WeatherManager.BP_WeatherManager_C',
    '/Game/Robot_Dog/Blueprint/BP_SpotRobot.BP_SpotRobot_C',
    '/Game/Human_Avatar/DefaultCharacter/Blueprint/BP_Default_Character.BP_Default_Character_C',
    '/Game/InteractableAsset/Box/BP_Interactable_Box.BP_Interactable_Box_C',
    '/Game/InteractableAsset/Cup/BP_Mug.BP_Mug_C',
    '/Game/Interactable_Vehicle/Blueprint/BP_VehicleBase_Destruction.BP_VehicleBase_Destruction_C',
]
# Prefabs whose instances own a camera sensor (appear in `vget /cameras`).
CAMERA_PREFABS = (
    'Base_User_Agent_C', 'BP_SpotRobot_C', 'BP_Default_Character_C',
)
CITY_RE = re.compile(r'^/Game/CityDatabase/blueprints/[A-Za-z0-9_]+\.[A-Za-z0-9_]+_C$')

# Command templates reported by `vget /unrealcv/commands`. Placeholders match
# one whitespace-free token (see unrealcv.Client._matches_command_template).
TEMPLATES = [
    'vget /unrealcv/commands',
    'vget /unrealcv/status',
    'vget /objects',
    'vget /bodies',
    'vset /objects/spawn [str] [str]',
    'vset /objects/spawn_bp_asset [str] [str]',
    'vget /object/[str]/location',
    'vset /object/[str]/location [float] [float] [float]',
    'vget /object/[str]/rotation',
    'vset /object/[str]/rotation [float] [float] [float]',
    'vget /object/[str]/scale',
    'vset /object/[str]/scale [float] [float] [float]',
    'vget /object/[str]/color',
    'vset /object/[str]/color [uint] [uint] [uint]',
    'vset /object/[str]/physics [bool]',
    'vset /object/[str]/collision [bool]',
    'vset /object/[str]/object_mobility [bool]',
    'vset /object/[str]/name [str]',
    'vset /object/[str]/destroy',
    'vset /object/[str]/hide',
    'vset /object/[str]/show',
    'vget /object/[str]/uclass_name',
    'vset /action/clean_garbage',
    'vset /action/game/pause',
    'vset /action/game/resume',
    'vget /action/game/is_paused',
    'vset /action/tick',
    'vset /action/tick_intervel [float]',
    'vset /action/set_fixed_frame_rate [float]',
    'vget /cameras',
    'vget /camera/[uint]/location',
    'vset /camera/[uint]/location [float] [float] [float]',
    'vget /camera/[uint]/rotation',
    'vset /camera/[uint]/rotation [float] [float] [float]',
    'vget /camera/[uint]/fov',
    'vset /camera/[uint]/fov [float]',
    'vget /camera/[uint]/size',
    'vset /camera/[uint]/size [uint] [uint]',
    'vget /camera/[uint]/lit [str]',
    'vget /camera/[uint]/depth [str]',
    'vget /camera/[uint]/object_mask [str]',
    'vget /camera/[uint]/normal [str]',
    'vrun [str]',
    'vrun [str] [str]',
    'vrun [str] [str] [str]',
] + ['vbp [str] [str]' + ' [str]' * n for n in range(0, 9)]

LEVEL_ACTORS = ['Floor', 'PlayerStart', 'DirectionalLight', 'SkyLight',
                'SkyAtmosphere', 'ExponentialHeightFog', 'PostProcessVolume']


# --------------------------------------------------------------------------
# Binary image encoders (stdlib only)
# --------------------------------------------------------------------------
def _png_chunk(tag, data):
    return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)


def encode_png_rgba(w, h, row_fn):
    """row_fn(y) -> bytes of length 4*w (RGBA)."""
    raw = bytearray()
    for y in range(h):
        raw += b'\x00' + row_fn(y)
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (b'\x89PNG\r\n\x1a\n' + _png_chunk(b'IHDR', ihdr)
            + _png_chunk(b'IDAT', zlib.compress(bytes(raw), 1)) + _png_chunk(b'IEND', b''))


def encode_bmp_bgr(w, h, rgb):
    """Solid-color 24-bit bottom-up BMP. rgb must contain a byte >= 0x80 so the
    payload is never valid UTF-8 (see SPEC 1.5)."""
    stride = ((24 * w + 31) // 32) * 4
    row = bytes([rgb[2], rgb[1], rgb[0]]) * w
    row += b'\x00' * (stride - len(row))
    pixels = row * h
    off = 14 + 40
    file_hdr = b'BM' + struct.pack('<IHHI', off + len(pixels), 0, 0, off)
    info = struct.pack('<IiiHHIIiiII', 40, w, h, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    return file_hdr + info + pixels


def encode_npy_f32(w, h, value_fn):
    header = "{'descr': '<f4', 'fortran_order': False, 'shape': (%d, %d), }" % (h, w)
    pad = 64 - ((10 + len(header) + 1) % 64)
    header = header + ' ' * pad + '\n'
    data = array('f')
    for y in range(h):
        v = value_fn(y)
        data.extend([v] * w)
    if sys.byteorder != 'little':
        data.byteswap()
    return b'\x93NUMPY\x01\x00' + struct.pack('<H', len(header)) + header.encode('latin1') + data.tobytes()


# --------------------------------------------------------------------------
# World state
# --------------------------------------------------------------------------
HUMAN_PREFABS = ('Base_User_Agent_C', 'BP_Default_Character_C', 'Base_Pedestrian_C')
CONTENT_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Content'))


class Bodies:
    """Config/Bodies.json, resolved the way SWCharacterBase does (fallback chain, then placeholder)."""

    def __init__(self, path):
        self.path = path
        self.data = {}
        if path and os.path.exists(path):
            with open(path) as f:
                self.data = json.load(f)
        self.bodies = self.data.get('bodies', {})
        self.actors = {k.lower(): v for k, v in self.data.get('actors', {}).items()}

    @staticmethod
    def loadable(mesh):
        if not mesh or not mesh.startswith('/Game/'):
            return False
        pkg = mesh.split('.', 1)[0][len('/Game/'):]
        return os.path.exists(os.path.join(CONTENT_DIR, pkg + '.uasset'))

    def choose(self, name, agent):
        return self.actors.get(name.lower()) or self.data.get('default_agent' if agent else 'default_resident') or ''

    def resolve(self, body_id):
        """-> (shown id, tier, warning) for SetBody; tiered bodies start far, as on the server."""
        b = self.bodies[body_id]
        start, tier = (b['far'], 'far') if b.get('far') in self.bodies else (body_id, 'near')
        seen, cur, warn = set(), start, ''
        while cur in self.bodies and cur not in seen:
            seen.add(cur)
            if self.loadable(self.bodies[cur].get('mesh')):
                return cur, (tier if cur == start else 'fallback'), warn
            warn += "body '%s': mesh '%s' did not load; " % (cur, self.bodies[cur].get('mesh', ''))
            cur = self.bodies[cur].get('fallback', '')
        return 'placeholder', 'placeholder', warn + 'using the placeholder'


class Obj:
    def __init__(self, name, cls, has_camera=False):
        self.name = name
        self.cls = cls
        self.loc = [0.0, 0.0, 0.0]
        self.rot = [0.0, 0.0, 0.0]
        self.scale = [1.0, 1.0, 1.0]
        self.color = [0, 0, 0]
        self.collision = True
        self.physics = False
        self.movable = True
        self.hidden = False
        self.has_camera = has_camera
        self.body = None  # (shown, tier, requested) for human prefabs


class Camera:
    def __init__(self, owner=None):
        self.owner = owner  # Obj or None (level camera)
        self.loc = [0.0, 0.0, 200.0]
        self.rot = [0.0, 0.0, 0.0]
        self.fov = 90.0
        self.size = [640, 480]


class World:
    def __init__(self, prefabs, bodies=None):
        self.lock = threading.Lock()
        self.prefabs = set(prefabs)
        self.objects = {}  # lower-name -> Obj (insertion order == spawn order)
        for n in LEVEL_ACTORS:
            self.objects[n.lower()] = Obj(n, 'level')
        self.level_camera = Camera()
        self.agent_cameras = {}  # id(Obj) -> Camera
        self.paused = False
        self.tick_interval = 0.05
        self.ticks = 0
        self.bodies = bodies or Bodies(None)

    def find(self, name):
        return self.objects.get(name.lower())

    def cameras(self):
        cams = [self.level_camera]
        for o in self.objects.values():
            if o.has_camera:
                cams.append(self.agent_cameras.setdefault(id(o), Camera(o)))
        return cams

    def camera(self, idx):
        cams = self.cameras()
        if not (0 <= idx < len(cams)):
            return None
        cam = cams[idx]
        if cam.owner is not None and not getattr(cam, '_placed', False):
            o = cam.owner
            cam.loc = [o.loc[0], o.loc[1], o.loc[2] + 70.0]
            cam.rot = [0.0, o.rot[1], 0.0]
        return cam

    def class_ok(self, path):
        return path in self.prefabs or bool(CITY_RE.match(path))


def fmt3(v):
    return '%.3f %.3f %.3f' % tuple(v)


def parse_bool(s):
    s = s.strip().lower()
    if s in ('1', 'true', 'yes', 'on'):
        return True
    if s in ('0', 'false', 'no', 'off'):
        return False
    raise ValueError(s)


def floats(tokens, n):
    if len(tokens) != n:
        raise ValueError('expected %d numbers, got %d' % (n, len(tokens)))
    vals = [float(t) for t in tokens]
    if any(math.isnan(v) or math.isinf(v) for v in vals):
        raise ValueError('non-finite number')
    return vals


class Handler:
    def __init__(self, world, verbose=False):
        self.w = world
        self.verbose = verbose

    # Returns str or bytes
    def handle(self, cmd):
        toks = cmd.split()
        if not toks:
            return 'error empty command'
        verb = toks[0]
        try:
            with self.w.lock:
                if verb == 'vrun':
                    return 'ok' if len(toks) > 1 else 'error vrun needs a console command'
                if verb == 'vbp':
                    if len(toks) < 3:
                        return 'error vbp needs <object> <function> [args...]'
                    obj = self.w.find(toks[1])
                    if obj is None:
                        return 'error Can not find object %s' % toks[1]
                    if toks[2] in ('SetBody', 'GetBody') and len(toks) == (4 if toks[2] == 'SetBody' else 3):
                        return self._body(obj, toks[2], toks[3:])
                    return 'error mock server does not implement blueprint function %s' % toks[2]
                if verb not in ('vget', 'vset') or len(toks) < 2:
                    return 'error Can not find a handler for URI %s' % cmd
                return self._uri(verb, toks[1], toks[2:])
        except ValueError as e:
            return 'error invalid arguments: %s' % e

    def _body(self, obj, fn, args):
        if obj.body is None:
            return "error '%s' has no human body" % obj.name
        if fn == 'GetBody':
            shown, tier, requested = obj.body
            return json.dumps({'body': shown, 'tier': tier, 'requested': requested}, separators=(',', ':'))
        body_id = args[0]
        if body_id not in self.w.bodies.bodies:
            return "error unknown body '%s' (not in %s)" % (body_id, self.w.bodies.path)
        shown, tier, warn = self.w.bodies.resolve(body_id)
        obj.body = (shown, tier, body_id)
        reply = {'ok': True, 'body': shown, 'tier': tier, 'requested': body_id}
        if warn:
            reply['warning'] = warn if shown == 'placeholder' else warn + "showing '%s'" % shown
        return json.dumps(reply, separators=(',', ':'))

    def _uri(self, verb, uri, args):
        w = self.w
        parts = uri.strip('/').split('/')
        if verb == 'vget' and uri == '/unrealcv/commands':
            return '\n'.join(TEMPLATES)
        if verb == 'vget' and uri == '/unrealcv/status':
            return 'Is Listening\nClient Connected\n9000\nConfig\n'
        if verb == 'vget' and uri == '/bodies':
            return json.dumps({o.name: {'body': o.body[0], 'tier': o.body[1], 'requested': o.body[2], 'px': 0, 'fading': False}
                               for o in w.objects.values() if o.body is not None}, separators=(',', ':'))
        if verb == 'vget' and uri == '/objects':
            return ' '.join(o.name for o in w.objects.values())
        if verb == 'vset' and parts[0] == 'objects' and len(parts) == 2 and parts[1] in ('spawn', 'spawn_bp_asset'):
            if len(args) != 2:
                return 'error usage: vset /objects/%s <class> <name>' % parts[1]
            path, name = args
            if not w.class_ok(path):
                return 'error Can not load class %s' % path
            if w.find(name) is not None:
                return 'error Object %s already exists' % name
            short = path.rsplit('.', 1)[-1]
            o = Obj(name, path, has_camera=short in CAMERA_PREFABS)
            if short in HUMAN_PREFABS:
                chosen = w.bodies.choose(name, agent=short != 'Base_Pedestrian_C')
                o.body = w.bodies.resolve(chosen)[:2] + (chosen,) if chosen in w.bodies.bodies else ('placeholder', 'placeholder', chosen)
            w.objects[name.lower()] = o
            return name
        if parts[0] == 'object' and len(parts) >= 3:
            return self._object(verb, parts[1], '/'.join(parts[2:]), args)
        if parts[0] == 'action':
            sub = '/'.join(parts[1:])
            if verb == 'vset' and sub == 'clean_garbage':
                return 'ok'
            if verb == 'vset' and sub == 'game/pause':
                w.paused = True
                return 'ok'
            if verb == 'vset' and sub == 'game/resume':
                w.paused = False
                return 'ok'
            if verb == 'vget' and sub == 'game/is_paused':
                return 'true' if w.paused else 'false'
            if verb == 'vset' and sub == 'tick':
                w.ticks += 1
                return 'ok'
            if verb == 'vset' and sub in ('tick_intervel', 'set_fixed_frame_rate'):
                (v,) = floats(args, 1)
                if sub == 'tick_intervel':
                    w.tick_interval = v
                return 'ok'
        if verb == 'vget' and uri == '/cameras':
            names = ['LevelCamera'] + ['%s_Camera' % c.owner.name for c in w.cameras()[1:]]
            return ' '.join(names)
        if parts[0] == 'camera' and len(parts) >= 3:
            try:
                idx = int(parts[1])
            except ValueError:
                return 'error invalid camera id %s' % parts[1]
            cam = w.camera(idx)
            if cam is None:
                return 'error Camera %d does not exist' % idx
            return self._camera(verb, cam, parts[2], args)
        return 'error Can not find a handler for URI %s %s' % (verb, uri)

    def _object(self, verb, name, prop, args):
        w = self.w
        o = w.find(name)
        if o is None:
            return 'error Can not find object %s' % name
        if verb == 'vget':
            if prop == 'location':
                return fmt3(o.loc)
            if prop == 'rotation':
                return fmt3(o.rot)
            if prop == 'scale':
                return fmt3(o.scale)
            if prop == 'color':
                return '(R=%d,G=%d,B=%d,A=255)' % tuple(o.color)
            if prop == 'uclass_name':
                return o.cls.rsplit('.', 1)[-1] if o.cls != 'level' else o.name
            return 'error unknown property %s' % prop
        if prop == 'location':
            o.loc = floats(args, 3)
            return 'ok'
        if prop == 'rotation':
            o.rot = floats(args, 3)
            return 'ok'
        if prop == 'scale':
            o.scale = floats(args, 3)
            return 'ok'
        if prop == 'color':
            vals = [int(float(a)) for a in args]
            if len(vals) != 3 or any(v < 0 or v > 255 for v in vals):
                raise ValueError('color must be 3 ints 0-255')
            o.color = vals
            return 'ok'
        if prop in ('physics', 'collision', 'object_mobility'):
            if len(args) != 1:
                raise ValueError('expected one bool')
            setattr(o, {'object_mobility': 'movable'}.get(prop, prop), parse_bool(args[0]))
            return 'ok'
        if prop == 'name':
            if len(args) != 1:
                raise ValueError('expected new name')
            new = args[0]
            if new.lower() != o.name.lower() and w.find(new) is not None:
                return 'error Object %s already exists' % new
            # keep spawn order: rebuild dict
            items = [(k, v) for k, v in w.objects.items()]
            w.objects = {}
            for k, v in items:
                if v is o:
                    o.name = new
                    w.objects[new.lower()] = o
                else:
                    w.objects[k] = v
            return 'ok'
        if prop == 'destroy':
            del w.objects[o.name.lower()]
            w.agent_cameras.pop(id(o), None)
            return 'ok'
        if prop in ('hide', 'show'):
            o.hidden = prop == 'hide'
            return 'ok'
        return 'error unknown property %s' % prop

    def _camera(self, verb, cam, prop, args):
        if verb == 'vset':
            if prop == 'location':
                cam.loc = floats(args, 3)
                cam._placed = True
                return 'ok'
            if prop == 'rotation':
                cam.rot = floats(args, 3)
                cam._placed = True
                return 'ok'
            if prop == 'fov':
                (cam.fov,) = floats(args, 1)
                return 'ok'
            if prop == 'size':
                if len(args) != 2:
                    raise ValueError('expected W H')
                wdt, hgt = int(args[0]), int(args[1])
                if wdt <= 0 or hgt <= 0:
                    raise ValueError('size must be positive')
                cam.size = [wdt, hgt]
                return 'ok'
            return 'error unknown camera property %s' % prop
        if prop == 'location':
            return fmt3(cam.loc)
        if prop == 'rotation':
            return fmt3(cam.rot)
        if prop == 'fov':
            return '%.3f' % cam.fov
        if prop == 'size':
            return '%d %d' % tuple(cam.size)
        if prop in ('lit', 'depth', 'object_mask', 'normal'):
            if len(args) != 1:
                return 'error usage: vget /camera/<id>/%s png|bmp|npy|<filename>' % prop
            return self._capture(cam, prop, args[0])
        return 'error unknown camera property %s' % prop

    def _capture(self, cam, mode, fmt):
        wdt, hgt = cam.size
        seed = int(abs(cam.loc[0] + 3 * cam.loc[1] + 7 * cam.loc[2] + 11 * cam.rot[1])) % 97
        if mode == 'object_mask':
            # paint the colors of the last few colored objects as horizontal bands
            colored = [o.color for o in self.w.objects.values() if any(o.color)] or [[0, 0, 0]]
            bands = colored[-8:]

            def row(y):
                c = bands[y * len(bands) // hgt]
                return bytes([c[0], c[1], c[2], 255]) * wdt
        else:
            base = (90 + seed, 140, 200) if mode == 'lit' else (128, 128, 255)

            def row(y):
                t = y / max(1, hgt - 1)
                return bytes([int(base[0] * (1 - t * 0.5)), base[1], int(base[2] * (0.5 + 0.5 * t)), 255]) * wdt
        if fmt == 'png':
            return encode_png_rgba(wdt, hgt, row)
        if fmt == 'bmp':
            return encode_bmp_bgr(wdt, hgt, (200, 120, 40))
        if fmt == 'npy':
            if mode != 'depth':
                return 'error npy is only supported for depth in this mock'
            return encode_npy_f32(wdt, hgt, lambda y: 100.0 + 9900.0 * y / max(1, hgt - 1))
        # anything else is a filename
        path = fmt
        try:
            d = os.path.dirname(os.path.abspath(path))
            os.makedirs(d, exist_ok=True)
            with open(path, 'wb') as f:
                f.write(encode_png_rgba(wdt, hgt, row))
        except OSError as e:
            return 'error can not save %s: %s' % (path, e)
        return os.path.abspath(path)


# --------------------------------------------------------------------------
# Networking
# --------------------------------------------------------------------------
def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def send_frame(sock, payload):
    sock.sendall(HDR.pack(MAGIC, len(payload)) + payload)


REQ_RE = re.compile(rb'^(\d+):(.*)$', re.S)


def serve_client(conn, handler, verbose):
    send_frame(conn, b'connected to SimWorldMock')
    while True:
        hdr = recv_exact(conn, 8)
        if hdr is None:
            return
        magic, size = HDR.unpack(hdr)
        if magic != MAGIC:
            if verbose:
                print('bad magic 0x%08x, closing' % magic, flush=True)
            return
        payload = recv_exact(conn, size)
        if payload is None:
            return
        m = REQ_RE.match(payload)
        if not m:
            if verbose:
                print('unframed request %r ignored' % payload[:60], flush=True)
            continue
        rid, body = m.group(1), m.group(2).decode('utf-8', errors='replace')
        reply = handler.handle(body)
        if isinstance(reply, str):
            reply = reply.encode('utf-8')
        if verbose:
            shown = reply[:80] if len(reply) < 200 else b'<%d bytes>' % len(reply)
            print('%s:%s -> %r' % (rid.decode(), body[:100], shown), flush=True)
        send_frame(conn, rid + b':' + reply)


def load_prefabs(assets_path):
    prefabs = list(KNOWN_PREFABS)
    if assets_path and os.path.exists(assets_path):
        with open(assets_path) as f:
            data = json.load(f)
        prefabs += [v['asset_path'] for k, v in data.items() if k != 'colors']
    return prefabs


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    default_assets = os.path.normpath(os.path.join(here, '..', '..', 'simworld', 'data', 'ue_assets.json'))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--host', default=os.environ.get('SIMCV_HOST', '127.0.0.1'))
    ap.add_argument('--port', type=int, default=int(os.environ.get('SIMCV_PORT', '9000')))
    ap.add_argument('--assets', default=default_assets, help='ue_assets.json for the prefab catalog')
    ap.add_argument('--bodies', default=os.path.normpath(os.path.join(here, '..', 'Config', 'Bodies.json')),
                    help='Bodies.json for SetBody/GetBody')
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args(argv)

    world = World(load_prefabs(a.assets), Bodies(a.bodies))
    handler = Handler(world, a.verbose)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((a.host, a.port))
    srv.listen(4)
    print('mock UnrealCV server listening on %s:%d' % (a.host, a.port), flush=True)

    busy = threading.Lock()

    def run(conn):
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            serve_client(conn, handler, a.verbose)
        except (ConnectionError, OSError):
            pass
        finally:
            conn.close()
            busy.release()

    try:
        while True:
            conn, addr = srv.accept()
            if not busy.acquire(blocking=False):
                # UnrealCV allows a single client; extra connections are closed
                # without a handshake.
                conn.close()
                continue
            threading.Thread(target=run, args=(conn,), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()


if __name__ == '__main__':
    main()
