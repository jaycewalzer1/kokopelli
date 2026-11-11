"""Object labels in the Sim-Transfer paint (world_transfer.py --labels), on the tiny fake model of
test_wm_multicontrol_a.py: a paint with no label in frame is bit for bit the unlabeled paint, the mask reaches the
attention at the right keys, and the settings land in the sidecar.

The fake canvas is 48x32: one row of two tokens, the right one half padding. The fake tokenizer makes one token per 16
characters, so a label's words are a few text keys among about forty.
"""
import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from kokopelli.wm import labels as lb
from kokopelli.wm import world_transfer as wt
from tests.wm.test_wm_multicontrol_a import FRAMES, H, W, FakeWorld, fake_arrays

CHARS = 16
BASE = json.dumps({"subjects": [{"description": "a timber footbridge"}], "background_setting": "A paved square."})
BALLOON = "red latex balloon on a thin white string"


def fake_offsets(model_dir, text):
    return text, [(i, min(len(text), i + CHARS)) for i in range(0, len(text), CHARS)]


def fake_tokenize(model_dir, text):
    """Ids that depend on the text, so a caption with a label subject really is a different text cache."""
    return [1 + sum(text[a:b].encode()) % 15 for a, b in fake_offsets(model_dir, text)[1]] + [2, 7]


class LabelWorld(FakeWorld):
    def patches(self):
        return super().patches() + [mock.patch.object(wt, "tokenize", fake_tokenize),
                                    mock.patch.object(wt, "token_offsets", fake_offsets)]

    def labels(self, name, entries, paint):
        """labels.json plus label frames; paint(k) -> uint16 [H, W] for clip frame k."""
        folder = self.tmp / name
        (folder / "labels").mkdir(parents=True)
        path = folder / "labels.json"
        path.write_text(json.dumps({"version": 1, "labels": entries}))
        for k in range(FRAMES):
            Image.fromarray(paint(k).astype(np.uint16)).save(folder / "labels" / f"{k:04d}.png")
        return path, folder / "labels"

    def paint(self, name, control, labels=None, prompt=BASE, **settings):
        args = argparse.Namespace(prompt=prompt, hint="seg", control=control, output=str(self.tmp / f"{name}.mp4"),
                                  size=f"{W}x{H}", frames=None, seed=2025, window=3, sink=1, quantize=None,
                                  decode_chunk=6, model_dir=str(self.model_dir), save_latents=str(self.tmp / f"{name}.npy"),
                                  raw_prompt=False, extra=None)
        if labels:
            args.labels, args.label_frames = (str(p) for p in labels)
            for key, default in (("steps", 2), ("tau", 0.25), ("mode", "hard"), ("beta", 5.0), ("store", False), ("max", 6)):
                setattr(args, f"label_{key}", settings.get(key, default))
        wt.run(args)
        return np.load(args.save_latents), json.loads(Path(args.output + ".json").read_text())


def left_half(k):
    lab = np.zeros((H, W), np.uint16)
    lab[:, :24] = 1          # three quarters of token 0, none of token 1
    return lab


class PaintTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.arrays = fake_arrays()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.world = LabelWorld(self._tmp.name, self.arrays).__enter__()
        self.seg = self.world.video("seg", 11)
        self.entry = {"actor": "GEN_BP_balloon_0", "label": BALLOON, "class": "balloon", "priority": "hero"}

    def tearDown(self):
        self.world.__exit__()
        self._tmp.cleanup()

    def test_labels_that_are_never_in_frame_leave_the_paint_bitwise_unchanged(self):
        plain, side = self.world.paint("plain", self.seg)
        labels = self.world.labels("empty", [self.entry], lambda k: np.zeros((H, W), np.uint16))
        nothing, labeled_side = self.world.paint("nothing", self.seg, labels, steps=4, store=True)
        self.assertEqual(plain.shape, (1, 4, 2, 3, 48))
        np.testing.assert_array_equal(nothing, plain)
        self.assertEqual(labeled_side["formatted_prompt"], side["formatted_prompt"])
        self.assertNotIn("labels", side)
        self.assertNotIn("manifest", side)
        self.assertEqual(labeled_side["labels"]["dropped"], [{"actor": "GEN_BP_balloon_0", "why": "never in frame"}])

    def test_the_caption_gains_the_label_and_the_mask_changes_the_paint(self):
        labels = self.world.labels("half", [self.entry, {"actor": "GEN_BP_ball_2", "class": "ball"}], left_half)
        plain, _ = self.world.paint("plain", self.seg)
        tier_a, side_a = self.world.paint("tier_a", self.seg, labels, steps=0)
        hard, side = self.world.paint("hard", self.seg, labels, steps=2)
        one, _ = self.world.paint("one", self.seg, labels, steps=1)
        stored, side_s = self.world.paint("stored", self.seg, labels, steps=2, store=True)
        soft, side_soft = self.world.paint("soft", self.seg, labels, steps=2, mode="soft", beta=2.0)
        for latents in (tier_a, hard, one, stored, soft):
            self.assertTrue(np.isfinite(latents).all())
        differ = lambda a, b: float(np.abs(a - b).max())
        self.assertGreater(differ(tier_a, plain), 1e-3)      # Tier A: the words alone already change the paint
        self.assertGreater(differ(hard, tier_a), 1e-3)       # Tier B: so does who may read them
        self.assertGreater(differ(hard, one), 1e-3)          # the second masked step counts
        self.assertGreater(differ(soft, hard), 1e-3)
        np.testing.assert_array_equal(stored[:, 0], hard[:, 0])   # the store pass only reaches later latent frames
        self.assertGreater(differ(stored[:, 1:], hard[:, 1:]), 1e-3)

        subjects = json.loads(side["formatted_prompt"])["subjects"]
        self.assertEqual([s["description"] for s in subjects], ["a timber footbridge", BALLOON])
        self.assertEqual(subjects[1]["location"], "Left of frame, mid height")
        self.assertEqual(side["formatted_prompt"], side_a["formatted_prompt"])   # A and B differ only in the mask
        self.assertEqual(side["prompt"], BASE)
        block = side["labels"]
        self.assertEqual((block["steps"], block["mode"], block["store"], block["tau"], block["max"]), (2, "hard", False, 0.25, 6))
        self.assertEqual((block["count"], block["named"], block["grid"]), (2, 1, [1, 2]))
        self.assertEqual(block["watched"], ["GEN_BP_ball_2"])
        named, = block["named_labels"]
        self.assertEqual(named["tokens"], {"min": 1, "median": 1.0, "max": 1})
        self.assertEqual((named["latents_in_frame"], named["latents_under_one_token"]), (4, 0))
        s, e = named["span"]
        text, offsets = fake_offsets(None, side["formatted_prompt"])
        self.assertIn(BALLOON, text[offsets[s][0]:offsets[e - 1][1]])
        self.assertEqual(named["banned_words"], ["balloon"])                     # prompts/build.py BANNED
        self.assertFalse(block["banned_words_reach_whole_frame"])                # hard mask: only its region reads it
        self.assertTrue(side_a["labels"]["banned_words_reach_whole_frame"])      # caption only: everything reads it
        self.assertTrue(side_soft["labels"]["banned_words_reach_whole_frame"])
        self.assertEqual(side_soft["labels"]["beta"], 2.0)
        self.assertIsNone(block["beta"])
        self.assertTrue(side_s["labels"]["store"])
        self.assertEqual(side["manifest"]["labels"]["sha256"], lb.sha256(labels[0]))
        self.assertEqual(side["manifest"]["labels"]["steps"], 2)
        self.assertIn("seconds_per_latent", block)

    def test_a_label_over_the_whole_frame_is_the_caption_only_paint(self):
        """Every token is in the region, so the hard mask hides nothing: all four steps and the store pass masked must
        equal Tier A exactly."""
        labels = self.world.labels("whole", [self.entry], lambda k: np.ones((H, W), np.uint16))
        tier_a, _ = self.world.paint("tier_a", self.seg, labels, steps=0)
        whole, side = self.world.paint("whole", self.seg, labels, steps=4, store=True)
        np.testing.assert_array_equal(whole, tier_a)
        self.assertEqual(side["labels"]["named_labels"][0]["tokens"]["min"], 2)

    def test_missing_label_frames_or_a_plain_text_prompt_fail_before_the_model_loads(self):
        path, frames = self.world.labels("short", [self.entry], left_half)
        (frames / f"{FRAMES - 1:04d}.png").unlink()
        with mock.patch.object(wt, "shard_arrays", side_effect=AssertionError("loaded the model")):
            with self.assertRaisesRegex(ValueError, "label frames"):
                self.world.paint("short", self.seg, (path, frames))
            with self.assertRaisesRegex(ValueError, "structured JSON caption"):   # plain text has no subjects list
                self.world.paint("plain_text", self.seg, self.world.labels("ok", [self.entry], left_half),
                                 prompt="a bridge at noon")


class MaskAtTheAttentionTest(unittest.TestCase):
    """The Generator with a mask, against the same Generator with the hidden keys simply removed."""

    def test_hiding_text_columns_from_every_token_equals_deleting_them(self):
        import mlx.core as mx
        arrays = fake_arrays()
        rope = wt.Rope()
        ids = [1, 5, 9, 2, 7, 3, 11, 4]
        text_kv = wt.text_cache(arrays, ids, rope)
        gen = wt.Generator(arrays)
        n = 2
        tokens = mx.array(np.random.RandomState(3).standard_normal((1, n, 192)).astype(np.float32))
        cos, sin = rope.tables(mx.array([[20000.0] * n, [0.0] * n, [0.0, 1.0]]))
        earlier = gen(tokens * 0.5, cos, sin, [[kv] for kv in text_kv], store=True)[1]   # a history entry
        context = lambda text: [[text[i], earlier[i]] for i in range(36)]
        run = lambda ctx, mask=None: np.array(gen(tokens, cos, sin, ctx, sigma=0.9, mask=mask)[0])

        hidden = [2, 3, 4]                                               # a label's span, read by no token
        bias = np.zeros((n, len(ids)), np.float32)
        bias[:, hidden] = -np.inf
        mask = wt.attention_mask(bias, len(ids) + 2 * n)                 # keys: text | one history entry | own
        self.assertEqual((mask.shape, mask.dtype), ((1, 1, n, len(ids) + 2 * n), mx.bfloat16))
        self.assertTrue((np.array(mask.astype(mx.float32))[..., len(ids):] == 0).all())
        keep = mx.array([i for i in range(len(ids)) if i not in hidden])
        plain = run(context(text_kv))
        masked = run(context(text_kv), mask)
        deleted = run(context([(k[:, :, keep], v[:, :, keep]) for k, v in text_kv]))
        effect = np.abs(masked - plain).max()
        self.assertGreater(effect, 1e-2)
        self.assertLess(np.abs(masked - deleted).max(), 0.1 * effect)    # bf16 rounding, far below the mask's effect
        # Shifted one column over, the mask hides different keys, so it no longer matches the deletion: the column
        # index of a text key in the concatenation is its token index.
        shifted = np.zeros_like(bias)
        shifted[:, [3, 4, 5]] = -np.inf
        self.assertGreater(np.abs(run(context(text_kv), wt.attention_mask(shifted, len(ids) + 2 * n)) - deleted).max(),
                           0.25 * effect)
        np.testing.assert_array_equal(run(context(text_kv), wt.attention_mask(np.zeros_like(bias), len(ids) + 2 * n)), plain)
        self.assertIsNone(wt.attention_mask(None, 99))


class WrapperTest(unittest.TestCase):
    def test_transfer_video_passes_the_label_flags(self):
        with mock.patch.object(wt.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            wt.transfer_video("p", {"seg": "/x/seg.mp4"}, "/tmp/o.mp4")
            self.assertNotIn("--labels", run.call_args[0][0])
            wt.transfer_video("p", {"seg": "/x/seg.mp4"}, "/tmp/o.mp4",
                              labels={"file": "/x/labels.json", "frames": "/x/clip/labels", "steps": 1, "mode": "soft",
                                      "beta": 2, "store": True})
            command = run.call_args[0][0]
            for flag, value in (("--labels", "/x/labels.json"), ("--label-frames", "/x/clip/labels"), ("--label-steps", "1"),
                                ("--label-mode", "soft"), ("--label-beta", "2")):
                self.assertEqual(command[command.index(flag) + 1], value)
            self.assertIn("--label-store", command)
            self.assertNotIn("--label-tau", command)


if __name__ == "__main__":
    unittest.main()
