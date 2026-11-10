"""A 2D grid standing in for SimWorld: a few people who wander and a few objects the agent can use."""
import math
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from kokopelli.loop.frames import file_hash
from kokopelli.loop.interfaces import Capture, PhysicsSim, SimStep

WIDTH, HEIGHT, CELL = 448, 256, 16
COLUMNS, ROWS = WIDTH // CELL, HEIGHT // CELL
SPEED = 5.0  # cells every 15 sim-seconds
REACH = 1.5
HEARING = 6.0
START = {
    "agent": [3.0, 8.0],
    "npcs": {"ana": [8.0, 4.0], "ben": [20.0, 11.0], "neighbor": [24.0, 3.0]},
    "objects": {"bench": [14.0, 8.0], "mailbox": [6.0, 13.0], "ball": [18.0, 5.0], "door": [1.0, 2.0]},
}
NPC_COLORS = {"ana": (150, 90, 100), "ben": (80, 95, 110), "neighbor": (95, 110, 80)}
OBJECT_COLORS = {"bench": (90, 67, 52), "mailbox": (120, 60, 50), "ball": (190, 150, 70), "door": (60, 45, 35)}
SEG_IDS = {"agent": 10, "ana": 20, "ben": 30, "neighbor": 40, "bench": 50, "mailbox": 60, "ball": 70, "door": 80}
FOV_DEGREES = 90.0


def _distance(a, b):
    return math.dist(a, b)


def _toward(position, target, step):
    gap = _distance(position, target)
    if gap <= step:
        return list(target)
    return [position[0] + (target[0] - position[0]) * step / gap, position[1] + (target[1] - position[1]) * step / gap]


def _intrinsics():
    # A pinhole camera: focal length in pixels follows from the field of view and the image width.
    focal = (WIDTH / 2) / math.tan(math.radians(FOV_DEGREES) / 2)
    return {"fx": round(focal, 2), "fy": round(focal, 2), "cx": WIDTH / 2, "cy": HEIGHT / 2, "width": WIDTH, "height": HEIGHT}


class MockSim(PhysicsSim):
    def reset(self, seed, start_time, out_dir, capture_offsets):
        self.seed, self.out_dir, self.capture_offsets = seed, Path(out_dir), capture_offsets
        self.state = {
            "tick": 0, "sim_time": start_time, "time_of_day": "", "weather": "clear",
            "agent": {"pos": list(START["agent"]), "facing": "east", "velocity": [0.0, 0.0], "goal": None, "holding": None},
            "npcs": {name: {"pos": list(pos)} for name, pos in START["npcs"].items()},
            "objects": {name: {"pos": list(pos), "state": "at rest"} for name, pos in START["objects"].items()},
            "last_result": {},
        }
        self._describe()
        return SimStep(self.get_state(), [self._capture(0, 0)], self._visible())

    def step(self, action, tick, render=True):
        started = time.perf_counter()
        self.state["tick"] = tick
        self.state["last_result"] = self._apply(action)
        apply_seconds = time.perf_counter() - started
        captures, render_seconds, step_seconds = [], 0.0, 0.0
        previous = 0
        for offset in self.capture_offsets:
            clock = time.perf_counter()
            self._advance(offset - previous, tick, offset)
            step_seconds += time.perf_counter() - clock
            previous = offset
            if render:
                clock = time.perf_counter()
                captures.append(self._capture(tick, offset))
                render_seconds += time.perf_counter() - clock
        seconds = {"apply": round(apply_seconds, 4), "step": round(step_seconds, 4), "render": round(render_seconds, 4)}
        return SimStep(self.get_state(), captures, self._visible(), seconds)

    def get_state(self):
        return _copy(self.state)

    def restore_state(self, state):
        self.state = _copy(state)

    def _apply(self, action):
        kind, agent = action["type"], self.state["agent"]
        if kind == "move_to":
            agent["goal"] = action["target"]
            return {"action": kind, "ok": True, "target": action["target"]}
        if kind == "look_at":
            agent["goal"] = None
            agent["facing"] = self._heading(self._position_of(action["target"]))
            return {"action": kind, "ok": True, "target": action["target"]}
        if kind == "interact":
            return self._interact(action["target"])
        if kind == "speak":
            heard = [name for name, npc in self.state["npcs"].items() if _distance(npc["pos"], agent["pos"]) <= HEARING]
            return {"action": kind, "ok": True, "text": action["text"], "heard_by": heard}
        agent["goal"] = None
        return {"action": kind, "ok": True}

    def _interact(self, target):
        agent, item = self.state["agent"], self.state["objects"].get(target)
        if item is None:
            return {"action": "interact", "ok": False, "target": target, "reason": "not an object"}
        if _distance(item["pos"], agent["pos"]) > REACH:
            return {"action": "interact", "ok": False, "target": target, "reason": "too far"}
        changes = {"ball": "held", "door": "open", "mailbox": "open", "bench": "sat on"}
        item["state"] = "at rest" if item["state"] == changes[target] else changes[target]
        agent["holding"] = target if item["state"] == "held" else None
        return {"action": "interact", "ok": True, "target": target, "state": item["state"]}

    def _advance(self, seconds, tick, offset):
        agent = self.state["agent"]
        before = list(agent["pos"])
        step = SPEED * seconds / 15
        if agent["goal"]:
            goal = self._position_of(agent["goal"])
            agent["pos"] = _toward(agent["pos"], goal, step)
            agent["facing"] = self._heading(goal)
            if _distance(agent["pos"], goal) < 0.01:
                agent["goal"] = None
        agent["velocity"] = [round((agent["pos"][i] - before[i]) / seconds, 3) for i in range(2)]
        for name, npc in self.state["npcs"].items():
            # A stream named by seed, person and moment: the people move the same whatever the agent does.
            draw = random.Random(f"{self.seed}:{name}:{tick}:{offset}")
            npc["pos"] = [min(COLUMNS - 1.0, max(0.0, npc["pos"][0] + draw.uniform(-1.5, 1.5))),
                          min(ROWS - 1.0, max(0.0, npc["pos"][1] + draw.uniform(-1.5, 1.5)))]
        if agent["holding"]:
            self.state["objects"][agent["holding"]]["pos"] = list(agent["pos"])
        moment = datetime.fromisoformat(self.state["sim_time"]) + timedelta(seconds=seconds)
        self.state["sim_time"] = moment.isoformat()
        self._describe()

    def _describe(self):
        hour = datetime.fromisoformat(self.state["sim_time"]).hour
        self.state["time_of_day"] = "night" if hour < 6 or hour >= 20 else "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
        agent = self.state["agent"]
        self.state["camera"] = {"intrinsics": _intrinsics(), "extrinsics": {"position": agent["pos"], "facing": agent["facing"]}}

    def _position_of(self, name):
        if name in self.state["npcs"]:
            return self.state["npcs"][name]["pos"]
        return self.state["objects"][name]["pos"]

    def _heading(self, target):
        x, y = target[0] - self.state["agent"]["pos"][0], target[1] - self.state["agent"]["pos"][1]
        if abs(x) >= abs(y):
            return "east" if x >= 0 else "west"
        return "south" if y >= 0 else "north"

    def _visible(self):
        return [*self.state["npcs"], *self.state["objects"]]

    def _capture(self, tick, offset):
        folder = self.out_dir / "ticks" / f"{tick:04d}"
        folder.mkdir(parents=True, exist_ok=True)
        # Filter mode captures every frame, so its offsets aren't whole seconds.
        label = f"{offset:02d}" if isinstance(offset, int) else f"{offset:07.3f}"
        paths = {name: folder / f"sim_{label}_{name}.png" for name in ("rgb", "depth", "seg")}
        Image.fromarray(self._rgb()).save(paths["rgb"])
        Image.fromarray(self._depth()).save(paths["depth"])
        Image.fromarray(self._seg()).save(paths["seg"])
        return Capture(offset, *(str(paths[name]) for name in ("rgb", "depth", "seg")),
                       hashes={name: file_hash(path) for name, path in paths.items()})

    def _entities(self):
        yield "agent", self.state["agent"]["pos"], (143, 71, 57)
        for name, npc in self.state["npcs"].items():
            yield name, npc["pos"], NPC_COLORS[name]
        for name, item in self.state["objects"].items():
            yield name, item["pos"], OBJECT_COLORS[name]

    def _rgb(self):
        hour = datetime.fromisoformat(self.state["sim_time"]).hour
        ground = (205, 195, 175) if 6 <= hour < 20 else (95, 90, 90)
        image = Image.new("RGB", (WIDTH, HEIGHT), ground)
        draw = ImageDraw.Draw(image)
        for x in range(0, WIDTH, CELL):
            draw.line([(x, 0), (x, HEIGHT)], fill=(185, 175, 155))
        for y in range(0, HEIGHT, CELL):
            draw.line([(0, y), (WIDTH, y)], fill=(185, 175, 155))
        for name, (x, y), color in self._entities():
            center = (x * CELL + CELL / 2, y * CELL + CELL / 2)
            box = [center[0] - 7, center[1] - 7, center[0] + 7, center[1] + 7]
            (draw.rectangle if name in self.state["objects"] else draw.ellipse)(box, fill=color)
            draw.text((center[0] + 9, center[1] - 6), name, fill=(43, 30, 24))
        return np.asarray(image)

    def _depth(self):
        # Top-down, so "depth" here is distance from the agent, in the 0-255 range of a grayscale image.
        ys, xs = np.mgrid[0:HEIGHT, 0:WIDTH]
        x, y = self.state["agent"]["pos"]
        distance = np.hypot(xs - (x * CELL + CELL / 2), ys - (y * CELL + CELL / 2))
        return np.uint8(np.clip(distance / math.hypot(WIDTH, HEIGHT) * 255, 0, 255))

    def _seg(self):
        image = Image.new("L", (WIDTH, HEIGHT), 0)
        draw = ImageDraw.Draw(image)
        for name, (x, y), _ in self._entities():
            center = (x * CELL + CELL / 2, y * CELL + CELL / 2)
            draw.rectangle([center[0] - 7, center[1] - 7, center[0] + 7, center[1] + 7], fill=SEG_IDS[name])
        return np.asarray(image)


def _copy(value):
    import json
    return json.loads(json.dumps(value))
