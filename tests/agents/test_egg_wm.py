"""Dry run of the egg scene's closed loop (kokopelli/agents/egg_wm.py): no Unreal, no Cosmos, no Qwen, no GPU.

A fake sim stands in for SimWorld (Mara at the Fern Common House door, Teo a few metres away, painted frames are
just coloured fields), a fake world model passes the blur control through as the "painting", and a scripted brain
answers like a model that holds the lay belief: it refuses when the starving cue is in its prompt, gives otherwise.
That's enough to check the wiring: the cue reaches the prompt and no number does, the body verbs change the body by the
world's rules, the outcome is recorded, and body.jsonl lines up with the film for the overlay.

    tools/fable/test_all.sh tests/agents/test_egg_wm.py      (see AGENTS.md: tests only run under the memory guard)
"""
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

import numpy as np

from kokopelli.agents import egg_wm, live, live_wm
from kokopelli.wm import llm_model

PROMPTS = []


def scripted_ask(prompt, images=(), max_tokens=300, temperature=0.4):
    PROMPTS.append(prompt)
    asked_already = "You hand Teo" in prompt or "Sorry, Teo" in prompt
    severe = any(word in prompt for word in ("hollow and aching", "gnawing emptiness", "shaky and empty"))
    if not asked_already:
        if severe:
            return '{"thought": "I can barely stand, I need these.", "action": {"type": "say", "text": "Sorry, Teo, I only have two."}}'
        return '{"thought": "Of course.", "action": {"type": "give", "target": "teo", "object": "egg"}}'
    if "plate:" not in prompt and "egg_bowl: empty" not in prompt:
        return '{"thought": "Breakfast.", "action": {"type": "cook", "object": "egg"}}'
    if "plate:" in prompt:
        return '{"thought": "Eat.", "action": {"type": "eat"}}'
    return '{"thought": "Nice morning.", "action": {"type": "wait"}}'


W, H = 64, 36


class FakeStream:
    """WorldStream's interface: push controls, get painted frames back (here: the blur control itself)."""

    def __init__(self, prompt, **kwargs):
        self.info = {"weights": "fake", "formatted_prompt": prompt}
        self.last = {}

    def push(self, controls):
        frames = controls["blur"]
        self.last = {"frames_out": len(frames), "latents": 1, "s_per_latent": 0.0, "peak_gb": 0.0}
        return frames

    def release(self):
        pass

    def close(self):
        pass


class FakeSim:
    """SimWorldPhysics's interface with nothing moving: two people at a door, the clock advancing."""

    def __init__(self, cfg):
        self.cfg, self.dir, self.t, self.k = cfg, Path(cfg.out_dir), 0.0, 0
        self.dir.mkdir(parents=True, exist_ok=True)
        self.wire = NS(request=lambda *a, **k: "ok")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _state(self):
        x, y, z = self.cfg.agent_position
        teo = self.cfg.npcs[0]
        start = 8 * 3600 + 5 * 60 + int(self.t)
        pose = lambda loc, yaw=0.0: NS(location=NS(x=loc[0], y=loc[1], z=loc[2]), rotation=NS(yaw=yaw))  # noqa: E731
        return NS(sim_time_s=self.t, time_of_day=NS(clock=f"{start // 3600:02d}:{start // 60 % 60:02d}:{start % 60:02d}"),
                  agent=NS(pose=pose((x, y, z), self.cfg.agent_yaw), posture="standing", held_object=None),
                  npcs=[NS(id=teo.id, pose=pose(teo.position))], objects=[])

    def _capture(self):
        self.k += 1
        renders = {}
        for modality, ext in (("rgb", "png"), ("depth", "npy"), ("segmentation", "png")):
            path = self.dir / f"c{self.k:05d}_{modality}.{ext}"
            if ext == "npy":
                np.save(path, np.full((H, W), 900.0, np.float32))
            else:
                live_wm.ctl.Image.fromarray(np.full((H, W, 3), (self.k * 7) % 255, np.uint8)).save(path)
            renders[modality] = NS(path=str(path), format=ext)
        return NS(state=self._state(), renders=renders)

    def reset(self, seed=0):
        return self._capture()

    def step(self, action):
        captures = []
        for offset in self.cfg.capture_offsets_s:
            self.t = round(self.t + (offset - (captures and self.cfg.capture_offsets_s[len(captures) - 1] or 0)), 6)
            captures.append(self._capture())
        return NS(outcome=NS(status="completed", detail=""), final_state=captures[-1].state, captures=captures)


def run_level(level, out_root):
    args = SimpleArgs(level=level, out=str(out_root / level))
    life = egg_wm.EggLife(args)
    life.run()
    return life


class SimpleArgs(NS):
    def __init__(self, **over):
        super().__init__(level="half", arm="cue", port=9001, minutes=1.0, clock="08:05", room_warmth=58.0,
                         weights="models/fake", size=f"{W}x{H}", fps=2, seed=2025, window=24, sink=1, quantize=8,
                         wm_prompt="test", out=None)
        self.__dict__.update(over)
        self.steps = max(1, int(round(self.minutes * 60 / live.STEP_S)))
        self.who, self.situation = egg_wm.egg.WHO, egg_wm.egg.SITUATION
        self.speed, self.follow, self.vision, self.body = 1.6, False, "unreal", "mara"


class EggLoopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        # Stand-ins for the sim, the world model and Qwen, put on the real modules for this class only and taken off
        # again afterwards: the whole tree runs in one process, so nothing here may outlive the class.
        # live.ROOT: run folders land in the temp dir, not out/. LLM_MODEL_WEIGHTS: decide() sets it, so it's restored.
        cls.patches = [mock.patch.object(live, "SimWorldPhysics", FakeSim), mock.patch.object(live_wm, "WorldStream", FakeStream),
                       mock.patch.object(live, "ROOT", cls.tmp), mock.patch.object(llm_model, "ask", scripted_ask),
                       mock.patch.object(llm_model, "load_llm", lambda: None), mock.patch.object(llm_model, "unload", lambda: None),
                       mock.patch.object(llm_model, "LLM_MODEL_WEIGHTS", Path("models/fake"))]
        for patch in cls.patches:
            patch.start()
        PROMPTS.clear()
        cls.lives = {level: run_level(level, cls.tmp / "links") for level in ("full", "half", "starving")}
        cls.prompts_at_setup = list(PROMPTS)   # before any test that builds another life adds to the list

    @classmethod
    def tearDownClass(cls):
        for patch in cls.patches:
            patch.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def result(self, level):
        return json.loads((self.tmp / "links" / level / "egg.json").read_text())

    def test_the_level_decides_the_answer_for_a_lay_belief_brain(self):
        self.assertEqual(self.result("full")["outcome"], "gave")
        self.assertEqual(self.result("starving")["outcome"], "declined")

    def test_the_cue_reaches_the_prompt_and_no_body_number_does(self):
        first = [p for p in PROMPTS if "Morning, Mara!" in p]
        self.assertTrue(any("hollow and aching" in p or "gnawing" in p or "shaky and empty" in p for p in first))
        for prompt in PROMPTS:
            self.assertIsNone(re.search(r"\b(92|8\.0|energy|warmth)\b|\bfood\W*\d", prompt))
            self.assertIn('"type": "give"', prompt)

    def test_the_loops_prompts_are_pinned(self):
        # Every prompt the three dry runs sent, in order, as the ported code first produced them (Phase 0 of
        # docs/SENSATIONS_OVERNIGHT.md). A refactor of how the prompt is assembled must leave these byte for byte.
        golden = json.loads((Path(__file__).resolve().parent / "golden" / "egg_loop_prompts.json").read_text())
        self.assertEqual(len(self.prompts_at_setup), len(golden["prompts"]))
        for k, (now, then) in enumerate(zip(self.prompts_at_setup, golden["prompts"], strict=True)):
            self.assertEqual(now, then, f"prompt {k}")

    def test_giving_moves_an_egg_by_the_worlds_rules(self):
        full = self.result("full")
        self.assertLess(full["body_at_end"]["eggs"] + full["body_at_end"]["cooked"], egg_wm.egg.EGGS_AT_START)

    def test_body_log_has_a_line_per_step_with_time_and_feeling(self):
        lines = [json.loads(line) for line in (self.tmp / "links" / "starving" / "body.jsonl").read_text().splitlines()]
        self.assertEqual(len(lines), SimpleArgs().steps + 1)
        self.assertEqual(lines[0]["t"], 0.0)
        self.assertTrue(lines[0]["felt"])
        self.assertTrue(all(b["t"] > a["t"] for a, b in zip(lines, lines[1:], strict=False)))

    def test_film_and_sidecar_are_written(self):
        run = (self.tmp / "links" / "full").resolve()
        self.assertTrue((run / "world_model.mp4").exists())
        meta = json.loads((run / "run.json").read_text())
        self.assertEqual((meta["scene"], meta["level"], meta["arm"]), ("egg", "full", "cue"))

    def test_a_run_on_stand_ins_says_so_in_every_record(self):
        # Nothing here was painted by Cosmos or answered by Qwen, so no record may name them.
        result = self.result("full")
        self.assertIs(result["dry_run"], True)
        self.assertIsNone(result["world_model"])
        self.assertIsNone(result["agent_model"])
        sidecar = json.loads(((self.tmp / "links" / "full").resolve() / "run.json").read_text())
        self.assertIs(sidecar["dry_run"], True)
        # The sidecar has a place for the precision and both weights folders, and a stand-in has no folder to name.
        self.assertEqual((sidecar["world_model_weights"], sidecar["agent_weights"]), (None, None))
        self.assertIn("quantize", sidecar)
        # A real painter reports its folder's name from another process; the path is the one place that worker loads from.
        from kokopelli.wm import world_transfer
        self.assertEqual(egg_wm.painter_weights(world_transfer.MODEL_DIR.name), str(world_transfer.MODEL_DIR))
        self.assertEqual([egg_wm.painter_weights(name) for name in (None, "fake (no model)")], [None, None])

    def test_overlay_and_triptych(self):
        from kokopelli.body import overlay
        for level in ("full", "half", "starving"):
            made = overlay.overlay(self.tmp / "links" / level)
            w, h, _, frames = overlay.probe(made)
            self.assertEqual((w, h), (W + overlay.PANEL_W, H))
            self.assertGreater(frames, 1)
        # The panel shows a choice from the moment it is made, not a step later.
        lines = [{"t": 0.0, "last_action": None, "outcome": None}, {"t": 15.0, "last_action": {"type": "give"}, "outcome": "gave"}]
        self.assertEqual(overlay.shown_at(lines, 3.0), {"t": 0.0, "last_action": {"type": "give"}, "outcome": "gave"})
        self.assertIs(overlay.shown_at(lines, 15.0), lines[1])
        # The cue shown is the one that went into the choice beside it: both are recorded on the following line.
        lines = [{"t": 0.0, "felt": ["a"], "last_action": None}, {"t": 15.0, "felt": ["a"], "last_action": {"type": "give"}},
                 {"t": 30.0, "felt": ["b"], "last_action": {"type": "cook"}}]
        self.assertEqual([(shown["felt"], shown["last_action"]) for shown in (overlay.shown_at(lines, t) for t in (3.0, 20.0, 30.0))],
                         [(["a"], {"type": "give"}), (["b"], {"type": "cook"}), (["b"], {"type": "cook"})])
        # A film too short for the panel's text is enlarged by a whole number, and the record says by how much.
        self.assertEqual([overlay.fitting_scale(h) for h in (480, 256, 36)], [1, 2, 14])
        big = overlay.overlay(self.tmp / "links" / "full", out=self.tmp / "big.mp4", scale=2)
        self.assertEqual(overlay.probe(big)[:2], (2 * W + overlay.PANEL_W, 2 * H))
        self.assertEqual(json.loads((self.tmp / "big.mp4.json").read_text())["film_enlarged"], 2)
        tri = overlay.triptych(self.tmp / "links")
        w, h, _, _ = overlay.probe(tri)
        self.assertEqual(w, 3 * (W + overlay.PANEL_W))
        meta = json.loads(tri.with_name(tri.name + ".json").read_text())
        self.assertIs(meta["dry_run"], True)
        self.assertIs(json.loads((self.tmp / "links" / "full" / "overlay.mp4.json").read_text())["dry_run"], True)
        self.assertEqual(meta["outcomes"], {"full": "gave", "half": "gave", "starving": "declined"})

    def test_voice_is_placed_at_decision_times_and_muxed(self):
        from kokopelli.body import overlay, voice
        run = self.tmp / "links" / "starving"
        lines = voice.script(run)
        self.assertTrue(lines and lines[0][0] == 0.0)
        tone = lambda text: np.sin(np.linspace(0, 200, voice.SAMPLE_RATE // 2)).astype(np.float32) * 0.2  # noqa: E731
        wav = voice.make(run, speak=tone)
        made = overlay.with_voice(overlay.overlay(run), wav)
        streams = __import__("subprocess").run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                                                str(made)], capture_output=True, text=True).stdout.split()
        self.assertEqual(sorted(streams), ["audio", "video"])

    def test_an_existing_out_is_refused(self):
        with self.assertRaises(SystemExit):
            egg_wm.EggLife(SimpleArgs(level="full", out=str(self.tmp / "links" / "full")))


if __name__ == "__main__":
    unittest.main()
