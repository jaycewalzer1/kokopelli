import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from runtime.config import Config
from runtime.run import run
from runtime.viewer import serve


class ViewerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent = Path(tempfile.mkdtemp(prefix="wmloop_"))
        cls.folder = cls.parent / "run"
        run(Config(ticks=2), cls.folder)
        (cls.parent / "secret.txt").write_text("outside the run")
        cls.server = serve(cls.folder, port=8891)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.url + path) as response:
            return response.read()

    def test_pages_are_served(self):
        for path in ("/", "/viewer.js", "/viewer.css", "/design.css"):
            self.assertTrue(self.get(path))

    def test_the_run_comes_from_the_log(self):
        data = json.loads(self.get("/api/run"))
        self.assertEqual(len(data["ticks"]), 2)

    def test_files_in_the_run_are_served(self):
        tick = json.loads(self.get("/api/run"))["ticks"][0]
        self.assertTrue(self.get(f"/files/{tick['chunks'][0]['clip']}"))

    def test_nothing_outside_the_run_is_served(self):
        for path in ("/files/../secret.txt", "/files/%2e%2e/secret.txt", "/files/../../../../etc/hosts"):
            request = urllib.request.Request(self.url + path)
            with self.assertRaises(urllib.error.HTTPError, msg=path) as caught:
                urllib.request.urlopen(request)
            self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
