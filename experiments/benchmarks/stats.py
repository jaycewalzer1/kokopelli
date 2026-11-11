"""Statistics for a run: arm means with confidence intervals, tests of the pre-registered contrasts, and the pass rule.

The unit that matters: a seed is one trained adapter. 50 samples from one adapter show that adapter's behavior well,
but they can't show that training reliably produces it. So tests shuffle within a seed, and the pass rule also
requires the right direction in each of several seeds. See HANDOFF.md for what this can and can't claim.
"""
import numpy as np
import pandas as pd

STRATA = ["seed", "item_id", "template"]


def to_frame(rows):
    """Valid, scored samples as a table. Invalid samples are counted separately by parse_failures."""
    columns = ["arm", "instrument", "item_id", "template", "seed", "sample", "score"]
    frame = pd.DataFrame([{key: row[key] for key in columns} for row in rows if row["valid"] and row["score"] is not None], columns=columns)
    frame["score"] = pd.to_numeric(frame["score"])
    return frame


def bootstrap_ci(values, strata=None, n_boot=2000, level=0.95, seed=0):
    """A bootstrap 95% confidence interval for a mean.

    The idea: we have one set of samples, but want to know how much the mean could vary if we collected them again. So
    we pretend our samples are the whole population, redraw from them with replacement thousands of times, and see where
    the middle 95% of the means falls. No normal-curve assumption is needed.

    `strata` keeps each group's sample count fixed in every redraw (for example, each item and template), so an
    unbalanced redraw can't move the mean just by favoring easy items.
    """
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    groups = [np.arange(len(values))] if strata is None else [np.flatnonzero(strata == value) for value in pd.unique(strata)]
    means = np.zeros(n_boot)
    for group in groups:
        draws = rng.integers(0, len(group), size=(n_boot, len(group)))
        means += values[group][draws].sum(axis=1)
    means /= len(values)
    tail = (1 - level) / 2 * 100
    return (float(np.percentile(means, tail)), float(np.percentile(means, 100 - tail)))


def _strata_labels(frame):
    return frame[STRATA].astype(str).agg("|".join, axis=1).to_numpy()


def _one_sample_each(frame):
    """True when each (seed, item, template) holds one sample, as with a guardrail's questions."""
    return len(frame) > 0 and frame.groupby(STRATA).size().max() == 1


def _ci_labels(frame):
    """What a bootstrap may redraw within. With one sample per stratum, redrawing inside a stratum changes nothing and
    gives a falsely exact interval of zero width. So in that case the items themselves are redrawn, within each seed."""
    return frame.seed.astype(str).to_numpy() if _one_sample_each(frame) else _strata_labels(frame)


def _matched(frame, arm_a, arm_b):
    """Only strata both arms have, so a difference can't come from one arm having answered different items."""
    a, b = frame[frame.arm == arm_a], frame[frame.arm == arm_b]
    shared = set(_strata_labels(a)) & set(_strata_labels(b))
    return a[np.isin(_strata_labels(a), list(shared))], b[np.isin(_strata_labels(b), list(shared))]


def permutation_test(a_values, b_values, a_strata=None, b_strata=None, n_perm=5000, seed=0):
    """A two-sided permutation test for a difference in means.

    The idea: if the arm made no difference, the labels "a" and "b" are arbitrary. So we shuffle them many times and
    count how often the shuffled difference is at least as big as the real one. That share is the p-value: how often
    chance alone would give a gap this large. Shuffling only within a stratum (same seed, item and template) means an
    item's difficulty can't be mistaken for an arm effect.
    """
    a_values, b_values = np.asarray(a_values, float), np.asarray(b_values, float)
    if len(a_values) == 0 or len(b_values) == 0:
        return float("nan")
    a_strata = np.zeros(len(a_values), int) if a_strata is None else a_strata
    b_strata = np.zeros(len(b_values), int) if b_strata is None else b_strata
    observed = a_values.mean() - b_values.mean()
    rng = np.random.default_rng(seed)

    strata = []
    for label in pd.unique(np.concatenate([a_strata, b_strata])):
        pool = np.concatenate([a_values[a_strata == label], b_values[b_strata == label]])
        strata.append((pool, int((a_strata == label).sum())))
    extreme = 0
    for _ in range(n_perm):
        a_sum = b_sum = 0.0
        for pool, n_a in strata:
            shuffled = rng.permutation(pool)
            a_sum += shuffled[:n_a].sum()
            b_sum += shuffled[n_a:].sum()
        if abs(a_sum / len(a_values) - b_sum / len(b_values)) >= abs(observed) - 1e-12:
            extreme += 1
    # The +1s count the real labeling as one of the shuffles, so a p-value can never be exactly 0.
    return (extreme + 1) / (n_perm + 1)


def cohens_d(a_values, b_values):
    """An effect size: the gap between means, in units of the typical spread. Around 0.2 is small and 0.8 is large."""
    a_values, b_values = np.asarray(a_values, float), np.asarray(b_values, float)
    if len(a_values) < 2 or len(b_values) < 2:
        return float("nan")
    pooled = np.sqrt(((len(a_values) - 1) * a_values.var(ddof=1) + (len(b_values) - 1) * b_values.var(ddof=1)) / (len(a_values) + len(b_values) - 2))
    return float((a_values.mean() - b_values.mean()) / pooled) if pooled > 0 else float("nan")


def holm(p_values):
    """Holm correction for testing several contrasts at once.

    With 4 tests at alpha .05, the chance of at least one false alarm is about 19%, not 5%. Holm fixes this: sort the
    p-values, multiply the smallest by 4, the next by 3, and so on. Keep them from ever going down along the way, and
    cap them at 1. It's a safer but less strict cousin of the Bonferroni correction, which multiplies every one by 4.
    """
    p_values = list(p_values)
    order = sorted((p, i) for i, p in enumerate(p_values) if p == p)  # p == p skips NaN
    adjusted = [float("nan")] * len(p_values)
    worst = 0.0
    for rank, (p, index) in enumerate(order):
        worst = max(worst, min(1.0, p * (len(order) - rank)))
        adjusted[index] = worst
    return adjusted


def difference_ci(a, b, n_boot=2000, seed=0):
    """A bootstrap interval for the difference between two arms' means."""
    if a.empty or b.empty:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    if _one_sample_each(a) and _one_sample_each(b):
        # Both arms answered the same questions, so compare question by question. Easy questions are easy for both,
        # and pairing removes that shared variation, which makes the interval properly narrower.
        pairs = a[STRATA + ["score"]].merge(b[STRATA + ["score"]], on=STRATA, suffixes=("_a", "_b"))
        return bootstrap_ci((pairs.score_a - pairs.score_b).to_numpy(float), strata=pairs.seed.astype(str).to_numpy(), n_boot=n_boot, seed=seed)
    def boots(frame):
        values, labels = frame.score.to_numpy(float), _ci_labels(frame)
        total = np.zeros(n_boot)
        for label in pd.unique(labels):
            group = values[labels == label]
            total += group[rng.integers(0, len(group), size=(n_boot, len(group)))].sum(axis=1)
        return total / len(values)
    differences = boots(a) - boots(b)
    return (float(np.percentile(differences, 2.5)), float(np.percentile(differences, 97.5)))


def arm_table(frame):
    """Mean and bootstrap CI per arm and instrument."""
    rows = []
    for (instrument, arm), group in frame.groupby(["instrument", "arm"]):
        low, high = bootstrap_ci(group.score, strata=_ci_labels(group))
        rows.append({"instrument": instrument, "arm": arm, "n": len(group), "mean": group.score.mean(),
                     "sd": group.score.std(), "ci_low": low, "ci_high": high})
    return pd.DataFrame(rows)


def template_table(frame):
    """The same, per paraphrase. If one wording shows an effect and the others don't, the effect belongs to the wording."""
    rows = []
    for (instrument, template, arm), group in frame.groupby(["instrument", "template", "arm"]):
        low, high = bootstrap_ci(group.score, strata=_ci_labels(group))
        rows.append({"instrument": instrument, "template": template, "arm": arm, "n": len(group), "mean": group.score.mean(), "ci_low": low, "ci_high": high})
    return pd.DataFrame(rows)


def seed_table(frame):
    return frame.groupby(["instrument", "arm", "seed"], as_index=False).score.agg(n="size", mean="mean")


def parse_failures(rows):
    """Parse failure rates per arm and instrument. A gap between arms can itself bias results, so reports show these."""
    table = pd.DataFrame([{"arm": r["arm"], "instrument": r["instrument"], "valid": r["valid"], "retried": r["attempts"] > 1} for r in rows])
    if table.empty:
        return table
    return table.groupby(["instrument", "arm"], as_index=False).agg(
        n=("valid", "size"), invalid=("valid", lambda v: int((~v).sum())), retried=("retried", "sum"),
        invalid_rate=("valid", lambda v: float((~v).mean())))


def evaluate_contrasts(frame, config, n_perm=5000):
    """Test each pre-registered contrast. Returns one row per contrast, with a plain status."""
    settings, rows = config["settings"], []
    for contrast in config["contrasts"]:
        rows.append(_evaluate_one(frame, contrast, settings, n_perm))
    tested = [row for row in rows if row["kind"] == "difference"]
    for row, adjusted in zip(tested, holm([row["p"] for row in tested]), strict=False):
        row["p_holm"] = adjusted
    for row in rows:
        row["status"] = _status(row, settings)
    return pd.DataFrame(rows)


def _evaluate_one(frame, contrast, settings, n_perm):
    part = frame[frame.instrument == contrast["instrument"]]
    a, b = _matched(part, contrast["a"], contrast["b"])
    row = {"id": contrast["id"], "kind": contrast["kind"], "instrument": contrast["instrument"], "a": contrast["a"], "b": contrast["b"],
           "expected": contrast.get("direction", ""), "margin": contrast.get("margin"), "n_a": len(a), "n_b": len(b), "difference": float("nan"),
           "ci_low": float("nan"), "ci_high": float("nan"), "d": float("nan"), "p": float("nan"), "p_holm": float("nan"),
           "seeds_right": 0, "seeds_wrong": 0, "seeds_total": 0}
    if a.empty or b.empty:
        return row
    row["difference"] = float(a.score.mean() - b.score.mean())
    row["ci_low"], row["ci_high"] = difference_ci(a, b)
    row["d"] = cohens_d(a.score, b.score)
    if contrast["kind"] == "difference":
        row["p"] = permutation_test(a.score.to_numpy(), b.score.to_numpy(), _strata_labels(a), _strata_labels(b), n_perm=n_perm)
        sign = 1 if contrast["direction"] == "positive" else -1
        per_seed = a.groupby("seed").score.mean() - b.groupby("seed").score.mean()
        row["seeds_total"] = int(per_seed.notna().sum())
        row["seeds_right"] = int((per_seed * sign > 0).sum())
        row["seeds_wrong"] = int((per_seed * sign <= 0).sum())
    return row


def _status(row, settings):
    if row["difference"] != row["difference"]:
        return "not run"
    if row["kind"] == "difference":
        sign = 1 if row["expected"] == "positive" else -1
        right_way = row["difference"] * sign > 0
        significant = row["p_holm"] < settings["alpha"]
        seeds_ok = row["seeds_right"] >= settings["min_seeds_right"] and row["seeds_wrong"] <= settings["max_seeds_wrong"]
        if right_way and significant and seeds_ok:
            return "pass"
        if right_way and significant:
            return "fail: too few seeds agree"
        if significant:
            return "fail: significant, wrong direction"
        return "fail: not significant"
    if row["kind"] == "equivalence":
        # A non-significant difference doesn't show that two arms are the same, since the test may just lack power.
        # To claim "near", the whole interval must fit inside the margin.
        return "pass" if -row["margin"] <= row["ci_low"] and row["ci_high"] <= row["margin"] else "inconclusive: interval exceeds margin"
    if row["kind"] == "guardrail":
        # The point estimate decides. With a few hundred questions, the interval is often wider than the margin (see HANDOFF.md).
        if abs(row["difference"]) > row["margin"]:
            return "fail: moved more than margin"
        return "pass" if -row["margin"] <= row["ci_low"] and row["ci_high"] <= row["margin"] else "pass (point estimate only: interval exceeds margin)"
    raise ValueError(f"Unknown contrast kind: {row['kind']}")
