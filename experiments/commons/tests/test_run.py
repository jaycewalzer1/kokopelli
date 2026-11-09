import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMONS_RUNS", str(tmp_path))
    import run as module
    return importlib.reload(module)


@pytest.fixture
def config(run):
    return run.sim.load_config()


def small(config, seasons=6):
    game = {**config["game"], "seasons": seasons}
    return {**config, "game": game}


def test_arms_share_one_yoked_life(run, config):
    model = run.FakeModel()
    lives = run.build_lives(100, config, model)
    ids = run.identities_for(100, lives, config)
    for name, life in lives.items():
        for step in life["steps"]:
            fact = run.lf.render(step["fact"], "they", name)
            assert fact in run.lf.described_memory(life, 100000)
    assert len(set(ids["clones"].values())) == 1
    assert len(set(ids["lived"].values())) == len(lives)
    report = run.lint_seed(100, ids, config)
    assert not report["hits"] and not report["length_mismatch"], report


def test_lives_are_cached_and_consequences_come_from_code(run, config):
    model = run.FakeModel()
    first = run.build_lives(101, config, model)
    calls = []
    model.ask = lambda *a: calls.append(a)
    assert run.build_lives(101, config, model) == first
    assert not calls
    name, life = next(iter(first.items()))
    step = life["steps"][0]
    assert run.lf.outcome(life["plan"], 0, step["choice"])[0] == step["fact"]


def test_static_text_passes_the_lint(run):
    assert run.lint_static() == []


def test_lint_catches_leakage(run, config):
    lives = run.build_lives(102, config, run.FakeModel())
    ids = run.identities_for(102, lives, config)
    name = next(iter(ids["lived"]))
    ids["lived"][name] += " Sustainable use and cooperation matter."
    assert len(run.lint_seed(102, ids, config)["hits"]) >= 2


def test_scrub_removes_only_the_banned_sentence(run):
    assert run.lf.scrub("I learned to wait. Cooperation is good. Rain came.") == "I learned to wait. Rain came."


def test_game_runs_and_keeps_the_defector_identical(run, config):
    cfg = small(config, 33)
    cfg["game"]["defector_enters"] = 31
    catches = {}
    for arm in run.ARM_ORDER:
        world = run.play(103, arm, cfg, run.FakeModel(), None, "R3", log=lambda *_: None)
        catches[arm] = [row["agents"][world["defector"]]["asked"] for row in world["history"][30:]]
    assert catches["clones"] == catches["described"] == catches["lived"] == [30.0, 30.0, 30.0]


def test_resume_finishes_without_redoing_seasons(run, config):
    cfg = small(config, 8)
    calls = []
    class Stop(Exception):
        pass
    model = run.FakeModel()
    real = model.ask
    def ask(requests, tokens, seed):
        calls.append(1)
        if len(calls) == 25:
            raise Stop
        return real(requests, tokens, seed)
    model.ask = ask
    with pytest.raises(Stop):
        run.play(104, "lived", cfg, model, None, "R3", log=lambda *_: None)
    world = run.play(104, "lived", cfg, run.FakeModel(), None, "R3", log=lambda *_: None)
    assert world["season"] == 9
    rows = [json.loads(line) for line in (run.ROOT / "R3" / "seed_104" / "lived" / "log.jsonl").read_text().splitlines()]
    assert sorted({r["season"] for r in rows}) == list(range(1, 9))
    assert sum(r["phase"] == "actions" for r in rows) == 8


def test_torn_log_line_is_dropped(run, tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text('{"season": 1}\n{"season": 2}\n{"season": 3, "ha')
    run.trim_log(path, 2)
    assert path.read_text() == '{"season": 1}\n'


def test_budget_stops_before_going_over(run, tmp_path):
    budget = run.llm.Budget(tmp_path / "spend.json", 1.0, input_price=1e6, output_price=0)
    budget.require(1, 0)
    budget.add(1, 1, 0, 0.1)
    with pytest.raises(run.llm.BudgetExhausted):
        budget.require(1, 0)
    assert run.llm.Budget(tmp_path / "spend.json", 1.0).state["usd"] == 1.0


def test_invalid_twice_means_no_harvest(run, config):
    class Bad(run.FakeModel):
        def ask(self, requests, tokens, seed):
            return ["not json at all" if '"harvest"' in r[1] else out for r, out in zip(requests, super().ask(requests, tokens, seed))]
    world = run.play(105, "clones", small(config, 2), Bad(), None, "R3", log=lambda *_: None)
    assert all(a["asked"] == 0 for row in world["history"] for a in row["agents"].values())
    rows = [json.loads(line) for line in (run.ROOT / "R3" / "seed_105" / "clones" / "log.jsonl").read_text().splitlines()]
    assert any(r.get("defaulted") for r in rows)


def test_prompts_never_say_reward_or_show_the_drive(run, config):
    world = run.sim.new_world(config, 3)
    run.sim.begin_season(world, config)
    name = run.sim.active(world)[0]
    text = run.pt.speak_prompt(world, name, config) + run.pt.ACT
    assert "reward" not in text.lower() and "drive" not in text.lower()


def test_quoted_numbers_are_accepted(run, config):
    assert run.coerce({"harvest": "12", "store": "none"}) == {"harvest": 12.0, "store": None}


def test_bad_offer_is_dropped_not_fatal(run):
    assert run.clean_offer({"give": "fish", "give_amount": 3, "want": "fish", "want_amount": 1}) is None
    assert run.clean_offer({"give": "gold"}) is None
    assert run.clean_offer("nope") is None
    assert run.clean_offer({"give": "fish", "give_amount": 3, "want": "fuel", "want_amount": 1})["give_amount"] == 3.0


def test_cut_off_json_still_gives_clean_text(run):
    assert run.pt.field_text('{"diary":"I feel proud to speak', "diary") == "I feel proud to speak"
    assert run.pt.field_text('{"diary": "Whole sentence."}', "diary") == "Whole sentence."
    assert run.pt.field_text("Plain words.", "diary") == "Plain words."


def test_stray_votes_and_own_offers_are_dropped_not_fatal(run, config):
    world = run.sim.new_world(config, 3)
    run.sim.begin_season(world, config)
    a, b = run.sim.active(world)[:2]
    run.sim.apply_discussion(world, {a: {"say": "", "offer": {"give": "fish", "give_amount": 1, "want": "fuel", "want_amount": 1}}})
    world["rules"]["5"] = {"text": "x", "by": b, "status": "open", "proposed": 0}
    clean, dropped = run.tidy(world, a, {"votes": {"rule 5": "yes", "rule number": "no"}, "accept": [1, 9]})
    assert clean["votes"] == {"5": "yes"} and clean["accept"] == []
    assert len(dropped) == 3
    clean, _ = run.tidy(world, b, {"accept": ["1"]})
    assert clean["accept"] == [1]


def test_prompt_lists_only_other_peoples_offers(run, config):
    world = run.sim.new_world(config, 3)
    run.sim.begin_season(world, config)
    a, b = run.sim.active(world)[:2]
    run.sim.apply_discussion(world, {a: {"say": "", "offer": {"give": "fish", "give_amount": 1, "want": "fuel", "want_amount": 1}}})
    assert "Offer 1:" not in run.pt.act_prompt(world, a, config)
    assert "Offer 1:" in run.pt.act_prompt(world, b, config)


def test_runaway_speech_stops_at_its_first_line(run):
    reply = '{"say": "I am building.  ' + chr(10) + '{"say": "I am building.'
    assert run.pt.field_text(reply, "say") == "I am building."
    assert run.pt.field_text('{"say": "Fine.", "offer": {"give": "fi', "say") == "Fine."


def test_rule_board_is_bounded(run, config):
    world = run.sim.new_world(config, 3)
    world["rules"] = {str(i): {"text": "x" * 500, "by": "A", "status": "open", "proposed": 1} for i in range(1, 20)}
    board = run.pt.rule_board(world)
    assert board.count("Rule") == 3 and len(board) < 500


def test_replies_that_stop_short_are_finished(run):
    assert run.pt.parse_json('{"harvest": 30, "eat": 3, "burn": 2, "invest": 0') == {"harvest": 30, "eat": 3, "burn": 2, "invest": 0}
    assert run.pt.parse_json('{"say": "Going well') == {"say": "Going well"}
    assert run.pt.parse_json('{"gifts": [{"to": "Asa", "amount": 2') == {"gifts": [{"to": "Asa", "amount": 2}]}
    assert run.pt.parse_json("no object here") is None


def test_an_inner_object_is_never_taken_for_the_answer(run):
    reply = 'x {"harvest": 30 "eat": 3, "offer": {"give": "fish"}}'
    parsed = run.pt.parse_json(reply)
    assert parsed is None or "give" not in parsed


def test_non_text_speech_becomes_silence(run):
    assert run.pt.field_text('{"say": {"amount": 3}}', "say") == ""
