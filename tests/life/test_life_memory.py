"""The real generator's memory, prompts and answers, with a stand-in for the model. Nothing here loads it."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from kokopelli.life.engine import Budget, Engine
from kokopelli.life.generator import MockGenerator
from kokopelli.life.llm_generator import BadAnswer, LLMGenerator, parse_closing, parse_opening
from kokopelli.life.memory import recall
from kokopelli.life.overnight import month_at, overnight_phases
from kokopelli.life.panel import make_server
from kokopelli.life.seed import LifeSeed
from kokopelli.life.store import Store
from kokopelli.life.windows import children, find, life_window
from kokopelli.settings import LIFE_LLM

BIRTH = date(1990, 3, 14)
SEED = LifeSeed("test", BIRTH, place="Atlanta", family=({"name": "Ana", "relationship": "mother"},), rng_seed=7, hidden_target="CANARY")
FIRST_MONTH = "month:1992-03-14T00:00:00"
FIRST_WEEK = "week:1992-03-14T00:00:00"
SECOND_WEEK = "week:1992-03-16T00:00:00"
OPENING = json.dumps({"salience": 0.1, "setting": "A quiet stretch.", "pressures": [{"text": "a cold", "odds": 0.5}], "open_questions": []})
CLOSING = json.dumps({"summary": "It passed quietly.", "what_happened": "Nothing much."})


def result(text):
    return SimpleNamespace(text=text, prompt_tokens=10, generation_tokens=5, generation_tps=50.0, peak_memory=1.0, finish_reason="stop")


class FakeModel:
    """Answers in the shape each prompt asks for, and keeps what it was sent."""

    def __init__(self):
        self.sent = []

    def __call__(self, system, user, max_tokens, temperature, seed):
        self.sent.append((system, user, seed))
        return result(OPENING if "Write the opening" in system else CLOSING)


class MemoryTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "life.db")
        self.run_id = self.store.create_run(SEED)
        self.model = FakeModel()
        seed, key = self.store.public_seed(self.run_id), self.store.rng_key(self.run_id)
        self.generator = LLMGenerator(seed, key, complete=self.model)
        self.engine = Engine(self.store, self.run_id, generator=self.generator, budget=Budget(seconds=60))

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()


class RecallTest(MemoryTestCase):
    def test_outline_runs_from_the_life_down_to_the_parent(self):
        self.engine.run(until="day:1992-03-14T00:00:00")
        memory = recall(self.store, self.run_id, find(SECOND_WEEK, BIRTH))
        self.assertEqual([item["level"] for item in memory["outline"]], ["life", "year", "season", "month"])

    def test_detail_fades_with_distance(self):
        self.engine.run(until="day:1992-03-24T00:00:00")
        memory = recall(self.store, self.run_id, find("day:1992-03-25T00:00:00", BIRTH))
        by_level = {item["level"]: item for item in memory["recent"]}
        self.assertIn("what_happened", by_level["day"])
        self.assertNotIn("what_happened", by_level["week"])

    def test_nothing_from_the_future_is_recalled(self):
        self.engine.run(until=FIRST_MONTH)
        memory = recall(self.store, self.run_id, find(FIRST_WEEK, BIRTH))
        self.assertEqual(memory["recent"], [])

    def test_big_moments_stick_only_from_ages_that_could_form_them(self):
        class Loud(FakeModel):
            def __call__(self, system, user, max_tokens, temperature, seed):
                text = json.dumps({"salience": 1.0, "setting": "x", "pressures": [], "open_questions": []})
                return result(text if "Write the opening" in system else CLOSING)
        generator = LLMGenerator(self.store.public_seed(self.run_id), "k", complete=Loud())
        target = month_at(BIRTH, 8)
        Engine(self.store, self.run_id, generator=generator, budget=Budget(seconds=60), deepest="month").run(until=target.id)
        vivid = recall(self.store, self.run_id, find(month_at(BIRTH, 8).id, BIRTH))["vivid"]
        # A toddler's memory_strength is 0.2, which keeps even the biggest moment under the floor.
        self.assertTrue(vivid)
        self.assertGreater(min(item["start_t"] for item in vivid), "1994-03-14")


class PromptTest(MemoryTestCase):
    def test_every_prompt_has_a_system_and_never_the_target(self):
        self.engine.run(until=FIRST_WEEK)
        self.assertGreater(len(self.model.sent), 10)
        for system, user, _ in self.model.sent:
            self.assertIn("Never say what the person", system)
            self.assertNotIn("CANARY", system + user)

    def test_a_closing_is_told_how_its_pressures_went(self):
        self.engine.run(until="day:1992-03-14T00:00:00")
        closing = next(user for system, user, _ in self.model.sent if "Write the closing" in system)
        self.assertIn("a cold:", closing)

    def test_a_parent_closing_sees_its_children(self):
        self.engine.run(until=FIRST_WEEK)
        week_closing = [user for system, user, _ in self.model.sent if "Write the closing" in system][-1]
        self.assertIn("EARLIER IN THIS STRETCH", week_closing)

    def test_placeholder_people_stay_out_of_prompts(self):
        self.store.append_event(self.run_id, None, "1992-03-14T00:00:00", "person_met", {"name": "Person 1234", "relationship": "acquaintance"})
        self.engine.step()
        self.assertNotIn("Person 1234", self.model.sent[-1][1])
        self.assertIn("Ana", self.model.sent[-1][1])


class FocusTest(MemoryTestCase):
    def test_periods_get_a_focus_that_stays_put_on_replay(self):
        self.engine.run(until=FIRST_WEEK)
        users = [user for system, user, _ in self.model.sent if "Write the opening" in system]
        self.assertTrue(any("TURNS TOWARD" in user for user in users))
        self.assertNotIn("TURNS TOWARD", users[0])


class AnswerTest(MemoryTestCase):
    def test_ids_come_from_the_code(self):
        _, opening = parse_opening(json.dumps({"salience": 0.5, "setting": "x", "open_questions": [],
                                               "pressures": [{"id": "same", "text": "a", "odds": 0.1}, {"id": "same", "text": "b", "odds": 0.2}]}))
        self.assertEqual([pressure["id"] for pressure in opening["pressures"]], ["p0", "p1"])

    def test_text_around_the_json_is_ignored(self):
        self.assertEqual(parse_closing('Sure!\n```json\n' + CLOSING + '\n```')["summary"], "It passed quietly.")

    def test_bad_answers_are_refused(self):
        for raw in ("no json", '{"salience": 2, "setting": "x"}', '{"salience": 0.5, "setting": ""}', '{"salience": "high", "setting": "x"}'):
            with self.subTest(raw), self.assertRaises(BadAnswer):
                parse_opening(raw)

    def test_a_retry_gets_a_fresh_sample_and_can_succeed(self):
        seeds, answers = [], ["garbage", OPENING]

        def flaky(system, user, max_tokens, temperature, seed):
            seeds.append(seed)
            return result(answers.pop(0))
        generator = LLMGenerator(self.store.public_seed(self.run_id), "k", complete=flaky)
        Engine(self.store, self.run_id, generator=generator).step()
        self.assertEqual(len(seeds), 2)
        self.assertNotEqual(*seeds)
        self.assertEqual(self.store.node(self.run_id, life_window(BIRTH).id)["opening"]["setting"], "A quiet stretch.")

    def test_a_node_that_never_parses_is_marked_and_the_run_goes_on(self):
        calls = []

        def hopeless(system, user, max_tokens, temperature, seed):
            calls.append(seed)
            return result("garbage")
        generator = LLMGenerator(self.store.public_seed(self.run_id), "k", complete=hopeless)
        engine = Engine(self.store, self.run_id, generator=generator)
        engine.step()
        engine.step()
        self.assertEqual(len(calls), 2 * LIFE_LLM["attempts"])
        self.assertIn("[failed]", self.store.node(self.run_id, life_window(BIRTH).id)["opening"]["setting"])

    def test_the_same_try_at_the_same_node_gets_the_same_sample(self):
        self.engine.step()
        with tempfile.TemporaryDirectory() as temp:
            other = Store(Path(temp) / "life.db")
            run_id = other.create_run(SEED)
            model = FakeModel()
            Engine(other, run_id, generator=LLMGenerator(other.public_seed(run_id), other.rng_key(run_id), complete=model)).step()
            other.close()
        self.assertEqual(model.sent[0][2], self.model.sent[0][2])


class DeepestTest(MemoryTestCase):
    def test_a_skim_stops_at_the_month_even_when_salient(self):
        class Loud(FakeModel):
            def __call__(self, system, user, max_tokens, temperature, seed):
                text = json.dumps({"salience": 1.0, "setting": "x", "pressures": [], "open_questions": []})
                return result(text if "Write the opening" in system else CLOSING)
        generator = LLMGenerator(self.store.public_seed(self.run_id), "k", complete=Loud())
        Engine(self.store, self.run_id, generator=generator, deepest="month").run(until=FIRST_MONTH)
        self.assertEqual(self.store.child_nodes(self.run_id, FIRST_MONTH), [])
        self.assertIsNotNone(self.store.node(self.run_id, FIRST_MONTH)["closing"])

    def test_a_fork_from_a_skim_can_go_deeper(self):
        skim = Engine(self.store, self.run_id, generator=self.generator, deepest="month")
        skim.run(until="month:1992-04-01T00:00:00")
        fork = self.store.fork(self.run_id, FIRST_MONTH)
        generator = LLMGenerator(self.store.public_seed(fork), self.store.rng_key(fork), complete=self.model)
        Engine(self.store, fork, generator=generator).run(until=FIRST_WEEK)
        self.assertEqual(self.store.child_nodes(self.run_id, FIRST_MONTH), [])
        self.assertGreater(len(self.store.child_nodes(fork, FIRST_MONTH)), 0)

    def test_month_at_finds_the_month_holding_a_birthday(self):
        self.assertEqual(month_at(BIRTH, 2).id, FIRST_MONTH)
        self.assertEqual(month_at(BIRTH, 15).level, "month")

    def test_an_anchor_slice_reaches_the_finest_level(self):
        seed = LifeSeed("t", BIRTH, anchors=({"at": "1992-03-14T00:10:45", "text": "a storm"},))
        run_id = self.store.create_run(seed)
        generator = LLMGenerator(self.store.public_seed(run_id), "k", complete=self.model)
        Engine(self.store, run_id, generator=generator, budget=Budget(seconds=60)).run(until="min1:1992-03-14T00:10:00")
        self.assertIsNotNone(self.store.node(run_id, "sec30:1992-03-14T00:10:30"))

    def test_every_phase_of_the_overnight_plan_shares_the_whole_night(self):
        self.assertAlmostEqual(sum(phase["share"] for phase in overnight_phases()), 1)

    def test_a_grandparent_is_remembered_as_a_gist(self):
        self.engine.run(until="day:1992-03-14T00:00:00")
        self.store.conn.execute("DROP TRIGGER openings_no_UPDATE")
        self.store.conn.execute("UPDATE openings SET opening = json_set(opening, '$.setting', 'First part. Second part.')")
        self.assertEqual(recall(self.store, self.run_id, find(FIRST_WEEK, BIRTH))["outline"][-1]["setting"], "First part.")

    def test_mock_nodes_get_no_memory(self):
        self.assertFalse(MockGenerator.uses_memory)


class ConcurrencyTest(MemoryTestCase):
    def test_another_connection_can_open_and_read_while_a_write_is_held(self):
        # A model call happens inside a step's transaction, and the panel must not stall on it.
        self.engine.step()
        with self.store.atomic():
            self.store.append_event(self.run_id, None, "1992-03-14T00:00:00", "moved", {"place": "x"})
            reader = Store(Path(self.temp.name) / "life.db")
            reader.conn.execute("PRAGMA busy_timeout = 0")
            self.assertEqual(reader.counts(self.run_id)["opened"], 1)
            reader.close()


class WatchTest(unittest.TestCase):
    def test_a_watching_panel_refuses_every_write(self):
        import threading
        import urllib.error
        import urllib.request
        with tempfile.TemporaryDirectory() as temp:
            server = make_server(Path(temp) / "life.db", port=0, watching=True)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{server.server_port}"
            for path in ("/api/runs", "/api/run", "/api/step", "/api/fork"):
                with self.subTest(path), self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(urllib.request.Request(base + path, b"{}", method="POST"))
                self.assertEqual(caught.exception.code, 403)
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
