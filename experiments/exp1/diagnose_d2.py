"""Was the late D2 shift (fixed gate-closed probe, lawn_edge to back_row, nights 28-30) a learning effect?

The run kept only its final adapter, and the LoRA's starting matrices weren't seeded, so the adapter from before the shift
can't be recovered. This rebuilds one: same base model, same logged rows, nights 8-27, from a new (seeded) start, and logs how
close the rebuilt probes come to the ones the run logged. From there it replays nights 28-30 three ways:

    normal           the run's own rows (that day plus 5 replay days)
    today_only       that day's rows, none of the older ones
    no_lawn_penalty  the run's rows, with negative advantages on lawn_edge set to 0 (the KL term stays)

Each gradient step is split by transition. With Adam's moments fixed for the step, the update is linear in the gradient:
    dtheta = -lr * (b1 * m_prev + (1 - b1) * clip * sum_i g_i) / (sqrt(v_new) + eps)
so each transition's share of the change in the probe's log-odds, to first order, is <grad f, -lr (1-b1) clip g_i / denom>,
with what's left carried by the momentum from earlier steps. The sum is checked against the actual parameter change.

Then the probe is measured again in 4 wordings (the original and 3 paraphrases) with every option order.
"""
import gc
import itertools
import json
import math
import sys
import time

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
from mlx.utils import tree_flatten, tree_map, tree_unflatten

from experiments.exp1 import observe
from experiments.exp1.learn import DEFAULTS, Sleeper, replay_rows
from experiments.exp1.run import POLITE_GB, QWEN_WEIGHTS, ROOT, _pi, probes

SHIFT_NIGHTS = (28, 29, 30)   # sleep.jsonl index: the nights after free days 21, 22 and 23
PROBE, TARGET = "D2 gate closed", "back_row"
REBUILD_SEED = 0
VARIANTS = ("normal", "today_only", "no_lawn_penalty")

PARAPHRASES = [
    ("RECENT MORNINGS\nYou haven't been to this class before; today is your first morning.\n\nNOW\nIt's 09:20 and you've arrived at the edge "
     "of the lawn where the class meets. The class has already started, and the instructor is leading from the front.\nWeather: sunny and "
     "bright.\n\nHOW YOU FEEL\nYou feel grimy and uncomfortable, a little tense, and lonely.\n\nYOUR OPTIONS\n",
     {"back_row": "Quietly join at the back of the group.", "wait_for_break": "Hold off at the edge until the next transition, then join.",
      "lawn_edge": "Settle into a spot along the lawn's edge."}),
    ("WHAT CAME BEFORE\nNothing yet. This is the first time you've come to this class.\n\nRIGHT NOW\nThe clock says 09:20. You're standing where "
     "the class lawn begins. People are already moving, and the instructor is up front.\nIt's a clear, sunny day.\n\nHOW YOU'RE DOING\nYou feel "
     "grimy and uncomfortable, a little tense, and lonely.\n\nWHAT YOU CAN DO\n",
     {"back_row": "Ease in at the very back of the class without any fuss.", "wait_for_break": "Stay at the edge and join when the class next changes activity.",
      "lawn_edge": "Take a place at the side of the lawn."}),
    ("This is your first morning at this class, so there's nothing to look back on.\n\nIt is 09:20 on a bright, sunny day. You've come to the edge "
     "of the lawn and the class has begun, led by the instructor at the front. You feel grimy and uncomfortable, a little tense, and lonely.\n\n"
     "You could do one of these:\n",
     {"back_row": "Slip into the last row, quietly.", "wait_for_break": "Stand by until the next transition and join then.",
      "lawn_edge": "Pick somewhere along the border of the lawn."}),
]


def _log(message):
    print(time.strftime("%H:%M:%S"), message, flush=True)


def _flat(tree):
    return dict(tree_flatten(tree))


def _unflat(flat):
    return tree_unflatten(list(flat.items()))


def odds(policy, probe):
    scores = policy.scores(probe)
    i = probe["shown"].index(TARGET)
    others = mx.concatenate([scores[:i], scores[i + 1:]])
    return scores[i] - mx.logsumexp(others)


def _option_grads(policy, row, k):
    _, grad = nn.value_and_grad(policy.model, lambda model: policy.score_one(row, k))(policy.model)
    mx.eval(grad)
    return grad


def odds_grad(policy, probe):
    """Gradient of the probe's log-odds of the target, one option at a time, as in Sleeper._sample_grad."""
    i = probe["shown"].index(TARGET)
    scores = mx.stop_gradient(policy.scores(probe))

    def f(s):
        return s[i] - mx.logsumexp(mx.concatenate([s[:i], s[i + 1:]]))
    dscores = mx.grad(f)(scores)
    mx.eval(dscores)
    total = None
    for k in range(len(probe["shown"])):
        c = float(dscores[k])
        if c == 0.0:
            continue
        grad = tree_map(lambda g: g * c, _option_grads(policy, probe, k))
        total = grad if total is None else tree_map(lambda a, b: a + b, total, grad)
        mx.eval(total)
    return _flat(total)


def split_grad(sleeper, row, scale):
    """One transition's gradient, split into its policy-gradient and KL parts."""
    policy = sleeper.policy
    scores = mx.stop_gradient(policy.scores(row))
    d_total = mx.grad(lambda s: sleeper._loss_of_scores(s, row, scale)[0])(scores)
    d_pg = mx.grad(lambda s: sleeper._loss_of_scores(s, row, scale)[1][0])(scores)
    _, (pg, kl, weight) = sleeper._loss_of_scores(scores, row, scale)
    mx.eval(d_total, d_pg, pg, kl, weight)
    g_pg, g_kl = None, None
    for k in range(len(row["shown"])):
        a, b = float(d_pg[k]), float(d_total[k] - d_pg[k])
        if a == 0.0 and b == 0.0:
            continue
        grad = _option_grads(policy, row, k)
        pg_part = tree_map(lambda g: g * a, grad)
        kl_part = tree_map(lambda g: g * b, grad)
        g_pg = pg_part if g_pg is None else tree_map(lambda x, y: x + y, g_pg, pg_part)
        g_kl = kl_part if g_kl is None else tree_map(lambda x, y: x + y, g_kl, kl_part)
        mx.eval(g_pg, g_kl)
    return _flat(g_pg), _flat(g_kl), float(pg), float(kl), float(weight)


def attributed_step(sleeper, rows, probe):
    """One Adam step on these rows, returning each transition's first-order share of the change in the probe's log-odds."""
    policy, model, settings, optimizer = sleeper.policy, sleeper.policy.model, sleeper.settings, sleeper.optimizer
    b1, b2 = optimizer.betas
    eps, lr = optimizer.eps, settings["lr"]
    scale = 1.0 / len(rows)
    f_before = odds(policy, probe)
    mx.eval(f_before)
    df = odds_grad(policy, probe)
    parts, total = [], None
    for row in rows:
        g_pg, g_kl, pg, kl, weight = split_grad(sleeper, row, scale)
        parts.append((row, g_pg, g_kl, pg, kl, weight))
        whole = {k: g_pg[k] + g_kl[k] for k in g_pg}
        total = whole if total is None else {k: total[k] + whole[k] for k in total}
        mx.eval(total)
    norm = math.sqrt(sum(float((g * g).sum()) for g in total.values()))
    clip = min(settings["max_grad_norm"] / (norm + 1e-6), 1.0)
    state = _flat(optimizer.state)
    denom = {k: mx.sqrt(b2 * state[f"{k}.v"] + (1 - b2) * mx.square(clip * total[k])) + eps for k in total}
    mx.eval(denom)

    def effect(tree):
        return sum(float((df[k] * (-lr * (1 - b1) * clip * tree[k] / denom[k])).sum()) for k in df)

    momentum = sum(float((df[k] * (-lr * b1 * state[f"{k}.m"] / denom[k])).sum()) for k in df)
    transitions = [{"day": row["day"], "decision": row["decision"], "choice": row["choice"], "outcome": row["outcome_label"], "advantage": row["advantage"],
                    "pi_then": row["pi"][row["choice"]], "weight": round(weight, 4), "pg": round(pg, 6), "kl": round(kl, 6),
                    "effect_pg": effect(g_pg), "effect_kl": effect(g_kl)} for row, g_pg, g_kl, pg, kl, weight in parts]
    before = {k: mx.array(v) for k, v in _flat(model.trainable_parameters()).items()}
    mx.eval(before)
    clipped = _unflat({k: clip * g for k, g in total.items()})
    optimizer.update(model, clipped)
    mx.eval(model.trainable_parameters(), optimizer.state)
    sleeper.steps_taken += 1
    after = _flat(model.trainable_parameters())
    actual_linear = sum(float((df[k] * (after[k] - before[k])).sum()) for k in df)
    f_after = odds(policy, probe)
    mx.eval(f_after)
    del parts, total, denom
    gc.collect()
    return {"odds_before": float(f_before), "odds_after": float(f_after), "momentum_effect": momentum, "grad_norm": norm, "clip": clip,
            "first_order_sum": momentum + sum(t["effect_pg"] + t["effect_kl"] for t in transitions), "first_order_actual_update": actual_linear,
            "transitions": transitions}


def wordings(probe):
    head, block = probe["observation"].split("YOUR OPTIONS\n")
    lines = dict(line[2:].split(": ", 1) for line in block.strip().splitlines())
    out = [("original", head + "YOUR OPTIONS\n", lines)] + [(f"paraphrase {i + 1}", text, options) for i, (text, options) in enumerate(PARAPHRASES)]
    return out


def measure(policy, probe):
    """pi(target) in each wording and every option order."""
    by_wording, values = {}, []
    for name, head, lines in wordings(probe):
        found = []
        for order in itertools.permutations(probe["shown"]):
            text = head + "\n".join(f"- {o}: {lines[o]}" for o in order)
            observe.check(text)
            found.append(_pi(policy, {"system": probe["system"], "observation": text, "shown": list(order)})[TARGET])
        by_wording[name] = {"mean": sum(found) / len(found), "min": min(found), "max": max(found)}
        values += found
    return {"mean": sum(values) / len(values), "min": min(values), "max": max(values), "prompts": len(values), "by_wording": by_wording}


class Rebuild:
    """The base model with a seeded fresh LoRA, trained on the logged rows, resumable night by night."""

    def __init__(self, run, out):
        self.run, self.folder = run, out / "rebuild"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.rows = [json.loads(line) | {"system": observe.SYSTEM} for line in (run / "trajectory.jsonl").read_text().splitlines()]
        self.nights = {n["index"]: n for n in map(json.loads, (run / "sleep.jsonl").read_text().splitlines())}
        self.config = json.loads((run / "config.json").read_text())
        self.settings = DEFAULTS | self.config["learn"]
        self.probes = {p["probe"]: p for p in probes(self.config["seed"])}
        self.policy = self.sleeper = None

    def load(self):
        from experiments.exp1.policy import QwenPolicy
        mx.random.seed(REBUILD_SEED)
        self.policy = QwenPolicy(self.config.get("model_weights") or QWEN_WEIGHTS, self.config["lora"]["rank"], self.config["lora"]["alpha"])
        self.sleeper = Sleeper(self.policy, self.settings)

    def unload(self):
        self.policy = self.sleeper = None
        gc.collect()
        mx.clear_cache()

    def restore(self, adapters, optimizer=None, steps=0):
        self.policy.model.load_weights(list(mx.load(str(adapters)).items()), strict=False)
        mx.eval(self.policy.model.trainable_parameters())
        self.sleeper = Sleeper(self.policy, self.settings)
        if optimizer:
            self.sleeper.load_optimizer_state(mx.load(str(optimizer)), steps)

    def save(self, name, extra):
        self.policy.save(self.folder / f"{name}.adapters.safetensors")
        mx.save_safetensors(str(self.folder / f"{name}.optimizer.safetensors"), self.sleeper.optimizer_state())
        (self.folder / f"{name}.json").write_text(json.dumps(extra | {"lora_step": self.sleeper.steps_taken}))

    def files(self, name):
        return self.folder / f"{name}.adapters.safetensors", self.folder / f"{name}.optimizer.safetensors", json.loads((self.folder / f"{name}.json").read_text())

    def rows_for(self, night, variant):
        day = self.nights[night]["day"]
        days = 0 if variant == "today_only" else self.settings["replay_days"]
        rows = replay_rows(self.rows, day, days)
        if variant == "no_lawn_penalty":
            rows = [r | {"advantage": 0.0} if r["choice"] == "lawn_edge" and r["advantage"] < 0 else r for r in rows]
        return rows

    def probe_pis(self):
        return {name: _pi(self.policy, p) for name, p in self.probes.items()}


def rebuild(job, ram_share, guard):
    """Nights 8-27 on the logged rows. One checkpoint, overwritten each night; gives memory back if room runs short."""
    log_file = job.folder / "nights.jsonl"
    done = sum(1 for _ in log_file.open()) if log_file.exists() else 0
    free = [i for i in sorted(job.nights) if job.nights[i]["phase"] == "free" and i < SHIFT_NIGHTS[0]]
    guard.before()
    job.load()
    if done:
        adapters, optimizer, extra = job.files("latest")
        job.restore(adapters, optimizer, extra["lora_step"])
        _log(f"rebuild resumes after {done} nights")
    for night in free[done:]:
        stats = job.sleeper.sleep(job.rows_for(night, "normal"))
        found = job.probe_pis()
        logged = job.nights[night]
        with log_file.open("a") as f:
            f.write(json.dumps({"night": night, "day": logged["day"], "kl": stats["kl"], "logged_kl": logged["kl"], "grad_norm": stats["grad_norm"], "logged_grad_norm": logged["grad_norm"],
                                "probes": found, "logged_probes": logged["probes_after"]}) + "\n")
        job.save("latest", {"night": night})
        _log(f"night {night}: {TARGET} on the probe {found[PROBE][TARGET]:.3f} (run logged {logged['probes_after'][PROBE][TARGET]:.3f}), kl {stats['kl']:.4f} (run {logged['kl']:.4f})")
        room, _, _ = ram_share.room_gb()
        if night != free[-1] and room + ram_share.MARGIN_GB < ram_share.FLOOR_GB:
            _log("giving memory back; will resume from this night")
            job.unload()
            guard.loaded = False
            guard.before()
            job.load()
            adapters, optimizer, extra = job.files("latest")
            job.restore(adapters, optimizer, extra["lora_step"])


def main(run, out):
    sys.path.insert(0, str(ROOT))
    from kokopelli.ops import ram_share
    guard = ram_share.Guard(f"{run.name}_d2_diagnostic", POLITE_GB, log=_log)
    job = Rebuild(run, out)
    rebuild(job, ram_share, guard)
    adapters, optimizer, extra = job.files("latest")
    probe = job.probes[PROBE]
    results = {"model_weights": job.config.get("model_weights") or str(QWEN_WEIGHTS), "rebuild_seed": REBUILD_SEED, "shift_nights": SHIFT_NIGHTS, "probe": PROBE, "target": TARGET,
               "before_shift": extra, "measure": {}, "variants": {}}
    target = out / "d2.json"

    def write():
        target.write_text(json.dumps(results, indent=1))

    with job.policy.without_adapter():
        results["measure"]["untrained"] = measure(job.policy, probe)
    results["measure"]["rebuilt_before_shift"] = measure(job.policy, probe)
    job.restore(run / "checkpoint" / "adapters.safetensors")
    results["measure"]["run_final_adapter"] = measure(job.policy, probe)
    results["run_final_adapter_check"] = job.probe_pis()[PROBE]
    write()
    for variant in VARIANTS:
        job.restore(adapters, optimizer, extra["lora_step"])
        nights = []
        for night in SHIFT_NIGHTS:
            rows = job.rows_for(night, variant)
            steps = [attributed_step(job.sleeper, rows, probe) for _ in range(job.settings["steps"])]
            nights.append({"night": night, "day": job.nights[night]["day"], "samples": len(rows), "steps": steps, "probe_after": job.probe_pis()[PROBE],
                           "logged_probe_after": job.nights[night]["probes_after"][PROBE]})
            results["variants"][variant] = {"nights": nights}
            write()
            _log(f"{variant} night {night}: {TARGET} {nights[-1]['probe_after'][TARGET]:.3f} (run logged {nights[-1]['logged_probe_after'][TARGET]:.3f})")
        results["measure"][f"after_{variant}"] = measure(job.policy, probe)
        write()
    _log("done")
