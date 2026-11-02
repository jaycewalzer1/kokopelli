"""These call the real model."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from llm_model import ask, load_llm, unload
from settings import LLM_MODEL, LLM_MODEL_WEIGHTS


class LLMModelTest(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        unload()

    def test_settings_name_the_qwen_model(self):
        self.assertEqual(LLM_MODEL, "Qwen/Qwen3-VL-8B-Instruct")
        self.assertTrue(LLM_MODEL_WEIGHTS.is_dir())

    def test_answers_text(self):
        answer = ask("What is the capital of France? Answer with one word.", max_tokens=10)
        self.assertIn("paris", answer.lower())

    def test_answers_about_an_image(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "red.png"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=red:s=256x256",
                            "-frames:v", "1", str(image)], check=True)
            answer = ask("What color is this image? Answer with one word.", images=[image], max_tokens=10)
        self.assertIn("red", answer.lower())

    def test_max_tokens_limits_the_answer(self):
        answer = ask("Count from 1 to 100, separated by spaces.", max_tokens=5)
        self.assertLess(len(answer.split()), 10)

    def test_model_is_loaded_once_until_unloaded(self):
        first = load_llm()
        self.assertIs(load_llm(), first)
        unload()
        self.assertEqual(load_llm.cache_info().currsize, 0)


if __name__ == "__main__":
    unittest.main()
