import http.server
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np

from blend import probe
from runtime import check_video, compare, plan, preflight, replay
from runtime.config import Config
from runtime.frames import write_clip
from runtime.mocks.agent import NullAgent
from runtime.run import run
from runtime.stitch import expected_frames, stitch


def folder():
    return Path(tempfile.mkdtemp(prefix="wmloop_"))


class StitchTest(unittest.TestCase):
    def clips(self, count, frames=8):
        place = folder()
        return [write_clip([np.full((64, 64, 3), 40 + i * 2, np.uint8) for _ in range(frames)], place / f"{i}.mp4") for i in range(count)]

    def test_batches_give_the_same_length_as_one_join(self):
        clips, overlap = self.clips(7), 1
        whole, batched = stitch(clips, folder() / "whole.mp4", overlap, batch=50), stitch(clips, folder() / "batched.mp4", overlap, batch=3)
        self.assertEqual(probe(whole)[2], expected_frames([8] * 7, overlap))
        self.assertEqual(probe(batched)[2], expected_frames([8] * 7, overlap))

    def test_the_full_run_works_out_to_thirty_minutes(self):
        self.assertEqual(expected_frames([181] * 240, 1), 30 * 60 * 24 + 1)


class VideoCheckTest(unittest.TestCase):
    def setUp(self):
        self.run_dir = folder()
        run(Config(ticks=3), self.run_dir)

    def test_a_good_run_passes(self):
        problems, facts = check_video.check(self.run_dir)
        self.assertEqual(problems, [])
        self.assertEqual(facts["ticks"], 3)

    def test_a_changed_clip_is_caught(self):
        clip = replay.summarize(self.run_dir)["ticks"][0]["chunks"][0]["clip"]
        (self.run_dir / clip).write_bytes(b"not the clip")
        self.assertTrue(any("hash" in problem for problem in check_video.check(self.run_dir)[0]))

    def test_a_missing_video_is_caught_and_rebuilt(self):
        (self.run_dir / "final.mp4").unlink()
        self.assertTrue(check_video.check(self.run_dir)[0])
        self.assertEqual(check_video.check(self.run_dir, rebuild=True)[0], [])

    def test_a_short_video_is_caught(self):
        self.assertTrue(any("expected" in problem for problem in check_video.check(self.run_dir, expect_seconds=1800)[0]))


class PlanTest(unittest.TestCase):
    def test_estimates_scale_with_ticks_and_get_cheaper_down_the_list(self):
        measured = {"ticks": 3, "seconds": {"sim": 5.0, "wm": 100.0, "agent": 5.0, "total": 110.0}, "bytes_per_tick": 1024 ** 3, "preset": "gpu_full", "peak_memory_gb": {}}
        rows = plan.estimate(measured, ticks=60, dollars_per_gpu_hour=2.0)
        self.assertAlmostEqual(rows[0]["wall_hours"], 110 * 60 / 3600, places=1)
        self.assertAlmostEqual(rows[0]["gpu_hours"], rows[0]["wall_hours"] * 3, places=1)
        self.assertAlmostEqual(rows[0]["dollars"], rows[0]["gpu_hours"] * 2, places=1)
        self.assertTrue(all(row["seconds_per_tick"] < rows[0]["seconds_per_tick"] for row in rows[1:]))

    def test_it_measures_a_real_folder(self):
        run_dir = folder()
        run(Config(ticks=2), run_dir)
        measured = plan.measure(run_dir)
        self.assertGreater(measured["bytes_per_tick"], 0)
        self.assertEqual(measured["ticks"], 2)


class CompareTest(unittest.TestCase):
    def test_it_reports_the_gap_between_two_runs(self):
        agent, null = folder(), folder()
        run(Config(ticks=6), agent)
        run(Config(ticks=6), null, agent=NullAgent())
        result = compare.compare(agent, null)
        self.assertEqual(result["ticks_compared"], 6)
        self.assertGreater(result["agent_distance"]["max"], 0)
        self.assertGreater(result["actions_differ"], 0)


class ModelServer:
    def __enter__(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                body = json.dumps({"data": [{"id": "nvidia/Cosmos3-Nano"}]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()


class PreflightTest(unittest.TestCase):
    def test_mock_passes_here(self):
        self.assertEqual(preflight.main(["--backend", "mock", "--out", str(folder() / "x"), "--wm-preset", "mock"]), 0)

    def test_too_little_disk_fails(self):
        ok, detail = preflight._disk(folder(), 10 ** 9, "gpu_full")
        self.assertFalse(ok, detail)

    def test_a_missing_life_database_fails(self):
        self.assertFalse(preflight._life("/nowhere/life.db", 1, None, 60)[0])

    def test_a_server_without_the_model_fails(self):
        with ModelServer() as url:
            self.assertTrue(preflight._model_server(url, "nvidia/Cosmos3-Nano")[0])
            self.assertFalse(preflight._model_server(url, "Qwen/Other")[0])
        self.assertFalse(preflight._model_server("http://127.0.0.1:1", "x")[0])

    def test_every_failure_is_reported_at_once(self):
        parser = preflight.make_parser()
        args = parser.parse_args(["--out", str(folder() / "x"), "--life-db", "/nowhere", "--wm-url", "http://127.0.0.1:1",
                                  "--agent-url", "http://127.0.0.1:1", "--sim-port", "1"])
        failed = [name for name, ok, _ in preflight.run_checks(args) if not ok]
        for name in ("life tree", "Cosmos server", "Qwen server", "SimWorld server"):
            self.assertIn(name, failed)


class PreemptionTest(unittest.TestCase):
    """Kill a real process mid-run, the way Slurm does, and continue from the command line."""

    def command(self, *extra):
        return [sys.executable, "-m", "runtime.run", "--no-counterfactual", *extra]

    def test_a_killed_run_resumes_to_the_same_trajectory(self):
        whole, killed = folder() / "whole", folder() / "killed"
        subprocess.run(self.command("--ticks", "6", "--seed", "4", "--out", str(whole)), check=True, capture_output=True)
        process = subprocess.Popen(self.command("--ticks", "6", "--seed", "4", "--out", str(killed)), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 60
        while time.time() < deadline and not (killed / "checkpoint.json").exists():
            time.sleep(0.02)
        time.sleep(0.15)
        process.send_signal(signal.SIGKILL if os.environ.get("WMLOOP_HARD_KILL") else signal.SIGTERM)
        process.wait()
        self.assertNotEqual(process.returncode, 0, "the run finished before it could be killed")
        subprocess.run(self.command("--resume", str(killed), "--ticks", "6"), check=True, capture_output=True)
        self.assertEqual(replay.trajectory(whole), replay.trajectory(killed))

    def test_a_resume_takes_the_servers_new_addresses(self):
        from argparse import Namespace

        from runtime.run import apply_new_addresses
        config = Config(wm_url="http://old:1", agent_url="http://old:2", sim_settings={"port": 1, "tick_interval_s": 0.1})
        apply_new_addresses(config, Namespace(wm_url="http://new:1", agent_url=None, sim_settings='{"port": 9}'))
        self.assertEqual(config.wm_url, "http://new:1")
        self.assertEqual(config.agent_url, "http://old:2")
        self.assertEqual(config.sim_settings, {"port": 9, "tick_interval_s": 0.1})


class MindTest(unittest.TestCase):
    def test_the_feeling_loop_wraps_the_agent_and_resumes(self):
        main_checkout = "/Users/jaycewalzer/Desktop/kokopelli"
        if not (Path(main_checkout) / "mind" / "feeling.py").exists():
            self.skipTest("mind/ isn't here")
        env = {**os.environ, "PYTHONPATH": f".:{main_checkout}"}
        out = folder() / "mind"
        code = (f"import sys; sys.path[:0] = ['.', {main_checkout!r}]\n"
                "from mind.feeling import FeelingAgent\nfrom mind.run import MockMind\n"
                "from pathlib import Path\nfrom runtime.config import Config\nfrom runtime.run import run\n"
                f"out = Path({str(out)!r})\nagent = FeelingAgent(MockMind(7), out / 'feelings.jsonl')\n"
                "s = run(Config(ticks=3, counterfactual=False), out, agent=agent)\nprint(s['run']['totals']['ticks'])\n")
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=Path(__file__).parents[2])
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        self.assertEqual(result.stdout.strip(), "3")
        self.assertTrue((out / "feelings.jsonl").stat().st_size)


if __name__ == "__main__":
    unittest.main()
