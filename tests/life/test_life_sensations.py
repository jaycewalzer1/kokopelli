"""The sensations view: listing sweeps and hunger videos, and serving only the videos it found."""
import json
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from experiments.sensation import sweep
from kokopelli.life import sensations
from kokopelli.life.panel import make_server


def make_video(path, seconds=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=gray:s=64x32:r=24:d={seconds}",
                    "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


class SensationsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.out = root / "sensation"
        sweep.report(sweep.run("hunger_egg", "mock", samples=8, out=cls.out / "hunger_mock", mock_tilt=0.5))
        run = cls.out / "videos" / "20261110-120000_cue"
        for level, outcome in (("full", "gave"), ("half", "gave"), ("starving", "declined")):
            real = root / "city_agents" / level   # the run folder the level link points at
            make_video(real / "world_model.mp4")
            make_video(real / "overlay.mp4")
            (real / "egg.json").write_text(json.dumps({"level": level, "arm": "cue", "outcome": outcome, "food_at_start": 8.0,
                                                       "first_response": {"action": {"type": "give"}, "thought": "Sure."}}))
            run.mkdir(parents=True, exist_ok=True)
            (run / level).symlink_to(real, target_is_directory=True)
        make_video(run / "hunger_triptych.mp4")
        make_video(root / "elsewhere.mp4")
        cls.patches = [mock.patch.object(sensations, "OUT", cls.out), mock.patch.object(sensations, "VIDEOS", cls.out / "videos")]
        for patch in cls.patches:
            patch.start()
        cls.server = make_server(root / "life.db", port=0)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        for patch in cls.patches:
            patch.stop()
        cls.temp.cleanup()

    def get(self, path, headers=None):
        return urllib.request.urlopen(urllib.request.Request(self.base + path, headers=headers or {}))

    def test_listing_has_the_sweep_and_the_video_run(self):
        body = json.load(self.get("/api/sensations"))
        self.assertEqual([s["id"] for s in body["sweeps"]], ["hunger_mock"])
        self.assertFalse(body["sweeps"][0]["real"])
        self.assertIn("matches what people predict", body["sweeps"][0]["verdicts"]["cue"]["verdict"])
        video = body["videos"][0]
        self.assertTrue(video["triptych"])
        self.assertEqual(video["levels"]["starving"]["outcome"], "declined")
        self.assertEqual(video["levels"]["full"]["has"], {"overlay": True, "voice": False, "plain": True})

    def test_videos_are_served_with_ranges(self):
        with self.get("/api/sensations/video?run=20261110-120000_cue&kind=overlay&level=half", {"Range": "bytes=0-99"}) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(len(response.read()), 100)
        with self.get("/api/sensations/video?run=20261110-120000_cue&kind=triptych") as response:
            self.assertEqual(response.headers["Content-Type"], "video/mp4")

    def test_nothing_outside_the_listing_is_served(self):
        for query in ("run=../elsewhere&kind=triptych", "run=20261110-120000_cue&kind=voice&level=full",
                      "run=20261110-120000_cue&kind=overlay&level=../../elsewhere", "run=20261110-120000_cue&kind=config"):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.get(f"/api/sensations/video?{query}")
            self.assertEqual(caught.exception.code, 404, query)

    def test_the_page_is_in_every_sidebar(self):
        with self.get("/sensations") as response:
            self.assertIn(b'<a href="/sensations" aria-current="page">', response.read())
        for page in ("/", "/worlds", "/city-live", "/queue"):
            with self.get(page) as response:
                self.assertIn(b'href="/sensations"', response.read(), page)


if __name__ == "__main__":
    unittest.main()
