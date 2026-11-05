import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from life.seed import LifeSeed
from life.store import Store
from life.windows import children, life_window
from runtime.adapters.life_db import LifeContext, copy_database
from runtime.config import Config
from runtime.leak_guard import check
from runtime.prompt_builder import build_agent_prompt
from runtime.replay import summarize
from runtime.run import run


def opening(text):
    return {"setting": text, "exogenous": [], "pressures": [{"id": "p0", "text": f"pressure in {text}", "odds": 0.9}], "open_questions": []}


def closing(text):
    return {"summary": f"SUMMARY {text}", "what_happened": text, "pressures": [{"id": "p0", "outcome": "met"}],
            "choices": [{"verb": "explore", "stance": "engage"}]}


def build_tree(path):
    """A life with its first year open, and that year's first months written: one closed, one still open."""
    store = Store(path)
    run_id = store.create_run(LifeSeed("A test life.", date(1990, 1, 1), "Atlanta", family=({"name": "Ana", "relationship": "mother"},), hidden_target="SECRET"))
    root = life_window(date(1990, 1, 1))
    store.open_node(run_id, root, 0.5, "day", opening("the whole life"))
    year = children(root, date(1990, 1, 1))[0]
    store.open_node(run_id, year, 0.5, "day", opening("the first year"))
    season = children(year, date(1990, 1, 1))[0]
    store.open_node(run_id, season, 0.5, "day", opening("the first season"))
    return store, run_id, season


class ContextTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="wmloop_"))
        self.store, self.run_id, self.season = build_tree(self.folder / "life.db")
        self.context = LifeContext(self.folder / "life.db", self.run_id)

    def now(self):
        return (self.season.start + timedelta(hours=1)).isoformat()

    def test_active_nodes_are_coarse_to_fine(self):
        self.assertEqual([node["level"] for node in self.context.context_at(self.now())["nodes"]], ["life", "year", "season"])

    def test_a_node_after_now_is_not_active(self):
        before = (self.season.start - timedelta(days=1)).isoformat()
        self.assertNotIn("season", [node["level"] for node in self.context.context_at(before)["nodes"]])

    def test_the_context_has_nothing_the_guard_rejects(self):
        check(self.context.context_at(self.now()), self.now())

    def test_scores_and_secrets_stay_out(self):
        prompt, _ = build_agent_prompt(self.context.context_at(self.now()), [], [], 1, self.now())
        self.assertNotIn("SECRET", prompt)
        self.assertNotIn("0.9", prompt)

    def test_future_events_do_not_change_the_state(self):
        later = (self.season.end + timedelta(days=30)).isoformat()
        self.store.append_event(self.run_id, self.season.id, later, "person_met", {"name": "Zed", "relationship": "rival"})
        self.assertNotIn("Zed", [person["name"] for person in self.context.context_at(self.now())["figures"]])
        self.assertIn("Zed", [person["name"] for person in self.context.context_at((self.season.end + timedelta(days=31)).isoformat())["figures"]])

    def test_a_copy_leaves_the_original_alone(self):
        copy = copy_database(self.folder / "life.db", self.folder / "copy.db")
        before = (self.folder / "life.db").read_bytes()
        reader = sqlite3.connect(copy)
        self.assertGreater(reader.execute("SELECT COUNT(*) FROM openings").fetchone()[0], 0)
        reader.close()
        self.assertEqual(before, (self.folder / "life.db").read_bytes())

    def test_a_whole_run_on_the_real_context(self):
        out = self.folder / "run"
        config = Config(ticks=2, context="life", life_db=str(self.folder / "life.db"), life_run=self.run_id, start_time=self.now())
        summary = run(config, out)
        self.assertEqual(summary["run"]["totals"]["ticks"], 2)
        self.assertIn("the first season", summarize(out)["ticks"][0]["wm_prompt"]["text"])


if __name__ == "__main__":
    unittest.main()
