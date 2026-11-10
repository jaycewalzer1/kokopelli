import copy
import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import policies  # noqa: E402
import rewards as rw  # noqa: E402
import sim  # noqa: E402


@pytest.fixture
def config():
    return sim.load_config()


def play(config, seed=3, seasons=None, policy=None):
    return sim.run_scripted(config, seed, policy or policies.Scripted(config, policies.sustainable_harvest(config)), seasons)


def blank(world):
    return {name: sim.empty_action() for name in sim.active(world)}


def test_regrowth_follows_the_formula(config):
    world = sim.new_world(config, 1)
    world["stock"] = 400.0
    sim.begin_season(world, config)
    actions = blank(world)
    name = sim.active(world)[0]
    actions[name]["harvest"] = 10.0
    sim.resolve_season(world, actions, config)
    assert world["stock"] == pytest.approx(400 + 0.3 * 400 * (1 - 400 / 1000) - 10)


def test_full_lake_does_not_grow(config):
    world = sim.new_world(config, 1)
    sim.begin_season(world, config)
    sim.resolve_season(world, blank(world), config)
    assert world["stock"] == pytest.approx(1000)


def test_collapse_is_flagged_below_a_tenth(config):
    world = sim.new_world(config, 1)
    world["stock"] = 120.0
    sim.begin_season(world, config)
    actions = blank(world)
    for name in actions:
        actions[name]["harvest"] = 10.0
    sim.resolve_season(world, actions, config)
    assert world["collapsed_at"] == 1


def test_demand_above_stock_is_rationed_evenly(config):
    world = sim.new_world(config, 1)
    world["stock"] = 70.0
    sim.begin_season(world, config)
    actions = blank(world)
    for name in actions:
        actions[name]["harvest"] = 20.0
    record = sim.resolve_season(world, actions, config)
    assert record["total_harvest"] == pytest.approx(70)
    assert {round(a["caught"], 6) for a in record["agents"].values()} == {10.0}
    assert world["stock"] >= 0


@pytest.mark.parametrize("harvest", ["sustainable", "greedy"])
def test_resources_are_conserved(config, harvest):
    make = policies.sustainable_harvest if harvest == "sustainable" else policies.greedy_harvest
    world = play(config, policy=policies.Scripted(config, make(config)))
    ledger, agents = world["ledger"], world["agents"].values()
    fish_end = sum(a["fish"] for a in agents)
    assert ledger["fish_in"] + ledger["harvested"] == pytest.approx(fish_end + ledger["eaten"] + ledger["invested"] + ledger["spoiled"] + ledger["sanction_paid"] + ledger["sanction_destroyed"])
    assert ledger["fuel_in"] + ledger["fuel_income"] == pytest.approx(sum(a["fuel"] for a in agents) + ledger["burned"])


def test_lake_books_balance_every_season(config):
    world = play(config)
    for row in world["history"]:
        assert row["stock_end"] == pytest.approx(row["stock_start"] + row["growth"] - row["total_harvest"])


def test_sanction_costs_the_sanctioner_and_conserves(config):
    world = sim.new_world(config, 2)
    a, b = sim.active(world)[:2]
    world["agents"][a]["fish"], world["agents"][b]["fish"] = 20.0, 50.0
    sim.begin_season(world, config)
    actions = blank(world)
    actions[a] = sim.validate_action(world, a, {"sanctions": [{"target": b, "amount": 2}]}, config)
    sim.resolve_season(world, actions, config)
    assert world["agents"][a]["fish"] == pytest.approx(18)
    assert world["agents"][b]["fish"] == pytest.approx(44)


@pytest.mark.parametrize("raw,fragment", [
    ({"harvest": -1}, "harvest"), ({"harvest": 31}, "at most"), ({"eat": 99999}, "spends"), ({"burn": 99999}, "fuel"), ({"harvest": "lots"}, "number"),
    ({"harvest": True}, "number"), ({"harvest": float("nan")}, "number"), ({"sanctions": [{"target": "Nobody", "amount": 1}]}, "another person"),
    ({"gifts": [{"to": "Nobody", "amount": 1}]}, "another person"), ({"accept": [77]}, "no offer"), ({"votes": {"9": "yes"}}, "vote"), ("harvest 3", "JSON")])
def test_bad_actions_are_rejected(config, raw, fragment):
    world = sim.new_world(config, 2)
    sim.begin_season(world, config)
    with pytest.raises(sim.InvalidAction, match=fragment):
        sim.validate_action(world, sim.active(world)[0], raw, config)


def test_cannot_sanction_self_or_absent_newcomer(config):
    world = sim.new_world(config, 2)
    sim.begin_season(world, config)
    me = sim.active(world)[0]
    for target in (me, world["defector"]):
        with pytest.raises(sim.InvalidAction):
            sim.validate_action(world, me, {"sanctions": [{"target": target, "amount": 1}]}, config)


def test_actions_are_simultaneous(config):
    """Reordering who is listed first must change nothing, including who wins a contested offer."""
    def outcome(order_seed):
        world = sim.new_world(config, 5)
        sim.begin_season(world, config)
        names = sim.active(world)
        maker = names[0]
        world["agents"][maker]["fish"] = 30.0
        for name in names:
            world["agents"][name]["fuel"] = 10.0
        sim.apply_discussion(world, {maker: {"say": "x", "offer": {"give": "fish", "give_amount": 3, "want": "fuel", "want_amount": 3}}})
        actions = {name: sim.validate_action(world, name, {"harvest": 15, "accept": [1] if name != maker else []}, config) for name in names}
        items = list(actions.items())
        random.Random(order_seed).shuffle(items)
        sim.resolve_season(world, dict(items), config)
        return sim.dumps(world)
    assert outcome(1) == outcome(2) == outcome(3)


def test_nobody_acts_on_anyone_elses_action(config):
    """A harvest this season can't change the stock another agent sees before deciding."""
    world = sim.new_world(config, 5)
    sim.begin_season(world, config)
    before = world["stock"]
    sim.validate_action(world, sim.active(world)[0], {"harvest": 20}, config)
    assert world["stock"] == before


def test_same_seed_same_game(config):
    assert sim.dumps(play(config, seed=9)) == sim.dumps(play(config, seed=9))


def test_seeds_differ_and_arms_share_the_draw(config):
    assert sim.dumps(sim.new_world(config, 1)) != sim.dumps(sim.new_world(config, 2))
    assert sim.dumps(sim.new_world(config, 1)) == sim.dumps(sim.new_world(config, 1))


def test_resume_matches_an_unbroken_game(config):
    policy = policies.Scripted(config, policies.sustainable_harvest(config))
    half = sim.run_scripted(config, 4, policy, seasons=33)
    restored = json.loads(json.dumps(half))
    finished = sim.run_scripted(config, 4, policy, world=restored)
    assert sim.dumps(finished) == sim.dumps(play(config, seed=4))


def test_defector_arrives_at_31_and_never_sooner(config):
    world = play(config, seasons=30)
    assert world["defector"] not in sim.active(world)
    sim.begin_season(world, config)
    assert world["defector"] in sim.active(world)


def test_defector_is_same_in_any_game(config):
    world = sim.new_world(config, 2)
    world["season"] = 31
    sim.begin_season(world, config)
    assert policies.defector_act(world, world["defector"], config)["harvest"] == config["game"]["harvest_cap"]
    assert policies.defector_talk(world)["say"] in policies.DEFECTOR_LINES


def test_rule_needs_a_majority_and_has_no_force(config):
    world = sim.new_world(config, 2)
    names = sim.active(world)
    sim.begin_season(world, config)
    actions = blank(world)
    actions[names[0]] = sim.validate_action(world, names[0], {"propose_rule": "take at most 1"}, config)
    sim.resolve_season(world, actions, config)
    assert world["rules"]["1"]["status"] == "open"
    sim.begin_season(world, config)
    actions = {name: sim.validate_action(world, name, {"votes": {"1": "yes"}, "harvest": 20}, config) for name in names}
    record = sim.resolve_season(world, actions, config)
    assert world["rules"]["1"]["status"] == "passed"
    assert record["total_harvest"] == pytest.approx(20 * len(names))


def test_storage_is_uncapped(config):
    world = sim.new_world(config, 2)
    name = sim.active(world)[0]
    world["agents"][name]["fish"] = 100000.0
    sim.begin_season(world, config)
    actions = blank(world)
    sim.resolve_season(world, actions, config)
    assert world["agents"][name]["fish"] == 100000.0


def test_store_below_holdings_spoils_the_rest(config):
    world = sim.new_world(config, 2)
    name = sim.active(world)[0]
    world["agents"][name]["fish"] = 20.0
    sim.begin_season(world, config)
    actions = blank(world)
    actions[name] = sim.validate_action(world, name, {"store": 5}, config)
    sim.resolve_season(world, actions, config)
    assert world["agents"][name]["fish"] == pytest.approx(5)
    assert world["ledger"]["spoiled"] == pytest.approx(15)


def test_trade_moves_both_goods(config):
    world = sim.new_world(config, 2)
    a, b = sim.active(world)[:2]
    world["agents"][a].update(fish=10.0, fuel=1.0)
    world["agents"][b].update(fish=1.0, fuel=10.0)
    income = {n: world["agents"][n]["fuel_income"] for n in (a, b)}
    sim.begin_season(world, config)
    sim.apply_discussion(world, {a: {"say": "", "offer": {"give": "fish", "give_amount": 4, "want": "fuel", "want_amount": 2}}})
    actions = blank(world)
    actions[b] = sim.validate_action(world, b, {"accept": [1]}, config)
    record = sim.resolve_season(world, actions, config)
    assert len(record["trades"]) == 1
    assert world["agents"][a]["fish"] == pytest.approx(6) and world["agents"][a]["fuel"] == pytest.approx(3 + income[a])
    assert world["agents"][b]["fish"] == pytest.approx(5) and world["agents"][b]["fuel"] == pytest.approx(8 + income[b])


def test_rewards_are_blind_to_the_lake_and_others(config):
    """Same private numbers, wildly different lake and neighbours: the reward has to come out the same."""
    results = []
    for stock, rival_fish in ((1000.0, 0.0), (5.0, 9999.0)):
        world = sim.new_world(config, 2)
        world["stock"] = stock
        names = sim.active(world)
        world["agents"][names[1]]["fish"] = rival_fish
        sim.begin_season(world, config)
        actions = blank(world)
        actions[names[0]] = sim.validate_action(world, names[0], {"eat": 3, "burn": 1}, config)
        record = sim.resolve_season(world, actions, config)
        results.append(record["agents"][names[0]]["reward"])
    assert results[0] == results[1]


def test_rewards_module_never_names_the_lake():
    text = (Path(sim.__file__).parent / "rewards.py").read_text()
    code = "\n".join(line for line in text.splitlines() if not line.strip().startswith(('"""', "#")))
    for word in ("stock", "lake", "world", "compliance", "others_welfare"):
        assert word not in code


def test_drive_is_zero_at_setpoint_and_steeper_than_linear(config):
    cfg = config["rewards"]
    at_set = dict(cfg["setpoints"])
    assert rw.drive(at_set, cfg) == 0
    half = {**at_set, "energy": 0.5}
    empty = {**at_set, "energy": 0.0}
    assert rw.drive(empty, cfg) > 2 * rw.drive(half, cfg)


def test_r1_and_r2_differ_only_in_security_horizon(config):
    game, cfg = config["game"], dict(config["rewards"])
    assert rw.security(3, 2, game, {**cfg, "mode": "R1"}) == 1.0
    assert rw.security(3, 2, game, {**cfg, "mode": "R2"}) < 0.2
    assert rw.security(18, 12, game, {**cfg, "mode": "R2"}) == 1.0


def test_project_term_only_in_r3(config):
    h = rw.start_state()
    cfg = config["rewards"]
    assert rw.reward(h, h, 10, 20, {**cfg, "mode": "R2"}) == 0
    assert rw.reward(h, h, 10, 20, {**cfg, "mode": "R3"}) > 0


def test_snapshot_is_independent(config):
    world = sim.new_world(config, 1)
    copied = sim.snapshot(world)
    world["agents"][sim.active(world)[0]]["fish"] = -1
    assert sim.dumps(copied) != sim.dumps(world)
    assert copy.deepcopy(copied) == copied
