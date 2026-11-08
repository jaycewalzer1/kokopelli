"""Dry tests for two agents having lunch inside the world model (city/agents/lunch_wm.py, world_stream_multi.py).

No GPU, no Unreal, no Qwen, no weights:
  - the lunch loop runs on a fake world (real NavMap coordinates, toy walking), a scripted brain, and the fake
    world-model worker (a real subprocess speaking world_stream_multi's protocol);
  - TwoBodySim (the second humanoid and its head camera) runs against the adapter's fake UnrealCV server;
  - the shared-weights stream class is checked without MLX.

    .venv/bin/python -m unittest tests/test_city_lunch.py -v      (or -m pytest, where pytest is installed)
"""
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "city" / "agents"))

import lunch_wm as lw  # noqa: E402
from world_stream_multi import MultiWorldStream, SharedWeights, stream_class  # noqa: E402

W, H = 64, 32
STEP_S, FPS = 2.0, 4
FRAMES_PER_STEP = int(STEP_S * FPS)


def png(path, rgb):
    lw.ctl.Image.fromarray(rgb).save(path)


class FakeWorld:
    """The SimWorldPair interface with toy physics: bodies glide toward move_to goals at `speed` m/s."""

    def __init__(self, nav, folder, starts, speed=30.0, npcs=()):
        self.nav, self.dir, self.speed = nav, Path(folder), speed
        self.dir.mkdir(parents=True, exist_ok=True)
        self.pos = {k: list(v) for k, v in starts.items()}
        self.yaw = {k: 0.0 for k in starts}
        self.task = {k: None for k in starts}
        self.npc = list(npcs)
        self.sim_time_s, self.k, self.halted = 0.0, 0, False
        self.actions = []

    @property
    def clock(self):
        t = 12 * 3600 + 20 * 60 + int(self.sim_time_s)
        return f"{t // 3600:02d}:{t // 60 % 60:02d}:{t % 60:02d}"

    def _frame(self, k):
        self.k += 1
        x, y = self.pos[k]
        rgb = np.zeros((36, 64, 3), np.uint8)
        rgb[:, :, 0] = int(x) % 256
        rgb[:, :, 1] = int(y) % 256
        rgb[:18, :, 2] = 200
        seg = np.zeros((36, 64, 3), np.uint8)
        seg[:, 32:] = (128, 0, 128)
        out = {}
        for mod, ext in (("rgb", "png"), ("depth", "npy"), ("segmentation", "png")):
            out[mod] = str(self.dir / f"{k}_{self.k:05d}_{mod}.{ext}")
        png(out["rgb"], rgb)
        np.save(out["depth"], np.full((36, 64), 800.0 + x, np.float32))
        png(out["segmentation"], seg)
        return out

    def reset(self):
        return {k: [self._frame(k)] for k in self.pos}

    def _goal(self, k, a):
        if a.get("target_id"):
            t = a["target_id"]
            return self.pos[t] if t in self.pos else dict(self.npc)[t]
        return (a["position"]["x"] / 100, a["position"]["y"] / 100)

    def step(self, actions):
        self.actions.append(actions)
        outcomes = {}
        for k, a in actions.items():
            t = a["type"]
            if t == "move_to":
                self.task[k] = a
            elif t in ("wait", "look_at", "interact", "drop_object"):
                self.task[k] = None
                if t == "look_at":
                    g = self._goal(k, a)
                    self.yaw[k] = math.degrees(math.atan2(g[1] - self.pos[k][1], g[0] - self.pos[k][0]))
            phase = None
            if self.task[k]:
                g = self._goal(k, self.task[k])
                d = math.dist(self.pos[k], g)
                reach = self.task[k]["arrival_radius_cm"] / 100
                step = min(self.speed * STEP_S, max(0.0, d - reach * 0.5))
                if d > 0:
                    self.pos[k] = [self.pos[k][0] + (g[0] - self.pos[k][0]) * step / d,
                                   self.pos[k][1] + (g[1] - self.pos[k][1]) * step / d]
                phase = "arrived" if math.dist(self.pos[k], g) <= reach else "walking"
                if phase == "arrived":
                    self.task[k] = None
            status = {"arrived": "completed", "walking": "in_progress"}.get(phase, "completed")
            outcomes[k] = {"status": status, "detail": "", "phase": phase}
        self.sim_time_s += STEP_S
        frames = {k: [self._frame(k) for _ in range(FRAMES_PER_STEP)] for k in self.pos}
        return outcomes, frames

    def bodies(self):
        return {k: lw.Body(tuple(p), self.yaw[k]) for k, p in self.pos.items()}

    def npcs(self):
        return list(self.npc)

    def objects(self):
        return []

    def halt(self):
        self.halted = True


def section(prompt, start, end):
    return prompt.split(start, 1)[1].split(end, 1)[0]


class ScriptedBrain:
    """Stands in for Qwen. Walks to lunch, shouts once from too far away, and answers whatever it hears."""

    def __init__(self, test_shout=True):
        self.calls, self.unloads, self.lines = [], 0, {"Mara": 0, "Iris": 0}
        self.test_shout = test_shout

    def ask(self, prompt, image):
        name = re.match(r"You are (\w+)", prompt).group(1)
        other = "Iris" if name == "Mara" else "Mara"
        self.calls.append({"name": name, "prompt": prompt, "image": image})
        heard = section(prompt, "What you heard:\n", "\n\nYour notes")
        close = section(prompt, "Who is right next to you (close enough to talk):\n", "\n")
        mine = [c for c in self.calls if c["name"] == name]
        if name == "Mara" and len(mine) == 1 and self.test_shout:
            return json.dumps({"thought": "Is that her?", "action": {"type": "say", "text": "Iris? Is that you?"}})
        if other in heard:
            self.lines[name] += 1
            return json.dumps({"thought": "answer", "action": {"type": "say", "text": f"{name} line {self.lines[name]}"}})
        if other.lower() in close:
            if self.lines[name] == 0:
                self.lines[name] += 1
                return json.dumps({"thought": "there she is", "action": {"type": "say", "text": f"{name} opens"}})
            return json.dumps({"thought": "listen", "action": {"type": "wait"}})
        if "You are at The Kettle" in prompt:
            return json.dumps({"thought": "wait for her", "action": {"type": "wait"}})
        return json.dumps({"thought": "lunch", "action": {"type": "go_to", "place": "kettle_cafe"}})

    def unload(self):
        self.unloads += 1


def lunch_args(out):
    args = lw.build_args(["--minutes", "0.4", "--step-s", str(STEP_S), "--fps", str(FPS), "--size", f"{W}x{H}",
                          "--fake-wm", "--out", str(out), "--weights", "/models/Qwen3-VL-8B-Instruct-4bit"])
    return args


class LunchLoopTest(unittest.TestCase):
    """One run shared by the assertions below: 12 steps of 2 s at 4 fps."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="test_city_lunch_"))
        cls.out = cls.tmp / "run"
        nav = lw.NavMap()
        args = lunch_args(cls.out)
        lw.people(args, nav)
        cls.steps = args.steps
        starts = {"mara": nav.doors["fern_common"], "iris": nav.doors["fern_bakery"]}
        cls.world = FakeWorld(nav, cls.tmp / "sim", starts)
        cls.brain = ScriptedBrain()
        cls.wm = MultiWorldStream(out_dir=cls.out / "wm", fake=True)
        lw.open_streams(cls.wm, args, ["mara", "iris"])
        cls.lunch = lw.Lunch(args, cls.world, cls.wm, cls.brain, out=cls.out, nav=nav, cast=None)
        cls.lunch.run(cls.steps)
        cls.stats = cls.wm.stats()
        cls.wm.close()
        cls.events = [json.loads(l) for l in (cls.out / "events.jsonl").read_text().splitlines()]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def kind(self, k):
        return [e for e in self.events if e["kind"] == k]

    def test_steps_ran(self):
        self.assertEqual(self.steps, 12)
        self.assertTrue(self.world.halted)

    def test_both_walk_to_lunch_and_meet(self):
        b = self.world.bodies()
        door = self.lunch.nav.doors["kettle_cafe"]
        self.assertLess(math.dist(b["mara"].xy, door), 3)
        self.assertLess(math.dist(b["iris"].xy, door), 3)

    def test_a_shout_from_too_far_is_not_heard(self):
        shout = [e for e in self.kind("says") if "Is that you" in e["text"]]
        self.assertEqual(len(shout), 1)
        heard = [e for e in self.kind("heard_by") if e["step"] == shout[0]["step"] and e["mind"] == "mara"][0]
        self.assertEqual(heard["listeners"], [])
        self.assertFalse(any("Is that you" in c["prompt"] for c in self.brain.calls if c["name"] == "Iris"))

    def test_a_real_back_and_forth_happens_and_alternates(self):
        talk = [e for e in self.kind("says") if "Is that you" not in e["text"]]
        self.assertGreaterEqual(len(talk), 6, [e["text"] for e in talk])
        speakers = [e["mind"] for e in talk]
        for a, b in zip(speakers, speakers[1:]):
            self.assertNotEqual(a, b, speakers)

    def test_every_line_said_nearby_reaches_the_other_ones_next_prompt(self):
        talk = [e for e in self.kind("says") if "Is that you" not in e["text"]]
        for e in talk[:-1]:
            listener = "Iris" if e["mind"] == "mara" else "Mara"
            later = [c for c in self.brain.calls if c["name"] == listener and e["text"] in c["prompt"]]
            self.assertTrue(later, f"{listener} never heard {e['text']!r}")
            self.assertIn(e["text"], section(later[0]["prompt"], "What you heard:\n", "\n\nYour notes"))

    def test_the_listener_answers_in_the_same_step(self):
        talk = [e for e in self.kind("says") if "Is that you" not in e["text"]]
        acts = self.kind("act")
        for e in talk[:-1]:
            listener = "iris" if e["mind"] == "mara" else "mara"
            answer = [a for a in acts if a["mind"] == listener and a["step"] == e["step"] and a["reason"] == "heard"]
            if not answer:   # the speaker spoke as the step's second decider; the answer comes first next step
                answer = [a for a in acts if a["mind"] == listener and a["step"] == e["step"] + 1 and a["reason"] == "heard"]
            self.assertTrue(answer, f"no prompt answer to {e['text']!r} at step {e['step']}")

    def test_a_speaker_waits_for_the_answer(self):
        """Nobody decides twice in one step, and once talking, nobody talks twice in a row."""
        acts = self.kind("act")
        per_step = {}
        for a in acts:
            per_step.setdefault((a["step"], a["mind"]), 0)
            per_step[(a["step"], a["mind"])] += 1
        self.assertEqual(max(per_step.values()), 1)

    def test_agents_see_only_painted_frames(self):
        for c in self.brain.calls:
            p = Path(c["image"])
            self.assertTrue(p.exists())
            self.assertEqual(p.parent, self.out / "frames" / c["name"].lower())
            self.assertTrue(p.name.startswith("seen_"), p)
        self.assertFalse(any("/sim/" in c["image"] for c in self.brain.calls))

    def test_world_model_weights_load_once_per_paint_for_both_streams(self):
        """The worker drops the weights before Qwen thinks and reloads once per step for both agents."""
        self.assertEqual(set(self.stats["streams"]), {"mara", "iris"})
        self.assertLessEqual(self.stats["weight_loads"], self.steps + 1)
        self.assertGreaterEqual(self.stats["weight_loads"], 2)
        self.assertGreaterEqual(self.brain.unloads, self.steps)

    def frames_in(self, film):
        out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                              "stream=nb_read_frames,width,height", "-of", "json", str(film)], capture_output=True, text=True)
        s = json.loads(out.stdout)["streams"][0]
        return int(s["nb_read_frames"]), int(s["width"]), int(s["height"])

    @unittest.skipUnless(shutil.which("ffprobe"), "needs ffprobe")
    def test_films_are_continuous(self):
        total = 1 + self.steps * FRAMES_PER_STEP
        for name in ("mara", "iris", "sim_mara", "sim_iris"):
            n, w, h = self.frames_in(self.out / "film" / f"{name}.mp4")
            self.assertEqual((n, w, h), (total, W, H), name)
        n, w, h = self.frames_in(self.out / "film" / "side_by_side.mp4")
        self.assertEqual((n, w, h), (total, 2 * W + 4, H))
        for agent in ("mara", "iris"):
            for hint in lw.HINTS:
                self.assertEqual(self.frames_in(self.out / "controls" / agent / f"{hint}.mp4")[0], total)

    def test_logs_and_model_names(self):
        run = json.loads((self.out / "run.json").read_text())
        self.assertEqual(run["model"], "Cosmos3-Nano-Sim-Transfer")
        self.assertEqual(run["agent_model"], "Qwen3-VL-8B-Instruct-4bit")
        self.assertTrue(run["finished"])
        self.assertEqual(run["steps_done"], self.steps)
        self.assertEqual(run["seeds"], {"mara": 2025, "iris": 2026})
        side = json.loads((self.out / "film" / "side_by_side.mp4.json").read_text())
        self.assertEqual(side["model"], "Cosmos3-Nano-Sim-Transfer")
        md = (self.out / "transcript.md").read_text()
        self.assertIn("**Mara:**", md)
        self.assertIn("**Iris:**", md)
        live = json.loads((self.out / "live.json").read_text())
        self.assertEqual(set(live["agents"]), {"mara", "iris"})
        self.assertFalse(live["running"])
        # raw captures are deleted once they're controls
        self.assertEqual(list((self.tmp / "sim").glob("*")), [])


class NpcLunchTest(unittest.TestCase):
    def test_the_barista_tells_both_about_lunch(self):
        tmp = Path(tempfile.mkdtemp(prefix="test_city_lunch_npc_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        nav = lw.NavMap()
        args = lunch_args(tmp / "run")
        args.steps = 2
        lw.people(args, nav)
        cast = lw.lunch_cast(nav)
        door = nav.doors["kettle_cafe"]
        world = FakeWorld(nav, tmp / "sim", {"mara": door, "iris": (door[0] + 3, door[1])}, npcs=[("ana", (door[0] + 2, door[1] + 2))])

        class Brain(ScriptedBrain):
            def ask(self, prompt, image):
                self.calls.append({"name": re.match(r"You are (\w+)", prompt).group(1), "prompt": prompt})
                if len(self.calls) == 1:
                    return json.dumps({"thought": "", "action": {"type": "say", "text": "Ana, what's for lunch?"}})
                return json.dumps({"thought": "", "action": {"type": "wait"}})

        brain = Brain()
        wm = MultiWorldStream(out_dir=tmp / "run" / "wm", fake=True)
        self.addCleanup(wm.close)
        lw.open_streams(wm, args, ["mara", "iris"])
        lw.Lunch(args, world, wm, brain, out=tmp / "run", nav=nav, cast=cast).run(args.steps)
        iris = [c["prompt"] for c in brain.calls if c["name"] == "Iris"]
        self.assertTrue(any("Ana, what's for lunch?" in p for p in iris))
        self.assertTrue(any("nettle soup" in section(p, "What you heard:\n", "\n\nYour notes") for p in iris))
        self.assertIn("ana: Ana, barista", "\n".join(iris))


class SharedWeightsTest(unittest.TestCase):
    def test_streams_share_one_generator_and_release_lets_it_go(self):
        made = []
        shared = SharedWeights(lambda: made.append(object()) or made[-1])
        Stream = stream_class()
        a, b = Stream(shared), Stream(shared)
        a._load()
        b._load()
        self.assertIs(a.gen, b.gen)
        self.assertEqual(shared.loads, 1)
        shared.drop()
        a.release()
        b.release()
        self.assertIsNone(a.gen)
        self.assertIsNone(b.gen)
        b._load()
        self.assertEqual(shared.loads, 2)

    def test_fake_worker_keeps_streams_apart(self):
        tmp = Path(tempfile.mkdtemp(prefix="test_wsm_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        wm = MultiWorldStream(out_dir=tmp, fake=True)
        self.addCleanup(wm.close)
        wm.open("a", "p", size=f"{W}x{H}", fps=FPS)
        wm.open("b", "p", size=f"{W}x{H}", fps=FPS)
        ctl = {h: np.full((5, H, W, 3), 100, np.uint8) for h in lw.HINTS}
        self.assertEqual(len(wm.push("a", ctl)), 5)    # latents 0 and 1: frames 0-4
        self.assertEqual(len(wm.push("a", {h: v[:2] for h, v in ctl.items()})), 0)   # 7 in, latent 2 not complete
        self.assertEqual(len(wm.push("b", {h: v[:1] for h, v in ctl.items()})), 1)   # b has its own clock
        with self.assertRaises(RuntimeError):
            wm.push("c", ctl)


class TwoBodySimTest(unittest.TestCase):
    """The second humanoid and its head camera, over the real wire to the adapter's fake UnrealCV server."""

    def setUp(self):
        try:
            from runtime.tests.fake_unrealcv import FakeUnrealCV
        except ImportError as e:
            self.skipTest(f"no fake server: {e}")
        self.server = FakeUnrealCV().start()
        self.addCleanup(self.server.stop)
        tmp = Path(tempfile.mkdtemp(prefix="wmloop_lunch_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        tick = 1 / (2 * FPS)
        cfg = lw.SimWorldConfig(port=self.server.port, tick_interval_s=tick, velocity_window_s=tick, control_interval_s=0.5,
                                step_seconds=1.0, capture_offsets_s=tuple(k / FPS for k in range(1, FPS + 1)),
                                settle_s=0, init_settle_s=0, resolution=(32, 18), out_dir=str(tmp), npcs=[], objects=[],
                                agent_position=(0.0, 0.0, 100.0), spawn_weather_manager=False,
                                request_timeout_s=5.0, connect_timeout_s=5.0, reconnect_backoff_s=0.01)
        self.world = lw.SimWorldPair(cfg, "mara", "iris", (6.0, 0.0), 180.0)
        self.addCleanup(self.world.sim.close)

    def test_two_bodies_two_cameras_and_a_frame_per_tick_each(self):
        frames = self.world.reset()
        sim = self.world.sim
        self.assertNotEqual(sim.camera_id, sim.friend_camera_id)
        self.assertIn(lw.FRIEND_ACTOR, self.server.actors)
        self.assertEqual(self.server.cameras[sim.friend_camera_id].owner, lw.FRIEND_ACTOR)
        self.assertEqual(self.server.cameras[sim.camera_id].owner, lw.AGENT_ACTOR)
        self.assertEqual([len(frames["mara"]), len(frames["iris"])], [1, 1])
        before = self.world.bodies()["iris"].xy
        outcomes, frames = self.world.step({"mara": {"type": "wait"},
                                            "iris": {"type": "move_to", "position": {"x": -1000.0, "y": 0.0, "z": 100.0},
                                                     "arrival_radius_cm": 120}})
        for k in ("mara", "iris"):
            paths = [f["rgb"] for f in frames[k]] + [f["depth"] for f in frames[k]]
            self.assertEqual(len(frames[k]), FPS)
            self.assertEqual(len(set(paths)), len(paths), "every capture tick must keep its own file")
            self.assertTrue(all(Path(p).exists() for p in paths))
        self.assertTrue(all(Path(f["rgb"]).name.startswith("friend_") for f in frames["iris"]))
        after = self.world.bodies()["iris"].xy
        self.assertEqual(outcomes["iris"]["status"], "in_progress")
        self.assertGreater(math.dist(after, before), 0.5)   # walked ahead (she faces -x) toward x = -10 m
        # each can walk up to the other; the friend's "mara" means the adapter's agent
        outcomes, _ = self.world.step({"mara": {"type": "move_to", "target_id": "iris", "arrival_radius_cm": 250},
                                       "iris": {"type": "look_at", "target_id": "mara"}})
        self.assertIn(outcomes["mara"]["status"], ("in_progress", "completed"))
        self.assertEqual(outcomes["iris"]["status"], "completed")
        self.world.halt()


if __name__ == "__main__":
    unittest.main()
