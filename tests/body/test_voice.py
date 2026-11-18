"""kokopelli/body/voice.py without the model: where lines land, what the sidecar says, and the listen-test proxy.

A stand-in `speak` (a sine tone) replaces Kokoro throughout, so nothing here loads a model or needs the network. The
real Kokoro has not been through these: see docs/log/sensations/2026-11-11-voice.md.
"""
import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from importlib import metadata
from pathlib import Path
from unittest import mock

import numpy as np

from kokopelli.body import voice

RATE = voice.SAMPLE_RATE


def tone(seconds=0.5, peak=0.2, lead=0.0):
    """A stand-in speaker: `lead` seconds of silence, then a sine at `peak`."""
    def speak(text):
        wave_ = np.sin(np.linspace(0, 400 * seconds, int(seconds * RATE))).astype(np.float32) * peak
        return np.concatenate([np.zeros(int(lead * RATE), np.float32), wave_])
    return speak


def fake_run(folder, thoughts, film_seconds=6, dry=None):
    """A run folder with just what voice.make reads: a grey film, egg.json and one body line. Not a real run."""
    folder.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=gray:s=64x36:r=2:d={film_seconds}",
                    "-pix_fmt", "yuv420p", str(folder / "world_model.mp4")], check=True)
    responses = [{"clock": f"08:05:{at:02d}", "thought": text} for at, text in thoughts]
    result = {"level": "starving", "responses": responses}
    if dry:
        result["dry_run"] = dry
    (folder / "egg.json").write_text(json.dumps(result))
    (folder / "body.jsonl").write_text(json.dumps({"t": 0.0, "clock": "08:05:00"}) + "\n")
    return folder


class PlaceTest(unittest.TestCase):
    def test_a_line_lands_at_its_decision_time(self):
        track, placed = voice.place([(1.0, "a")], 4, tone())
        self.assertEqual(len(track), 4 * RATE + 1)
        self.assertEqual((placed[0]["starts"], placed[0]["seconds"]), (1.0, 0.5))
        self.assertTrue(np.all(track[:RATE] == 0) and np.any(track[RATE:RATE + 100] != 0))
        self.assertNotIn("delayed", placed[0])

    def test_a_line_that_would_overlap_waits_and_says_so(self):
        _, placed = voice.place([(0.0, "a"), (0.2, "b")], 4, tone(1.0))
        self.assertEqual(placed[1]["starts"], 1.0 + voice.GAP_S)
        self.assertIn("waited 1.10 s for the line before it", placed[1]["delayed"])

    def test_lines_the_film_has_no_room_for_are_dropped_or_cut_with_the_reason(self):
        _, placed = voice.place([(1.5, "cut"), (1.6, "squeezed out"), (9.0, "too late"), (0.0, "")], 2, tone(1.0))
        self.assertIn("the film ended 0.50 s before the line did", placed[0]["cut"])
        self.assertEqual(placed[1]["dropped"], "the line before it ran to the end of the film")
        self.assertEqual(placed[2]["dropped"], "past the end of the film")
        _, silent = voice.place([(0.0, "a")], 2, lambda text: np.zeros(0, np.float32))
        self.assertEqual(silent[0]["dropped"], "no audio came back for this line")

    def test_audio_that_comes_back_two_dimensional_is_flattened(self):
        track, placed = voice.place([(0.0, "a")], 2, lambda text: tone()(text).reshape(1, -1))
        self.assertEqual(placed[0]["seconds"], 0.5)


class CheckTest(unittest.TestCase):
    def test_a_clean_track_passes_with_its_numbers(self):
        track, placed = voice.place([(0.0, "a"), (2.0, "b")], 4, tone(peak=0.2))
        result = voice.check(track, placed, 4)
        self.assertTrue(result["passed"])
        self.assertEqual(result["clipping"]["peak"], 0.2)
        self.assertEqual((result["timing"]["on_time"], result["timing"]["delayed"], result["timing"]["dropped"]), (2, 0, 0))
        self.assertLessEqual(abs(result["duration"]["off_by_s"]), 0.001)
        self.assertIn("nobody has listened", result["what_this_is"])

    def test_clipping_is_caught_before_the_clip_hides_it(self):
        lines = [(0.0, "loud")]
        clipped, _ = voice.render(lines, 2, tone(peak=1.5))
        self.assertEqual(float(np.abs(clipped).max()), 1.0)   # what the wav holds: the clip has hidden it
        track, placed = voice.place(lines, 2, tone(peak=1.5))
        result = voice.check(track, placed, 2)
        self.assertFalse(result["passed"])
        self.assertFalse(result["clipping"]["ok"])
        self.assertEqual(result["clipping"]["peak"], 1.5)
        self.assertGreater(result["clipping"]["samples_over"], 0)
        self.assertFalse(voice.check(clipped, placed, 2)["clipping"]["samples_over"])   # the clipped track can't show it

    def test_a_wrong_length_fails(self):
        track, placed = voice.place([(0.0, "a")], 4, tone())
        result = voice.check(track, placed, 5)
        self.assertFalse(result["duration"]["ok"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["duration"]["off_by_s"], -1.0)
        self.assertFalse(voice.check(track, placed, 0)["duration"]["ok"])   # a film ffprobe couldn't count

    def test_a_late_line_with_its_reason_passes_and_is_counted_delayed(self):
        track, placed = voice.place([(0.0, "a"), (0.2, "b")], 4, tone(1.0))
        result = voice.check(track, placed, 4)
        self.assertTrue(result["timing"]["ok"])
        self.assertEqual((result["timing"]["on_time"], result["timing"]["delayed"]), (1, 1))
        self.assertAlmostEqual(result["timing"]["worst_late_s"], 1.1, places=2)

    def test_a_short_wait_inside_the_tolerance_counts_as_on_time(self):
        track, placed = voice.place([(0.0, "a"), (0.6, "b")], 4, tone(0.5))   # free at 0.8, so b waits 0.2 s
        self.assertIn("delayed", placed[1])
        self.assertEqual(voice.check(track, placed, 4)["timing"]["on_time"], 2)

    def test_silence_at_the_front_of_a_line_is_lateness_nobody_explained(self):
        track, placed = voice.place([(1.0, "a")], 4, tone(lead=0.7))
        result = voice.check(track, placed, 4)
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["timing"]["unexplained"]), 1)
        self.assertIn("0.70 s after its decision with nothing in its way", result["timing"]["unexplained"][0]["why"])
        self.assertAlmostEqual(placed[0]["heard"], 1.7, places=2)

    def test_a_line_whose_audio_is_all_zeros_is_not_counted_as_spoken(self):
        track, placed = voice.place([(0.0, "a")], 2, lambda text: np.zeros(RATE // 2, np.float32))
        result = voice.check(track, placed, 2)
        self.assertFalse(result["timing"]["ok"])
        self.assertIn("silent", result["timing"]["unexplained"][0]["why"])

    def test_dropped_lines_are_counted_and_dont_fail_the_check(self):
        track, placed = voice.place([(0.0, "a"), (9.0, "b")], 2, tone())
        result = voice.check(track, placed, 2)
        self.assertTrue(result["passed"])
        self.assertEqual((result["timing"]["lines"], result["timing"]["dropped"]), (2, 1))


class SidecarTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_what_the_model_sidecar_names(self):
        about = voice.about_model()
        self.assertEqual((about["model"], about["voice"]), ("mlx-community/Kokoro-82M-bf16", "af_heart"))
        self.assertRegex(about["revision"], r"^[0-9a-f]{40}$")
        self.assertEqual(about["licence"]["name"], "Apache-2.0")
        self.assertTrue(about["licence"]["read"] and about["licence"]["url"].endswith(voice.MODEL))
        self.assertEqual(about["mlx_audio"], metadata.version("mlx-audio"))
        self.assertTrue(about["parameters"] and about["precision"])

    def test_a_stand_in_track_never_carries_the_models_name(self):
        run = fake_run(self.tmp / "stand_in", [(0, "I can barely stand."), (4, "Breakfast.")])
        wav = voice.make(run, speak=tone())
        sidecar = json.loads((run / "voice.json").read_text())
        self.assertIsNone(sidecar["model"])
        self.assertIn("not Kokoro", sidecar["stand_in"])
        self.assertNotIn("revision", sidecar)
        self.assertNotIn("Kokoro-82M", json.dumps({k: v for k, v in sidecar.items() if k != "stand_in"}))
        self.assertNotIn("dry_run", sidecar)
        self.assertTrue(sidecar["check"]["passed"])
        self.assertEqual(sidecar["check"]["duration"]["film_s"], 6.0)
        self.assertEqual([line["at"] for line in sidecar["lines"]], [0.0, 4.0])
        self.assertEqual(wav, run.resolve() / "voice.wav")

    def test_a_dry_runs_voice_says_it_is_a_dry_run(self):
        label = "fake sim, fake world model, scripted brain: not a real run"
        run = fake_run(self.tmp / "dry", [(0, "Of course.")], dry=label)
        voice.make(run, speak=tone())
        self.assertEqual(json.loads((run / "voice.json").read_text())["dry_run"], label)

    def test_the_check_reads_the_wav_that_was_written(self):
        run = fake_run(self.tmp / "written", [(0, "Eat.")])
        wav = voice.make(run, speak=tone())
        track, placed = voice.place(voice.script(run), 6, tone())
        (run / "short.wav").write_bytes(b"")
        voice.write_wav(run / "short.wav", track[: 3 * RATE])
        self.assertTrue(voice.check(track, placed, 6, wav=wav)["duration"]["ok"])
        self.assertEqual(voice.check(track, placed, 6, wav=run / "short.wav")["duration"]["voice_s"], 3.0)


class NeedsTest(unittest.TestCase):
    def test_missing_lists_what_isnt_importable_without_importing_it(self):
        before = set(sys.modules)
        with mock.patch.object(voice, "find_spec", lambda name: None if name in ("misaki", "en_core_web_sm") else object()):
            self.assertEqual(voice.missing(), ["misaki", "en_core_web_sm"])
        self.assertFalse({name for name in set(sys.modules) - before if name.split(".")[0] in voice.NEEDS})

    def test_kokoro_refuses_before_loading_anything_when_something_is_missing(self):
        with mock.patch.object(voice, "missing", lambda: ["misaki", "spacy"]), \
             mock.patch.dict(sys.modules, {"mlx_audio.tts.utils": None}):   # importing the loader would raise ImportError
            with self.assertRaises(voice.VoiceUnavailable) as caught:
                voice.kokoro()
        self.assertIn("misaki, spacy not installed", str(caught.exception))

    def test_the_command_leaves_no_voice_files_when_kokoro_cant_speak(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        run = fake_run(tmp / "run", [(0, "Eat.")])
        with mock.patch.object(voice, "missing", lambda: ["misaki"]), mock.patch.object(sys, "argv", ["voice", str(run)]):
            with self.assertRaises(SystemExit) as stopped:
                voice.main()
        self.assertIn("misaki", str(stopped.exception.code))   # a message, so the exit status is 1
        self.assertFalse((run / "voice.wav").exists() or (run / "voice.json").exists())

    def test_needs_flag_reports_and_exits_nonzero_when_something_is_missing(self):
        out = io.StringIO()
        with mock.patch.object(voice, "missing", lambda: ["misaki"]), mock.patch.object(sys, "argv", ["voice", "--needs"]), \
             contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stopped:
            voice.main()
        self.assertEqual(stopped.exception.code, 1)
        self.assertTrue(re.search(r"missing: misaki", out.getvalue()))


if __name__ == "__main__":
    unittest.main()
