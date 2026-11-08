"""world_stream.Worker frame bookkeeping, with no model: the films must have exactly as many frames as the controls.

The fake VAE behaves like the MLX port's: a clip of T latents decodes to 4*T frames (the first latent gives 4, where the
reference gives 1), and encoding n frames gives 1 + (n-1)//4 latents. Painting returns the control latent unchanged.

    .venv/bin/python -m unittest tests/test_world_stream.py
"""
import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import world_stream  # noqa: E402

H, W = 16, 32


class FakeMx:
    """The few mlx.core calls the Worker's bookkeeping makes, over numpy."""
    float32 = np.float32
    bfloat16 = np.float32

    @staticmethod
    def concatenate(xs, axis=0):
        return np.concatenate(xs, axis=axis)

    @staticmethod
    def eval(*_):
        pass

    @staticmethod
    def clear_cache():
        pass

    @staticmethod
    def reset_peak_memory():
        pass

    @staticmethod
    def get_peak_memory():
        return 0


def fake_encode(video, vae_dir):
    n = len(video)
    t = 1 + (n - 1) // 4
    lat = np.zeros((1, t, H // 16 or 1, W // 16 or 1, 48), np.float32)
    lat[0, :, 0, 0, 0] = np.arange(t)   # remember which latent this is
    return lat


def fake_decode(latents, vae_dir):
    t = latents.shape[1]
    return np.full((1, 4 * t, H, W, 3), 0.5, np.float32)   # the port: 4 frames per latent, the first included


class WorkerFrameCount(unittest.TestCase):
    def setUp(self):
        sys.modules["cosmos3_mlx"] = types.ModuleType("cosmos3_mlx")
        enc = types.ModuleType("cosmos3_mlx.encode_vae")
        enc.encode_video = fake_encode
        dec = types.ModuleType("cosmos3_mlx.decode_vae")
        dec.decode_latents = fake_decode
        sys.modules["cosmos3_mlx.encode_vae"], sys.modules["cosmos3_mlx.decode_vae"] = enc, dec
        w = world_stream.Worker()
        w.mx, w.model_dir = FakeMx, Path("/nonexistent")
        w.width, w.height, w.hints = W, H, ["blur", "seg", "depth", "edge"]
        w.frames_in, w.tail_start, w.n_painted, w.frames_out = 0, 0, 0, 0
        w.tail = {h: None for h in w.hints}
        w.lat_c = {h: [] for h in w.hints}
        w.painted = []
        w.gen = object()
        w._load = lambda: None
        w._paint_latent = lambda f, lat_cs: lat_cs[0]
        self.w = w
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        for name in ("cosmos3_mlx", "cosmos3_mlx.encode_vae", "cosmos3_mlx.decode_vae"):
            sys.modules.pop(name, None)
        self.tmp.cleanup()

    def push(self, n):
        paths = {}
        for h in self.w.hints:
            paths[h] = f"{self.tmp.name}/{h}_{self.w.frames_in}.npy"
            np.save(paths[h], np.zeros((n, H, W, 3), np.uint8))
        out = f"{self.tmp.name}/out_{self.w.frames_in}.npy"
        reply = self.w.push(paths, out)
        return np.load(out) if reply["frames"] else np.zeros((0, H, W, 3), np.uint8)

    def test_first_push_matches_controls(self):
        self.assertEqual(len(self.push(21)), 21)        # 1 + 4*5 frames -> 6 latents -> 21 frames

    def test_two_pushes_match_controls(self):
        a = self.push(21)
        b = self.push(28)
        self.assertEqual(len(a) + len(b), 49)
        self.assertEqual(self.w.frames_out, 49)

    def test_single_first_frame_then_steps(self):
        """A life starts with the reset frame alone, then whole steps (live_wm.py / lunch_wm.py)."""
        total = len(self.push(1))
        self.assertEqual(total, 1)
        for _ in range(3):
            total += len(self.push(360))
        self.assertEqual(total, 1 + 3 * 360)

    def test_single_latent_first_push_that_decodes_to_one_frame(self):
        """The real port decodes a lone first latent to fewer than 4 frames (bodies demo run, 2026-11-08); the agent
        must still get its one frame, or it has nothing to look at in step 0."""
        dec = sys.modules["cosmos3_mlx.decode_vae"]
        dec.decode_latents = lambda lat, vae: np.full((1, 1 if lat.shape[1] == 1 else 4 * lat.shape[1], H, W, 3), 0.5, np.float32)
        self.assertEqual(len(self.push(1)), 1)
        self.assertEqual(len(self.push(360)), 360)

    def test_ragged_pushes_lag_at_most_three(self):
        """A latent is painted only once its 4 frames are in, so output can trail input by up to 3 frames."""
        sent = got = 0
        for n in (1, 7, 10, 3, 13):
            sent += n
            got += len(self.push(n))
            self.assertTrue(0 <= sent - got <= 3, (sent, got))


if __name__ == "__main__":
    unittest.main()
