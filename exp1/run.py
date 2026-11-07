"""One life lived by a policy that learns while it sleeps. Experiment 1's model run.

    python -m exp1.run out/exp1/runs/exp1_lived_s0 --arm lived --seed 0 --policy qwen --lr 2e-5 --guardrails mmlu ifeval
    python -m exp1.run out/exp1/runs/exp1_table_s0 --policy table --lr 2.0          # the same loop with no model, for checks

Through the GPU queue for qwen (it loads about 18 GB). A killed run picks up from its last night with the same command:
the life is replayed from the trajectory's choices (the world is deterministic given them), and the adapter, optimizer,
baseline and trajectory are restored from that night's checkpoint.

Writes, in the run folder:
    config.json            settings, the model weights used, and the git commit
    outcome_schedule.json  every outcome this life could get, drawn before it started (for audit)
    trajectory.jsonl       one row per decision: state, felt text, the observation, pi, choice, outcome, reward, advantage
    sleep.jsonl            one row per night: the update's losses and KL, and pi before and after on today's states and probes
    status.json            where the run is, for the panel
    checkpoint/            adapter, optimizer and learner state after the last night
    guardrails.json        base vs trained on MMLU and IFEval subsets, if asked for
    reference.json         random, always-safe and tabular baselines for this seed and arm
    report.json            shares, rewards and the predicted direction, beside those baselines
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import mlx.core as mx
import numpy as np

from exp1 import baselines, observe
from exp1 import homeostasis as H
from exp1.learn import DEFAULTS, Baseline, Sleeper, replay_rows
from exp1.world import ARMS, Decision, Life
from life import scenario

ROOT = Path(__file__).resolve().parents[1]
QWEN_WEIGHTS = Path.home() / "Desktop/kokopelli/models/Qwen3-VL-8B-Instruct"
PROBE_GROUPS = (("D1", None), ("D2", True), ("D2", False), ("D3", None))


def _write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=1, default=_plain))
    os.replace(temporary, path)


def _plain(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    raise TypeError(type(value))


def _append(path, row):
    with open(path, "a") as file:
        file.write(json.dumps(row, default=_plain) + "\n")


def _git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or None
    except OSError:
        return None


def probes(seed):
    """Fixed observations, one per decision (D2 with and without the gap): a first morning at the average entry state.

    Scored every night, they show the policy shifting with nothing else changing, unlike real states whose history and
    feelings differ from day to day."""
    rng = np.random.default_rng([seed, 31])
    rows = []
    for decision, gate in PROBE_GROUPS:
        h = np.mean(H.entry_states(decision, rng, 2000, None, gate), axis=0)
        arrival = None if decision == "D1" else ("09:08" if gate else "09:20")
        shown = scenario.shown_options(decision, None if decision == "D1" else _clock(arrival), bool(gate))
        pending = Decision(0, "probe", None, decision, shown, [], h, H.felt_text(h), None, arrival, gate if decision == "D2" else None)
        name = decision if gate is None else f"{decision} gate {'open' if gate else 'closed'}"
        rows.append({"probe": name, "system": observe.SYSTEM, "observation": observe.observation(pending, [], seed), "shown": shown})
    return rows


def _clock(text):
    from datetime import time as clock
    hour, minute = map(int, text.split(":"))
    return clock(hour, minute)


def _logp(policy, row):
    logp = policy.log_probs(row)
    mx.eval(logp)
    return np.array(logp, dtype=np.float64)


def _pi(policy, row, logp=None):
    logp = _logp(policy, row) if logp is None else logp
    return dict(zip(row["shown"], np.exp(logp).round(6).tolist()))


def make_policy(kind, weights, rank, alpha, adapter=None, temperature=1.0):
    if kind == "table":
        from exp1.policy import TablePolicy
        policy = TablePolicy()
        if adapter:
            policy.model.load_weights(str(adapter))
        return policy
    from exp1.policy import QwenPolicy
    return QwenPolicy(weights, rank, alpha, adapter, temperature)


class Run:
    def __init__(self, folder, arm, seed, days, policy_kind, settings, weights=QWEN_WEIGHTS, rank=16, alpha=32, temperature=1.0):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.files = {name: self.folder / name for name in ("trajectory.jsonl", "sleep.jsonl", "status.json", "config.json")}
        self.checkpoint = self.folder / "checkpoint"
        self.arm, self.seed, self.days, self.kind = arm, seed, days, policy_kind
        self.settings = DEFAULTS | settings
        config = {"arm": arm, "seed": seed, "days": days, "policy": policy_kind, "learn": self.settings,
                  "model_weights": str(weights) if policy_kind == "qwen" else None, "lora": {"rank": rank, "alpha": alpha, "targets": ["q_proj", "v_proj"]},
                  "choice_temperature": temperature, "reward": "homeostatic drive reduction, outcome step only (exp1/homeostasis.py)",
                  "commit": _git_commit(), "system_prompt": observe.SYSTEM}
        resuming = (self.checkpoint / "state.json").exists()
        if resuming:
            saved = json.loads(self.files["config.json"].read_text())
            same = ("arm", "seed", "days", "policy", "choice_temperature")
            if {k: saved.get(k, 1.0 if k == "choice_temperature" else None) for k in same} != {k: config[k] for k in same}:
                raise ValueError("this folder holds a different run; use a new folder")
        else:
            config["started"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _write_json(self.files["config.json"], config)
        adapter = self.checkpoint / "adapters.safetensors" if resuming else None
        if policy_kind == "table" and temperature != 1.0:
            raise ValueError("--choice-temperature is for the qwen policy")
        self.policy = make_policy(policy_kind, weights, rank, alpha, adapter, temperature)
        self.sleeper = Sleeper(self.policy, self.settings)
        self.life = Life(seed, arm, days)
        _write_json(self.folder / "outcome_schedule.json", self.life.schedule)
        self.baseline = Baseline(scenario.DECISIONS)
        self.trajectory = []
        self.probes = probes(seed)
        self.started = time.time()
        if resuming:
            self._resume()
        else:
            for name in ("trajectory.jsonl", "sleep.jsonl"):
                self.files[name].write_text("")

    # ----- resume -----
    def _resume(self):
        state = json.loads((self.checkpoint / "state.json").read_text())
        rows = [json.loads(line) for line in self.files["trajectory.jsonl"].read_text().splitlines()][:state["decisions"]]
        for row in rows:
            record = self.life.choose(row["choice"])
            if abs(record["reward"] - row["reward"]) > 1e-9 or record["outcome_label"] != row["outcome_label"]:
                raise RuntimeError(f"replaying decision {len(self.trajectory)} gave a different outcome; the world changed since this run started")
            self.trajectory.append(row)
        self.files["trajectory.jsonl"].write_text("".join(json.dumps(row, default=_plain) + "\n" for row in rows))
        nights = [json.loads(line) for line in self.files["sleep.jsonl"].read_text().splitlines()][:state["nights"]]
        self.files["sleep.jsonl"].write_text("".join(json.dumps(row, default=_plain) + "\n" for row in nights))
        self.baseline = Baseline(scenario.DECISIONS, state["baseline"])
        self.sleeper.load_optimizer_state(mx.load(str(self.checkpoint / "optimizer.safetensors")), state["lora_step"])
        print(f"resumed after {len(rows)} decisions and {len(nights)} nights", flush=True)

    def _save_checkpoint(self, nights):
        self.checkpoint.mkdir(exist_ok=True)
        if self.kind == "qwen":
            self.policy.save(self.checkpoint / "adapters.safetensors")
        else:
            self.policy.model.save_weights(str(self.checkpoint / "adapters.safetensors"))
        state = self.sleeper.optimizer_state()
        if state:
            mx.save_safetensors(str(self.checkpoint / "optimizer.safetensors"), state)
        _write_json(self.checkpoint / "state.json", {"decisions": len(self.trajectory), "nights": nights, "baseline": self.baseline.values,
                                                     "lora_step": self.sleeper.steps_taken})

    # ----- the life -----
    def status(self, phase, **extra):
        rows = self.trajectory
        _write_json(self.files["status.json"], {"phase": phase, "decisions": len(rows), "free_day": self.life.free_day if not self.life.exploring else 0,
                                                "days": self.days, "explore_days": self.life.explore_days, "lora_step": self.sleeper.steps_taken,
                                                "elapsed_s": round(time.time() - self.started), "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                                "pid": os.getpid(), **extra})

    def decide(self):
        pending = self.life.pending()
        row = {"system": observe.SYSTEM, "observation": observe.observation(pending, self.life.records, self.seed), "shown": pending.shown}
        logp = _logp(self.policy, row)
        pi = _pi(self.policy, row, logp)
        base_logp = self.policy.base_log_probs(row)
        n = len(self.trajectory)
        if pending.forced:
            choice = pending.forced
        else:
            p = np.exp(logp - logp.max())
            choice = pending.shown[np.random.default_rng([self.seed, 11, n]).choice(len(p), p=p / p.sum())]
        reason = None if pending.forced else self.policy.reason(row, choice, seed=self.seed * 100003 + n) if self.kind == "qwen" else ""
        record = self.life.choose(choice)
        baseline, advantage = self.baseline.advantage(pending.decision, record["reward"])
        out = {"n": n, **record, **row, "pi": pi, "logp": logp.tolist(), "base_pi": dict(zip(pending.shown, np.exp(base_logp).round(6).tolist())),
               "base_logp": base_logp.tolist(), "reason": reason, "baseline": round(baseline, 6), "advantage": round(advantage, 6),
               "trained": not pending.forced, "lora_step": self.sleeper.steps_taken}
        del out["system"]   # in config.json; the same for every row
        self.trajectory.append(out)
        _append(self.files["trajectory.jsonl"], out)
        return out

    def night(self, morning_rows):
        """The sleep update after a morning. Exploration mornings aren't trained on, so their nights only log that."""
        day = morning_rows[0]["day"]
        base = {"index": morning_rows[0]["index"], "day": day, "phase": morning_rows[0]["phase"]}
        if morning_rows[0]["phase"] != "free":
            return base | {"steps": 0, "skipped": "exploration morning: forced choices aren't trained on"}
        rows = [r | {"system": observe.SYSTEM} for r in replay_rows(self.trajectory, day, self.settings["replay_days"])]
        today = [r | {"system": observe.SYSTEM} for r in morning_rows]
        probes_before = {p["probe"]: _pi(self.policy, p) for p in self.probes}
        stats = self.sleeper.sleep(rows)
        today_after = [{"decision": r["decision"], "choice": r["choice"], "advantage": r["advantage"], "pi_before": r["pi"],
                        "pi_after": _pi(self.policy, r)} for r in today]
        probes_after = {p["probe"]: _pi(self.policy, p) for p in self.probes}
        return base | stats | {"replay_days": self.settings["replay_days"], "today": today_after,
                               "probes_before": probes_before, "probes_after": probes_after}

    def live(self, pause=None):
        """Lives to the end and returns True, or returns False after a night's checkpoint if pause() says to stop."""
        nights = len(self.files["sleep.jsonl"].read_text().splitlines())
        self.status("living")
        while not self.life.finished:
            index = self.life.index
            morning = [row for row in self.trajectory if row["index"] == index]
            while not self.life.finished and self.life.index == index:
                morning.append(self.decide())
                self.status("living")
            self.status("sleeping", night_after=morning[0]["day"] if morning[0]["phase"] == "free" else "exploration")
            night = self.night(morning)
            _append(self.files["sleep.jsonl"], night)
            nights += 1
            self._save_checkpoint(nights)
            print(f"morning {index} ({morning[0]['phase']} day {morning[0]['day']}): "
                  + ", ".join(f"{r['decision']} {r['choice']} r={r['reward']:+.3f}" for r in morning)
                  + (f" | sleep kl={night.get('kl', 0):.4f} grad={night.get('grad_norm', 0):.3f}" if night.get("steps") else ""), flush=True)
            if pause and not self.life.finished and pause():
                return False
        self.status("finished")
        return True

    def finish(self, guardrail_checks=(), lives=200):
        if guardrail_checks:
            self.status("guardrails")
            from exp1 import guardrails
            found = guardrails.run(self.policy, guardrail_checks)
            _write_json(self.folder / "guardrails.json", {"results": found, "flag_points": guardrails.FLAG_POINTS})
        self.status("baselines")
        reference = baselines.reference(self.seed, self.arm, self.days, lives)
        _write_json(self.folder / "reference.json", reference)
        summary = baselines.summarize_rows(self.trajectory, self.days)
        nights = [json.loads(line) for line in self.files["sleep.jsonl"].read_text().splitlines()]
        trained = [n for n in nights if n.get("steps")]
        _write_json(self.folder / "report.json", {
            "arm": self.arm, "seed": self.seed, "policy": self.kind, "decisions": len(self.trajectory), "nights_trained": len(trained),
            "lora_steps": self.sleeper.steps_taken, **summary, "direction": baselines.direction(self.arm, summary["shares"]),
            "final_probes": trained[-1]["probes_after"] if trained else None,
            "first_probes": trained[0]["probes_before"] if trained else None,
            "final_kl": trained[-1]["kl"] if trained else None,
            "versus": {"random_mean_reward": reference["random"]["this_seed"]["mean_reward"]["all"],
                       "always_safe_mean_reward": reference["always_safe"]["this_seed"]["mean_reward"]["all"]}})
        self.status("done")


POLITE_GB = 20   # Qwen bf16 plus a sleep step peaks at about 18.5 GB


def polite(make, folder):
    """Live the whole life as a polite job (ram_share.py). Waits for room before loading the model. After each night's
    checkpoint, if the room left falls below ram_share's floor, unloads and waits, then resumes from that checkpoint.
    Returns the Run, model loaded, with its life finished."""
    import gc
    sys.path.insert(0, str(ROOT))
    import ram_share

    def log(message):
        print(message, flush=True)
        status = folder / "status.json"
        if status.exists():   # keep the panel from calling a waiting run stopped
            value = json.loads(status.read_text())
            _write_json(status, value | {"phase": "waiting for memory", "updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "waiting": message})

    def short():
        room, _, _ = ram_share.room_gb()
        return room + ram_share.MARGIN_GB < ram_share.FLOOR_GB

    guard = ram_share.Guard(folder.name, POLITE_GB, log=log)
    while True:
        guard.before()
        run = make()
        if run.live(pause=short):
            return run
        log(f"ram_share: {folder.name} gives back its model after {len(run.trajectory)} decisions and will resume from that checkpoint")
        del run
        gc.collect()
        mx.clear_cache()
        guard.loaded = False


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder")
    parser.add_argument("--arm", choices=ARMS, default="lived")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--days", type=int, default=25)
    parser.add_argument("--policy", choices=("qwen", "table"), default="qwen")
    parser.add_argument("--weights", default=str(QWEN_WEIGHTS))
    parser.add_argument("--lr", type=float, default=DEFAULTS["lr"])
    parser.add_argument("--beta", type=float, default=DEFAULTS["beta"])
    parser.add_argument("--steps", type=int, default=DEFAULTS["steps"], choices=(1, 2, 3, 4))
    parser.add_argument("--replay-days", type=int, default=DEFAULTS["replay_days"])
    parser.add_argument("--choice-temperature", type=float, default=1.0,
                        help="divide option scores by this before the softmax; 1.0 is the spec, above 1 flattens pi")
    parser.add_argument("--guardrails", nargs="*", default=[], choices=("mmlu", "ifeval"))
    parser.add_argument("--reference-lives", type=int, default=200)
    parser.add_argument("--polite", action="store_true",
                        help="share memory through ram_share.py: wait for room before loading Qwen, and give it back after a night if room runs out")
    options = parser.parse_args()
    settings = {"lr": options.lr, "beta": options.beta, "steps": options.steps, "replay_days": options.replay_days}
    make = lambda: Run(options.folder, options.arm, options.seed, options.days, options.policy, settings, options.weights,
                       temperature=options.choice_temperature)
    run = polite(make, Path(options.folder)) if options.polite else make()
    if not options.polite:
        run.live()
    run.finish(options.guardrails, options.reference_lives)
    print(json.dumps(json.loads((run.folder / "report.json").read_text())["direction"], indent=1))


if __name__ == "__main__":
    main()
