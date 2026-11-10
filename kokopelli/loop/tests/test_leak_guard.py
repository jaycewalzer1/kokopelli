import tempfile
import unittest
from pathlib import Path

from kokopelli.loop.config import Config
from kokopelli.loop.interfaces import ContextDB
from kokopelli.loop.leak_guard import LeakError, check, drop_future
from kokopelli.loop.mocks.context import MockContext
from kokopelli.loop.prompt_builder import build_agent_prompt, build_wm_prompt
from kokopelli.loop.replay import load
from kokopelli.loop.run import run

NOW = "2004-06-12T16:00:00"


class GuardTest(unittest.TestCase):
    def test_future_dated_item_fails(self):
        with self.assertRaisesRegex(LeakError, "future-dated"):
            check({"events": [{"t": "2004-06-12T16:00:01", "text": "soon"}]}, NOW)

    def test_item_dated_exactly_now_passes(self):
        check({"events": [{"t": NOW, "text": "now"}]}, NOW)

    def test_banned_field_fails_at_any_depth(self):
        with self.assertRaisesRegex(LeakError, "fraction_lived"):
            check({"a": [{"b": {"fraction_lived": 0.5}}]}, NOW)
        for field in ("hidden_target", "rng_key", "salience", "depth_limit", "odds", "closing", "end_t"):
            with self.assertRaises(LeakError, msg=field):
                check({field: 1}, NOW)

    def test_banned_field_named_in_text_fails(self):
        with self.assertRaisesRegex(LeakError, "banned field"):
            check({"text": "you are at fraction_lived=0.4"}, NOW)

    def test_future_date_in_text_fails(self):
        with self.assertRaisesRegex(LeakError, "future date"):
            check({"text": "On 2031-01-01 everything changes."}, NOW)

    def test_ordinary_words_pass(self):
        check({"text": "She took aim at the target. The odds looked good. Past 2004-06-11 it rained."}, NOW)

    def test_filter_drops_only_the_future(self):
        kept, dropped = drop_future([{"t": "2004-06-12T15:00:00"}, {"t": NOW}, {"t": "2005-01-01T00:00:00"}], NOW)
        self.assertEqual((len(kept), dropped), (2, 1))


class PromptsTest(unittest.TestCase):
    def state(self):
        place = {"pos": [1.0, 2.0], "state": "at rest"}
        return {"time_of_day": "afternoon", "weather": "clear", "agent": {"pos": [1.0, 1.0], "facing": "east"},
                "npcs": {"ana": {"pos": [2.0, 2.0]}}, "objects": {"ball": place}}

    def test_mock_context_drops_its_future_event_and_builds_clean_prompts(self):
        context = MockContext().context_at(NOW)
        self.assertGreater(context["dropped"], 0)
        wm, _ = build_wm_prompt(context, self.state(), {"type": "wait"}, "Style.", NOW)
        agent, _ = build_agent_prompt(context, [], ["ana"], 6, NOW)
        for text in (wm, agent):
            self.assertNotIn("decades away", text)

    def test_future_note_stops_the_agent_prompt(self):
        with self.assertRaises(LeakError):
            build_agent_prompt(MockContext().context_at(NOW), [{"t": "2031-01-01T00:00:00", "text": "x"}], [], 6, NOW)

    def test_the_agent_prompt_never_carries_physical_state(self):
        prompt, _ = build_agent_prompt(MockContext().context_at(NOW), [], ["ana"], 6, NOW)
        self.assertNotIn("Camera at", prompt)


class LeakyContext(MockContext, ContextDB):
    def context_at(self, now):
        return {**super().context_at(now), "fraction_lived": 0.5}


class RunStopsTest(unittest.TestCase):
    def test_a_leak_stops_the_run_and_leaves_an_alarm_in_the_log(self):
        with tempfile.TemporaryDirectory(prefix="wmloop_") as folder:
            with self.assertRaises(LeakError):
                run(Config(ticks=2), Path(folder), context=LeakyContext())
            kinds = [event["kind"] for event in load(folder)]
            self.assertIn("leak_alarm", kinds)
            self.assertNotIn("wm_chunk", kinds)


if __name__ == "__main__":
    unittest.main()
