import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from kokopelli.mind.check import flip, stats, verdict
from kokopelli.mind.feeling import (APPRAISE, BIG_NOTE, CHANGE, FeelingAgent, decision_point, inner_context, parse_appraisal, parse_change, read_rows, settle,
                          timeline)

try:
    from kokopelli.loop.config import Config
    from kokopelli.loop.run import run
    from kokopelli.mind.check import compare, replay
    from kokopelli.mind.run import MockMind, check_weights, measured_qwen, summarize
except ImportError:
    Config = None

    def check_weights(path):
        raise SystemExit("fused")

needs_runtime = unittest.skipIf(Config is None, "needs the agent-loop branch on PYTHONPATH")
CALM = {"feeling": "calm", "intensity": 0.2, "why": "Nothing moved."}
CHANGED = '{"changed": true, "what": "The ball rolled away."}'
NOTHING = '{"changed": false, "what": ""}'
PROMPT = "You are living this life.\n\nDecide what to do for the next 30 seconds.\nActions"


@dataclass
class Input:
    prompt: str
    images: list
    visible: list
    now: str
    tick: int
    retry_error: str | None = None


class Inner:
    """Replays appraisals in order, and records every prompt and set of images it was sent."""

    def __init__(self, appraisals, action='{"action": {"type": "wait"}}', change=CHANGED):
        self.appraisals, self.action, self.change, self.prompts, self.images, self.released = list(appraisals), action, change, [], [], False

    def decide(self, agent_input):
        self.prompts.append(agent_input.prompt)
        self.images.append(agent_input.images)
        if agent_input.prompt == CHANGE:
            return self.change
        if APPRAISE in agent_input.prompt:
            reply = self.appraisals.pop(0)
            return reply if isinstance(reply, str) else json.dumps(reply)
        return self.action

    def release(self):
        self.released = True


def turn(tick, visible=("bench",), retry=None):
    return Input(PROMPT, [], list(visible), f"2004-06-12T16:{tick:02d}:00", tick, retry)


def agent_with(inner):
    return FeelingAgent(inner, Path(tempfile.mkdtemp(prefix="mind_")) / "feelings.jsonl")


class ParseTest(unittest.TestCase):
    def test_reads_a_fenced_reply_and_clamps_intensity(self):
        parsed = parse_appraisal('```json\n{"feeling": " Scared ", "intensity": 3, "why": "Fire."}\n```')
        self.assertEqual(parsed, {"feeling": "scared", "intensity": 1.0, "why": "Fire."})

    def test_bad_replies_are_none(self):
        for raw in ("I feel fine", '{"feeling": "ok"}', '{"feeling": "", "intensity": 1}', '{"feeling": "ok", "intensity": "high"}', "[1]"):
            self.assertIsNone(parse_appraisal(raw), raw)


class ChangeTest(unittest.TestCase):
    def test_reads_what_changed(self):
        self.assertEqual(parse_change(CHANGED), ("The ball rolled away.", True))
        self.assertEqual(parse_change('{"changed": true}'), ("Something changed.", True))
        self.assertEqual(parse_change(NOTHING), (None, True))

    def test_only_a_clear_yes_counts_and_an_unreadable_reply_is_flagged(self):
        self.assertEqual(parse_change('{"changed": "false", "what": "no"}'), (None, True))
        for raw in ("no idea", "[1]", '{"what": "x"}'):
            self.assertEqual(parse_change(raw), (None, False), raw)


def feeling(word, intensity):
    return {"feeling": word, "intensity": intensity, "why": ""}


class SettleTest(unittest.TestCase):
    def test_the_first_feeling_is_taken_as_given(self):
        self.assertEqual(settle(None, feeling("happy", 0.9)), feeling("happy", 0.9))

    def test_intensity_moves_a_limited_step(self):
        self.assertEqual(settle(feeling("happy", 0.3), feeling("happy", 0.9))["intensity"], 0.45)
        self.assertEqual(settle(feeling("happy", 0.9), feeling("happy", 0.1))["intensity"], 0.75)
        self.assertEqual(settle(feeling("happy", 0.3), feeling("happy", 0.35))["intensity"], 0.35)

    def test_very_happy_has_to_fade_before_it_can_become_sad(self):
        mood, path = feeling("happy", 0.9), []
        for _ in range(6):
            mood = settle(mood, feeling("sad", 0.9))
            path.append((mood["feeling"], mood["intensity"]))
        self.assertEqual(path, [("happy", 0.75), ("happy", 0.6), ("happy", 0.45), ("happy", 0.3), ("sad", 0.3), ("sad", 0.45)])


class DecisionPointTest(unittest.TestCase):
    def test_each_rule(self):
        self.assertEqual(decision_point(None, CALM, ["a"], [], 0), ("small", "first look"))
        self.assertEqual(decision_point("calm", {**CALM, "intensity": 0.9}, ["a"], ["a"], 1), ("big", "strong feeling"))
        self.assertEqual(decision_point("calm", CALM, ["a", "b"], ["a"], 1), ("small", "what's in view changed"))
        self.assertEqual(decision_point("calm", {"feeling": "glad", "intensity": 0.5, "why": ""}, ["a"], ["a"], 1), ("small", "feeling changed"))
        self.assertEqual(decision_point("calm", CALM, ["a"], ["a"], 4), ("small", "been a while"))
        self.assertEqual(decision_point("calm", CALM, ["a"], ["a"], 1, "A door opened."), ("small", "something changed"))

    def test_quiet_moments_are_not_decision_points(self):
        self.assertIsNone(decision_point("calm", CALM, ["a"], ["a"], 1))
        self.assertIsNone(decision_point("calm", {**CALM, "intensity": 0.6}, ["a"], ["a"], 1))
        self.assertIsNone(decision_point("calm", None, ["a"], ["a"], 1))


@needs_runtime
class FeelingAgentTest(unittest.TestCase):
    def test_nothing_changing_asks_no_feeling_and_keeps_the_last_one(self):
        inner = Inner([CALM], change=NOTHING)
        agent = agent_with(inner)
        agent.decide(turn(1))
        agent.decide(turn(2))
        self.assertEqual(sum(APPRAISE in prompt for prompt in inner.prompts), 1)
        row = agent._appraisal_rows()[-1]
        self.assertEqual((row["feeling"], row["intensity"], row["carried"]), ("calm", 0.2, True))

    def test_a_change_is_judged_from_images_alone_with_the_last_frame_first(self):
        inner = Inner([CALM, CALM])
        agent = agent_with(inner)
        agent.decide(Input(PROMPT, ["a1", "a2"], ["bench"], "t1", 1))
        agent.decide(Input(PROMPT, ["b1", "b2"], ["bench"], "t2", 2))
        at = inner.prompts.index(CHANGE)
        self.assertEqual(inner.images[at], ["a2", "b1", "b2"])
        self.assertIn("What just changed: The ball rolled away.", inner.prompts[at + 1])
        self.assertIn("What just changed: The ball rolled away.", inner.prompts[at + 2])

    def test_a_shock_makes_a_big_moment_while_the_mood_moves_slowly(self):
        inner = Inner([{"feeling": "happy", "intensity": 0.9, "why": "Cake."}, {"feeling": "scared", "intensity": 0.9, "why": "Smoke."}])
        agent = agent_with(inner)
        agent.decide(turn(1))
        agent.decide(turn(2))
        row = agent._appraisal_rows()[-1]
        self.assertEqual((row["feeling"], row["intensity"], row["point"]), ("happy", 0.75, "big"))
        self.assertEqual(row["reported"]["feeling"], "scared")

    def test_an_unreadable_change_is_kept_and_counts_as_nothing(self):
        inner = Inner([CALM], change="no idea")
        agent = agent_with(inner)
        agent.decide(turn(1))
        agent.decide(turn(2))
        self.assertEqual(agent._appraisal_rows()[-1]["change_raw"], "no idea")
        self.assertTrue(agent._appraisal_rows()[-1]["carried"])

    def test_records_the_flat_reply_real_qwen_writes(self):
        for raw in ('{"action": "look_at", "target": "bench"}', '{"type": "look_at", "target": "bench"}'):
            agent = agent_with(Inner([CALM], raw))
            agent.decide(turn(1))
            self.assertEqual(timeline(agent.path)[0]["action"], {"type": "look_at", "target": "bench"})

    def test_a_reply_the_loop_would_reject_is_not_recorded_as_a_choice(self):
        for raw in ('{"action": {"type": "look_at", "target": "dragon"}}', '{"action": "dance"}', "no idea"):
            agent = agent_with(Inner([CALM], raw))
            agent.decide(turn(1))
            self.assertIsNone(timeline(agent.path)[0]["action"], raw)

    def test_appraises_before_deciding_and_carries_the_feeling_into_the_decision(self):
        inner = Inner([CALM])
        agent_with(inner).decide(turn(1))
        self.assertIn(APPRAISE, inner.prompts[0])
        self.assertNotIn("Decide what to do", inner.prompts[0])
        self.assertIn("calm (0.2): Nothing moved.", inner.prompts[1])

    def test_a_quiet_tick_makes_no_decision_call(self):
        inner = Inner([CALM], change=NOTHING)
        agent = agent_with(inner)
        agent.decide(turn(1))
        self.assertEqual(agent.decide(turn(2)), '{"action": {"type": "wait"}}')
        self.assertEqual(len(inner.prompts), 3)
        self.assertEqual(inner.prompts[2], CHANGE)

    def test_a_quiet_tick_keeps_walking_only_toward_something_in_view(self):
        inner = Inner([CALM], '{"action": {"type": "move_to", "target": "bench"}}', NOTHING)
        agent = agent_with(inner)
        agent.decide(turn(1))
        self.assertEqual(json.loads(agent.decide(turn(2))), {"action": {"type": "move_to", "target": "bench"}})
        # Losing sight of it changes the view, so that tick decides afresh. Check the carry-on itself directly.
        self.assertEqual(agent._carry_on(turn(3, visible=("door",))), '{"action": {"type": "wait"}}')

    def test_a_retry_decides_again_without_feeling_again(self):
        inner = Inner([CALM])
        agent = agent_with(inner)
        agent.decide(turn(1))
        agent.decide(turn(1, retry="bad reply"))
        self.assertEqual(sum(APPRAISE in prompt for prompt in inner.prompts), 1)
        self.assertEqual(len(agent._appraisal_rows()), 1)

    def test_a_big_moment_gets_the_note(self):
        inner = Inner([CALM, {"feeling": "scared", "intensity": 0.9, "why": "Smoke."}])
        agent = agent_with(inner)
        agent.decide(turn(1))
        self.assertNotIn(BIG_NOTE, inner.prompts[1])
        agent.decide(turn(2))
        self.assertIn(BIG_NOTE, inner.prompts[4])

    def test_a_garbled_appraisal_keeps_the_run_going(self):
        inner = Inner([CALM, "no idea"])
        agent = agent_with(inner)
        agent.decide(turn(1))
        self.assertEqual(agent.decide(turn(2)), '{"action": {"type": "wait"}}')
        row = agent._appraisal_rows()[-1]
        self.assertIsNone(row["feeling"])
        self.assertEqual(row["raw"], "no idea")

    def test_a_new_agent_on_the_same_file_remembers(self):
        path = Path(tempfile.mkdtemp(prefix="mind_")) / "feelings.jsonl"
        FeelingAgent(Inner([CALM]), path).decide(turn(1))
        inner = Inner([CALM])
        FeelingAgent(inner, path).decide(turn(2))
        self.assertEqual(inner.prompts[0], CHANGE)
        self.assertIn("Nothing moved.", inner.prompts[1])

    def test_release_reaches_the_inner_agent(self):
        inner = Inner([])
        agent_with(inner).release()
        self.assertTrue(inner.released)


class InnerContextTest(unittest.TestCase):
    def test_empty_past(self):
        text = inner_context([])
        self.assertIn("(nothing yet)", text)
        self.assertIn("nothing yet", text)

    @needs_runtime
    def test_prompts_stop_growing_however_long_the_run_and_however_long_the_replies(self):
        long = {"feeling": "x" * 500, "intensity": 0.2, "why": "y" * 5000}
        inner = Inner([long] * 60)
        agent = agent_with(inner)
        for tick in range(1, 61):
            agent.decide(turn(tick))
        appraisals = [prompt for prompt in inner.prompts if APPRAISE in prompt]
        self.assertEqual(len(appraisals[10]), len(appraisals[59]))
        self.assertLess(len(appraisals[59]), 2000)


@needs_runtime
class ResumeTest(unittest.TestCase):
    def test_a_repeated_tick_replaces_what_it_felt_before(self):
        path = Path(tempfile.mkdtemp(prefix="mind_")) / "feelings.jsonl"
        agent = FeelingAgent(Inner([CALM, {"feeling": "abandoned", "intensity": 0.2, "why": "Killed after this."}, CALM]), path)
        agent.decide(turn(1))
        agent.decide(turn(2))
        agent.decide(turn(2))
        self.assertEqual([row["tick"] for row in agent._appraisal_rows()], [1, 2])
        self.assertNotIn("abandoned", path.read_text())

    def test_a_line_torn_by_a_kill_is_dropped(self):
        path = Path(tempfile.mkdtemp(prefix="mind_")) / "feelings.jsonl"
        FeelingAgent(Inner([CALM]), path).decide(turn(1))
        with open(path, "a") as file:
            file.write('{"kind": "appraisal", "tick": 2, "fee')
        rows = read_rows(path)
        self.assertEqual({row["tick"] for row in rows}, {1})
        inner = Inner([CALM])
        FeelingAgent(inner, path).decide(turn(2))
        self.assertEqual(len(read_rows(path)), len(rows) + 2)


@needs_runtime
class TimelineTest(unittest.TestCase):
    def test_every_tick_says_what_was_felt_and_done(self):
        inner = Inner([CALM], '{"action": {"type": "move_to", "target": "bench"}}', NOTHING)
        agent = agent_with(inner)
        agent.decide(turn(1))
        agent.decide(turn(2))
        first, second = timeline(agent.path)
        self.assertEqual((first["point"], first["decided"]), ("small", True))
        self.assertEqual((second["point"], second["decided"]), (None, False))
        self.assertEqual(second["action"], {"type": "move_to", "target": "bench"})

    def test_costs_are_recorded_when_the_agent_reports_them(self):
        inner = Inner([CALM])
        inner.last_usage = {"prompt_tokens": 12}
        agent = agent_with(inner)
        agent.decide(turn(1))
        self.assertEqual(agent._appraisal_rows()[0]["usage"], {"prompt_tokens": 12})


def fake_run(folder, feelings):
    """A run's files, with the decision ticks given by which feelings are strong."""
    folder.mkdir(exist_ok=True)
    inner = Inner(feelings, '{"action": {"type": "move_to", "target": "bench"}}')
    agent = FeelingAgent(inner, folder / "feelings.jsonl")
    events = []
    for tick in range(1, len(feelings) + 1):
        agent.decide(turn(tick))
        events.append({"kind": "agent_input", "tick": tick, "data": {"prompt": PROMPT, "images": []}})
    (folder / "events.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
    return folder


class Reacts:
    """A stand-in model whose action depends on the feeling it was told about."""

    def __init__(self, on_word):
        self.on_word = on_word

    def decide(self, agent_input):
        action = {"type": "wait"} if self.on_word in agent_input.prompt else {"type": "look_at", "target": "bench"}
        return json.dumps({"action": action})


class Garbled:
    def decide(self, agent_input):
        return "no idea"


@needs_runtime
class CheckTest(unittest.TestCase):
    def test_flip_does_not_read_invalid_answers_as_no_effect(self):
        folder = fake_run(Path(tempfile.mkdtemp(prefix="mind_")) / "run", [{"feeling": "scared", "intensity": 0.9, "why": "Smoke."}] * 25)
        report = flip(folder, Garbled())
        self.assertEqual((report["decisions"], report["valid_decisions"]), (25, 0))
        self.assertIn("too few", report["verdict"])

    def test_stats_report_variation_and_what_was_grounded_in_view(self):
        folder = fake_run(Path(tempfile.mkdtemp(prefix="mind_")) / "run", [{"feeling": "calm", "intensity": 0.2, "why": "The bench is empty."},
                                                                           {"feeling": "scared", "intensity": 0.9, "why": "Smoke everywhere."}])
        report = stats(folder)
        self.assertEqual(report["distinct_feelings"], 2)
        self.assertEqual(report["why_names_something_in_view"], {"hits": 1, "total": 2, "rate": 0.5})
        self.assertEqual(report["actions_by_feeling"]["scared"], {"move_to": 1})

    def test_flip_sees_an_effect_only_when_the_strong_feeling_differs_from_the_placebo(self):
        folder = fake_run(Path(tempfile.mkdtemp(prefix="mind_")) / "run", [{"feeling": "scared", "intensity": 0.9, "why": "Smoke."}] * 25)
        report = flip(folder, Reacts("terrified"))
        self.assertEqual(report["decisions"], 25)
        self.assertEqual(report["strong_changed_action"]["rate"], 1.0)
        self.assertEqual(report["placebo_changed_action"]["rate"], 0.0)
        self.assertIn("changes the action", report["verdict"])
        self.assertIn("no clear effect", flip(folder, Reacts("no such word"))["verdict"])

    def test_flip_swaps_only_the_latest_feeling(self):
        folder = fake_run(Path(tempfile.mkdtemp(prefix="mind_")) / "run", [{"feeling": "scared", "intensity": 0.9, "why": "Smoke."}] * 2)
        seen = []

        class Records(Reacts):
            def decide(self, agent_input):
                seen.append(agent_input.prompt)
                return super().decide(agent_input)

        flip(folder, Records("terrified"))
        self.assertIn("scared", seen[-1])
        self.assertIn("terrified", seen[-1])
        self.assertNotIn("terrified", seen[-2])

    def test_too_few_decisions_says_so(self):
        self.assertIn("too few", verdict({"total": 8, "rate": 1.0}, {"total": 8, "rate": 0.0}))


@needs_runtime
class LoopTest(unittest.TestCase):
    def test_the_loop_runs_unchanged_and_resumes_with_the_past(self):
        folder = Path(tempfile.mkdtemp(prefix="mind_"))
        feelings = folder / "feelings.jsonl"
        config = Config(ticks=12, seed=7, counterfactual=False)
        totals = run(config, folder, agent=FeelingAgent(MockMind(7), feelings))["run"]["totals"]
        self.assertEqual(totals["ticks"], 12)
        self.assertEqual(totals["invalid_replies"], 0)
        summary = summarize(feelings)
        self.assertEqual(summary["ticks"], 12)
        self.assertGreater(summary["points"]["none"], 0)
        self.assertEqual(summary["points"]["big"], 1)
        config = Config(ticks=15, seed=7, counterfactual=False)
        run(config, folder, agent=FeelingAgent(MockMind(7), feelings), resume=True)
        self.assertEqual(summarize(feelings)["ticks"], 15)

    def _mock_run(self, ticks=12):
        folder = Path(tempfile.mkdtemp(prefix="mind_"))
        run(Config(ticks=ticks, seed=7, counterfactual=False), folder, agent=FeelingAgent(MockMind(7), folder / "feelings.jsonl"))
        return folder

    def test_replay_rebuilds_the_prompts_the_run_really_used(self):
        folder = self._mock_run()
        report = replay(folder, MockMind(7))
        self.assertEqual(report["valid"]["rate"], 1.0)
        self.assertEqual(report["changed_action"]["hits"], 0)

    def test_replay_counts_broken_replies_and_changed_behaviour_separately(self):
        folder = self._mock_run()
        decisions = replay(folder, MockMind(7))["decisions"]
        self.assertGreater(decisions, 1)

        class Broken:
            calls = 0

            def decide(self, agent_input):
                Broken.calls += 1
                return "wait" if Broken.calls == 1 else '{"action": {"type": "speak", "text": "A changed reply."}}'

        report = replay(folder, Broken())
        self.assertEqual(report["valid"]["hits"], decisions - 1)
        self.assertEqual(report["changed_action"]["hits"], decisions - 1)
        self.assertEqual(report["trials"][0]["raw"], "wait")

    def test_compare_reports_where_two_runs_part_and_any_other_difference(self):
        base, same, other_seed = self._mock_run(), self._mock_run(), self._mock_run()
        report = compare(base, same)
        self.assertEqual(report["settings_that_differ"], [])
        self.assertIsNone(report["first_tick_acting_differently"])
        config = json.loads((other_seed / "config.json").read_text())
        (other_seed / "config.json").write_text(json.dumps({**config, "seed": 8}))
        self.assertEqual(compare(base, other_seed)["settings_that_differ"], ["seed"])

    def test_a_kill_between_checkpoints_leaves_one_record_per_tick(self):
        folder = Path(tempfile.mkdtemp(prefix="mind_"))
        feelings = folder / "feelings.jsonl"
        run(Config(ticks=6, seed=7, counterfactual=False), folder, agent=FeelingAgent(MockMind(7), feelings))
        with open(feelings, "a") as file:  # Tick 7 got partway, with no checkpoint, then the job was preempted.
            file.write(json.dumps({"kind": "appraisal", "tick": 7, "t": "2004-06-12T16:03:30", "raw": None, "feeling": "abandoned",
                                   "intensity": 0.2, "why": "", "visible": [], "point": None, "reason": None, "seconds": 0, "usage": None}) + "\n")
            file.write('{"kind": "choice", "tick": 7, "ac')
        run(Config(ticks=8, seed=7, counterfactual=False), folder, agent=FeelingAgent(MockMind(7), feelings), resume=True)
        ticks = [row["tick"] for row in read_rows(feelings) if row["kind"] == "appraisal"]
        self.assertEqual(ticks, list(range(1, 9)))
        self.assertNotIn("abandoned", feelings.read_text())


class WeightsTest(unittest.TestCase):
    def test_an_adapter_folder_is_refused_with_the_way_forward(self):
        folder = Path(tempfile.mkdtemp(prefix="mind_"))
        (folder / "adapters.safetensors").write_bytes(b"")
        with self.assertRaisesRegex(SystemExit, "fused"):
            check_weights(folder)

    @needs_runtime
    def test_a_tiny_fused_folder_loads_and_answers_through_the_measured_agent(self):
        from kokopelli.wm import llm_model
        from experiments.homeostatic.export import write_full_weights
        from kokopelli.settings import LLM_MODEL_WEIGHTS
        from experiments.homeostatic.tests.test_homeostatic_grpo import tiny_model

        folder = Path(tempfile.mkdtemp(prefix="mind_")) / "fused"
        original = llm_model.LLM_MODEL_WEIGHTS
        write_full_weights(tiny_model(), LLM_MODEL_WEIGHTS, folder)
        config = json.loads((folder / "config.json").read_text())
        config["skip_vision"] = True
        config["text_config"] |= {"hidden_size": 32, "num_hidden_layers": 2, "intermediate_size": 64, "num_attention_heads": 2,
                                  "num_key_value_heads": 2, "head_dim": 16, "max_position_embeddings": 2048}
        (folder / "config.json").write_text(json.dumps(config))
        agent = measured_qwen(str(folder))
        try:
            agent.release()
            reply = agent.decide(turn(1))
            self.assertIsInstance(reply, str)
            self.assertEqual(llm_model.LLM_MODEL_WEIGHTS, str(folder))
            self.assertGreater(agent.last_usage["prompt_tokens"], 0)
            self.assertEqual(agent.last_usage["images"], 0)
        finally:
            agent.release()
            llm_model.LLM_MODEL_WEIGHTS = original


if __name__ == "__main__":
    unittest.main()


class KnownEventTest(unittest.TestCase):
    """P5: with events on, a failed action or a change in view is felt even when the frame-only check says nothing
    changed (real Qwen said so on 19 of 19 ticks of qwen_change_20)."""

    def ticks(self, events):
        inner = Inner([CALM, {"feeling": "annoyed", "intensity": 0.5, "why": "It didn't work."}], change=NOTHING)
        agent = FeelingAgent(inner, Path(tempfile.mkdtemp(prefix="mind_")) / "feelings.jsonl", events=events)
        agent.decide(turn(1))
        agent.decide(Input(PROMPT.replace("Decide", "It didn't work. Decide"), [], ["bench", "ana"], "2004-06-12T16:02:00", 2))
        return agent._appraisal_rows()[-1], inner

    def test_off_by_default_the_event_is_not_felt(self):
        row, inner = self.ticks(None)
        self.assertTrue(row["carried"])
        self.assertEqual(row["feeling"], "calm")

    def test_on_the_event_is_appraised(self):
        row, inner = self.ticks(True)
        self.assertFalse(row["carried"])
        self.assertEqual(row["change_from"], "event")
        self.assertIn("Now in view: ana.", row["change"])
        self.assertIn("didn't work", row["change"])
        self.assertIn("What just changed: Now in view: ana.", inner.prompts[-2])
