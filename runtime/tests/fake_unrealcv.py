"""A fake UnrealCV server: speaks the real wire format with a toy world behind it.

It proves our client sends what we believe is right. It proves nothing about Unreal. Reply
formats are copied from how the client code parses them, and the physics is simple kinematics
invented for tests. See runtime/SIMWORLD.md for what a real run still has to check.

Wire format (unrealcv/__init__.py:61,120-133): every message is a little-endian uint32 magic,
a uint32 size, then the payload. A request's payload is "<id>:<command>", and the reply is
"<same id>:<body>". On accept the server sends a message starting with "connected".
Binds only to 127.0.0.1, on an ephemeral port unless told otherwise.
"""
import json
import math
import re
import socket
import struct
import threading
import zlib
from io import BytesIO
from typing import Optional

import numpy as np

MAGIC = 0x9E2B83C1
OK = "ok"
ERROR_UNKNOWN = "error: fake server does not know this command"
EYE_HEIGHT_CM = 160.0
PICKUP_REACH_CM = 400.0


def png_bytes(rgba: np.ndarray) -> bytes:
    """Encode an HxWx4 uint8 array as a PNG with only the standard library."""
    height, width, _ = rgba.shape
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    rows = b"".join(b"\x00" + rgba[y].tobytes() for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 1)) + chunk(b"IEND", b""))


class Actor:
    def __init__(self, name, asset=""):
        self.name, self.asset = name, asset
        self.location = [0.0, 0.0, 0.0]
        self.rotation = [0.0, 0.0, 0.0]
        self.scale = [1.0, 1.0, 1.0]
        self.collision = self.movable = None
        self.color = None
        self.max_speed = 200.0
        self.walking = False
        self.step_left = 0.0
        self.step_sign = 1
        self.turn_left = 0.0  # signed degrees still to turn
        self.turn_rate = 0.0
        self.sitting = False
        self.holding = None
        self.vehicle = None
        self.drive = (0.0, 0.0, 0.0)
        self.gesture = None


class Camera:
    """Camera 0 sits still. The others ride on the pawn that spawned them, like a head camera."""
    def __init__(self, owner=None):
        self.owner = owner
        self.location = [0.0, 0.0, 200.0]
        self.rotation = [0.0, 0.0, 0.0]
        self.rotation_override = None
        self.fov = 90.0
        self.size = (640, 480)


class FakeUnrealCV:
    """Knobs for failure tests are the attributes set in __init__ under "failure modes"."""

    def __init__(self, port: int = 0, advertise_commands: bool = True, drift_cm: float = 0.0):
        self.requested_port = port
        self.port: Optional[int] = None
        self.advertise_commands = advertise_commands
        self.commands: list[str] = []  # every command accepted, in order
        self.rejected: list[str] = []  # every command we did not recognise
        self.lock = threading.RLock()
        self._listener = None
        self._client = None
        self._thread = None
        self._running = False
        self.connections = 0
        self.busy_rejections = 0

        # failure modes
        self.silent_hello = False  # accept TCP, never say hello: a server still loading
        self.hello_text = b"connected to fake UnrealCV"
        self.hang_on: Optional[str] = None  # never answer a command starting with this
        self.drop_on: Optional[str] = None  # close the socket on a command starting with this
        self.fail_once = True  # hang_on and drop_on fire once, then clear
        self.missing_assets: set[str] = set()  # spawning these does nothing, as if the asset were absent
        self.refuse: set[str] = set()  # command prefixes answered with an error
        self.blocked: set[str] = set()  # these actors cannot move, as if against a wall
        self.reply_as_bool = False  # send {"Success": true} rather than {"Success": "true"}
        self.restore_noise_cm = drift_cm  # added to every teleport, to model an imperfect restore
        self.nondeterminism = 0.0  # extra cm per tick while walking, to model a non-repeatable engine

        self.reset_world()

    def reset_world(self) -> None:
        with self.lock:
            self.actors: dict[str, Actor] = {}
            self.cameras = [Camera()]
            self.paused = False
            self.tick_interval: Optional[float] = None
            self.tick_count = 0
            self.level = None
            self.window = None
            self.sun_pitch, self.sun_yaw, self.sun_intensity = -26.0, -20.0, 10.0  # communicator.py:967
            self.fog = (0.0, 0.0, 0.0)
            self.atmosphere = (1.0, 1.0)
            self._off_counter = 0

    ###################################################
    # Socket handling
    ###################################################

    def start(self) -> "FakeUnrealCV":
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", self.port if self.port else self.requested_port))
        self._listener.listen(4)
        self.port = self._listener.getsockname()[1]
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True, name="wmloop_fake_unrealcv")
        self._thread.start()
        return self

    def stop(self) -> None:
        self._running = False
        if self._client:
            self._close_client()
        if self._listener:
            try:
                self._listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._listener.close()
            self._listener = None
        if self._thread:
            self._thread.join(timeout=2)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def drop_client(self) -> None:
        """Cut the current client off without warning."""
        self._close_client()

    def _close_client(self) -> None:
        client, self._client = self._client, None
        if client:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            client.close()

    def _accept_loop(self) -> None:
        while self._running:
            try:
                sock, _ = self._listener.accept()
            except OSError:
                return
            if self._client is not None:  # "Currently only one client is allowed" (unrealcv/__init__.py:147)
                self.busy_rejections += 1
                self._send(sock, b"Server is busy")
                sock.close()
                continue
            self.connections += 1
            self._client = sock
            threading.Thread(target=self._serve, args=(sock,), daemon=True, name="wmloop_fake_client").start()

    @staticmethod
    def _send(sock, payload: bytes) -> None:
        sock.sendall(struct.pack("<II", MAGIC, len(payload)) + payload)

    @staticmethod
    def _recv_exact(sock, count: int) -> Optional[bytes]:
        data = b""
        while len(data) < count:
            chunk = sock.recv(count - len(data))
            if not chunk:
                return None
            data += chunk
        return data

    def _serve(self, sock) -> None:
        try:
            if self.silent_hello:
                while self._client is sock and sock.recv(1):
                    pass
                return
            self._send(sock, self.hello_text)
            while True:
                header = self._recv_exact(sock, 8)
                if header is None:
                    return
                magic, size = struct.unpack("<II", header)
                if magic != MAGIC:
                    raise ValueError(f"client sent bad magic {magic:#x}")
                match = re.match(rb"(\d+):(.*)", self._recv_exact(sock, size), re.S)
                message_id, command = match.group(1), match.group(2).decode()
                if self._fires(self.drop_on, command, "drop_on"):
                    return
                if self._fires(self.hang_on, command, "hang_on"):
                    continue
                reply = self.handle(command)
                body = reply if isinstance(reply, bytes) else reply.encode()
                self._send(sock, message_id + b":" + body)
        except (OSError, ValueError):
            return
        finally:
            if self._client is sock:
                self._close_client()

    def _fires(self, prefix, command, attribute) -> bool:
        if prefix and command.startswith(prefix):
            if self.fail_once:
                setattr(self, attribute, None)
            return True
        return False

    ###################################################
    # Commands. Each pattern cites the client line that sends it.
    ###################################################

    def handle(self, command: str):
        with self.lock:
            for prefix in self.refuse:
                if command.startswith(prefix):
                    self.commands.append(command)
                    return "error: refused by test"
            for pattern, handler in self.routes():
                match = re.fullmatch(pattern, command)
                if match:
                    self.commands.append(command)
                    return handler(*match.groups())
            self.rejected.append(command)
            return ERROR_UNKNOWN

    def routes(self):
        name = r"(\S+)"
        number = r"(-?[\d.]+(?:e-?\d+)?)"
        return [
            (r"vget /unrealcv/commands", self._commands_list),  # unrealcv/__init__.py:244
            (r"vrun setres (\d+)x(\d+)w", self._setres),  # unrealcv.py:64
            (r"vrun Editor\.AsyncSkinnedAssetCompilation 2", lambda: OK),  # unrealcv.py:66
            (rf"vset /action/game/level {name}", self._level),  # unrealcv/api.py:1338
            (r"vset /action/clean_garbage", lambda: OK),  # unrealcv.py:102
            (r"vget /objects", lambda: " ".join(self.actors)),  # unrealcv.py:252
            (r"vget /cameras", lambda: " ".join(f"cam{i}" for i in range(len(self.cameras)))),  # unrealcv.py:890
            (r"vget /action/game/is_paused", lambda: str(self.paused).lower()),  # unrealcv/api.py:1384

            (rf"vset /objects/spawn_bp_asset {name} {name}", self._spawn),  # unrealcv.py:95
            (rf"vset /object/{name}/location {number} {number} {number}", self._set_location),  # unrealcv.py:112
            (rf"vset /object/{name}/rotation {number} {number} {number}", self._set_rotation),  # unrealcv.py:124
            (rf"vset /object/{name}/scale {number} {number} {number}", self._set_scale),  # unrealcv.py:136
            (rf"vset /object/{name}/color (\d+) (\d+) (\d+)", self._set_color),  # unrealcv.py:148
            (rf"vset /object/{name}/collision (True|False)", self._set_collision),  # unrealcv.py:181
            (rf"vset /object/{name}/object_mobility (True|False)", self._set_movable),  # unrealcv.py:192
            (rf"vset /object/{name}/destroy", self._destroy),  # unrealcv.py:241
            (rf"vset /object/{name}/name {name}", self._rename),  # unrealcv.py:263
            (rf"vget /object/{name}/location", self._get_location),  # unrealcv.py:290
            (rf"vget /object/{name}/rotation", self._get_rotation),  # unrealcv.py:321
            (rf"vget /object/{name}/color", self._get_color),  # unrealcv/api.py:744

            (rf"vset /action/tick_intervel {number}", self._tick_interval),  # unrealcv.py:225
            (r"vset /action/game/pause", self._pause),  # unrealcv.py:216
            (r"vset /action/game/resume", self._resume),  # unrealcv.py:219
            (r"vset /action/tick", self._tick),  # unrealcv.py:231

            (r"vset /camera/(\d+)/rotation " + f"{number} {number} {number}", self._set_camera_rotation),  # unrealcv.py:971
            (r"vset /camera/(\d+)/location " + f"{number} {number} {number}", self._set_camera_location),  # unrealcv.py:960
            (r"vset /camera/(\d+)/fov " + number, self._set_camera_fov),  # unrealcv.py:982
            (r"vset /camera/(\d+)/size (\d+) (\d+)", self._set_camera_size),  # unrealcv.py:993
            (r"vget /camera/(\d+)/location", self._get_camera_location),  # unrealcv.py:910
            (r"vget /camera/(\d+)/rotation", self._get_camera_rotation),  # unrealcv.py:923
            (r"vget /camera/(\d+)/fov", lambda c: f"{self._camera(c).fov}"),  # unrealcv.py:936
            (r"vget /camera/(\d+)/size", lambda c: "{} {}".format(*self._camera(c).size)),  # unrealcv.py:949
            (r"vget /camera/(\d+)/lit (png|bmp)", self._render_lit),  # unrealcv.py:1055
            (r"vget /camera/(\d+)/depth npy", self._render_depth),  # unrealcv.py:1050
            (r"vget /camera/(\d+)/object_mask (png|bmp)", self._render_mask),  # unrealcv.py:1055

            (rf"vbp {name} ([A-Za-z_0-9]+)((?: \S+)*)", self._blueprint),  # unrealcv.py:159 onward
        ]

    def _commands_list(self):
        if not self.advertise_commands:
            return "error: unknown command"  # an older server, unrealcv/__init__.py:249
        return "\n".join(["vget /unrealcv/commands", "vget /objects", "vset /action/tick", "vbp [str] [str]"])

    def _setres(self, w, h):
        self.window = (int(w), int(h))
        return OK

    def _level(self, name):
        self.reset_world()
        self.level = name
        return OK

    def _spawn(self, asset, name):
        if asset in self.missing_assets:
            return OK  # a real server's behaviour for a missing asset is unknown, so model the worst: silence
        actor = Actor(name, asset)
        self.actors[name] = actor
        if "Pedestrian" in asset or "User_Agent" in asset or "Default_Character" in asset:
            self.cameras.append(Camera(owner=name))  # agent_system.rst:71: each pawn gets a camera in spawn order
        return OK

    def _actor(self, name) -> Actor:
        if name not in self.actors:
            raise KeyError(name)
        return self.actors[name]

    def _missing(self, name):
        return f"error: object {name} not found"

    def _set_location(self, name, x, y, z):
        if name not in self.actors:
            return self._missing(name)
        noise = self.restore_noise_cm
        self.actors[name].location = [float(x) + noise, float(y), float(z)]
        return OK

    def _set_rotation(self, name, p, y, r):
        if name not in self.actors:
            return self._missing(name)
        self.actors[name].rotation = [float(p), float(y), float(r)]
        return OK

    def _set_scale(self, name, x, y, z):
        if name not in self.actors:
            return self._missing(name)
        self.actors[name].scale = [float(x), float(y), float(z)]
        return OK

    def _set_color(self, name, r, g, b):
        if name not in self.actors:
            return self._missing(name)
        self.actors[name].color = (int(r), int(g), int(b))
        return OK

    def _set_collision(self, name, value):
        if name not in self.actors:
            return self._missing(name)
        self.actors[name].collision = value == "True"
        return OK

    def _set_movable(self, name, value):
        if name not in self.actors:
            return self._missing(name)
        self.actors[name].movable = value == "True"
        return OK

    def _destroy(self, name):
        self.actors.pop(name, None)
        return OK

    def _rename(self, name, new_name):
        if name not in self.actors:
            return self._missing(name)
        actor = self.actors.pop(name)
        actor.name = new_name
        self.actors[new_name] = actor
        for camera in self.cameras:
            if camera.owner == name:
                camera.owner = new_name
        return OK

    def _get_location(self, name):
        if name not in self.actors:
            return self._missing(name)
        return " ".join(f"{v:.6f}" for v in self.actors[name].location)

    def _get_rotation(self, name):
        if name not in self.actors:
            return self._missing(name)
        return " ".join(f"{v:.6f}" for v in self.actors[name].rotation)

    def _get_color(self, name):
        if name not in self.actors:
            return self._missing(name)
        r, g, b = self.actors[name].color or (0, 0, 0)
        return f"(R={r},G={g},B={b},A=255)"  # format from unrealcv/api.py:1487

    def _tick_interval(self, seconds):
        self.tick_interval = float(seconds)
        return OK

    def _pause(self):
        self.paused = True
        return OK

    def _resume(self):
        self.paused = False
        return OK

    def _tick(self):
        if not self.paused or self.tick_interval is None:
            return "error: fake server only ticks when paused with an interval set"
        self.tick_count += 1
        self._advance(self.tick_interval)
        return OK

    ###################################################
    # Toy physics
    ###################################################

    def _advance(self, dt: float) -> None:
        for actor in self.actors.values():
            if actor.turn_left:
                turn = math.copysign(min(abs(actor.turn_left), actor.turn_rate * dt), actor.turn_left)
                actor.rotation[1] += turn
                actor.turn_left -= turn
                if abs(actor.turn_left) < 1e-9:
                    actor.turn_left = 0.0
            speed, sign = 0.0, 1
            if actor.walking:
                speed = actor.max_speed
            if actor.step_left > 0:
                speed, sign = actor.max_speed, actor.step_sign
                actor.step_left = max(0.0, actor.step_left - dt)
            if actor.drive[0] > 0:
                speed = 500.0 * actor.drive[0]
            if speed and actor.name not in self.blocked:
                yaw = math.radians(actor.rotation[1])
                actor.location[0] += sign * speed * dt * math.cos(yaw) + self.nondeterminism
                actor.location[1] += sign * speed * dt * math.sin(yaw)
        for actor in self.actors.values():
            if actor.holding and actor.holding in self.actors:
                self.actors[actor.holding].location = list(actor.location)

    def _blueprint(self, name, function, args):
        args = args.split()
        if name not in self.actors:
            return self._missing(name)
        actor = self.actors[name]
        handler = getattr(self, f"_bp_{function}", None)
        if handler is None:
            return f"error: {name} has no function {function}"
        return handler(actor, *args)

    def _result(self, success: bool) -> str:
        if self.reply_as_bool:
            return json.dumps({"Success": success})
        return json.dumps({"Success": "true" if success else "false"})  # unrealcv.py:680-684

    def _bp_MoveForward(self, a):
        a.walking = True
        return OK

    def _bp_StopAgent(self, a):
        a.walking = False
        a.step_left = 0.0
        return OK

    _bp_StopPedestrian = _bp_StopAgent

    def _bp_TurnAround(self, a, seconds, angle, clockwise):
        if (float(angle) > 0) != (int(clockwise) > 0):
            return "error: fake server expects the sign of angle and clockwise to match (unrealcv.py:627-632)"
        a.turn_left = float(angle)
        a.turn_rate = abs(float(angle)) / float(seconds)
        return OK

    _bp_Rotate_Angle = _bp_TurnAround

    def _bp_StepForward(self, a, seconds, direction):
        a.step_left = float(seconds)
        a.step_sign = 1 if int(direction) == 0 else -1
        return OK

    def _bp_SetMaxSpeed(self, a, speed):
        a.max_speed = float(speed)
        return OK

    def _bp_SitDown(self, a):
        a.sitting = True
        return self._result(True)

    def _bp_StandUp(self, a):
        ok = a.sitting
        a.sitting = False
        return self._result(ok)

    def _bp_PickUp(self, a, target):
        if target not in self.actors:
            return self._result(False)
        ok = math.dist(a.location[:2], self.actors[target].location[:2]) <= PICKUP_REACH_CM
        if ok:
            a.holding = target
        return self._result(ok)

    def _bp_DropOff(self, a):
        ok = a.holding is not None
        a.holding = None
        return self._result(ok)

    def _bp_GetOnScooter(self, a):
        """Humanoid disappears into the nearest scooter, as communicator.py:110-125 implies."""
        scooters = [s for s in self.actors.values() if "Scooter" in s.asset]
        if not scooters:
            return "error: no scooter"
        nearest = min(scooters, key=lambda s: math.dist(s.location, a.location))
        for camera in self.cameras:
            if camera.owner == a.name:
                camera.owner = nearest.name
        del self.actors[a.name]
        return OK

    def _bp_GetOffScooter(self, scooter):
        self._off_counter += 1
        name = f"Base_User_Agent_C_{self._off_counter}"
        fresh = Actor(name, "/Game/TrafficSystem/Pedestrian/Base_User_Agent.Base_User_Agent_C")
        fresh.location = [scooter.location[0] + 100, scooter.location[1], scooter.location[2]]
        fresh.rotation = list(scooter.rotation)
        self.actors[name] = fresh
        for camera in self.cameras:
            if camera.owner == scooter.name:
                camera.owner = name
        scooter.drive = (0.0, 0.0, 0.0)
        return OK

    def _bp_EnterVehicle(self, a, vehicle):
        ok = vehicle in self.actors
        a.vehicle = vehicle if ok else None
        return self._result(ok)

    def _bp_ExitVehicle(self, a, vehicle):
        ok = a.vehicle == vehicle
        a.vehicle = None
        return self._result(ok)

    def _bp_SetState(self, a, throttle, brake, steering):
        a.drive = (float(throttle), float(brake), float(steering))
        return OK

    def _gesture(self, a, kind):
        a.gesture = kind
        return OK

    def _bp_Discussion(self, a, variant):
        return self._gesture(a, f"discuss{variant}")

    def _bp_Arguing(self, a, variant):
        return self._gesture(a, f"argue{variant}")

    def _bp_Listening(self, a):
        return self._gesture(a, "listen")

    def _bp_Wave2Dog(self, a):
        return self._gesture(a, "wave")

    def _bp_Directing(self, a):
        return self._gesture(a, "direct")

    def _bp_StopAction(self, a):
        a.gesture = None
        return OK

    def _bp_GetCollisionNum(self, a):
        return json.dumps({"HumanCollision": 0, "ObjectCollision": 0, "BuildingCollision": 0, "VehicleCollision": 0})

    def _bp_UpdateObjects(self, a):
        return OK

    # Weather replies are padded with tabs and newlines, as communicator.py:958-960 cleans up.
    def _bp_SetSunDirection(self, a, pitch, yaw):
        self.sun_pitch, self.sun_yaw = float(pitch), float(yaw)
        return OK

    def _bp_GetSunDirection(self, a):
        return f'{{\r\n\t"rotation": "P={self.sun_pitch:.6f} Y={self.sun_yaw:.6f} R=0.000000"\r\n}}'

    def _bp_SetSunIntensity(self, a, value):
        self.sun_intensity = float(value)
        return OK

    def _bp_GetSunIntensity(self, a):
        return f'{{\r\n\t"SunIntensity": {self.sun_intensity}\r\n}}'

    def _bp_SetFog(self, a, density, distance, falloff):
        self.fog = (float(density), float(distance), float(falloff))
        return OK

    def _bp_GetFog(self, a):
        d, s, f = self.fog
        return f'{{\r\n\t"FogDensity": {d},\r\n\t"FogDistance": {s},\r\n\t"FogFalloff": {f}\r\n}}'

    def _bp_SetAtmosphere(self, a, rayleigh, mie):
        self.atmosphere = (float(rayleigh), float(mie))
        return OK

    def _bp_GetAtmosphere(self, a):
        r, m = self.atmosphere
        return f'{{\r\n\t"Rayleigh Scattering Scale": {r},\r\n\t"Mie Scattering Scale": {m}\r\n}}'

    ###################################################
    # Cameras and images
    ###################################################

    def _camera(self, index) -> Camera:
        return self.cameras[int(index)]

    def _camera_pose(self, camera: Camera):
        if camera.owner and camera.owner in self.actors:
            owner = self.actors[camera.owner]
            location = [owner.location[0], owner.location[1], owner.location[2] + EYE_HEIGHT_CM]
            return location, camera.rotation_override or list(owner.rotation)
        return camera.location, camera.rotation_override or camera.rotation

    def _set_camera_rotation(self, index, p, y, r):
        self._camera(index).rotation_override = [float(p), float(y), float(r)]
        return OK

    def _set_camera_location(self, index, x, y, z):
        self._camera(index).location = [float(x), float(y), float(z)]
        return OK

    def _set_camera_fov(self, index, fov):
        self._camera(index).fov = float(fov)
        return OK

    def _set_camera_size(self, index, w, h):
        self._camera(index).size = (int(w), int(h))
        return OK

    def _get_camera_location(self, index):
        return " ".join(f"{v:.6f}" for v in self._camera_pose(self._camera(index))[0])

    def _get_camera_rotation(self, index):
        return " ".join(f"{v:.6f}" for v in self._camera_pose(self._camera(index))[1])

    def _world_fingerprint(self) -> int:
        """A small number from the world state, so images change exactly when the world does."""
        text = ";".join(f"{a.name}:{a.location[0]:.3f},{a.location[1]:.3f}" for a in sorted(self.actors.values(), key=lambda a: a.name))
        return zlib.crc32(text.encode()) & 0xFF

    def _render_lit(self, index, fmt):
        w, h = self._camera(index).size
        daylight = max(0.0, min(1.0, -self.sun_pitch / 45.0)) * min(1.0, self.sun_intensity / 10.0)
        level = int(20 + 200 * daylight)
        image = np.full((h, w, 4), 255, dtype=np.uint8)
        image[:, :, 0] = level
        image[:, :, 1] = level
        image[:, :, 2] = self._world_fingerprint()
        return png_bytes(image)

    def _render_depth(self, index):
        w, h = self._camera(index).size
        depth = np.full((h, w), 1000.0, dtype=np.float32) + float(self._world_fingerprint())
        out = BytesIO()
        np.save(out, depth, allow_pickle=False)
        return out.getvalue()

    def _render_mask(self, index, fmt):
        w, h = self._camera(index).size
        image = np.zeros((h, w, 4), dtype=np.uint8)
        image[:, :, 3] = 255
        colored = [a for a in sorted(self.actors.values(), key=lambda a: a.name) if a.color]
        for i, actor in enumerate(colored):  # one vertical stripe per coloured actor
            image[:, i * max(1, w // max(1, len(colored))):, :3] = actor.color
        return png_bytes(image)
