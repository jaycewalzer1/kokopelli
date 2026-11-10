"""The city moodboard's store, and that only the panel's own page can write to it."""
import base64
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from kokopelli.life import moodboard
from kokopelli.life.panel import make_server

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode()


class MoodboardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_add_saves_the_file_and_puts_it_up_for_review(self):
        image = moodboard.add(PNG, " Rooftop farm ", "https://example.com/a", {"channel": "solarpunk"}, folder=self.folder)
        self.assertTrue((self.folder / image["file"]).is_file())
        saved = json.loads((self.folder / "board.json").read_text())["images"]
        self.assertEqual([(item["id"], item["status"], item["title"]) for item in saved], [(image["id"], "proposed", "Rooftop farm")])

    def test_the_same_picture_is_kept_once(self):
        first = moodboard.add(PNG, folder=self.folder)
        again = moodboard.add(PNG, "another title", folder=self.folder)
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(len(moodboard.board(self.folder)["images"]), 1)

    def test_refuses_what_isnt_a_picture(self):
        with self.assertRaises(ValueError):
            moodboard.add(base64.b64encode(b"<html>not a picture</html>").decode(), folder=self.folder)

    def test_review_changes_only_status_section_and_note(self):
        image = moodboard.add(PNG, folder=self.folder)
        moodboard.update(image["id"], {"status": "kept", "section": "light", "note": "dusk", "file": "../../etc/passwd"}, folder=self.folder)
        saved = moodboard.board(self.folder)["images"][0]
        self.assertEqual((saved["status"], saved["section"], saved["note"], saved["file"]), ("kept", "light", "dusk", image["file"]))
        with self.assertRaises(ValueError):
            moodboard.update(image["id"], {"status": "deleted"}, folder=self.folder)
        with self.assertRaises(ValueError):
            moodboard.update(image["id"], {"section": "no-such-section"}, folder=self.folder)

    def test_a_removed_picture_keeps_its_reason_and_file(self):
        image = moodboard.add(PNG, folder=self.folder)
        moodboard.update(image["id"], {"status": "removed", "note": "too sci-fi"}, folder=self.folder)
        saved = moodboard.board(self.folder)["images"][0]
        self.assertEqual((saved["status"], saved["note"]), ("removed", "too sci-fi"))
        self.assertTrue(moodboard.image_file(image["id"], folder=self.folder)[0].is_file())


class MoodboardRouteTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = make_server(Path(self.temp.name) / "life.db", port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def test_a_write_from_another_site_is_refused(self):
        request = urllib.request.Request(f"{self.base}/api/moodboard/add", data=json.dumps({"data": PNG}).encode(),
                                         headers={"Content-Type": "application/json", "Origin": "https://example.com"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 403)

    def test_the_page_is_served(self):
        with urllib.request.urlopen(f"{self.base}/moodboard") as response:
            self.assertIn(b"City moodboard", response.read())


if __name__ == "__main__":
    unittest.main()
