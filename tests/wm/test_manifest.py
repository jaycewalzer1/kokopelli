"""kokopelli/wm/manifest.py: commit and dirty state from a throwaway git repo, weight identity from a toy weights folder."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from kokopelli.wm import manifest as mf  # noqa: E402

FIELDS = ("commit", "dirty", "weights", "seed", "prompt", "quantize", "controls", "resolution", "fake")


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


class GitStateTest(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="test_manifest_git_"))
        self.addCleanup(shutil.rmtree, self.repo, True)
        git(self.repo, "init", "-q")
        (self.repo / "a.py").write_text("x = 1\n")
        git(self.repo, "add", "a.py")
        git(self.repo, "commit", "-qm", "one")
        mf.git_state.cache_clear()
        self.addCleanup(mf.git_state.cache_clear)

    def state(self):
        mf.git_state.cache_clear()
        return mf.git_state(self.repo)

    def test_clean_checkout(self):
        s = self.state()
        self.assertRegex(s["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(s["dirty"], {"dirty": False, "diff_sha256": None, "untracked": 0})

    def test_an_edit_makes_it_dirty_and_the_hash_follows_the_diff(self):
        (self.repo / "a.py").write_text("x = 2\n")
        first = self.state()["dirty"]
        self.assertTrue(first["dirty"])
        self.assertRegex(first["diff_sha256"], r"^[0-9a-f]{64}$")
        (self.repo / "a.py").write_text("x = 3\n")
        self.assertNotEqual(self.state()["dirty"]["diff_sha256"], first["diff_sha256"])

    def test_an_untracked_file_makes_it_dirty(self):
        (self.repo / "new.py").write_text("")
        self.assertEqual(self.state()["dirty"], {"dirty": True, "diff_sha256": None, "untracked": 1})

    def test_not_a_repo(self):
        plain = Path(tempfile.mkdtemp(prefix="test_manifest_plain_"))
        self.addCleanup(shutil.rmtree, plain, True)
        mf.git_state.cache_clear()
        self.assertEqual(mf.git_state(plain), {"commit": None, "dirty": None})


class WeightsTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="test_manifest_w_"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(mf.weights_info.cache_clear)
        (self.dir / "transformer").mkdir()
        self.index = self.dir / "transformer" / "model.safetensors.index.json"
        self.index.write_text(json.dumps({"weight_map": {"w": "model-00001-of-00001.safetensors"}}))
        (self.dir / "config.json").write_text("{}")
        # a 3 GB sparse file: hashing it would take seconds, stat'ing it doesn't
        with open(self.dir / "transformer" / "model-00001-of-00001.safetensors", "wb") as f:
            f.truncate(3 * 2 ** 30)
        (self.dir / ".cache").mkdir()
        (self.dir / ".cache" / "stale.safetensors").write_bytes(b"x")

    def test_hashes_the_index_and_sizes_the_weights_without_reading_them(self):
        w = mf.weights_info(str(self.dir))
        self.assertEqual(w["sha256"], {"transformer/model.safetensors.index.json": hashlib.sha256(self.index.read_bytes()).hexdigest(),
                                       "config.json": hashlib.sha256(b"{}").hexdigest()})
        self.assertEqual(w["sizes"], {"transformer/model-00001-of-00001.safetensors": 3 * 2 ** 30})
        self.assertEqual(w["total_bytes"], 3 * 2 ** 30)

    def test_missing_weights_say_so(self):
        self.assertEqual(mf.weights_info(str(self.dir / "nope")), {"path": str(self.dir / "nope"), "exists": False})


class ManifestTest(unittest.TestCase):
    def test_every_field_and_the_fake_label(self):
        m = mf.manifest(weights={"agent": None, "world_model": None}, seed=7, prompt="p", quantize=8,
                        controls={"edge": 0.25}, resolution="64x32", fake=True, fake_world_model=True)
        for field in FIELDS:
            self.assertIn(field, m)
        self.assertEqual((m["fake"], m["fake_world_model"], m["weights"]), (True, True, {}))

    def test_a_real_run_names_its_weights(self):
        m = mf.manifest(weights=ROOT / "tests", seed=1)
        self.assertFalse(m["fake"])
        self.assertEqual(m["weights"]["path"], str(ROOT / "tests"))
        self.assertTrue(m["weights"]["exists"])


if __name__ == "__main__":
    unittest.main()
