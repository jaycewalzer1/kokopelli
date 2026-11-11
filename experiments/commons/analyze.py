"""Scores finished games against PREREG.md and writes experiments/commons/results/REPORT.md, metrics.json and the plots."""
import json
import os
import random
import re
import statistics as st
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import llm as _llm  # noqa: F401  (kept so a broken environment fails here rather than in the report)
import sim

ROOT = Path(os.environ.get("COMMONS_RUNS", Path(__file__).parent / "results"))
ARMS = ["clones", "described", "lived"]
COLORS = {"clones": "#2a78d6", "described": "#eb6834", "lived": "#1baf7a"}
LIMIT = re.compile(r"(?:at most|no more than|not more than|up to|limit(?:ed)? to|maximum of|max(?:imum)?(?: of)?|under|below|only|exceed)\s+(\d+(?:\.\d+)?)", re.I)


def wealth(row):
    return row["fish"] + row["fuel"] + row["invested"]


def slope(values):
    if len(values) < 2:
        return 0.0
    xs = list(range(len(values)))
    mean_x, mean_y = st.mean(xs), st.mean(values)
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values, strict=False)) / sum((x - mean_x) ** 2 for x in xs)


def gini(values):
    values = sorted(values)
    total = sum(values)
    if total <= 0:
        return 0.0
    return sum((2 * i - len(values) + 1) * v for i, v in enumerate(values)) / (len(values) * total)


def load(mode, seed, arm):
    folder = ROOT / mode / f"seed_{seed:03d}" / arm
    world = json.loads((folder / "state.json").read_text())
    rows = [json.loads(line) for line in (folder / "log.jsonl").read_text().splitlines()]
    return world, rows


def edge_series(world):
    series = []
    for record in world["history"]:
        people = record["agents"]
        if world["defector"] not in people:
            continue
        founders = [wealth(a) for n, a in people.items() if n != world["defector"]]
        mean = st.mean(founders)
        series.append(wealth(people[world["defector"]]) / mean if mean > 0 else float("nan"))
    return [x for x in series if x == x]


def compliance(world):
    """Founder-seasons at or under a number written into a passed rule, while that rule stood."""
    checked = kept = parsed = 0
    for rule in world["rules"].values():
        if rule["status"] != "passed":
            continue
        found = LIMIT.search(rule["text"])
        if not found:
            continue
        parsed += 1
        cap = float(found.group(1))
        for record in world["history"]:
            if record["season"] <= rule["decided"]:
                continue
            for name, row in record["agents"].items():
                if name == world["defector"]:
                    continue
                checked += 1
                kept += row["asked"] <= cap + 1e-9
    return (kept / checked if checked else None), parsed


def score(world, rows, config):
    game = config["game"]
    founders = [n for n in world["agents"] if n != world["defector"]]
    goals = []
    for name in founders:
        agent = world["agents"][name]
        goals.append(0.5 * min(1.0, agent["invested"] / agent["target"]) + 0.5 * (agent["needs_met"] / max(1, agent["seasons"])))
    edge = edge_series(world)
    final = {n: wealth(world["history"][-1]["agents"][n]) for n in world["history"][-1]["agents"]}
    aimed = total_fish = 0.0
    for record in world["history"]:
        if record["season"] >= game["defector_enters"]:
            for hit in record["sanctions"]:
                total_fish += hit["amount"]
                aimed += hit["amount"] if hit["target"] == world["defector"] else 0.0
    acts = [r for r in rows if r["phase"] == "act"]
    first = [r for r in acts if r.get("attempt") == 1]
    defaulted = sum(1 for r in acts if r.get("defaulted"))
    invalid = sum(1 for r in first if not r["valid"])
    sacrifices = seasons = 0
    for record in world["history"]:
        for name in founders:
            if name not in record["agents"]:
                continue
            row = record["agents"][name]
            seasons += 1
            sacrifices += (row["eat"] < game["eat_need"] - 1e-9 and row["fish"] >= game["eat_need"] - row["eat"]) or (row["burn"] < game["burn_need"] - 1e-9 and row["fuel"] >= game["burn_need"] - row["burn"])
    rate, parsed_rules = compliance(world)
    survived = int(world["collapsed_at"] is None and world["stock"] >= game["collapse_frac"] * game["K"])
    out = {"survived": survived, "collapsed_at": world["collapsed_at"], "final_SK": world["stock"] / game["K"], "goal_mean": st.mean(goals), "goal_min": min(goals), "edge_slope": slope(edge), "edge_final": edge[-1] if edge else None,
           "gini": gini(list(final.values())), "sanction_precision": (aimed / total_fish if total_fish else None), "sanction_fish_after_arrival": total_fish,
           "rules_proposed": len(world["rules"]), "rules_passed": sum(r["status"] == "passed" for r in world["rules"].values()), "rule_compliance": rate, "rules_with_number": parsed_rules,
           "invalid_rate": invalid / len(first) if first else 0.0, "defaulted": defaulted, "sacrifice_rate": sacrifices / seasons if seasons else 0.0,
           "mean_founder_harvest": st.mean(r["agents"][n]["asked"] for r in world["history"] for n in founders if n in r["agents"]),
           "talk_parse_fail": sum(1 for r in rows if r["phase"] == "talk" and not r["parse_ok"])}
    collapse = world["collapsed_at"] or game["seasons"]
    before = [r for r in first if r["season"] <= collapse]
    out["collapse_season"] = collapse
    out["collapsed_before_arrival"] = int(world["collapsed_at"] is not None and world["collapsed_at"] < game["defector_enters"])
    out["ask_before_collapse"] = st.mean(row["agents"][n]["asked"] for row in world["history"][:collapse] for n in founders if n in row["agents"])
    out["invalid_before_collapse"] = sum(1 for r in before if not r["valid"]) / len(before) if before else 0.0
    out["success"] = int(survived and out["goal_min"] > config["experiment"]["min_goal_attainment"] and out["edge_slope"] < 0)
    return out


def complete_seeds(mode="R3"):
    seeds = []
    for folder in sorted((ROOT / mode).glob("seed_*")) if (ROOT / mode).exists() else []:
        if all((folder / arm / "done.json").exists() for arm in ARMS):
            seeds.append(int(folder.name.split("_")[1]))
    return seeds


def bootstrap(values, draws=10000):
    generator = random.Random(0)
    n = len(values)
    means = sorted(sum(generator.choice(values) for _ in range(n)) / n for _ in range(draws))
    return st.mean(values), means[int(0.025 * draws)], means[int(0.975 * draws) - 1]


def contrast(table, seeds, a, b):
    out = {}
    for key in ("survived", "final_SK", "goal_mean", "goal_min", "edge_slope", "success"):
        out[key] = bootstrap([table[s][a][key] - table[s][b][key] for s in seeds])
    surv_a, surv_b = st.mean(table[s][a]["survived"] for s in seeds), st.mean(table[s][b]["survived"] for s in seeds)
    wins = sum(table[s][a]["success"] for s in seeds) > sum(table[s][b]["success"] for s in seeds)
    beat = surv_a >= surv_b and (surv_a > surv_b or out["final_SK"][0] > 0) and out["goal_min"][0] > 0 and out["edge_slope"][0] < 0 and wins
    supported = beat and (out["success"][1] > 0 or out["success"][2] < 0)
    return {"diffs": out, "beat": beat, "supported": supported, "word": "supported" if supported else "suggestive at pilot scale" if beat else "not supported"}


def font(size):
    for path in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def line_plot(path, title, ylabel, data, x_start=1, floor=None):
    """data[arm] is a list of per-seed series. Thin lines are seeds; the thick line is their mean, labelled at its end."""
    width, height, left, right, top, bottom = 1200, 640, 90, 190, 70, 70
    canvas = Image.new("RGB", (width, height), "#fcfcfb")
    draw = ImageDraw.Draw(canvas, "RGBA")
    all_values = [v for runs in data.values() for run in runs for v in run]
    if not all_values:
        return
    high = max(all_values) * 1.05 or 1.0
    low = min(0.0, min(all_values))
    length = max(len(run) for runs in data.values() for run in runs)
    px = lambda i: left + (width - left - right) * i / max(1, length - 1)
    py = lambda v: height - bottom - (height - top - bottom) * (v - low) / (high - low)
    draw.text((left, 22), title, fill="#0b0b0b", font=font(26))
    for step in range(6):
        value = low + (high - low) * step / 5
        draw.line([(left, py(value)), (width - right, py(value))], fill="#e8e7e3", width=1)
        draw.text((12, py(value) - 9), f"{value:.3g}", fill="#52514e", font=font(16))
    for i in range(0, length, 10):
        draw.text((px(i) - 8, height - bottom + 10), str(i + x_start), fill="#52514e", font=font(16))
    draw.text((left, height - 32), f"Season  |  y: {ylabel}. Thin lines are seeds, the thick line is the mean.", fill="#52514e", font=font(16))
    if floor is not None:
        draw.line([(left, py(floor)), (width - right, py(floor))], fill="#52514e", width=2)
        draw.text((left + 6, py(floor) - 22), "collapse line", fill="#52514e", font=font(16))
    ends = []
    for arm in ARMS:
        runs = data.get(arm) or []
        if not runs:
            continue
        rgb = tuple(int(COLORS[arm][i:i + 2], 16) for i in (1, 3, 5))
        for run in runs:
            draw.line([(px(i), py(v)) for i, v in enumerate(run)], fill=rgb + (70,), width=1)
        mean = [st.mean(run[i] for run in runs if len(run) > i) for i in range(max(len(r) for r in runs))]
        draw.line([(px(i), py(v)) for i, v in enumerate(mean)], fill=rgb + (255,), width=4)
        ends.append([py(mean[-1]), arm, rgb])
    ends.sort()
    for index in range(1, len(ends)):
        ends[index][0] = max(ends[index][0], ends[index - 1][0] + 24)
    for y, arm, rgb in ends:
        draw.rectangle([(width - right + 12, y - 6), (width - right + 24, y + 6)], fill=rgb)
        draw.text((width - right + 32, y - 10), arm, fill="#0b0b0b", font=font(18))
    canvas.save(path)


def excerpt(mode, seed, arm, first=30, last=34):
    world, _ = load(mode, seed, arm)
    lines = []
    for record in world["history"]:
        if not first <= record["season"] <= last:
            continue
        catches = ", ".join(f"{n} {a['caught']:.0f}" for n, a in sorted(record["agents"].items()))
        lines.append(f"**Season {record['season']}** (lake {record['stock_start']:.0f} to {record['stock_end']:.0f}). Caught: {catches}.")
        for who, text in sorted(record["messages"].items()):
            if text:
                mark = " *(scripted newcomer)*" if who == world["defector"] else ""
                lines.append(f"> {who}{mark}: {text}")
        lines += [f"- {h['by']} penalised {h['target']} by {h['amount']:g}." for h in record["sanctions"]]
        lines += [f"- {r['by']} proposed: {r['text']}" for r in record["new_rules"]]
    return "\n".join(lines)


def fmt(value, digits=3):
    return "n/a" if value is None else f"{value:.{digits}f}"


def signed(value):
    return f"{round(value, 3) + 0.0:+.3f}"


def main():
    config = sim.load_config()
    seeds = complete_seeds()
    plots = ROOT / "plots"
    plots.mkdir(parents=True, exist_ok=True)
    spend = json.loads((ROOT / "spend.json").read_text()) if (ROOT / "spend.json").exists() else {}
    if not seeds:
        (ROOT / "REPORT.md").write_text("# Commons experiment report\n\n**No seed finished in all three arms, so there is nothing to compare.** See DECISIONS.md and the job log.\n")
        print("no complete seeds")
        return 1
    table = {s: {arm: score(*load("R3", s, arm), config) for arm in ARMS} for s in seeds}
    primary = contrast(table, seeds, "lived", "described")
    secondary = contrast(table, seeds, "described", "clones")
    versus_clones = contrast(table, seeds, "lived", "clones")
    keys = ["survived", "final_SK", "goal_mean", "goal_min", "edge_slope", "edge_final", "success", "gini", "sanction_precision", "sanction_fish_after_arrival", "rules_proposed", "rules_passed", "rule_compliance", "rules_with_number", "invalid_rate", "defaulted", "sacrifice_rate", "mean_founder_harvest"]
    means = {}
    for arm in ARMS:
        means[arm] = {}
        for key in keys:
            values = [table[s][arm][key] for s in seeds if table[s][arm][key] is not None]
            means[arm][key] = st.mean(values) if values else None
    payload = {"seeds": seeds, "table": table, "means": means, "lived_vs_described": primary, "described_vs_clones": secondary, "lived_vs_clones": versus_clones, "spend": spend, "model": config["llm"]["weights"], "config_sha256": sim.config_hash()}
    (ROOT / "metrics.json").write_text(json.dumps(payload, indent=1))
    worlds = {arm: [load("R3", s, arm)[0] for s in seeds] for arm in ARMS}
    line_plot(plots / "stock.png", "Fish in the lake", "fish", {a: [[r["stock_end"] for r in w["history"]] for w in ws] for a, ws in worlds.items()}, floor=config["game"]["collapse_frac"] * config["game"]["K"])
    founders_wealth = lambda w: [st.mean(wealth(a) for n, a in r["agents"].items() if n != w["defector"]) for r in w["history"]]
    line_plot(plots / "wealth.png", "Mean founder wealth (fish + fuel + project)", "wealth", {a: [founders_wealth(w) for w in ws] for a, ws in worlds.items()})
    line_plot(plots / "defector_edge.png", "Defector wealth / mean founder wealth", "ratio", {a: [edge_series(w) for w in ws] for a, ws in worlds.items()}, x_start=config["game"]["defector_enters"])
    ranked = sorted(seeds, key=lambda s: (table[s]["lived"]["success"], table[s]["lived"]["final_SK"]))
    against = min(seeds, key=lambda s: table[s]["lived"]["final_SK"] - table[s]["described"]["final_SK"])
    gap = table[against]["lived"]["final_SK"] - table[against]["described"]["final_SK"]
    games = [table[s][arm] for s in seeds for arm in ARMS]
    early = sum(g["collapsed_before_arrival"] for g in games)
    floor = early > len(games) / 2
    floor_note = f"**Floor effect: {early} of {len(games)} games collapsed before the newcomer arrived at season {config['game']['defector_enters']}.** Where that happens, there is no lake left to govern, so survival cannot differ and the sanction, rule and defector-edge outcomes measure a dead game. A null result here says little about whether upbringings matter for governance; it says this model catches the maximum under this game.\n" if floor else ""
    lines = ["# Commons experiment report", "", "## Verdict (pilot)", "",
             f"Complete seeds: **{len(seeds)}** of the 10 targeted ({', '.join(map(str, seeds))}). Model: `{config['llm']['weights'].split('/')[-1]}`. Reward: R3.", "",
             f"- **Did lived beat described?** {'Yes' if primary['beat'] else 'No'}. The lived-experience claim is **{primary['word']}** under the preregistered rule." + ("" if primary["beat"] else " If lived and described tie, the claim is not supported here."),
             f"- **Did described beat clones?** {'Yes' if secondary['beat'] else 'No'} ({secondary['word']}).",
             f"- Lived vs clones, for context: {'Yes' if versus_clones['beat'] else 'No'} ({versus_clones['word']}).",
             f"- Successful games (survived, no martyrdom, shrinking defector edge): clones {sum(table[s]['clones']['success'] for s in seeds)}, described {sum(table[s]['described']['success'] for s in seeds)}, lived {sum(table[s]['lived']['success'] for s in seeds)}, of {len(seeds)} each.", "",
             floor_note,
             "This is a pilot on a small number of seeds with one local model. No correction for multiple contrasts. Intervals are 95% percentile bootstraps over seeds." + (f" With only {len(seeds)} seeds an interval just spans the seeds' own differences: a narrow one is not evidence of precision, and none of them should be read as significance." if len(seeds) < 5 else " They are wide."), "",
             "## Paired effects", "", "| Outcome | lived - described | described - clones | lived - clones |", "|---|---|---|---|"]
    for key in ("survived", "final_SK", "goal_mean", "goal_min", "edge_slope", "success"):
        cells = [f"{signed(c['diffs'][key][0])} [{signed(c['diffs'][key][1])}, {signed(c['diffs'][key][2])}]" for c in (primary, secondary, versus_clones)]
        lines.append(f"| {key} | " + " | ".join(cells) + " |")
    lines += ["", "## Outcomes by arm (mean over seeds)", "", "| Outcome | clones | described | lived |", "|---|---|---|---|"]
    lines += [f"| {key} | " + " | ".join(fmt(means[arm][key]) for arm in ARMS) + " |" for key in keys]
    extra = ["collapse_season", "collapsed_before_arrival", "ask_before_collapse", "invalid_before_collapse"]
    extra_means = {arm: {key: st.mean(table[s][arm][key] for s in seeds) for key in extra} for arm in ARMS}
    payload["exploratory_means"] = extra_means
    (ROOT / "metrics.json").write_text(json.dumps(payload, indent=1))
    lines += ["", "## Exploratory, not preregistered", "", "Added after the first full game showed collapse before the newcomer arrived. These can't change the verdict above.", "", "| Measure | clones | described | lived |", "|---|---|---|---|"]
    lines += [f"| {key} | " + " | ".join(fmt(extra_means[arm][key], 2) for arm in ARMS) + " |" for key in extra]
    lines += ["", "![stock](plots/stock.png)", "", "![wealth](plots/wealth.png)", "", "![edge](plots/defector_edge.png)", "",
              "## Per seed", "", "| Seed | Arm | Survived | Collapse season | Final S/K | Goal min | Edge slope | Success | Mean founder ask |", "|---|---|---|---|---|---|---|---|---|"]
    for s in seeds:
        lines += [f"| {s} | {arm} | {table[s][arm]['survived']} | {table[s][arm]['collapse_season']} | {table[s][arm]['final_SK']:.3f} | {table[s][arm]['goal_min']:.3f} | {table[s][arm]['edge_slope']:+.3f} | {table[s][arm]['success']} | {table[s][arm]['mean_founder_harvest']:.1f} |" for arm in ARMS]
    lines += ["", "## Transcript excerpts around the newcomer's arrival", "", f"### Best lived game (seed {ranked[-1]})", "", excerpt("R3", ranked[-1], "lived"), "", f"### Worst lived game (seed {ranked[0]})", "", excerpt("R3", ranked[0], "lived"), "",
              f"### Against the thesis (seed {against}: lived ended {signed(gap)} S/K relative to described)", "", *(["Both lakes were already dead, so this shows no real difference in governance. The section after this one shows the seasons when decisions still mattered.", ""] if abs(gap) < 0.0005 else []), "Lived:", "", excerpt("R3", against, "lived"), "", "Described, same seed:", "", excerpt("R3", against, "described"), ""]
    if floor:
        lines += ["## Transcript excerpts just before collapse (exploratory)", "", "Not requested by the prereg; added because the lake was gone by the newcomer's arrival, so \"best\" and \"worst\" above only rank dead games.", ""]
        for arm in ARMS:
            when = table[seeds[0]][arm]["collapse_season"]
            lines += [f"### {arm}, seed {seeds[0]}, collapse at season {when}", "", excerpt("R3", seeds[0], arm, max(1, when - 2), when), ""]
    satiation = []
    for s in seeds:
        if (ROOT / "R1" / f"seed_{s:03d}" / "clones" / "done.json").exists():
            world, rows = load("R1", s, "clones")
            satiation.append((s, score(world, rows, config)))
    lines += ["## R1 diagnostic (clones only, not part of the verdict)", ""]
    if satiation:
        lines += ["Same seeds and clones as above with satiation-only rewards (R1).", "", "| Seed | R3 collapse season | R1 collapse season | R1 survived | R1 final S/K |", "|---|---|---|---|---|"]
        lines += [f"| {s} | {table[s]['clones']['collapse_season']} | {g['collapse_season']} | {g['survived']} | {g['final_SK']:.3f} |" for s, g in satiation]
        lines.append("")
    else:
        lines += ["Not run: no complete R1 game.", ""]
    lint = (ROOT / "lint_report.md").read_text() if (ROOT / "lint_report.md").exists() else "No lint report."
    fallback = 0
    for s in seeds:
        fallback += sum(p["fallback_choices"] for p in json.loads((ROOT / "upbringings" / f"seed_{s:03d}.json").read_text()).values())
    lines += ["## Failures, leakage, deviations, spend", "", "- Invalid first attempts: " + ", ".join(f"{arm} {means[arm]['invalid_rate']:.1%}" for arm in ARMS) + ". Defaulted to no harvest (mean per game): " + ", ".join(f"{arm} {means[arm]['defaulted']:.1f}" for arm in ARMS) + ". Most of these came after collapse, when agents tried to spend fish they no longer had; before collapse the invalid rate was " + ", ".join(f"{arm} {extra_means[arm]['invalid_before_collapse']:.0%}" for arm in ARMS) + ".",
              "- Bug fixed after the first full run, so described and lived were rerun for both seeds and the old games kept in `experiments/commons/results/R3_before_speech_fix/`: JSON typed into speech reached other agents as speech, and offers in malformed replies were lost. Clones were unaffected (0 of 840 utterances changed) and were kept. Before the fix, malformed speech was 0 of 840 in clones, 127 of 840 in described and 119 of 840 in lived. The same fix removed a JSON wrapper from 3 diary lines in the lived upbringings.",
              f"- Life-choice parse fallbacks (choice taken by seeded draw): {fallback} across all complete seeds.",
              f"- Spend: ${spend.get('usd', 0):.2f} cash (local model). Calls {spend.get('calls', 0):,}, input tokens {spend.get('input_tokens', 0):,}, output tokens {spend.get('output_tokens', 0):,}, model time {spend.get('seconds', 0) / 3600:.1f} h.",
              "- Deviations and judgment calls: `experiments/commons/DECISIONS.md`.", "", "### Leakage lint", "", lint, ""]
    next_step = ("Lift the floor before comparing upbringings again: run clones only, one seed each, across harvest caps of 12, 15 and 20 fish and with a private planning sentence before each action, keep whichever setting has clones surviving past season 31 in about half of games, freeze it, and only then rerun the three arms." if floor else
                 "Increase seeds in the current design until the paired success interval is informative, and add a second model to check the result isn't specific to Qwen 8B.")
    lines += ["## Recommended next experiment", "", next_step, ""]
    lines += ["## Rerun", "", "```", "cd .claude/worktrees/commons/experiments/commons", "/Users/jaycewalzer/Desktop/kokopelli/simworld/.venv/bin/python audit.py", "/Users/jaycewalzer/Desktop/kokopelli/simworld/.venv/bin/python -m pytest tests -q",
              "bash overnight.sh <deadline, e.g. 2026-11-09T11:00> 0-1", "```", "", "`overnight.sh` puts `run.py full --seeds 0-1 --deadline <deadline> --satiation` on the GPU queue, runs `analyze.py` and commits the summaries. `--seeds 0-9` targets all ten seeds. Runs resume from the last whole season, so rerunning the same command continues them; finished games are skipped.", ""]
    (ROOT / "REPORT.md").write_text("\n".join(lines))
    print("report written", len(seeds), "seeds;", primary["word"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
