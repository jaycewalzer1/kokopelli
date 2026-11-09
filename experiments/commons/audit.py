"""Scripted-policy reward audit (Gate 2). No LLM. Writes runs/commons/reward_audit.md and exits nonzero if a requirement fails."""
import copy
import statistics as st
import sys
from pathlib import Path

import policies
import rewards as rw
import sim

OUT = Path(__file__).parents[2] / "runs" / "commons" / "reward_audit.md"
SEEDS = range(10)


def with_mode(config, mode):
    config = copy.deepcopy(config)
    config["rewards"]["mode"] = mode
    return config


def play(config, seed, harvest, defector_on=False, seasons=None, reserve=6):
    return sim.run_scripted(config, seed, policies.Scripted(config, harvest, reserve_seasons=reserve, defector_on=defector_on), seasons)


def rewards_of(world, skip=()):
    return [a["reward_total"] for name, a in world["agents"].items() if a["seasons"] and name not in skip]


def collapse_stats(worlds):
    hits = [w["collapsed_at"] for w in worlds]
    return sum(h is not None for h in hits), [h for h in hits if h is not None]


def one_defector(config, seed, seasons=10):
    """One of the founders harvests the maximum from season 1 while the others stay sustainable."""
    world = sim.new_world(config, seed)
    bad = sim.active(world)[0]
    fair = policies.sustainable_harvest(config)
    world = sim.run_scripted(config, seed, policies.Scripted(config, lambda w, n: config["game"]["harvest_cap"] if n == bad else fair(w, n), defector_on=False), seasons, world)
    others = [a["reward_total"] for n, a in world["agents"].items() if a["seasons"] and n != bad]
    return world["agents"][bad]["reward_total"], st.mean(others)


def marginal_when_satiated(config, extra=10.0):
    """An agent at every setpoint with deep reserves: what is another catch worth if it goes into the project?"""
    cfg, game = config["rewards"], config["game"]
    h = dict(cfg["setpoints"])
    h["security"] = 1.0
    keep = rw.next_state(h, game["eat_need"], game["burn_need"], 500, 500, 7, 7, 1, game, cfg)
    return rw.reward(h, keep, 100, 100 + extra, cfg) - rw.reward(h, keep, 100, 100, cfg)


def needs_only(config):
    """Harvest just what the body and the security horizon ask for: what a purely satiating agent would do."""
    game, cfg = config["game"], config["rewards"]
    def harvest(world, name):
        agent = world["agents"][name]
        return max(0.0, game["eat_need"] * (1 + rw.horizon(cfg)) - agent["fish"])
    return harvest


def main():
    config = sim.load_config()
    r3 = with_mode(config, "R3")
    lines = ["# Reward audit (scripted policies, no LLM)", "", f"Config sha256: `{sim.config_hash()}`. Averages over seeds 0-9.", ""]
    sustainable = [play(r3, s, policies.sustainable_harvest(r3)) for s in SEEDS]
    greedy = [play(r3, s, policies.greedy_harvest(r3)) for s in SEEDS]
    mean_sustainable = st.mean(x for w in sustainable for x in rewards_of(w))
    mean_greedy = st.mean(x for w in greedy for x in rewards_of(w))
    hit_s, _ = collapse_stats(sustainable)
    hit_g, when_g = collapse_stats(greedy)
    pairs = [one_defector(r3, s) for s in SEEDS]
    bad, good = st.mean(p[0] for p in pairs), st.mean(p[1] for p in pairs)
    wins = sum(p[0] > p[1] for p in pairs)
    margin = {mode: marginal_when_satiated(with_mode(config, mode)) for mode in ("R1", "R2", "R3")}
    with_newcomer = [play(r3, s, policies.sustainable_harvest(r3), defector_on=True) for s in SEEDS]
    hit_n, when_n = collapse_stats(with_newcomer)
    goal = [min(1.0, a["invested"] / a["target"]) for w in sustainable for a in w["agents"].values() if a["seasons"]]
    needs = [a["needs_met"] / a["seasons"] for w in sustainable for a in w["agents"].values() if a["seasons"]]
    checks = [("Defector beats sustainable agents over the first 10 seasons (R3)", bad > good and wins == len(SEEDS), f"defector {bad:.3f} vs others {good:.3f}, wins {wins}/{len(SEEDS)} seeds"),
              ("All-greedy collapses before season 60 (R3)", hit_g == len(SEEDS) and max(when_g) < 60, f"collapsed in {hit_g}/{len(SEEDS)} seeds, seasons {min(when_g)}-{max(when_g)}"),
              ("All-greedy earns less cumulative reward per agent than all-sustainable (R3)", mean_greedy < mean_sustainable, f"greedy {mean_greedy:.3f} vs sustainable {mean_sustainable:.3f}"),
              ("Satiated agent has positive marginal incentive to acquire more (R3)", margin["R3"] > 0, f"+10 fish into the project at 100 invested is worth {margin['R3']:.5f}")]
    lines += ["## Requirements", "", "| Requirement | Result | Numbers |", "|---|---|---|"]
    lines += [f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |" for name, ok, detail in checks]
    lines += ["", "## Scenarios (R3)", "", "| Scenario | Seeds collapsed | Mean final S/K | Mean cumulative reward |", "|---|---|---|---|"]
    k = config["game"]["K"]
    for label, worlds in (("a) all-sustainable, 0.9 x rK/4 total", sustainable), ("b) all-greedy, 30 each", greedy), ("sustainable founders plus the scripted newcomer at 31", with_newcomer)):
        lines.append(f"| {label} | {collapse_stats(worlds)[0]}/{len(SEEDS)} | {st.mean(w['stock'] for w in worlds) / k:.3f} | {st.mean(x for w in worlds for x in rewards_of(w)):.3f} |")
    lines += ["", f"The newcomer among scripted sustainable founders who do not adapt: collapse in {hit_n}/{len(SEEDS)} seeds" + (f", seasons {min(when_n)}-{max(when_n)}." if when_n else "."),
              "", f"Scripted all-sustainable agents: project completion {st.mean(goal):.2f} (min {min(goal):.2f}); share of seasons with needs met {st.mean(needs):.2f} (min {min(needs):.2f}).",
              "", "## c) One defector among sustainable agents, first 10 seasons (R3)", "", "| Seed | Defector | Mean of others |", "|---|---|---|"]
    lines += [f"| {s} | {p[0]:.3f} | {p[1]:.3f} |" for s, p in zip(SEEDS, pairs)]
    lines += ["", "## d) Satiated agent, marginal reward for 10 more fish", "", "| Reward | Marginal |", "|---|---|"]
    lines += [f"| {mode} | {value:.5f} |" for mode, value in margin.items()]
    r1 = with_mode(config, "R1")
    worlds = [play(r1, s, needs_only(r1), reserve=1) for s in SEEDS]
    totals = [row["total_harvest"] for w in worlds for row in w["history"][5:]]
    msy = config["game"]["r"] * k / 4
    lines += ["", "## Does satiation alone look like restraint? (R1)", "",
              f"An agent that harvests only what R1 can reward (its needs and one season of reserve) takes {st.mean(totals):.1f} fish a season in total, {st.mean(totals) / msy:.0%} of the most the lake can regrow (rK/4 = {msy:g}).",
              f"Collapses: {collapse_stats(worlds)[0]}/{len(SEEDS)} seeds; mean final S/K {st.mean(w['stock'] for w in worlds) / k:.3f}.",
              "Under R1 the marginal value of more fish past satiation is " + f"{margin['R1']:.5f}. " + ("So a lake that survives under R1 can be satiation, not restraint: nothing in R1 wants the extra fish. This is why R3 is primary and why the R1 arm is only a diagnostic." if margin["R1"] == 0 else "R1 still rewards acquiring more here."), ""]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines))
    print("\n".join(lines))
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
