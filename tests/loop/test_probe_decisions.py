import tempfile
import unittest
from pathlib import Path

from kokopelli.loop import probe_decisions as probe
from kokopelli.loop.config import Config
from kokopelli.loop.mocks.context import MockContext
from kokopelli.loop.prompt_builder import build_agent_prompt
from kokopelli.loop.run import run

NOW = "2004-06-12T16:00:00"
VISIBLE = ["door", "ball", "ana"]


def prompt(notes=()):
    return build_agent_prompt(MockContext().context_at(NOW), list(notes), VISIBLE, 6, NOW)[0]


class VariantTest(unittest.TestCase):
    def test_notes_really_come_out(self):
        written = prompt([{"t": NOW, "text": "The pigeons are gone."}])
        self.assertIn("pigeons", written)
        cleared = probe.without_notes(written)
        self.assertNotIn("pigeons", cleared)
        self.assertEqual(cleared, prompt())

    def test_the_list_really_reverses(self):
        self.assertIn("You can see: ana, ball, door.", probe.reversed_list(prompt(), VISIBLE))

    def test_replies_are_read_or_say_why_not(self):
        self.assertEqual(probe.read_reply('{"action": "look_at", "target": "door"}', VISIBLE)["action"], "look_at door")
        self.assertIsNone(probe.read_reply("no idea", VISIBLE)["action"])

    def test_it_runs_over_a_whole_run(self):
        folder = Path(tempfile.mkdtemp(prefix="wmloop_"))
        run(Config(ticks=2, counterfactual=False), folder)
        calls = []

        def ask(text, images, temperature):
            calls.append((text, images, temperature))
            return '{"action": {"type": "wait"}}'

        rows = probe.probe(folder, ask)
        self.assertEqual(len(rows), 2 * (5 + probe.SAMPLES_AT_TEMPERATURE))
        self.assertTrue(all(Path(path).exists() or "blank" in path for _, images, _ in calls for path in images))
        self.assertEqual(probe.tally(rows)["as_logged t=0.0"], {"wait": 2})
        self.assertEqual({row["tick"] for row in probe.probe(folder, ask, only_ticks=[2])}, {2})


if __name__ == "__main__":
    unittest.main()
