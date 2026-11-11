"""kokopelli/wm/label_check.py with a stand-in for Qwen: which crops are asked, how answers become accuracy, flips and
neighbour leak, the outside-change measure and the calibration report. The real checker run needs the GPU queue."""
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from kokopelli.wm import label_check as lc

W, H, FRAMES = 96, 64, 13
RED, GREEN = (200, 30, 30), (30, 200, 30)


def meta():
    """Three listed actors at the painted size: a labeled balloon (left), a watched ball (right), and a labeled lamp
    whose mask is only 4 px wide."""
    def row(index, actor, label, cls, box, priority="normal"):
        return {"index": index, "actor": actor, "label": label, "class": cls, "priority": priority,
                "bbox": [box] * FRAMES, "area_px": [1] * FRAMES}
    return {"size": [W, H], "frames": FRAMES, "labels": [
        row(1, "balloon_0", "red latex balloon", "balloon", [8, 16, 40, 48], "hero"),
        row(2, "ball_0", "", "ball", [56, 16, 88, 48]),
        row(3, "lamp_0", "a glass lamp globe", "lamp", [44, 2, 48, 30]),
        {"index": 4, "actor": "post_0", "label": "a steel post", "class": "", "priority": "normal",
         "bbox": [None] * FRAMES, "area_px": [0] * FRAMES}]}


def frames(balloon_until=FRAMES):
    """The left object is red up to frame `balloon_until`, green after; the right one is always green."""
    out = np.full((FRAMES, H, W, 3), 128, np.uint8)
    for i in range(FRAMES):
        out[i, 16:48, 8:40] = RED if i < balloon_until else GREEN
        out[i, 16:48, 56:88] = GREEN
    return out


class ColourJudge:
    """Reads the crop it is shown: a red middle is a balloon, a green one a ball."""

    def __init__(self, reply=None):
        self.asked, self.reply = [], reply

    def __call__(self, prompt, images=(), max_tokens=512, temperature=0.0):
        self.asked.append((prompt, [str(p) for p in images]))
        if not images:
            return "Lantern, moon, bulb, and maybe a balloon."
        picture = cv2.cvtColor(cv2.imread(str(images[0])), cv2.COLOR_BGR2RGB)
        self.shapes = getattr(self, "shapes", []) + [picture.shape]
        r, g, _ = picture[picture.shape[0] // 2, picture.shape[1] // 2]
        return self.reply or ("It is a Balloon." if r > g else "ball")


class CheckTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Path(tmp.name) / "confusables.json"

    def test_one_question_per_listed_actor_per_latent_frame(self):
        judge = ColourJudge()
        report = lc.check_frames(frames(), meta(), judge, self.cache, lag=0)
        balloon, ball, lamp = report["actors"]                           # post_0 has no class: nothing to ask
        self.assertEqual([i for i, _ in balloon["answers"]], [0, 4, 8, 12])
        self.assertEqual((balloon["accuracy"], balloon["flips"], balloon["labeled"]), (1.0, 0, True))
        self.assertEqual((ball["accuracy"], ball["labeled"], ball["said_labeled_class"]), (1.0, False, 0.0))
        self.assertEqual((lamp["asked"], lamp["too_small"], lamp["accuracy"]), (0, 4, None))
        self.assertEqual(report["summary"], {"labeled_accuracy": 1.0, "hero_accuracy": 1.0, "labeled_flips": 0,
                                             "watched_accuracy": 1.0, "neighbor_leak": 0.0, "never_asked": ["lamp_0"]})
        self.assertEqual(balloon["options"][0], "balloon")
        self.assertEqual(balloon["options"][-1], "other")
        self.assertIn("ball", balloon["options"])                        # the other classes in the clip are offered
        self.assertEqual(len(judge.asked), 8)
        self.assertTrue(all(min(shape[:2]) >= lc.CROP_SIDE for shape in judge.shapes))   # 48 px crops, enlarged
        self.assertTrue(all("exactly one word" in prompt for prompt, _ in judge.asked))

    def test_a_balloon_that_becomes_a_ball_halfway_is_a_flip_and_half_right(self):
        report = lc.check_frames(frames(balloon_until=6), meta(), ColourJudge(), self.cache, lag=0)
        balloon = report["actors"][0]
        self.assertEqual([a for _, a in balloon["answers"]], ["balloon", "balloon", "ball", "ball"])
        self.assertEqual((balloon["accuracy"], balloon["flips"]), (0.5, 1))

    def test_a_batch_paint_runs_three_frames_behind_its_clip(self):
        """world_transfer.py's films show clip frame i at painted frame i + 3, so that is the frame to crop. Here the
        object turns from balloon to ball at painted frame 6: clip frames 0 and 4 are painted frames 3 and 7."""
        report = lc.check_frames(frames(balloon_until=6), meta(), ColourJudge(), self.cache)
        self.assertEqual(report["actors"][0]["answers"], [[0, "balloon"], [4, "ball"], [8, "ball"]])   # clip frame 12 isn't painted yet

    def test_a_label_leaking_onto_its_neighbour_is_counted(self):
        report = lc.check_frames(frames(), meta(), ColourJudge(reply="balloon"), self.cache, lag=0)
        ball = report["actors"][1]
        self.assertEqual((ball["accuracy"], ball["said_labeled_class"]), (0.0, 1.0))
        self.assertEqual(report["summary"]["neighbor_leak"], 1.0)

    def test_an_answer_off_the_list_is_unparsed_and_wrong(self):
        report = lc.check_frames(frames(), meta(), ColourJudge(reply="A zeppelin, clearly"), self.cache, lag=0)
        self.assertEqual((report["actors"][0]["accuracy"], report["actors"][0]["unparsed"]), (0.0, 4))
        self.assertEqual(lc.parse("Other.", ["balloon", "ball", "other"]), "other")
        self.assertEqual(lc.parse("a ball or a balloon", ["balloon", "ball", "other"]), "ball")

    def test_the_question_order_is_shuffled_but_repeatable_and_other_stays_last(self):
        options = ["balloon", "ball", "orange", "lamp", "fruit", "other"]
        a, b = lc.question(options, "balloon_0:0"), lc.question(options, "balloon_0:4")
        self.assertEqual(a, lc.question(options, "balloon_0:0"))
        self.assertNotEqual(a, b)
        self.assertIn("other? Answer", a)
        self.assertEqual(options[-1], "other")                           # the caller's list is left alone

    def test_an_unlisted_class_asks_qwen_once_and_remembers(self):
        judge = ColourJudge()
        first = lc.confusables("lantern", judge, self.cache)
        self.assertEqual(first, ["moon", "bulb", "balloon"])             # the last word of each piece, never the class itself
        self.assertNotIn("lantern", first)
        self.assertEqual(lc.confusables("lantern", judge, self.cache), first)
        self.assertEqual(len(judge.asked), 1)
        self.assertEqual(json.loads(self.cache.read_text())["lantern"], first)
        self.assertEqual(lc.confusables("balloon", judge, self.cache), lc.CONFUSABLE["balloon"])   # hand table, no question

    def test_crop_pads_a_quarter_and_stays_in_the_frame(self):
        frame = np.zeros((64, 96, 3), np.uint8)
        frame[16:48, 8:40] = 255
        cut = lc.crop(frame, [8, 16, 40, 48])                            # 32 px box + 8 px each side = 48 px
        self.assertEqual(cut.shape[:2], (lc.CROP_SIDE, lc.CROP_SIDE))
        self.assertGreater(cut[112, 112, 0], 250)
        self.assertLess(cut[5, 5, 0], 5)
        edge = lc.crop(frame, [0, 0, 32, 32])                            # padding stops at the frame's edge
        self.assertEqual(edge.shape[0], edge.shape[1])


class ChangeTest(unittest.TestCase):
    def test_change_is_split_into_outside_and_inside_the_label_regions(self):
        base = np.full((4, 128, 192, 3), 100, np.uint8)
        painted = base.copy()
        painted[:, 48:80, 48:80] = 160                                   # the labeled object changed: wanted
        labels = np.zeros((4, 128, 192), np.uint16)
        labels[:, 48:80, 48:80] = 1
        same = lc.outside_change(painted, base, labels, lag=0)
        self.assertEqual((same["frames"], same["outside"]), (4, 0.0))
        self.assertGreater(same["inside"], 5)
        painted[:, :, 160:] = 110                                        # and so did the far side of the frame: not wanted
        self.assertGreater(lc.outside_change(painted, base, labels, lag=0)["outside"], 1)
        self.assertEqual(lc.outside_change(painted, base, labels)["frames"], 4)   # the default lag reuses label frame 0 early on


class CalibrateTest(unittest.TestCase):
    def test_error_rate_over_hand_sorted_crops(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "crops"
            for cls, colours in (("balloon", [RED, RED, RED, GREEN]), ("ball", [GREEN, GREEN])):
                (folder / cls).mkdir(parents=True)
                for i, colour in enumerate(colours):
                    cv2.imwrite(str(folder / cls / f"{i}.png"), np.full((32, 32, 3), colour[::-1], np.uint8))
            report = lc.calibrate(folder, ColourJudge(), Path(tmp) / "confusables.json")
            self.assertEqual((report["crops"], report["error"], report["usable"]), (6, 0.167, False))
            self.assertEqual(report["by_class"], {"ball": 0.0, "balloon": 0.25})
            self.assertEqual(report["model"], lc.LLM_MODEL)
            self.assertEqual(json.loads((folder / "calibration.json").read_text())["crops"], 6)


if __name__ == "__main__":
    unittest.main()
