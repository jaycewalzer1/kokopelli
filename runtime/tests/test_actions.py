import json
import tempfile
import unittest
from pathlib import Path

from runtime.actions import InvalidDecision, parse_decision
from runtime.config import Config
from runtime.mocks.agent import ScriptedAgent
from runtime.replay import load, summarize
from runtime.run import run

VISIBLE = ["ana", "ball"]


class SchemaTest(unittest.TestCase):
    def test_each_action_validates(self):
        for action in ({"type": "move_to", "target": "ana"}, {"type": "look_at", "target": "ball"}, {"type": "interact", "target": "ball"},
                       {"type": "speak", "text": "Hi"}, {"type": "wait"}):
            self.assertEqual(parse_decision(json.dumps({"action": action}), VISIBLE).action.type, action["type"])

    def test_code_fence_and_diary_are_fine(self):
        decision = parse_decision('```json\n{"action": {"type": "wait"}, "diary": "tired"}\n```', VISIBLE)
        self.assertEqual(decision.diary, "tired")

    def test_bad_replies_are_rejected(self):
        for raw in ("just words", "{not json}", '{"action": {"type": "fly"}}', '{"action": {"type": "move_to"}}',
                    '{"action": {"type": "wait", "speed": 3}}', '{"action": {"type": "wait"}, "reward": 1}',
                    '{"action": {"type": "speak", "text": ""}}'):
            with self.assertRaises(InvalidDecision, msg=raw):
                parse_decision(raw, VISIBLE)

    def test_target_it_cannot_see_is_rejected(self):
        with self.assertRaisesRegex(InvalidDecision, "can see"):
            parse_decision('{"action": {"type": "move_to", "target": "the moon"}}', VISIBLE)


class RetryTest(unittest.TestCase):
    def run_with(self, agent):
        folder = tempfile.mkdtemp(prefix="wmloop_")
        run(Config(ticks=2, counterfactual=False), Path(folder), agent=agent)
        return folder

    def test_one_bad_reply_gets_one_retry(self):
        tick = next(t for t in summarize(self.run_with(ScriptedAgent(1, invalid_ticks=[1])))["ticks"] if t["tick"] == 1)
        self.assertEqual([o["valid"] for o in tick["outputs"]], [False, True])
        self.assertNotIn("fallback", tick)

    def test_two_bad_replies_become_a_logged_wait(self):
        folder = self.run_with(ScriptedAgent(1, always_invalid_ticks=[1]))
        tick = next(t for t in summarize(folder)["ticks"] if t["tick"] == 1)
        self.assertEqual([o["valid"] for o in tick["outputs"]], [False, False])
        self.assertEqual(tick["decision"]["action"], {"type": "wait"})
        self.assertIn("agent_fallback", [event["kind"] for event in load(folder)])


if __name__ == "__main__":
    unittest.main()
