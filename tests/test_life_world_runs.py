"""The world model runs view: finding runs, reading video lengths, and serving only videos it found."""
import json
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from life import world_runs
from life.panel import make_server


def make_video(path, frames=24):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=gray:s=64x32:r=24:d={frames / 24}",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


class Folders(unittest.TestCase):
    """A fake machine: one loop run, one mind run, edge filter videos, a single generation and a clip collection."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.paths = {"agent_loop": root / "loop", "mind": root / "mind"}
        run = root / "loop" / "runs" / "real_run"
        run.mkdir(parents=True)
        (run / "config.json").write_text(json.dumps({"sim": "mock", "wm": "cosmos", "agent": "qwen", "ticks": 2}))
        (run / "events.jsonl").write_text(json.dumps({"kind": "tick_end", "tick": 0}) + "\n")
        make_video(run / "final.mp4", 48)
        mind = root / "mind" / "mock_mind"
        mind.mkdir(parents=True)
        (mind / "config.json").write_text(json.dumps({"sim": "mock", "wm": "mock", "agent": "qwen", "ticks": 1}))
        make_video(root / "out" / "edge_filter" / "transfer" / "painted.mp4", 24)
        make_video(root / "out" / "edge_filter" / "transfer" / "control.mp4", 24)
        (root / "out" / "edge_filter" / "transfer" / "notes.json").write_text(json.dumps({"painted": "What this run tried."}))
        make_video(root / "cosmos" / "one.mp4", 12)
        make_video(root / "out" / "world_data_1" / "clips" / "a.mp4", 16)
        rows = [{"file": "clips/a.mp4", "ok": True, "prompt": "A red ball", "category": "physics", "seed": 1},
                {"file": "clips/missing.mp4", "ok": True}, {"file": "clips/failed.mp4", "ok": False}]
        (root / "out" / "world_data_1" / "manifest.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        for name, value in (("OUT", root / "out"), ("EDGE_FILTER", root / "out" / "edge_filter"), ("CONTINUOUS", root / "out" / "continuous_video"),
                            ("COSMOS_OUTPUTS", root / "cosmos")):
            patcher = mock.patch.object(world_runs, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root = root


class LengthTest(Folders):
    def test_length_comes_from_the_header(self):
        self.assertAlmostEqual(world_runs.mp4_seconds(self.root / "loop" / "runs" / "real_run" / "final.mp4"), 2.0, places=1)

    def test_a_file_that_isnt_a_whole_mp4_has_no_length(self):
        broken = self.root / "broken.mp4"
        broken.write_bytes((self.root / "cosmos" / "one.mp4").read_bytes()[:200])
        self.assertIsNone(world_runs.mp4_seconds(broken))
        (self.root / "text.mp4").write_text("not a video")
        self.assertIsNone(world_runs.mp4_seconds(self.root / "text.mp4"))


class CollectTest(Folders):
    def setUp(self):
        super().setUp()
        self.body = world_runs.collect(self.paths)
        self.runs = {run["name"]: run for run in self.body["runs"]}

    def test_every_source_is_found(self):
        self.assertEqual(set(self.runs), {"real_run", "mock_mind", "painted", "control", "one", "a"})

    def test_kinds_say_what_made_each_video(self):
        kinds = {name: run["kind"] for name, run in self.runs.items()}
        self.assertEqual(kinds, {"real_run": "cosmos", "mock_mind": "mock", "painted": "cosmos", "control": "input", "one": "cosmos", "a": "cosmos"})

    def test_a_run_without_a_video_is_listed_without_one(self):
        self.assertFalse(self.runs["mock_mind"]["video"])
        self.assertIsNone(self.runs["mock_mind"]["seconds"])

    def test_notes_and_prompts_are_shown(self):
        self.assertEqual(self.runs["painted"]["about"], "What this run tried.")
        self.assertEqual(self.runs["a"]["prompt"], "A red ball")
        self.assertIn("1 of 2 ticks", self.runs["real_run"]["lines"])

    def test_longest_counts_only_cosmos_videos(self):
        self.assertEqual(self.body["longest"]["name"], "real_run")

    def test_no_file_paths_are_sent_to_the_page(self):
        self.assertTrue(all("path" not in run for run in self.body["runs"]))


class VideoFileTest(Folders):
    def test_a_listed_run_gives_its_video(self):
        run = next(run for run in world_runs.collect(self.paths)["runs"] if run["name"] == "painted")
        self.assertEqual(world_runs.video_file(run["id"], self.paths).name, "painted.mp4")

    def test_anything_not_listed_is_refused(self):
        for run_id in ("filter/etc/passwd", "filter/../../etc/passwd", "nope/x", "", "clips/" + str(self.root / "out" / "world_data_1" / "manifest.jsonl")):
            with self.subTest(run_id), self.assertRaises(KeyError):
                world_runs.video_file(run_id, self.paths)


class RouteTest(Folders):
    def setUp(self):
        super().setUp()
        self.video = self.root / "cosmos" / "one.mp4"
        patcher = mock.patch.object(world_runs, "video_file", lambda run_id: self.video if run_id == "ok" else (_ for _ in ()).throw(KeyError(run_id)))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = make_server(self.root / "life.db", port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def test_the_page_is_in_the_sidebar(self):
        with urllib.request.urlopen(self.base + "/worlds") as response:
            self.assertIn(b'<a href="/worlds" aria-current="page">', response.read())
        with urllib.request.urlopen(self.base + "/") as response:
            self.assertIn(b'href="/worlds"', response.read())

    def test_a_whole_video_and_a_range_of_it(self):
        data = self.video.read_bytes()
        with urllib.request.urlopen(self.base + "/api/worlds/video?id=ok") as response:
            self.assertEqual(response.read(), data)
            self.assertEqual(response.headers["Accept-Ranges"], "bytes")
        request = urllib.request.Request(self.base + "/api/worlds/video?id=ok", headers={"Range": "bytes=10-19"})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), data[10:20])
            self.assertEqual(response.headers["Content-Range"], f"bytes 10-19/{len(data)}")

    def test_a_range_past_the_end_is_refused(self):
        request = urllib.request.Request(self.base + "/api/worlds/video?id=ok", headers={"Range": f"bytes={10 ** 9}-"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 416)

    def test_an_unknown_video_is_not_found(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + "/api/worlds/video?id=nope")
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
