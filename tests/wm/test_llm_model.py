"""These call the real model."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import pytest

from kokopelli.wm.llm_model import ask, load_llm, unload
from kokopelli.settings import LLM_MODEL, LLM_MODEL_WEIGHTS

# Loading Qwen3-VL-8B (peak 16.5 GB) in the default run made tests/ peak at 18.3 GB, and five runs at once crashed the Mac.
# These are model jobs: run them through kokopelli/ops/gpu.py with RUN_MODEL_TESTS=1 (command in docs/fable_log/P1-M.md).
# The model marker (conftest.py skips it unless RUN_MODEL_TESTS is set). The unittest skip keeps a plain unittest run,
# which ignores markers, from loading the model as well.
MODEL = "loads Qwen3-VL-8B (peak 16.5 GB)"


def needs_model(test):
    test = unittest.skipUnless(os.environ.get("RUN_MODEL_TESTS"), f"{MODEL}; set RUN_MODEL_TESTS=1 and queue it")(test)
    return pytest.mark.model(reason=MODEL)(test)


class LLMModelTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        unload()

    def test_settings_name_the_qwen_model(self):
        self.assertEqual(LLM_MODEL, "Qwen/Qwen3-VL-8B-Instruct")
        self.assertTrue(LLM_MODEL_WEIGHTS.is_dir())

    @needs_model
    def test_answers_text(self):
        answer = ask("What is the capital of France? Answer with one word.", max_tokens=10)
        self.assertIn("paris", answer.lower())

    @needs_model
    def test_answers_about_an_image(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "red.png"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=red:s=256x256",
                            "-frames:v", "1", str(image)], check=True)
            answer = ask("What color is this image? Answer with one word.", images=[image], max_tokens=10)
        self.assertIn("red", answer.lower())

    @needs_model
    def test_max_tokens_limits_the_answer(self):
        answer = ask("Count from 1 to 100, separated by spaces.", max_tokens=5)
        self.assertLess(len(answer.split()), 10)

    @needs_model
    def test_model_is_loaded_once_until_unloaded(self):
        first = load_llm()
        self.assertIs(load_llm(), first)
        unload()
        self.assertEqual(load_llm.cache_info().currsize, 0)


if __name__ == "__main__":
    unittest.main()
