import email
import hashlib
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import numpy as np

from kokopelli.loop.adapters.cosmos_server import CosmosServerWorldModel
from kokopelli.loop.config import Config
from kokopelli.loop.frames import write_clip
from kokopelli.loop.mocks.agent import ScriptedAgent
from kokopelli.loop.replay import summarize
from kokopelli.loop.run import run


def parts(handler):
    """Split a multipart request into its fields, the way the real server would."""
    body = handler.rfile.read(int(handler.headers["Content-Length"]))
    if handler.headers["Content-Type"].startswith("application/x-www-form-urlencoded"):
        return {name: values[0].encode() for name, values in parse_qs(body.decode()).items()}
    message = email.message_from_bytes(b"Content-Type: " + handler.headers["Content-Type"].encode() + b"\r\n\r\n" + body)
    return {part.get_param("name", header="content-disposition"): part.get_payload(decode=True) for part in message.get_payload()}


class FakeServer:
    """Answers like vLLM-Omni's /v1/videos/sync, and remembers what it was sent."""

    def __enter__(self):
        folder = tempfile.mkdtemp(prefix="wmloop_")
        clip = Path(write_clip([np.full((256, 448, 3), 40 + 8 * i, np.uint8) for i in range(24)], f"{folder}/clip.mp4")).read_bytes()
        received = self.received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                received.append({"path": self.path, **parts(self)})
                self.send_response(200 if self.path == "/v1/videos/sync" else 404)
                self.send_header("Content-Length", str(len(clip)))
                self.end_headers()
                self.wfile.write(clip)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()


def hash_of(data):
    return hashlib.sha256(data).hexdigest()


class ServerTest(unittest.TestCase):
    def run_loop(self, server, **settings):
        folder = Path(tempfile.mkdtemp(prefix="wmloop_"))
        config = Config(ticks=2, wm="cosmos_server", wm_url=server.url, wm_preset="gpu_full", cond_frames=1, counterfactual=False, **settings)
        run(config, folder, agent=ScriptedAgent(1))
        return folder

    def test_each_chunk_sends_the_fields_the_readme_uses(self):
        with FakeServer() as server:
            self.run_loop(server)
        first = server.received[0]
        self.assertEqual(first["path"], "/v1/videos/sync")
        self.assertEqual(first["num_frames"], b"181")
        self.assertEqual(first["size"], b"832x480")
        self.assertEqual(first["num_inference_steps"], b"35")
        self.assertIn(b"input_reference", [key.encode() for key in first])

    def test_every_tick_makes_four_chunks_and_two_checks(self):
        with FakeServer() as server:
            folder = self.run_loop(server)
        self.assertEqual(len(server.received), 8)
        self.assertEqual([check["offset_s"] for check in summarize(folder)["ticks"][0]["drift"]], [15, 30])

    def test_a_re_anchor_sends_the_sims_frame_itself(self):
        with FakeServer() as server:
            folder = self.run_loop(server, drift_threshold=0.0)
            ticks = summarize(folder)["ticks"]
            anchor = ticks[0]["reanchors"][0]
            self.assertEqual(anchor["cond"], [{"path": anchor["frame"], "source": "sim"}])
            uploaded = [hash_of(item["input_reference"]) for item in server.received]
            self.assertIn(hash_of((folder / anchor["frame"]).read_bytes()), uploaded)

    def test_a_server_error_stops_the_run_with_a_real_error(self):
        import requests
        with FakeServer() as server:
            model = CosmosServerWorldModel(server.url + "/wrong", "832x480", 35)
            folder = tempfile.mkdtemp(prefix="wmloop_")
            frame = Path(folder) / "frame.png"
            frame.write_bytes(b"not really a png")

            class Request:
                prompt, frames, seed, control = "p", 81, 1, None
                cond = [type("Frame", (), {"path": str(frame)})]
                output = f"{folder}/out.mp4"

            with self.assertRaises(requests.HTTPError):
                model.render_chunk(Request)

    def test_more_than_one_conditioning_frame_is_refused(self):
        model = CosmosServerWorldModel("http://127.0.0.1:1", "832x480", 35)

        class Request:
            cond, control = [object(), object()], None

        with self.assertRaisesRegex(ValueError, "one frame"):
            model.render_chunk(Request)


if __name__ == "__main__":
    unittest.main()
