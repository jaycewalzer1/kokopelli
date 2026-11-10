"""Variant A (world_transfer_multi.py) without the real model: weight rules, per-branch history views, and the
weight-1 identity with world_transfer.run on a tiny fake checkpoint.

The fake keeps world_transfer's hardcoded 36 layers, 32/8 heads and 128 head dim (they sit in reshapes), but the hidden
size, MLP width and time-embedding width are free in world_transfer's code, so they are tiny here. The VAE, tokenizer,
ffmpeg and decoder are replaced by small deterministic stand-ins; both runners read them off the world_transfer module,
so they see the same fakes.

Run: ~/cosmos3/cosmos3-mlx/.venv/bin/python -m unittest tests.wm.test_wm_multicontrol_a
"""
import argparse
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kokopelli.wm import world_transfer as wt                     # noqa: E402
from kokopelli.wm import world_transfer_multi as wtm              # noqa: E402

D, MLP, TIME = 64, 32, 32          # hidden, MLP and time-embedding widths of the fake
W, H, FRAMES = 48, 32, 13          # canvas -> latent 2x3 (odd width exercises the patch padding), 4 latent frames
SIGMAS = [1.0, 0.9375, 0.8333333333333334, 0.625]


def fake_arrays():
    """Tiny random weights under the checkpoint's key names (both halves), float32; the code casts to bf16."""
    import mlx.core as mx
    rng = np.random.RandomState(0)
    lin = lambda o, i: rng.standard_normal((o, i)).astype(np.float32) / np.sqrt(i)
    ones = lambda n: (1 + 0.1 * rng.standard_normal(n)).astype(np.float32)
    small = lambda n: (0.02 * rng.standard_normal(n)).astype(np.float32)
    out = {"embed_tokens.weight": rng.standard_normal((16, D)).astype(np.float32),
           "proj_in.weight": lin(D, 192), "proj_in.bias": small(D), "proj_out.weight": lin(192, D),
           "proj_out.bias": small(192), "norm_moe_gen.weight": ones(D),
           "time_embedder.linear_1.weight": lin(TIME, 256), "time_embedder.linear_1.bias": small(TIME),
           "time_embedder.linear_2.weight": lin(D, TIME), "time_embedder.linear_2.bias": small(D)}
    for i in range(36):
        p = f"layers.{i}."
        for q, k, v, o in (("to_q", "to_k", "to_v", "to_out"), ("add_q_proj", "add_k_proj", "add_v_proj", "to_add_out")):
            out.update({p + f"self_attn.{q}.weight": lin(4096, D), p + f"self_attn.{k}.weight": lin(1024, D),
                        p + f"self_attn.{v}.weight": lin(1024, D), p + f"self_attn.{o}.weight": lin(D, 4096)})
        for mlp in ("mlp", "mlp_moe_gen"):
            out.update({p + f"{mlp}.gate_proj.weight": lin(MLP, D), p + f"{mlp}.up_proj.weight": lin(MLP, D),
                        p + f"{mlp}.down_proj.weight": lin(D, MLP)})
        for name, n in (("input_layernorm", D), ("post_attention_layernorm", D), ("input_layernorm_moe_gen", D),
                        ("post_attention_layernorm_moe_gen", D), ("self_attn.norm_q", 128), ("self_attn.norm_k", 128),
                        ("self_attn.norm_added_q", 128), ("self_attn.norm_added_k", 128)):
            out[p + name + ".weight"] = ones(n)
    return {k: mx.array(v) for k, v in out.items()}


class FakeWorld:
    """Patches world_transfer's IO (ffprobe, ffmpeg, tokenizer, VAE, shards) with deterministic stand-ins."""

    def __init__(self, tmp, arrays):
        self.tmp, self.arrays = Path(tmp), arrays
        self.model_dir = self.tmp / "model"
        self.model_dir.mkdir()
        (self.model_dir / "config.json").write_text(json.dumps({"cosmos3_nano_sim_bimanual": {
            "checkpoint_id": "fake", "fixed_step_sampler_config": {"t_list": SIGMAS}}}))
        self.videos = {}
        self.proj = np.random.RandomState(1).standard_normal((3, 48)).astype(np.float32)

    def video(self, name, seed):
        path = str(self.tmp / f"{name}.mp4")
        self.videos[path] = np.random.RandomState(seed).randint(0, 256, (FRAMES, H, W, 3)).astype(np.uint8)
        return path

    def encode(self, video, vae_dir):
        import mlx.core as mx
        t, h, w, _ = video.shape
        v = np.concatenate([video[:1], video[1:].reshape(-1, 4, h, w, 3).mean(1)])
        v = v.reshape(len(v), h // 16, 16, w // 16, 16, 3).mean((2, 4)) * 4 - 2
        return mx.array((v @ self.proj)[None].astype(np.float32))

    def patches(self):
        package = types.ModuleType("cosmos3_mlx")
        encode_vae = types.ModuleType("cosmos3_mlx.encode_vae")
        encode_vae.encode_video = self.encode
        package.encode_vae = encode_vae
        return [mock.patch.dict(sys.modules, {"cosmos3_mlx": package, "cosmos3_mlx.encode_vae": encode_vae}),
                mock.patch.object(wt, "probe_fps", lambda path: 24.0),
                mock.patch.object(wt, "read_video", lambda path, w, h, hint, frames=None: self.videos[str(path)][:frames]),
                mock.patch.object(wt, "tokenize", lambda model_dir, text: [1, 5, 9, 2, 7]),
                mock.patch.object(wt, "shard_arrays", lambda model_dir: dict(self.arrays)),
                mock.patch.object(wt, "decode_chunked",
                                  lambda lat, vae, chunk: np.zeros((4 * (lat.shape[1] - 1) + 1, H, W, 3), np.float32)),
                mock.patch.object(wt, "save_mp4", lambda frames, path, fps: None)]

    def __enter__(self):
        self.active = self.patches()
        for p in self.active:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.active):
            p.stop()

    def run_single(self, hint, path, name, window, sink):
        args = argparse.Namespace(prompt="a bridge", hint=hint, control=path, output=str(self.tmp / f"{name}.mp4"),
                                  size=f"{W}x{H}", frames=None, seed=2025, window=window, sink=sink, quantize=None,
                                  decode_chunk=6, model_dir=str(self.model_dir), save_latents=str(self.tmp / f"{name}.npy"),
                                  raw_prompt=False, extra=None)
        wt.run(args)
        return np.load(args.save_latents)

    def run_multi(self, controls, weights, name, window, sink):
        argv = ["a bridge", "--output", str(self.tmp / f"{name}.mp4"), "--size", f"{W}x{H}", "--seed", "2025",
                "--window", str(window), "--sink", str(sink), "--model-dir", str(self.model_dir),
                "--save-latents", str(self.tmp / f"{name}.npy")]
        for hint, path in controls.items():
            argv += ["--control", f"{hint}={path}"]
        for hint, w in (weights or {}).items():
            argv += ["--weight", f"{hint}={w}"]
        wtm.main(argv)
        sidecar = json.loads(Path(str(self.tmp / f"{name}.mp4") + ".json").read_text())
        return np.load(self.tmp / f"{name}.npy"), sidecar


class WeightTest(unittest.TestCase):
    def test_normalised_to_sum_one_in_control_order(self):
        w = wtm.normalize_weights({"blur": "a", "seg": "b", "depth": "c"}, {"seg": 3, "depth": 3, "blur": 4})
        self.assertEqual(list(w), ["blur", "seg", "depth"])
        self.assertAlmostEqual(sum(w.values()), 1.0)
        self.assertAlmostEqual(w["blur"], 0.4)

    def test_default_is_equal_and_one_control_is_exactly_one(self):
        self.assertEqual(wtm.normalize_weights({"blur": "a", "seg": "b"}), {"blur": 0.5, "seg": 0.5})
        self.assertEqual(wtm.normalize_weights({"blur": "a"}, {"blur": 0.3}), {"blur": 1.0})

    def test_zero_weight_is_allowed_if_the_sum_is_positive(self):
        self.assertEqual(wtm.normalize_weights({"blur": "a", "seg": "b"}, {"blur": 0, "seg": 2}), {"blur": 0.0, "seg": 1.0})

    def test_bad_weights_fail(self):
        controls = {"blur": "a", "seg": "b"}
        for weights in ({"blur": -0.1, "seg": 1}, {"blur": 0, "seg": 0}, {"blur": 1}, {"blur": 1, "seg": 1, "edge": 1},
                        {"blur": float("nan"), "seg": 1}, {"blur": float("inf"), "seg": 1}):
            with self.assertRaises(ValueError, msg=weights):
                wtm.normalize_weights(controls, weights)
        with self.assertRaises(ValueError):
            wtm.normalize_weights({}, {})

    def test_cli_pairs(self):
        self.assertEqual(wtm.parse_pairs(["blur=0.5", "seg=.5"], "--weight", float), {"blur": 0.5, "seg": 0.5})
        for bad in (["blur"], ["sky=1"], ["blur=1", "blur=2"]):
            with self.assertRaises(SystemExit):
                wtm.parse_pairs(bad, "--weight", float)

    def test_wrapper_builds_a_held_wmmc_command_and_checks_weights_first(self):
        with mock.patch.object(wtm.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            wtm.transfer_video_multi("p", {"blur": "/x/blur.mp4", "seg": "/x/seg.mp4"}, "/tmp/o.mp4",
                                     weights={"blur": 0.5, "seg": 0.5}, frames=17)
            command = run.call_args[0][0]
            self.assertEqual(command[2:4], ["hold", "--name"])
            self.assertTrue(command[4].startswith("wmmc_"))
            self.assertIn("blur=/x/blur.mp4", command)
            self.assertIn("seg=0.5", command)
            self.assertEqual(command[command.index("--frames") + 1], "17")
            with self.assertRaises(ValueError):
                wtm.transfer_video_multi("p", {"blur": "/x/blur.mp4"}, "/tmp/o.mp4", weights={"seg": 1})
            self.assertEqual(run.call_count, 1)


class HistoryTest(unittest.TestCase):
    def test_each_branch_sees_what_a_single_hint_history_would(self):
        for window, sink in ((0, 0), (51, 1), (3, 1), (2, 1), (4, 2), (5, 0)):
            n, frames = 3, 9
            multi = wtm.MultiHistory(n, window, sink)
            singles = [wt.History(window, sink) for _ in range(n)]
            for f in range(frames):
                for i in range(n):
                    self.assertEqual(multi.view(i, False), singles[i].view(False), (window, sink, f, i))
                    multi.add_control(i, ("C", i, f))
                    singles[i].add(("C", i, f))
                    self.assertEqual(multi.view(i, True), singles[i].view(True), (window, sink, f, i))
                if f < frames - 1:
                    r = ("R", f)
                    multi.add_target(r)
                    for s in singles:
                        s.add(r)
            if window and window < frames:   # eviction happened and the shared R entries are the same objects in every branch
                self.assertLess(len(multi.branches[0].entries), 2 * frames - 1)
            self.assertIs(multi.branches[0].entries[-2], multi.branches[2].entries[-2])


class FakeModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.arrays = fake_arrays()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.world = FakeWorld(self._tmp.name, self.arrays).__enter__()

    def tearDown(self):
        self.world.__exit__()
        self._tmp.cleanup()

    def test_one_control_at_weight_one_is_bitwise_world_transfer(self):
        blur = self.world.video("blur", 10)
        for window, sink in ((3, 1), (0, 0)):   # (3, 1) evicts within 4 latents; (0, 0) keeps the full history
            single = self.world.run_single("blur", blur, f"single_{window}", window, sink)
            multi, sidecar = self.world.run_multi({"blur": blur}, {"blur": 1}, f"multi_{window}", window, sink)
            self.assertEqual(single.shape, (1, 4, 2, 3, 48))
            self.assertTrue(np.isfinite(single).all() and np.abs(single).max() > 0)
            np.testing.assert_array_equal(multi, single)
        self.assertEqual(sidecar["variant"], "A")
        self.assertEqual(sidecar["weights"], {"blur": 1.0})
        ref = json.loads(Path(str(self.world.tmp / "single_0.mp4") + ".json").read_text())
        for key in ("formatted_prompt", "size", "frames", "latent_frames", "seed", "steps", "sigmas", "window", "sink"):
            self.assertEqual(sidecar[key], ref[key], key)

    def test_two_identical_controls_at_half_equal_one(self):
        blur = self.world.video("blur", 10)
        one, _ = self.world.run_multi({"blur": blur}, None, "one", 3, 1)
        two, sidecar = self.world.run_multi({"blur": blur, "edge": blur}, {"blur": 0.5, "edge": 0.5}, "two", 3, 1)
        np.testing.assert_allclose(two, one, rtol=0, atol=1e-2)
        self.assertEqual(sidecar["weights"], {"blur": 0.5, "edge": 0.5})

    def test_three_controls_shapes_and_effect(self):
        paths = {h: self.world.video(h, s) for h, s in (("blur", 10), ("seg", 11), ("depth", 12))}
        three, sidecar = self.world.run_multi(paths, {"blur": 0.4, "seg": 0.3, "depth": 0.3}, "three", 3, 1)
        blur, _ = self.world.run_multi({"blur": paths["blur"]}, None, "blur", 3, 1)
        self.assertEqual(three.shape, (1, 4, 2, 3, 48))
        self.assertTrue(np.isfinite(three).all())
        self.assertGreater(np.abs(three - blur).max(), 1e-3)   # the other branches do change the result
        self.assertAlmostEqual(sum(sidecar["weights"].values()), 1.0)
        self.assertEqual(sidecar["raw_weights"], {"blur": 0.4, "seg": 0.3, "depth": 0.3})
        for key in ("model", "controls", "steps", "sigmas", "seed", "window", "sink", "timing", "seconds", "peak_gb",
                    "ru_maxrss_gb", "formatted_prompt"):
            self.assertIn(key, sidecar)


if __name__ == "__main__":
    unittest.main()
