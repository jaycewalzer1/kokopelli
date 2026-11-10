"""Phase 5: is the base model's answer on these instruments stable, noisy, or somewhere useful in between?

To detect a shift, an instrument needs two things:
- Spread. If the model gives the same answer every time, there's a floor or ceiling and small shifts may not show.
- Signal. If answers look like coin flips, or just follow which option was listed first, there's no preference to shift.

Run:  python -m experiments.benchmarks.noise_check experiments/benchmarks/results/<run_id>
It only reports what's in the results file. If nothing was measured, it says so.
"""
import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from experiments.benchmarks.run import read_results

FROZEN_MODAL_SHARE = 0.95   # The same answer this often means there's almost no spread.
COIN_FLIP_INCONSISTENT = 0.5  # Half or more multiple-switching ladders means no stable preference.
RARE_BAD = {"hbwe_1", "hbwe_3"}
POSITION_GAP = 5.0 # Swapping the options moves the Holt-Laury score by at least half its 0-to-10 range.


def holt_laury_summary(rows):
    table = []
    for (arm, template), group in _groups(rows, "holt_laury"):
        valid = [row for row in group if row["valid"]]
        scores = np.array([row["score"] for row in valid], float)
        answers = Counter(row["extras"]["picks"] for row in valid)
        safe_first = [row["score"] for row in valid if row["option_order"].startswith("safe")]
        risky_first = [row["score"] for row in valid if row["option_order"].startswith("risky")]
        table.append({
            "arm": arm, "template": template, "n": len(group), "valid": len(valid),
            "mean_safe": _mean(scores), "sd_safe": float(scores.std(ddof=1)) if len(scores) > 1 else None,
            "min": float(scores.min()) if len(scores) else None, "max": float(scores.max()) if len(scores) else None,
            "distinct_answers": len(answers), "modal_share": answers.most_common(1)[0][1] / len(valid) if valid else None,
            "modal_answer": answers.most_common(1)[0][0] if valid else None,
            "at_floor_0_safe": _mean([row["score"] == 0 for row in valid]),
            "at_ceiling_10_safe": _mean([row["score"] == 10 for row in valid]),
            "risky_on_row_1": _mean([row["extras"]["first_risky_row"] == 1 for row in valid]),
            "multiple_switching": _mean([row["extras"]["multiple_switching"] for row in valid]),
            "dominated": _mean([row["extras"]["dominated"] for row in valid]),
            "safe_when_safe_first": _mean(safe_first), "safe_when_risky_first": _mean(risky_first),
            # A preference survives swapping the options. This gap is how much the score follows position instead.
            "position_gap": abs(_mean(safe_first) - _mean(risky_first)) if safe_first and risky_first else None,
        })
    return pd.DataFrame(table)


def lotteries_summary(rows):
    table = []
    for (arm, template), group in _groups(rows, "lotteries"):
        for item in sorted({row["item_id"] for row in group}):
            part = [row for row in group if row["item_id"] == item]
            valid = [row for row in part if row["valid"]]
            scores = [row["score"] for row in valid]
            first = [row["parsed_choice"] == "A" for row in valid]
            h_first = [row["extras"]["chosen"] == "H" for row in valid if row["option_order"].startswith("H")]
            l_first = [row["extras"]["chosen"] == "H" for row in valid if row["option_order"].startswith("L")]
            table.append({"arm": arm, "template": template, "item": item, "n": len(part), "valid": len(valid),
                          "underweighting_rate": _mean(scores), "chose_listed_first": _mean(first),
                          "chose_H": _mean([row["extras"]["chosen"] == "H" for row in valid]),
                          "chose_H_when_H_first": _mean(h_first), "chose_H_when_L_first": _mean(l_first)})
    return pd.DataFrame(table)


def lotteries_by_rare_kind(rows):
    """The underweighting rate, split by whether the rare outcome is bad or good news.

    From Hertwig et al.'s Table 1. Rare and bad: problem 1 (0 instead of 4) and 3 (-32 instead of 0). Rare and good: problems
    2, 5, 6 (a prize) and 4 (0 instead of -4). Underweighting a rare bad outcome makes the gamble look better, so it takes
    the risk. Underweighting a rare good outcome makes the gamble look worse, so it plays safe. The one score mixes
    the two, so a general shift toward risk raises one half and lowers the other, and they partly cancel.
    """
    table = {}
    for row in rows:
        if row["instrument"] == "lotteries" and row["valid"]:
            kind = "rare_bad" if row["item_id"] in RARE_BAD else "rare_good"
            table.setdefault(row["arm"], {}).setdefault(kind, []).append(row["score"])
    return {arm: {kind: {"rate": _mean(scores), "n": len(scores)} for kind, scores in kinds.items()} for arm, kinds in table.items()}


def rows_summary(rows):
    """The one-row-at-a-time pilot: the share choosing safe on each row, in each option order. A good curve falls from
    near 1 on row 1 to near 0 on row 10, and looks the same whichever option is listed first."""
    table = []
    for (arm, template), group in _groups(rows, "holt_laury_rows"):
        for order in ("safe,risky", "risky,safe"):
            curve = {}
            for row in range(1, 11):
                scores = [r["score"] for r in group if r["valid"] and r["extras"]["row"] == row and r["option_order"] == order]
                curve[row] = round(_mean(scores), 2) if scores else None
            table.append({"arm": arm, "template": template, "order": order, "safe_rate_by_row": curve})
    return table


def _groups(rows, instrument):
    groups = {}
    for row in rows:
        if row["instrument"] == instrument:
            groups.setdefault((row["arm"], row["template"]), []).append(row)
    return sorted(groups.items())


def _mean(values):
    values = [float(value) for value in values]
    return float(np.mean(values)) if values else None


def verdict_holt_laury(table):
    """Plain-language reading. The thresholds are rules of thumb, chosen before seeing real data, except the floor and
    ceiling rule and the position rule. Those were added after seeing the real base-model results, so they aren't blind.

    Position comes first: a pile-up at 0 or 10 means nothing if it comes from answering the same letter on every row."""
    if table.empty:
        return "NOT MEASURED"
    if "position_gap" in table and (table.position_gap.astype(float) >= POSITION_GAP).mean() >= 0.5:
        return "POSITION BIAS: most templates' scores follow which option is listed first, not what it pays"
    for column, label in (("at_floor_0_safe", "FLOOR: most answers are 0 safe choices, so a move toward more risk can't show"),
                          ("at_ceiling_10_safe", "CEILING: most answers are 10 safe choices, so a move toward more caution can't show")):
        if column in table and (table[column].astype(float) >= 0.5).mean() >= 0.5:
            return label
    frozen = (table.modal_share >= FROZEN_MODAL_SHARE).mean()
    noisy = (table.multiple_switching >= COIN_FLIP_INCONSISTENT).mean()
    if noisy == 1:
        return "PURE NOISE: most ladders switch back and forth, so there's no stable preference to shift"
    if frozen == 1:
        return "NEAR-IDENTICAL: one answer almost every sample in every template, so sampling alone can't show small shifts"
    if frozen > 0 or noisy > 0:
        return "MIXED: templates disagree. Read the table before trusting this instrument"
    return "USABLE SPREAD: answers vary, but stay mostly consistent"


def verdict_lotteries(table):
    if table.empty:
        return "NOT MEASURED"
    rate = table.underweighting_rate.astype(float)
    at_edge = ((rate <= 0.05) | (rate >= 0.95)).mean()
    position = (table.chose_listed_first.astype(float) - 0.5).abs().mean()
    if position >= 0.3:
        return "POSITION BIAS: choices follow which option is listed first more than what it offers"
    if at_edge >= 0.8:
        return f"NEAR-IDENTICAL: {at_edge:.0%} of cells are at 0 or 1, so sampling alone can't show small shifts"
    if at_edge >= 0.4:
        return f"MIXED: {at_edge:.0%} of cells are at 0 or 1"
    return "USABLE SPREAD: choice rates sit away from 0 and 1"


def smallest_detectable(sd, n_per_arm):
    """Roughly the smallest true gap two arms need for an 80% chance of detection at alpha .05: 2.8 x SD x sqrt(2/n)."""
    return 2.8 * sd * np.sqrt(2 / n_per_arm)


def control_shift(rows, instrument):
    """Positive control: did telling the model to be cautious or bold move the score? Mean per arm, if those arms ran."""
    means = {}
    for arm in ("base_cautious", "base", "base_bold"):
        scores = [row["score"] for row in rows if row["instrument"] == instrument and row["arm"] == arm and row["valid"]]
        if scores:
            means[arm] = {"mean": float(np.mean(scores)), "n": len(scores)}
    return means


def analyze(out):
    rows = read_results(out)
    record_path = Path(out) / "run_record.json"
    record = json.loads(record_path.read_text()) if record_path.exists() else {}
    hl, lot = holt_laury_summary(rows), lotteries_summary(rows)
    # The same folder can hold persona controls. Verdicts describe the plain base model only.
    hl_base = hl[hl.arm == "base"] if not hl.empty else hl
    lot_base = lot[lot.arm == "base"] if not lot.empty else lot
    return {
        "backend": record.get("backend"), "real": record.get("real"), "sampling": record.get("sampling"),
        "n_results": len(rows), "invalid": sum(not row["valid"] for row in rows),
        "holt_laury": hl.to_dict("records"), "holt_laury_verdict": verdict_holt_laury(hl_base),
        "lotteries": lot.to_dict("records"), "lotteries_verdict": verdict_lotteries(lot_base),
        "lotteries_by_rare_kind": lotteries_by_rare_kind(rows),
        "holt_laury_rows": rows_summary(rows),
        "controls": {name: control_shift(rows, name) for name in ("holt_laury", "lotteries")},
        "mean_latency_s": float(np.mean([row["latency_s"] for row in rows])) if rows else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run")
    args = parser.parse_args()
    summary = analyze(args.run)
    print(json.dumps(summary, indent=2))
    (Path(args.run) / "noise_check.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
