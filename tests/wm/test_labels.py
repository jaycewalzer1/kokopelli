"""kokopelli/wm/labels.py without a model: labels.json rules, the label pass built from segmentation frames, token regions
in patchify's order, caption subjects, token spans and the attention bias. The paint itself is tests/wm/test_label_paint.py.
"""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from kokopelli.wm import labels as lb
from kokopelli.wm import world_transfer as wt

BALLOON = "red latex balloon on a thin white string, slightly wrinkled near the knot"


def write_labels(folder, labels):
    path = Path(folder) / "labels.json"
    path.write_text(json.dumps({"version": 1, "labels": labels}))
    return path


def chunk_tokens(chat, size=7):
    """A stand-in tokenizer: one token per `size` characters, with the offsets the real one would report."""
    return [(i, min(len(chat), i + size)) for i in range(0, len(chat), size)]


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_entries_keep_file_order_and_defaults(self):
        path = write_labels(self.tmp.name, [{"actor": "A", "label": "  a red\n balloon ", "class": "Balloon", "priority": "hero"},
                                            {"actor": "B", "class": "ball"}])
        a, b = lb.load(path)
        self.assertEqual(a, {"index": 1, "actor": "A", "label": "a red balloon", "class": "balloon", "priority": "hero"})
        self.assertEqual(b, {"index": 2, "actor": "B", "label": "", "class": "ball", "priority": "normal"})

    def test_world_ids_resolve_through_the_table(self):
        path = write_labels(self.tmp.name, [{"world_id": "lantern_3", "label": "a paper lantern"}])
        self.assertEqual(lb.load(path, {"lantern_3": "CITY_lantern_3"})[0]["actor"], "CITY_lantern_3")
        with self.assertRaisesRegex(ValueError, "no actor is known"):
            lb.load(path)

    def test_bad_files_fail(self):
        for labels in ([{"actor": "A", "label": "x"}, {"actor": "A", "label": "y"}],     # the same actor twice
                       [{"actor": "A"}],                                                # nothing to say or check
                       [{"label": "x"}],                                                # nobody to put it on
                       [{"actor": "A", "label": "x", "priority": "top"}],
                       [{"actor": "A", "label": "x", "colour": [1, 2, 3]}]):
            with self.assertRaises(ValueError, msg=labels):
                lb.load(write_labels(self.tmp.name, labels))
        bad = Path(self.tmp.name) / "v2.json"
        bad.write_text(json.dumps({"version": 2, "labels": []}))
        with self.assertRaisesRegex(ValueError, "version"):
            lb.load(bad)


class PassTest(unittest.TestCase):
    """A 4-frame clip, 96x64: actor A is an 8x8 square moving right, actor B a fixed block, C never in frame."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clip = Path(self.tmp.name) / "clip"
        (self.clip / "segmentation").mkdir(parents=True)
        self.colors = {"A": (40, 200, 90), "B": (93, 163, 191), "C": (146, 126, 36), "agent": (9, 9, 9)}
        for k in range(4):
            seg = np.zeros((64, 96, 4), np.uint8)
            seg[..., 3] = 255
            seg[:, :48, :3] = (9, 9, 9)                                   # another actor, unlabeled
            seg[8:16, 8 + 4 * k:16 + 4 * k, :3] = self.colors["A"]
            seg[32:64, 64:96, :3] = self.colors["B"]
            Image.fromarray(seg).save(self.clip / "segmentation" / f"{k:04d}.png")
        self.labels = write_labels(self.tmp.name, [{"actor": "A", "label": BALLOON, "class": "balloon"},
                                                   {"actor": "B", "class": "ball"},
                                                   {"actor": "C", "label": "a paper lantern"}])
        self.entries = lb.load(self.labels)

    def test_frames_are_16_bit_indices_matched_by_exact_colour(self):
        meta = lb.build_pass(self.clip, self.entries, self.colors, self.labels)
        lab = Image.open(self.clip / "labels" / "0002.png")
        self.assertEqual(lab.mode, "I;16")
        lab = np.array(lab)
        self.assertEqual(lab.dtype, np.uint16)
        self.assertEqual(sorted(np.unique(lab).tolist()), [0, 1, 2])
        self.assertTrue((lab[8:16, 16:24] == 1).all())
        self.assertEqual(int((lab == 1).sum()), 64)
        self.assertEqual(int((lab == 2).sum()), 32 * 32)
        self.assertEqual(meta["frames"], 4)
        self.assertEqual(meta["size"], [96, 64])
        self.assertEqual(meta["actors"], ["A", "B", "C"])
        self.assertEqual(meta["labels_sha256"], lb.sha256(self.labels))
        a, b, c = meta["labels"]
        self.assertEqual(a["area_px"], [64] * 4)
        self.assertEqual(a["bbox"][3], [20, 8, 28, 16])
        self.assertEqual(a["centroid"][0], [11.5, 11.5])
        self.assertEqual(b["frames_visible"], 4)
        self.assertEqual((c["frames_visible"], c["bbox"]), (0, [None] * 4))
        self.assertTrue(any("C is never in frame" in w for w in meta["warnings"]))
        self.assertEqual(json.loads((self.clip / "labels_meta.json").read_text()), meta)

    def test_capture_colours_prefer_what_the_server_read_back(self):
        capture = {"mask_colors": [{"id": "a", "actor": "A", "assigned_rgb": [1, 2, 3], "readback_rgb": [4, 5, 6]},
                                   {"id": "b", "actor": "B", "assigned_rgb": [7, 8, 9], "readback_rgb": None},
                                   {"id": "c", "actor": "C", "assigned_rgb": None, "readback_rgb": None}]}
        self.assertEqual(lb.capture_colors(capture), {"A": (4, 5, 6), "B": (7, 8, 9)})

    def test_an_actor_without_a_colour_is_a_warning_and_a_shared_colour_an_error(self):
        meta = lb.build_pass(self.clip, self.entries, {"A": self.colors["A"], "B": self.colors["B"]})
        self.assertTrue(any(w.startswith("C has no usable mask colour") for w in meta["warnings"]))
        with self.assertRaisesRegex(ValueError, "share mask colour"):
            lb.build_pass(self.clip, self.entries, {**self.colors, "C": self.colors["A"]})
        meta = lb.build_pass(self.clip, self.entries, {**self.colors, "agent": self.colors["B"]})
        self.assertTrue(any("B shares mask colour" in w for w in meta["warnings"]))

    def test_stale_frames_and_a_reordered_file_are_refused(self):
        lb.build_pass(self.clip, self.entries, self.colors, self.labels)
        lb.check_meta(self.clip / "labels", self.entries)
        with self.assertRaisesRegex(ValueError, "rebuild the label pass"):
            lb.check_meta(self.clip / "labels", self.entries[::-1])
        Image.fromarray(np.zeros((64, 96), np.uint16)).save(self.clip / "labels" / "0009.png")
        with self.assertRaisesRegex(ValueError, "move them away"):
            lb.build_pass(self.clip, self.entries, self.colors)

    def test_reading_resizes_by_nearest_neighbour_and_stats_follow(self):
        lb.build_pass(self.clip, self.entries, self.colors)
        frames = lb.read_frames(self.clip / "labels", 48, 32, 3)
        self.assertEqual((frames.shape, frames.dtype), ((3, 32, 48), np.uint16))
        self.assertEqual(sorted(np.unique(frames).tolist()), [0, 1, 2])   # never a blend of two indices
        area, cx, cy = lb.frame_stats(frames, 3)
        np.testing.assert_allclose(area[0], 64 / (96 * 64), rtol=1e-6)
        np.testing.assert_allclose(area[1], 1 / 6, rtol=1e-6)
        self.assertFalse(area[2].any())
        self.assertTrue(np.isnan(cx[2]).all())
        np.testing.assert_allclose((cx[1, 0], cy[1, 0]), (80 / 96, 48 / 64), atol=1e-6)
        self.assertLess(cx[0, 0], cx[0, 2])                              # A moves right


class TokenTest(unittest.TestCase):
    def test_token_order_is_patchifys(self):
        """A latent whose every cell holds the number of the 2x2 patch it sits in comes out of patchify with token n
        holding n, and a label map whose every 32 px block is its own label puts label n on token n."""
        import mlx.core as mx
        h, w = 4, 6                                                      # latent cells: a 64x96 px picture
        hp, wp = 2, 3
        cell = (np.arange(h)[:, None] // 2) * wp + np.arange(w)[None, :] // 2
        lat = mx.array(np.broadcast_to(cell[None, None, :, :, None], (1, 1, h, w, 48)).astype(np.float32))
        tokens = np.array(wt.patchify(lat))
        self.assertEqual(tokens.shape, (1, hp * wp, 192))
        for n in range(hp * wp):
            self.assertTrue((tokens[0, n] == n).all(), n)
        frame = (np.repeat(np.repeat(cell, 16, 0), 16, 1) + 1).astype(np.uint16)   # label n+1 on patch n's pixels
        cover = lb.token_cover(frame[None], hp * wp)
        self.assertEqual(cover.shape, (hp * wp, hp, wp))
        np.testing.assert_array_equal(cover.reshape(hp * wp, hp * wp), np.eye(hp * wp, dtype=np.float32))

    def test_cover_is_a_share_over_the_latents_frames(self):
        frames = np.zeros((4, 64, 64), np.uint16)
        frames[:2, :32, :16] = 1                                         # half of token 0, in 2 of its 4 frames
        cover = lb.token_cover(frames, 1)
        np.testing.assert_allclose(cover[0], [[0.25, 0], [0, 0]])

    def test_a_half_padded_edge_token_counts_only_its_real_pixels(self):
        frames = np.ones((1, 48, 80), np.uint16)                         # latent 3x5: both last row and column padded
        cover = lb.token_cover(frames, 1)
        self.assertEqual(cover.shape, (1, 2, 3))
        np.testing.assert_array_equal(cover[0], np.ones((2, 3), np.float32))
        frames[:, 32:, :] = 0                                            # nothing on the half-height bottom row
        np.testing.assert_array_equal(lb.token_cover(frames, 1)[0], [[1, 1, 1], [0, 0, 0]])

    def test_a_tiny_object_keeps_its_one_best_token(self):
        frames = np.zeros((1, 64, 96), np.uint16)
        frames[0, 32:38, 62:70] = 1                                      # 6x8 px across two tokens, most of it in (1, 2)
        frames[0, :, :32] = 2                                            # a big one, for contrast
        inside, fell_back = lb.regions(lb.token_cover(frames, 3), 0.25)
        self.assertEqual(inside.shape, (3, 6))
        self.assertEqual(inside[0].tolist(), [False, False, False, False, False, True])
        self.assertEqual(inside[1].tolist(), [True, False, False, True, False, False])
        self.assertFalse(inside[2].any())                                # not in frame: no token at all
        self.assertEqual(fell_back.tolist(), [True, False, False])

    def test_no_labels_is_fine(self):
        inside, fell_back = lb.regions(lb.token_cover(np.zeros((1, 64, 96), np.uint16), 2)[[]], 0.25)
        self.assertEqual((inside.shape, fell_back.shape), ((0, 6), (0,)))


class CaptionTest(unittest.TestCase):
    def entries(self):
        return [{"index": 1, "actor": "A", "label": "a", "class": "", "priority": "normal"},
                {"index": 2, "actor": "B", "label": "", "class": "ball", "priority": "normal"},
                {"index": 3, "actor": "C", "label": "c", "class": "", "priority": "hero"},
                {"index": 4, "actor": "D", "label": "d", "class": "", "priority": "normal"},
                {"index": 5, "actor": "E", "label": "e", "class": "", "priority": "normal"}]

    def test_heroes_first_then_area_and_the_cap(self):
        area = np.array([[0.2, 0.2], [0.5, 0.5], [0.01, 0.0], [0.0, 0.0], [0.3, 0.3]], np.float32)
        chosen, dropped = lb.choose(self.entries(), area, 6)
        self.assertEqual([e["actor"] for e in chosen], ["C", "E", "A"])   # B is only watched, D never in frame
        self.assertEqual(dropped, [{"actor": "D", "why": "never in frame"}])
        chosen, dropped = lb.choose(self.entries(), area, 2)
        self.assertEqual([e["actor"] for e in chosen], ["C", "E"])
        self.assertEqual(dropped[-1], {"actor": "A", "why": "over the cap of 2 labels"})
        self.assertEqual(len(lb.choose(self.entries(), area, 0)[0]), 3)

    def test_subject_words_come_from_the_mask(self):
        nan = np.nan
        s = lb.subject({"label": BALLOON}, np.array([0, 0.01, 0.01]), np.array([nan, 0.1, 0.2]), np.array([nan, 0.1, 0.2]))
        self.assertEqual(s["description"], BALLOON)
        self.assertEqual(s["location"], "Upper left of frame")
        self.assertEqual(s["relative_size"], "Small in frame")
        self.assertEqual(list(s)[:4], ["description", "appearance_details", "location", "relative_size"])
        self.assertEqual(len(s), 14)                                     # NVIDIA's subject fields, as prompts/build.py
        moving = lb.subject({"label": "x"}, np.array([0.3, 0.3]), np.array([0.1, 0.9]), np.array([0.5, 0.9]))
        self.assertEqual(moving["location"], "Left of frame, mid height, moving to the lower right of frame")
        self.assertEqual(moving["relative_size"], "Large, filling much of the frame")

    def test_subjects_are_appended_to_the_structured_caption(self):
        base = json.dumps({"subjects": [{"description": "a bridge"}], "background_setting": "A plaza.", "fps": 30})
        out = json.loads(lb.caption(base, [{"description": BALLOON}]))
        self.assertEqual([s["description"] for s in out["subjects"]], ["a bridge", BALLOON])
        self.assertEqual(out["background_setting"], "A plaza.")
        self.assertEqual(list(json.loads(lb.caption('{"context": "x"}', [{"description": "y"}])))[0], "subjects")
        with self.assertRaisesRegex(ValueError, "structured JSON caption"):
            lb.caption("a bridge at noon", [{"description": BALLOON}])


class SpanTest(unittest.TestCase):
    def subjects(self):
        rest = {"location": "Upper left of frame", **lb.SUBJECT_REST}
        return [{"description": BALLOON, "appearance_details": "", **rest},
                {"description": BALLOON, "appearance_details": "", **{**rest, "location": "Centre of frame"}},   # a second balloon
                {"description": 'a café sign that says "open" — hand painted', "appearance_details": "", **rest}]

    def chat(self, subjects):
        text = wt.format_prompt(lb.caption(json.dumps({"subjects": [{"description": BALLOON + ", far away"}],
                                                       "background_setting": "A plaza."}), subjects), 149, 30.0, 832, 480)
        return f"<|im_start|>system\n{wt.SYSTEM_PROMPT}<|im_end|>\n<|im_start|>user\n{text}<|im_end|>\n"

    def test_every_label_gets_its_own_span_over_exactly_its_words(self):
        subjects = self.subjects()
        chat = self.chat(subjects)
        offsets = chunk_tokens(chat)
        spans = lb.find_spans(chat, offsets, subjects)
        self.assertEqual(len(spans), 3)
        for (s, e), subject in zip(spans, subjects, strict=True):
            written = json.dumps(subject["description"])[1:-1]           # as the caption spells it (escapes and all)
            covered = chat[offsets[s][0]:offsets[e - 1][1]]
            self.assertIn(written, covered)
            self.assertLess(len(covered), len(written) + 14)             # at most one 7-char token of slack each side
        self.assertLessEqual(spans[0][1], spans[1][0])                   # the twin balloons each have their own
        # The caption's own subject starts with the same words; it comes first in the text and is nobody's span.
        self.assertGreater(offsets[spans[0][0]][1], chat.find(json.dumps(subjects[0])))

    def test_a_cut_caption_or_a_missing_subject_fails(self):
        subjects = self.subjects()
        chat = self.chat(subjects)
        offsets = chunk_tokens(chat)
        cut = [o for o in offsets if o[1] < chat.find(json.dumps(subjects[2]))]
        with self.assertRaisesRegex(ValueError, "cut off"):
            lb.find_spans(chat, cut, subjects)
        with self.assertRaisesRegex(ValueError, "not found"):
            lb.find_spans(chat, offsets, subjects + [{"description": "a kite", **lb.SUBJECT_REST}])

    def test_real_tokenizer_offsets_line_up_with_tokenize(self):
        if not (wt.MODEL_DIR / "text_tokenizer").exists():
            self.skipTest("no Sim-Transfer tokenizer in models/")
        subjects = self.subjects()
        text = wt.format_prompt(lb.caption(json.dumps({"subjects": [], "background_setting": "A plaza."}), subjects),
                                149, 30.0, 832, 480)
        ids = wt.tokenize(wt.MODEL_DIR, text)
        chat, offsets = wt.token_offsets(wt.MODEL_DIR, text)
        self.assertEqual(len(offsets), len(ids) - 2)                     # tokenize adds EOS and <|vision_start|>
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(str(wt.MODEL_DIR / "text_tokenizer"))
        for (s, e), subject in zip(lb.find_spans(chat, offsets, subjects), subjects, strict=True):
            decoded = tokenizer.decode(ids[s:e])
            self.assertIn(json.dumps(subject["description"])[1:-1], decoded)
            self.assertLess(len(decoded), len(json.dumps(subject["description"])) + 8)


class MaskTest(unittest.TestCase):
    def setUp(self):
        self.inside = np.array([[True, True, False, False, False, False],     # label 0: tokens 0, 1
                                [False, False, False, False, False, False]])  # label 1: not in this latent frame
        self.spans = [(3, 6), (9, 11)]

    def test_hard_walls_only_the_labels_columns_from_outside_tokens(self):
        mask = lb.text_mask(self.spans, self.inside, 14)
        self.assertEqual((mask.shape, mask.dtype), ((6, 14), np.float32))
        self.assertTrue((mask[:2, 3:6] == 0).all())                      # inside the region: reads its label
        self.assertTrue(np.isneginf(mask[2:, 3:6]).all())                # outside: can't
        self.assertTrue(np.isneginf(mask[:, 9:11]).all())                # an off-screen label is read by nobody
        rest = np.delete(mask, [3, 4, 5, 9, 10], axis=1)
        self.assertTrue((rest == 0).all())                               # the rest of the caption: always readable,
        self.assertTrue(np.isfinite(mask).any(1).all())                  # so no row is ever all -inf

    def test_soft_biases_both_ways(self):
        mask = lb.text_mask(self.spans, self.inside, 14, "soft", 2.0)
        self.assertTrue((mask[:2, 3:6] == 2).all() and (mask[2:, 3:6] == -2).all() and (mask[:, 9:11] == -2).all())
        self.assertTrue(np.isfinite(mask).all())
        with self.assertRaises(ValueError):
            lb.text_mask(self.spans, self.inside, 14, "medium")

    def test_a_label_over_the_whole_frame_masks_nothing(self):
        self.assertIsNone(lb.text_mask([(3, 6)], np.ones((1, 6), bool), 14))
        self.assertIsNone(lb.text_mask([], np.zeros((0, 6), bool), 14))


if __name__ == "__main__":
    unittest.main()
