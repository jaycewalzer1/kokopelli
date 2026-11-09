"""Plays the arms. Every season is written atomically, so a killed run restarts at the last whole season.

python run.py full --seeds 0-9 --deadline 2026-11-09T08:30
python run.py smoke
python run.py lint --seeds 0-9
"""
import argparse
import datetime as dt
import json
import os
import random
import statistics as st
import sys
import time
from pathlib import Path

import life as lf
import llm
import policies
import prompts as pt
import sim

ROOT = Path(os.environ.get("COMMONS_RUNS", Path(__file__).parents[2] / "runs" / "commons"))
ARM_ORDER = ["clones", "described", "lived"]


class OutOfTime(RuntimeError):
    pass


def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text)
    with open(temporary) as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def append_rows(path, rows):
    """One write of whole lines, flushed to disk. A torn last line is dropped when the run resumes."""
    with open(path, "a") as handle:
        handle.write("".join(json.dumps(row) + "\n" for row in rows))
        handle.flush()
        os.fsync(handle.fileno())


def trim_log(path, season):
    """Throw away anything logged after the last saved season, and any half-written line."""
    if not path.exists():
        return
    kept = []
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row["season"] < season:
            kept.append(line)
    write_atomic(path, "".join(line + "\n" for line in kept))


def key(*parts):
    return random.Random(":".join(map(str, parts))).randrange(2**31)


class FakeModel:
    """Stands in for Qwen in tests and dry runs: well-formed answers of each kind, no model."""

    def ask(self, requests, max_tokens, seed):
        out = []
        for _, user in requests:
            if '"choice"' in user:
                out.append('{"choice": "%s"}' % random.Random(key(user, seed)).choice("AB"))
            elif '"diary"' in user:
                out.append('{"diary": "I keep thinking about that day."}')
            elif '"lessons"' in user:
                out.append('{"lessons": "People surprise me. Luck does too."}')
            elif '"say"' in user and '"harvest"' not in user:
                out.append('{"say": "Hello all.", "offer": null}')
            else:
                out.append('{"harvest": 7, "eat": 3, "burn": 0, "invest": 1, "store": null, "accept": [], "gifts": [], "sanctions": [], "propose_rule": null, "votes": {}}')
        return out


def founders(world):
    return [name for name in world["agents"] if name != world["defector"]]


def build_lives(seed, config, model, log=print):
    """Each founder lives their episodes once for this seed, in one cached file every arm reads from."""
    path = ROOT / "upbringings" / f"seed_{seed:03d}.json"
    if path.exists():
        return json.loads(path.read_text())
    names = founders(sim.new_world(config, seed))
    tokens = config["llm"]["life_max_tokens"]
    lives = {name: {"name": name, "plan": lf.plan_life(seed, name), "steps": [], "money": 0, "faith": 0, "fallback_choices": 0} for name in names}
    for step in range(8):
        requests = []
        for name in names:
            person = lives[name]
            episode = lf.EPISODES[person["plan"]["episodes"][step]]
            so_far = " ".join(row["diary"] for row in person["steps"][-2:])
            requests.append((pt.LIFE_SYSTEM, pt.life_choice(lf.render(episode[2], "you", name), lf.render(episode[3], "you", name), lf.render(episode[4], "you", name), episode[1], so_far)))
        answers = model.ask(requests, tokens, key(seed, "choice", step))
        diary_requests = []
        for name, answer in zip(names, answers):
            person = lives[name]
            parsed = pt.parse_json(answer) or {}
            choice = str(parsed.get("choice", "")).strip().upper()[:1]
            if choice not in ("A", "B"):
                choice = sim.rng("fallback", seed, name, step).choice("AB")
                person["fallback_choices"] += 1
            index = person["plan"]["episodes"][step]
            text, money, faith = lf.outcome(person["plan"], step, choice)
            person["money"] += money
            person["faith"] += faith
            episode = lf.EPISODES[index]
            person["steps"].append({"age": episode[1], "episode": index, "choice": choice, "option": episode[3 if choice == "A" else 4], "fact": text, "theme": episode[0]})
            diary_requests.append((pt.LIFE_SYSTEM, pt.life_diary(lf.render(episode[2], "you", name), lf.render(text, "you", name))))
        answers = model.ask(diary_requests, tokens, key(seed, "diary", step))
        for name, answer in zip(names, answers):
            parsed = pt.parse_json(answer) or {}
            lives[name]["steps"][-1]["diary"] = lf.scrub(str(parsed.get("diary") or answer))[:200]
    requests = [(pt.LIFE_SYSTEM, pt.life_lessons("\n".join(row["diary"] for row in lives[name]["steps"]))) for name in names]
    answers = model.ask(requests, tokens * 2, key(seed, "lessons"))
    for name, answer in zip(names, answers):
        parsed = pt.parse_json(answer) or {}
        lessons = lf.scrub(str(parsed.get("lessons") or answer))[:300]
        lives[name]["lessons"] = lessons or "I have seen good days and bad ones."
    write_atomic(path, json.dumps(lives, indent=1))
    log(f"lives built for seed {seed}")
    return lives


def identities_for(seed, lives, config):
    cap, names = config["experiment"]["memory_cap_chars"], list(lives)
    lived = {name: lf.lived_memory(lives[name], cap) for name in names}
    described = {name: lf.described_memory(lives[name], len(lived[name])) for name in names}
    length = round(st.mean(len(text) for text in described.values()))
    opener = "You are an ordinary adult who has lived by this lake for many years. "
    neutral = opener + lf.filler_text(max(0, length - len(opener)))
    return {"clones": {name: neutral for name in names}, "described": described, "lived": lived}


def lint_seed(seed, identities, config):
    """Fails on leakage or on arms of mismatched length. Agent speech during the game is behaviour, not leakage, so it isn't scanned."""
    tolerance = config["experiment"]["length_tolerance"]
    hits, lengths = [], {}
    for arm, people in identities.items():
        lengths[arm] = round(st.mean(len(text) for text in people.values()), 1)
        for name, text in people.items():
            for match in lf.BANNED.finditer(text):
                hits.append({"seed": seed, "arm": arm, "agent": name, "term": match.group(0), "context": text[max(0, match.start() - 40):match.end() + 40]})
    world = sim.new_world(config, seed)
    for name in founders(world):
        rendered = pt.system_for(world, name, config, identities, "clones")
        for match in lf.BANNED.finditer(rendered):
            hits.append({"seed": seed, "arm": "goal/rules", "agent": name, "term": match.group(0), "context": rendered[max(0, match.start() - 40):match.end() + 40]})
    mismatch = [{"seed": seed, "arm": a, "mean_chars": v, "against": lengths["lived"]} for a, v in lengths.items() if abs(v - lengths["lived"]) > tolerance * lengths["lived"]]
    return {"seed": seed, "lengths": lengths, "hits": hits, "length_mismatch": mismatch}


def lint_static():
    """The hand-written text: every game prompt and every branch of every episode."""
    hits = []
    texts = [pt.SYSTEM, pt.SPEAK, pt.ACT, pt.LIFE_SYSTEM, lf.FILLER, " ".join(sim.PROJECTS), " ".join(policies.DEFECTOR_LINES)]
    for episode in lf.EPISODES:
        texts += [episode[2], episode[3], episode[4], *[o[0] for branch in episode[5:] for o in branch]]
    for text in texts:
        hits += [{"term": m.group(0), "context": text[max(0, m.start() - 40):m.end() + 40]} for m in lf.BANNED.finditer(text)]
    return hits


def write_lint(reports, static):
    payload = {"static_hits": static, "seeds": reports}
    write_atomic(ROOT / "lint_report.json", json.dumps(payload, indent=1))
    bad = static or [r for r in reports if r["hits"] or r["length_mismatch"]]
    lines = ["# Leakage lint", "", f"Static text hits: {len(static)}.", "", "| Seed | Hits | Mean chars clones / described / lived | Length ok |", "|---|---|---|---|"]
    lines += [f"| {r['seed']} | {len(r['hits'])} | {r['lengths']['clones']} / {r['lengths']['described']} / {r['lengths']['lived']} | {'yes' if not r['length_mismatch'] else 'NO'} |" for r in reports]
    write_atomic(ROOT / "lint_report.md", "\n".join(lines) + "\n")
    return not bad


def clean_offer(raw):
    """Whatever the model wrote as an offer, or None if it isn't a usable one."""
    if not isinstance(raw, dict):
        return None
    try:
        offer = {"give": str(raw["give"]).lower(), "give_amount": float(raw["give_amount"]), "want": str(raw["want"]).lower(), "want_amount": float(raw["want_amount"])}
    except (KeyError, TypeError, ValueError):
        return None
    if {offer["give"], offer["want"]} != set(sim.GOODS) or offer["give_amount"] <= 0 or offer["want_amount"] <= 0 or offer["give_amount"] != offer["give_amount"] or offer["want_amount"] != offer["want_amount"]:
        return None
    return offer


def coerce(raw):
    """Models often quote numbers. Digits in a string are still the number they plainly meant."""
    if not isinstance(raw, dict):
        return raw
    out = dict(raw)
    for field in ("harvest", "eat", "burn", "invest", "store"):
        if isinstance(out.get(field), str):
            try:
                out[field] = float(out[field])
            except ValueError:
                out[field] = None if field == "store" else out[field]
    return out


def default_action(world, name, config):
    """After a failed repair: no harvest, as specified. Food and fuel are still consumed from what the person has."""
    game, agent = config["game"], world["agents"][name]
    action = sim.empty_action()
    action["eat"], action["burn"] = min(game["eat_need"], agent["fish"]), min(game["burn_need"], agent["fuel"])
    action["eat"] = min(action["eat"], max(0.0, agent["fish"] - sum(o["give_amount"] for o in world["offers"] if o["by"] == name and o["give"] == "fish")))
    action["burn"] = min(action["burn"], max(0.0, agent["fuel"] - sum(o["give_amount"] for o in world["offers"] if o["by"] == name and o["give"] == "fuel")))
    return action


def play(seed, arm, config, model, deadline=None, mode="R3", log=print):
    """One game, resuming from its last saved season."""
    folder = ROOT / mode / f"seed_{seed:03d}" / arm
    state_path, log_path = folder / "state.json", folder / "log.jsonl"
    done_path = folder / "done.json"
    if done_path.exists():
        return json.loads(state_path.read_text())
    config = {**config, "rewards": {**config["rewards"], "mode": "R3" if mode == "smoke" else mode}}
    lives = build_lives(seed, config, model, log)
    identities = identities_for(seed, lives, config)
    folder.mkdir(parents=True, exist_ok=True)
    if state_path.exists():
        world = json.loads(state_path.read_text())
    else:
        world = sim.new_world(config, seed)
    trim_log(log_path, world["season"])
    write_atomic(folder / "meta.json", json.dumps({"seed": seed, "arm": arm, "reward": mode, "model": config["llm"]["weights"], "config_sha256": sim.config_hash()}, indent=1))
    while world["season"] <= config["game"]["seasons"]:
        if deadline and time.time() > deadline:
            raise OutOfTime(f"deadline reached in {arm} seed {seed} at season {world['season']}")
        season = world["season"]
        sim.begin_season(world, config)
        people = [name for name in sim.active(world) if name != world["defector"]]
        rows = []
        requests = [(pt.system_for(world, n, config, identities, arm), pt.speak_prompt(world, n, config)) for n in people]
        answers = model.ask(requests, config["llm"]["discussion_max_tokens"], key(seed, arm, season, "talk"))
        talk = {}
        for name, answer, request in zip(people, answers, requests):
            parsed = pt.parse_json(answer)
            rows.append({"season": season, "phase": "talk", "agent": name, "raw": answer, "parse_ok": parsed is not None, **({"prompt": list(request)} if season in (1, 31) else {})})
            parsed = parsed or {"say": answer[:200]}
            talk[name] = {"say": str(parsed.get("say") or "")[:400], "offer": clean_offer(parsed.get("offer"))}
        if world["defector"] in sim.active(world):
            talk[world["defector"]] = policies.defector_talk(world)
        sim.apply_discussion(world, talk)
        requests = [(pt.system_for(world, n, config, identities, arm), pt.act_prompt(world, n, config)) for n in people]
        answers = model.ask(requests, config["llm"]["action_max_tokens"], key(seed, arm, season, "act"))
        actions, failed = {}, []
        for name, answer, request in zip(people, answers, requests):
            row = {"season": season, "phase": "act", "agent": name, "raw": answer, "attempt": 1, **({"prompt": list(request)} if season in (1, 31) else {})}
            try:
                actions[name] = sim.validate_action(world, name, coerce(pt.parse_json(answer)), config)
                row["valid"] = True
            except sim.InvalidAction as error:
                row["valid"], row["error"] = False, str(error)
                failed.append((name, request, str(error)))
            rows.append(row)
        if failed:
            repaired = model.ask([(s, pt.repair_prompt(u, e)) for _, (s, u), e in failed], config["llm"]["action_max_tokens"], key(seed, arm, season, "repair"))
            for (name, request, error), answer in zip(failed, repaired):
                row = {"season": season, "phase": "act", "agent": name, "raw": answer, "attempt": 2}
                try:
                    actions[name] = sim.validate_action(world, name, coerce(pt.parse_json(answer)), config)
                    row["valid"] = True
                except sim.InvalidAction as error:
                    actions[name] = default_action(world, name, config)
                    row["valid"], row["error"], row["defaulted"] = False, str(error), True
                rows.append(row)
        if world["defector"] in sim.active(world):
            actions[world["defector"]] = sim.validate_action(world, world["defector"], policies.defector_act(world, world["defector"], config), config)
        record = sim.resolve_season(world, actions, config)
        rows.append({"season": season, "phase": "actions", "actions": actions})
        append_rows(log_path, rows)
        write_atomic(state_path, json.dumps(world))
        log(f"{mode} seed {seed} {arm} season {season}: lake {record['stock_end']:.0f}, harvest {record['total_harvest']:.0f}")
    write_atomic(done_path, json.dumps({"finished": dt.datetime.now().isoformat(), "seasons": world["season"] - 1}))
    return world


def seeds_of(text):
    if "-" in text:
        start, end = text.split("-")
        return list(range(int(start), int(end) + 1))
    return [int(x) for x in text.split(",")]


def arms_for(seed):
    """Rotates which arm goes first, so an arm doesn't always run at the same point of the night."""
    return ARM_ORDER[seed % 3:] + ARM_ORDER[:seed % 3]


def make_model(args, config):
    if args.fake:
        return FakeModel()
    pricing = config["llm"]
    return llm.MlxModel(config, llm.Budget(ROOT / "spend.json", pricing["max_spend_usd"], pricing["usd_per_million_input_tokens"], pricing["usd_per_million_output_tokens"]))


def lint_all(seeds, config, model):
    static = lint_static()
    reports = []
    for seed in seeds:
        reports.append(lint_seed(seed, identities_for(seed, build_lives(seed, config, model), config), config))
    ok = write_lint(reports, static)
    if not ok:
        print("LINT FAILED: see runs/commons/lint_report.md", file=sys.stderr)
    return ok


def full(args, config, model):
    deadline = dt.datetime.fromisoformat(args.deadline).timestamp() if args.deadline else None
    seed_times, linted = [], []
    try:
        for seed in seeds_of(args.seeds):
            if all((ROOT / "R3" / f"seed_{seed:03d}" / arm / "done.json").exists() for arm in ARM_ORDER):
                linted.append(seed)
                continue
            if deadline and seed_times and time.time() + st.mean(seed_times) > deadline:
                print(f"stopping before seed {seed}: a whole seed takes about {st.mean(seed_times) / 60:.0f} min", flush=True)
                return 0
            started = time.time()
            linted.append(seed)
            if not lint_all(linted, config, model):
                return 2
            for arm in arms_for(seed):
                play(seed, arm, config, model, deadline, "R3")
            seed_times.append(time.time() - started)
        if args.satiation:
            for seed in seeds_of(args.seeds):
                if deadline and seed_times and time.time() + st.mean(seed_times) / 3 > deadline:
                    break
                play(seed, "clones", config, model, deadline, "R1")
    except (OutOfTime, llm.BudgetExhausted) as stop:
        print(f"stopped: {stop}", flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["full", "smoke", "lint"])
    parser.add_argument("--seeds", default="0-9")
    parser.add_argument("--deadline")
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--satiation", action="store_true")
    parser.add_argument("--smoke-seed", type=int, default=100)
    parser.add_argument("--smoke-seasons", type=int, default=34)
    args = parser.parse_args()
    config = sim.load_config()
    model = make_model(args, config)
    if args.action == "lint":
        return 0 if lint_all(seeds_of(args.seeds), config, model) else 2
    if args.action == "smoke":
        if not lint_all([args.smoke_seed], config, model):
            return 2
        shortened = {**config, "game": {**config["game"], "seasons": args.smoke_seasons}}
        for arm in ARM_ORDER:
            play(args.smoke_seed, arm, shortened, model, None, "smoke")
        return 0
    return full(args, config, model)


if __name__ == "__main__":
    sys.exit(main())
