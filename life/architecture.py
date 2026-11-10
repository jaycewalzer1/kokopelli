"""The whole system on one page: what exists, what's planned, and what is running. Nothing here starts or changes anything.

NODES and EDGES are the part to edit. A status comes from reading the code, so change it when the code changes:
    built     the code exists and does what the plan asks of it
    partial   some of it exists, and `why` says what's missing
    unproven  the code runs, but hasn't been shown to work
    planned   only the plan has it, so `files` stays empty
`kind` is what a part is, which sets its shape on the chart: a model, stored data, a process or loop step, or an input or output.
`files` are in this checkout, and are checked against the disk by tests/test_life_architecture.py. `branch_files` live only in a worktree
under .claude/worktrees, on a branch not merged here, and are only checked while that worktree exists. `plan` is a section of Kokopelli_Perspectives.

`at` is [column, row] on the desktop chart. An edge's `active` and `pulse` name the flags and counts snapshot() measures:
it moves while any active flag is true, and sends a token for each new row a pulse counts. An edge without them stays still.
`label_at` picks the stretch of an edge to label and how far along it. Route tokens: a port is a side and how far along it ("b.35"), "x1.5" runs along the gap right of column 1, "y3.5" the gap below row 3.
"""
import time
from pathlib import Path

from homeostatic import watch
from life import pipeline
from life.pipeline import STALL_SECONDS, beats_baselines, best_validation, plural, ps_listing, python_lines, runs_module
from settings import HOMEOSTATIC_OUT, HOMEOSTATIC_SEEDS, PIPELINE_PATHS, ROOT

STATUSES = {"built": "Built", "partial": "Partly built", "unproven": "Not working yet", "planned": "Planned"}

KINDS = {"model": "Model", "data": "Stored data", "io": "Input or output", "process": "Process or loop step"}

# What each section of Kokopelli_Perspectives is about, for the side panel.
PLAN_SECTIONS = {"§05": "The proposal", "§06": "System overview", "§07": "Generating the life", "§08": "World state", "§09": "The 30-second loop",
                 "§10": "Inside the agent", "§11": "The memory vault", "§12": "The imprint gate", "§13": "Training", "§13b": "The sleep interpreter",
                 "§14": "What success looks like", "§15": "Build notes"}

LANES = [
    {"name": "The life", "rows": [0, 1]},
    {"name": "The 30-second loop", "rows": [2, 3]},
    {"name": "Inside the agent", "rows": [4, 4]},
    {"name": "Sleep: living becomes weights", "rows": [5, 6]},
    {"name": "Around the system", "rows": [7, 7]},
]

NODES = [
    # The life
    {"id": "seed", "name": "Base prompt", "at": [0, 0], "status": "built", "kind": "io", "plan": "§07",
     "does": "The human-written start of a life: prompt, birth date, place, family, temperament and anchored events.",
     "why": "Stored with each run. Coming from outside the model is what stops a life being circular.",
     "files": ["life/seed.py"]},
    {"id": "tree", "name": "Life generator", "at": [1, 0], "status": "partial", "kind": "process", "plan": "§07",
     "does": "Writes a life top-down as a tree of time windows, from the whole life to 30 seconds, opening each lazily.",
     "why": "It writes real text on Qwen through life.overnight, down to 30-second scenes. The plan goes on to frames that tell Cosmos what to render, and nothing here does. The panel's own Run button only writes mock text.",
     "files": ["life/engine.py", "life/windows.py", "life/generator.py", "life/llm_generator.py", "life/prompts.py", "life/overnight.py"]},
    {"id": "state", "name": "World state", "at": [2, 0], "status": "partial", "kind": "data", "plan": "§08",
     "does": "An append-only log of the life. Current state is a replay of it, and written rows can't be edited.",
     "why": "The timeline is real and guarded. State holds only place, people, money and skills: the plan's places with reference images, health, job and possessions don't exist.",
     "files": ["life/store.py"]},
    {"id": "resolver", "name": "Resolver", "at": [3, 0], "status": "partial", "kind": "process", "plan": "§05",
     "does": "Decides which pressures in a window arose and logs what followed.",
     "why": "It's seeded dice. A stance only flips the sign of a small change, so decisions don't yet have the real consequences §05 asks for.",
     "files": ["life/resolver.py"]},
    {"id": "random", "name": "Random agent", "at": [4, 0], "status": "built", "kind": "process",
     "does": "Stands in for the agent at every choice point. It picks a verb from the stage's actions, and engage or avoid.",
     "why": "This is who lives every life so far. It tests the machinery and has no view of anything it picks between.",
     "files": ["life/agent.py"]},
    {"id": "backtest", "name": "Backtest grader", "at": [0, 1], "status": "partial", "kind": "process", "plan": "§08, §13b",
     "does": "Would compare a simulated timeline with a real life such as Van Gogh's, walled off from everything that trains.",
     "why": "The wall exists: hidden targets sit in their own table, and only life/scoring.py reads them. Nothing compares or grades anything.",
     "files": ["life/scoring.py", "life/store.py"]},
    {"id": "recall", "name": "Writer's recall", "at": [1, 1], "status": "built", "kind": "process",
     "does": "Gives the generator the past as a person holds it: where you are in life, recent detail fading to gist, and moments that stuck.",
     "why": "Used by real runs only. It serves the writer of the world, so it is not the agent's memory vault.",
     "files": ["life/memory.py"]},
    # The 30-second loop
    {"id": "loop", "name": "30-second loop", "at": [0, 2], "status": "partial", "kind": "process", "plan": "§09",
     "does": "Steps the sim 30 seconds, renders it, shows it to the agent, applies the decision, and checks for drift. Logs every step and resumes from a checkpoint.",
     "why": "Only on the feat/wm-agent-loop worktree, not merged, with uncommitted changes to run.py. It has run all the way through on mocks. Whether a real model has run in it is under Live. Its own copy of life/ differs from this checkout's.",
     "files": [], "branch_files": [".claude/worktrees/wm-agent-loop/runtime/loop.py", ".claude/worktrees/wm-agent-loop/runtime/run.py", ".claude/worktrees/wm-agent-loop/runtime/adapters/life_db.py", ".claude/worktrees/wm-agent-loop/runtime/mocks/world_model.py"]},
    {"id": "imprint", "name": "Imprint gate", "at": [1, 2], "status": "planned", "kind": "process", "plan": "§12",
     "does": "Would have a cheap LLM call decide which scenes are worth the cost of rendering.",
     "why": "No code. The generator's salience sets how deep a window opens, which is a different job, and no render depends on it.",
     "files": []},
    {"id": "cosmos", "name": "Cosmos3-Nano", "at": [2, 2], "status": "built", "kind": "model", "plan": "§06",
     "does": "The world model: renders a clip from text, from an image, or carrying on from a video.",
     "why": "Runs locally and has made clips, all from hand-written prompts so far. The loop's adapters for it are on the feat/wm-agent-loop worktree only.",
     "files": ["world_model.py", "settings.py"], "branch_files": [".claude/worktrees/wm-agent-loop/runtime/adapters/cosmos.py", ".claude/worktrees/wm-agent-loop/runtime/adapters/cosmos_server.py"]},
    {"id": "agent", "name": "The real agent", "at": [3, 2], "status": "partial", "kind": "process", "plan": "§09, §10",
     "does": "Watches the rendered frames, and returns a decision for the next 30 seconds with a short note to itself.",
     "why": "On this checkout LLMAgent still raises NotImplementedError. A Qwen agent exists on the feat/wm-agent-loop worktree only, with scripted mocks standing in so far. See Live for whether real Qwen has decided anything. It can't query its past: there's no vault or MCP.",
     "files": ["life/agent.py"], "branch_files": [".claude/worktrees/wm-agent-loop/runtime/adapters/qwen.py", ".claude/worktrees/wm-agent-loop/runtime/prompt_builder.py", ".claude/worktrees/wm-agent-loop/runtime/mocks/agent.py"]},
    {"id": "simworld", "name": "SimWorld", "at": [4, 2], "status": "partial", "kind": "process",
     "does": "A city simulator on Unreal that holds physical truth. The loop sends it an action, and it advances exactly 30 sim-seconds and returns state and renders.",
     "why": "An adapter exists on the feat/wm-simworld and feat/wm-agent-loop worktrees, and the bridge into the loop is uncommitted. It has only ever talked to a fake server. Its Unreal server has no Mac build, and the PACE job to try it hasn't been filled in or run.",
     "files": ["simworld/README.md", "simworld/simworld/communicator/unrealcv.py"],
     "branch_files": [".claude/worktrees/wm-agent-loop/runtime/adapters/simworld.py", ".claude/worktrees/wm-agent-loop/runtime/adapters/simworld_bridge.py", ".claude/worktrees/wm-agent-loop/runtime/SIMWORLD.md", ".claude/worktrees/wm-agent-loop/scripts/pace/wmloop_gate.sbatch"]},
    {"id": "mind", "name": "Feel-then-decide", "at": [1, 3], "status": "partial", "kind": "process",
     "does": "Wraps any agent so it appraises what it just saw, then decides only at a decision point. A feeling shapes its own later prompts, and is never a score.",
     "why": "Uncommitted on this checkout, and it needs runtime/ from the agent loop worktree to run. Tested with scripted feelings. Whether real Qwen has run it is under Live, and mind/OPEN_DECISIONS.md lists what's still undecided.",
     "files": ["mind/feeling.py", "mind/run.py", "mind/OPEN_DECISIONS.md", "tests/test_mind.py"]},
    {"id": "blend", "name": "Clips and blending", "at": [2, 3], "status": "built", "kind": "data",
     "does": "Finished clips land on disk, and blend.py crossfades clips into one video.",
     "why": "Tested and used for the continuous video. Whether blend.py itself is running isn't measured, only clips being written.",
     "files": ["blend.py", "tests/test_continuous_video.py"]},
    {"id": "dreamgym", "name": "DreamGym policy", "at": [4, 3], "status": "planned", "kind": "model", "plan": "§15",
     "does": "Named in the build notes as a starting point for the agent's exact policy.",
     "why": "Not in this repo, and nothing here uses it.",
     "files": []},
    # Inside the agent
    {"id": "vault", "name": "Memory vault", "at": [1, 4], "status": "planned", "kind": "data", "plan": "§11",
     "does": "Would be markdown folders for people, lessons, beliefs and diary, with notes deleted once read or written.",
     "why": "No code. life/memory.py is the writer's recall, and the loop's notes are a short list carried between ticks in its checkpoint. Neither is this.",
     "files": []},
    {"id": "mcp", "name": "MCP tools", "at": [2, 4], "status": "planned", "kind": "process", "plan": "§10",
     "does": "Would let the agent search its own past before each decision.",
     "why": "No code, and no tool calling around the model.",
     "files": []},
    {"id": "qwen", "name": "Qwen3-VL-8B", "at": [3, 4], "status": "built", "kind": "model", "plan": "§10",
     "does": "The open-weight model. It writes the world's text and is the model being trained, and is meant to become the agent.",
     "why": "Loads and answers locally. It peaks near 20 GB, so it and Cosmos barely fit together in this Mac's 36 GB.",
     "files": ["llm_model.py", "settings.py"]},
    {"id": "judge", "name": "External LLM judge", "at": [4, 4], "status": "planned", "kind": "model", "plan": "§10",
     "does": "Would score the agent's internal state from outside, as an LLM.",
     "why": "No code. The simulator below stands in, on purpose: its numbers can't be flattered, so reward hacking against a judge is still untested.",
     "files": []},
    # Sleep
    {"id": "interpreter", "name": "Sleep interpreter", "at": [0, 5], "status": "planned", "kind": "process", "plan": "§13b",
     "does": "Would read each day and set how hard that night's training goes, including skipping it. It never writes the lesson.",
     "why": "No code, and nothing calls a frontier model.",
     "files": []},
    {"id": "sft", "name": "Sleep SFT", "at": [1, 5], "status": "planned", "kind": "process", "plan": "§13",
     "does": "Would fine-tune a LoRA each night on the day's diary and lessons. The plan calls this the most plausible signal.",
     "why": "No code, and no diary to train on, since there's no vault or agent.",
     "files": []},
    {"id": "adapter", "name": "LoRA adapter", "at": [2, 5], "status": "unproven", "kind": "model", "plan": "§13",
     "does": "The small trainable layer on top of Qwen, which is where all of a life's learning would end up.",
     "why": "Training produces and saves adapters, and none has been shown to improve on the untrained model.",
     "files": ["homeostatic/train.py"]},
    {"id": "grpo", "name": "RL training", "at": [3, 5], "status": "unproven", "kind": "process", "plan": "§13",
     "does": "Tries every action from a state the model reached, scores each by branching the simulator, and trains the model toward the better ones. The loss and loop are mlx-vlm's GRPO; its sampled groups collapsed, so the groups are replaced.",
     "why": "The loop runs start to finish but hasn't beaten the untrained model. It runs on mlx-vlm locally, not Tinker, and against the simulator, not the judge. See the numbers under Live.",
     "files": ["homeostatic/grpo.py", "homeostatic/train.py"]},
    {"id": "sim", "name": "Homeostatic sim", "at": [4, 5], "status": "built", "kind": "process", "plan": "§10",
     "does": "A simulated life of four variables with delayed effects. Reward is the fall in drive, the distance from healthy ranges.",
     "why": "Works and is tested. It's a stand-in for the planned judge, not the judge.",
     "files": ["homeostatic/world.py"]},
    {"id": "tinker", "name": "Tinker LoRA API", "at": [1, 6], "status": "planned", "kind": "process", "plan": "§13b",
     "does": "The training service the plan names for nightly LoRA runs.",
     "why": "Not used anywhere. The only training today is local, through mlx-vlm.",
     "files": []},
    {"id": "nextevent", "name": "Next-event loss", "at": [2, 6], "status": "planned", "kind": "process", "plan": "§13",
     "does": "Would train the model to predict what happens next in its life, so it absorbs how its world works.",
     "why": "No code.",
     "files": []},
    {"id": "benchmark", "name": "Benchmark, report", "at": [3, 6], "status": "built", "kind": "io", "plan": "§14",
     "does": "Scores any policy on the same held-out lives, against baselines and controls, and writes the comparison.",
     "why": "Baselines and validation run. The full experiment hasn't finished, so there's no held-out result yet.",
     "files": ["homeostatic/benchmark.py", "homeostatic/evaluate.py", "homeostatic/experiment.py", "homeostatic/report.py"]},
    {"id": "success", "name": "Success criteria", "at": [4, 6], "status": "planned", "kind": "io", "plan": "§14",
     "does": "Consistent across unrelated problems, beyond what prompting gets, traceable to experiences, and not a caricature.",
     "why": "None is measured. The benchmark measures homeostasis, which is a far smaller question than having a perspective.",
     "files": []},
    # Around the system
    {"id": "panel", "name": "Dev panel", "at": [0, 7], "status": "built", "kind": "io",
     "does": "This page and its neighbors. It only reads what runs leave on disk and in ps, so it can't disturb them.",
     "why": "You're using it. The Life generator page writes mock runs only.",
     "files": ["life/panel.py", "life/architecture.py", "life/pipeline.py", "homeostatic/watch.py", "life/static/architecture.js", "life/static/queue.js"]},
    {"id": "swarm", "name": "Agent swarm", "at": [1, 7], "status": "planned", "kind": "process", "plan": "§15",
     "does": "Would have coding agents work continuously on making the sim more realistic.",
     "why": "Nothing does this as a system. Agents working in this repo coordinate by hand through AGENTS.md.",
     "files": ["AGENTS.md"]},
    {"id": "queue", "name": "GPU queue", "at": [2, 7], "status": "built", "kind": "process",
     "does": "Gives model jobs one turn at a time, in priority order, since two at once can run this Mac out of memory. Keeps a ledger of every job.",
     "why": "Merged into this checkout under ops/. See Live for what has really had a turn. It waits for model jobs started outside it, and runs on this Mac only.",
     "files": ["ops/gpu.py", "ops/status.py"]},
    {"id": "evals", "name": "Benchmarks", "at": [3, 7], "status": "partial", "kind": "process", "plan": "§14",
     "does": "Decision instruments, starting with Holt-Laury and lottery problems, run across arms under a pre-registration, with mock and real results kept apart.",
     "why": "Only on the feat/evals worktree, not merged, with uncommitted changes. Its tests pass on a mock backend. See Live for real results and whether the pre-registration is locked. It's a different thing from the homeostatic benchmark above.",
     "files": [], "branch_files": [".claude/worktrees/agent-a2d4c0a770bb9b339/benchmarks/run.py", ".claude/worktrees/agent-a2d4c0a770bb9b339/benchmarks/PREREG.md", ".claude/worktrees/agent-a2d4c0a770bb9b339/benchmarks/holt_laury/items.jsonl"]},
    {"id": "thirty", "name": "30-minute run", "at": [4, 7], "status": "partial", "kind": "io", "plan": "§09",
     "does": "The goal: 60 ticks of 30 sim-seconds with real SimWorld, Cosmos and Qwen. Everything above has to work for this to mean anything.",
     "why": "Each gate is read from files on the Pipeline view, and Live shows the verdict. A 60-tick run on mocks only shows the plumbing.",
     "files": ["life/pipeline.py"]},
]

ENGINE = ["overnight.running", "panel.running"]

EDGES = [
    {"from": "seed", "to": "tree", "label": "prompt", "status": "built"},
    {"from": "seed", "to": "backtest", "label": "hidden target", "status": "built"},
    {"from": "tree", "to": "state", "label": "writes", "status": "built", "active": ENGINE, "pulse": ["overnight.calls", "panel.writes"], "hop": 1},
    {"from": "resolver", "to": "state", "label": "events", "status": "built", "active": ENGINE, "pulse": ["panel.events"]},
    {"from": "random", "to": "resolver", "label": "stance", "status": "built", "active": ENGINE, "pulse": ["panel.choices"]},
    {"from": "state", "to": "recall", "label": "the past", "status": "built", "active": ["overnight.running"], "out": "b.2", "route": ["y0.65"], "in": "t.75"},
    {"from": "recall", "to": "tree", "label": "memory", "status": "built", "active": ["overnight.running"], "out": "t.3", "in": "b.3"},
    {"from": "qwen", "to": "tree", "label": "writes text", "status": "built", "active": ["overnight.running"], "pulse": ["overnight.calls"], "out": "t.12", "route": ["y3.7", "x1.5"], "in": "r.78", "label_at": [2, 0.72]},

    {"from": "tree", "to": "loop", "label": "events, map", "status": "partial", "active": ["loop.life_real"], "pulse": ["loop.ticks"], "out": "l.78", "route": ["x0.5", "y1.5"], "in": "t.5", "label_at": [2, 0.5]},
    {"from": "loop", "to": "imprint", "label": "next 30s", "status": "planned"},
    {"from": "imprint", "to": "cosmos", "label": "scene", "status": "planned"},
    {"from": "loop", "to": "cosmos", "label": "renders", "status": "partial", "active": ["loop.wm_real"], "pulse": ["loop.ticks"], "out": "t.85", "route": ["y1.75"], "in": "t.2", "label_at": [1, 0.5]},
    {"from": "cosmos", "to": "agent", "label": "video", "status": "partial", "active": ["loop.wm_real"], "pulse": ["loop.ticks"], "hop": 1},
    {"from": "agent", "to": "loop", "label": "decision", "status": "partial", "active": ["loop.running"], "pulse": ["loop.ticks"], "out": "b.2", "route": ["y2.65"], "in": "b.5", "hop": 2},
    {"from": "mind", "to": "agent", "label": "feels first", "status": "partial", "active": ["mind.running"], "pulse": ["mind.feelings"], "out": "t.8", "route": ["y2.3"], "in": "b.08"},
    {"from": "agent", "to": "resolver", "label": "replaces random", "status": "planned"},
    {"from": "simworld", "to": "agent", "label": "truth", "status": "partial", "active": ["loop.sim_real"], "pulse": ["loop.ticks"], "out": "l.3", "in": "r.3"},
    {"from": "dreamgym", "to": "agent", "label": "policy", "status": "planned", "out": "l.5", "route": ["x3.5"], "in": "r.75"},
    {"from": "cosmos", "to": "blend", "label": "clip", "status": "built", "active": ["world.running"], "pulse": ["world.clips"]},

    {"from": "qwen", "to": "agent", "label": "runs as", "status": "partial", "active": ["loop.agent_real"], "pulse": ["loop.ticks"]},
    {"from": "agent", "to": "vault", "label": "diary", "status": "planned", "out": "b.36", "route": ["y3.35"], "in": "t.5", "label_at": [1, 0.88]},
    {"from": "vault", "to": "mcp", "label": "notes", "status": "planned"},
    {"from": "mcp", "to": "qwen", "label": "queries", "status": "planned"},
    {"from": "agent", "to": "judge", "label": "state", "status": "planned", "out": "b.84", "route": ["y3.5"], "in": "t.5"},
    {"from": "judge", "to": "sim", "label": "stand-in", "status": "planned"},

    {"from": "vault", "to": "sft", "label": "lessons", "status": "planned", "out": "b.6", "in": "t.6"},
    {"from": "vault", "to": "interpreter", "label": "day log", "status": "planned", "out": "b.2", "route": ["y4.6"], "in": "t.5"},
    {"from": "interpreter", "to": "sft", "label": "dial", "status": "planned"},
    {"from": "tinker", "to": "sft", "label": "runs on", "status": "planned"},
    {"from": "sft", "to": "adapter", "label": "nightly", "status": "planned"},
    {"from": "nextevent", "to": "adapter", "label": "loss", "status": "planned"},
    {"from": "qwen", "to": "grpo", "label": "choices", "status": "built", "active": ["trainer.training"], "pulse": ["trainer.groups"], "out": "b.6", "in": "t.6"},
    {"from": "grpo", "to": "sim", "label": "actions", "status": "built", "active": ["trainer.training"], "pulse": ["trainer.groups"], "out": "r.3", "in": "l.3", "hop": 1},
    {"from": "sim", "to": "grpo", "label": "scores", "status": "built", "active": ["trainer.training"], "pulse": ["trainer.groups"], "out": "l.72", "in": "r.72", "hop": 2},
    {"from": "grpo", "to": "adapter", "label": "update", "status": "built", "active": ["trainer.training"], "pulse": ["trainer.updates"]},
    {"from": "adapter", "to": "qwen", "label": "weights", "status": "built", "active": ["trainer.running"], "pulse": ["trainer.updates"], "out": "t.7", "route": ["y4.65"], "in": "b.2", "hop": 1},
    {"from": "adapter", "to": "benchmark", "label": "plays lives", "status": "built", "active": ["trainer.validating"], "pulse": ["trainer.lives"], "out": "b.85", "route": ["y5.6"], "in": "t.25"},
    {"from": "sim", "to": "benchmark", "label": "drive", "status": "built", "active": ["trainer.validating"], "pulse": ["trainer.lives"], "out": "b.25", "route": ["y5.6"], "in": "t.75", "hop": 1},
    {"from": "benchmark", "to": "success", "label": "only homeostasis", "status": "planned"},
    {"from": "queue", "to": "evals", "label": "a turn", "status": "built", "active": ["queue.evals"], "pulse": ["evals.rows"]},
    {"from": "evals", "to": "success", "label": "not yet", "status": "planned", "out": "t.85", "route": ["y6.5"], "in": "b.5"},
]

OVERNIGHT = ROOT / "out" / "overnight"
WORLD_DATA = ROOT / "out"
SCRIPTS = {"txt2video.py", "img2video.py", "collect.py"}


def count_rows(path):
    try:
        return Path(path).read_bytes().count(b"\n")
    except OSError:
        return 0


def seconds_since(paths, now):
    times = [path.stat().st_mtime for path in paths if path.exists()]
    return now - max(times) if times else None


def trainer_signal(out, listing, now):
    # Only a process that is training. A job waiting in the GPU queue has the same words in its command line.
    running = watch.trainers("\n".join(line for line, parts in python_lines(listing) if runs_module(parts, "homeostatic.train")))
    folders = watch.run_folders(out) if Path(out).exists() else {}
    best, broken = best_validation(out) if folders else (None, [])
    baselines = watch.baselines(out)
    base, idle = baselines.get("base", {}).get("mean_drive"), baselines.get("idle", {}).get("mean_drive")
    signal = {"running": False, "run": None, "best": best, "broken": broken, "base": base, "idle": idle,
              "beaten": beats_baselines(best, base, idle), "held_out": len(watch.held_out_results(out))}
    name = next((name for name, folder in folders.items() if folder.resolve() in running), None)
    if name is None:
        return {**signal, "training": False, "validating": False, "updates": 0, "groups": 0, "lives": 0}
    run = watch.describe_run(name, out, running)
    folder = folders[name]
    lives_per_check = len(HOMEOSTATIC_SEEDS["validation"])
    checking = run["validating"]
    fresh = run["seconds_since_update"] < STALL_SECONDS
    latest = run["validation"][-1] if run["validation"] else None
    return {**signal, "running": True, "run": name, "done": run["done"], "total": run["total"], "quiet": run["seconds_since_update"],
            "stalled": not fresh, "collapsed": run["collapsed"], "latest": latest, "group": run["groups"][0] if run["groups"] else None,
            "checking": checking, "peak_gb": run["train"][-1].get("peak_memory") if run["train"] else None,
            "training": fresh and not checking, "validating": fresh and bool(checking),
            "updates": len(run["train"]), "groups": count_rows(folder / "rollouts.jsonl"),
            "lives": len(run["validation"]) * lives_per_check + (checking["done"] if checking else 0)}


def overnight_signal(folder, listing, now):
    running = any(runs_module(parts, "life.overnight") for _, parts in python_lines(listing))
    latest = Path(folder) / "latest"
    calls = count_rows(latest / "calls.jsonl")
    quiet = seconds_since([latest / "calls.jsonl", latest / "run.log"], now)
    # latest is a link to one of these, so it isn't counted again.
    states = [watch.read_json(path) for path in Path(folder).glob("*/state.json") if not path.parent.is_symlink()]
    return {"running": running and quiet is not None and quiet < STALL_SECONDS, "alive": running, "calls": calls, "quiet": quiet,
            "trials": sum(1 for state in states if state and state.get("trial")), "full": sum(1 for state in states if state and not state.get("trial"))}


def world_signal(folder, listing):
    jobs = sorted(Path(part).name for _, parts in python_lines(listing) for part in parts[1:3] if Path(part).name in SCRIPTS)
    clips = sum(1 for path in Path(folder).glob("*/manifest.jsonl") for row in watch.read_rows(path) if row.get("ok"))
    return {"running": bool(jobs), "jobs": jobs, "clips": clips}


def panel_signal(store, mock_running):
    runs = store.runs()
    count = lambda where="": store.conn.execute(f"SELECT COUNT(*) FROM events {where}").fetchone()[0]
    return {"running": mock_running > 0, "mock_running": mock_running, "writes": sum(store.last_seq(run["run_id"]) for run in runs),
            "events": count(), "choices": count("WHERE kind = 'choice'"), "runs": len(runs)}


def ago(seconds):
    return "n/a" if seconds is None else f"{seconds / 60:.0f} min ago" if seconds >= 90 else f"{seconds:.0f} s ago"


def drive_text(row):
    return f"{row['drive']:.1f} ({row['run']}, update {row['iteration']})"


def live_lines(trainer, overnight, world, panel):
    """What each node shows: one short line on the chart, and the full story in the side panel. Every number was just read."""
    live = {}
    held = plural(trainer["held_out"], "held-out result")
    scoring = []
    if trainer["base"] is not None:
        scoring.append(f"Untrained model: mean drive {trainer['base']:.1f} on the validation lives. Lower is healthier.")
    if trainer["best"]:
        scoring.append(f"Best trained run: {drive_text(trainer['best'])}.")
    else:
        scoring.append("No trained run has finished a validation with real replies.")
    scoring += [f"{row['run']} scored {row['drive']:.1f} at update {row['iteration']} by replying nothing usable, which is what doing nothing scores." for row in trainer["broken"]]
    if trainer["idle"] is not None:
        scoring.append(f"Doing nothing scores {trainer['idle']:.1f}. A run has to beat this too: one that learns to do nothing hasn't learned to stay healthy.")
    if trainer["beaten"]:
        scoring.append("A run now beats the untrained model on validation. Check it on held-out lives, then revisit this status.")

    best_short = f"{trainer['best']['drive']:.1f} vs base {trainer['base']:.1f}" if trainer["best"] and trainer["base"] is not None else "no valid score"
    if trainer["running"]:
        progress = f"update {trainer['done']} of {trainer['total']}"
        grpo = [f"{trainer['run']}: {progress}, last write {ago(trainer['quiet'])}."]
        if trainer["stalled"]:
            grpo.append("The process is alive but has written nothing lately, so nothing here is shown moving.")
        if trainer["checking"]:
            grpo.append(f"Validating now, life {trainer['checking']['done']} of {trainer['checking']['total']}.")
        if trainer["collapsed"]:
            grpo.append("The model has chosen the same action in every state for five updates, so it isn't responding to its state.")
        if trainer["group"]:
            group = trainer["group"]
            grpo.append(f"Latest state: scores {min(group['scores']):.1f} to {max(group['scores']):.1f}, and it chose {group.get('chosen') or 'something invalid'}.")
        if trainer["peak_gb"]:
            grpo.append(f"Peak memory {trainer['peak_gb']:.1f} GB.")
        latest = trainer["latest"]
        if latest:
            grpo.append(f"This run's latest validation: {latest['mean_drive']:.1f} at update {latest['iteration']}.")
        live["grpo"] = {"short": progress, "lines": grpo + scoring}
        live["qwen"] = {"short": "in use: training", "lines": [f"Loaded by homeostatic.train for {trainer['run']}."]}
        live["adapter"] = {"short": "being trained", "lines": [f"Updated in memory by {trainer['run']}, and saved on a schedule."]}
        live["sim"] = {"short": "scoring replies" if not trainer["checking"] else "scoring lives", "lines": [plural(trainer["groups"], "group") + " scored in this run."]}
        checking = f"life {trainer['checking']['done']} of {trainer['checking']['total']}" if trainer["checking"] else best_short
        live["benchmark"] = {"short": checking, "lines": scoring + [f"{held} so far."]}
    else:
        live["grpo"] = {"short": "idle", "lines": ["No training process is running."] + scoring}
        live["benchmark"] = {"short": best_short, "lines": scoring + [f"{held} so far."]}

    runs = f"{plural(overnight['trials'], 'trial run')}, {plural(overnight['full'], 'full overnight run')}."
    written = f"{plural(overnight['calls'], 'real LLM call')} in the latest run, last written {ago(overnight['quiet'])}."
    mock = f"{plural(panel['writes'], 'mock write')} in this panel's database across {plural(panel['runs'], 'run')}."
    live["tree"] = {"short": "writing" if overnight["running"] or panel["running"] else plural(overnight['calls'], 'real call'),
                    "lines": [written, runs, mock]}
    live["state"] = {"short": plural(panel["events"], "event"), "lines": [f"{plural(panel['events'], 'event')} logged in this panel's database, all from mock runs unless it's watching one."]}
    live["random"] = {"short": plural(panel["choices"], "choice"), "lines": [f"{plural(panel['choices'], 'choice')} made in this panel's database."]}
    if overnight["running"]:
        live.setdefault("qwen", {"short": "in use: writing", "lines": []})["lines"].append("Loaded by life.overnight to write the world.")

    jobs = ", ".join(world["jobs"])
    live["cosmos"] = {"short": "rendering" if world["running"] else plural(world['clips'], 'clip'),
                      "lines": [f"Running now: {jobs}." if world["running"] else "No render is running.", f"{plural(world['clips'], 'clip')} recorded in out/*/manifest.jsonl."]}
    live["blend"] = {"short": plural(world["clips"], "clip"), "lines": [f"{plural(world['clips'], 'clip')} recorded by collection runs."]}
    live.setdefault("qwen", {"short": "not loaded", "lines": ["No process here is using it."]})
    live["panel"] = {"short": "serving this page", "lines": [f"{plural(panel['mock_running'], 'mock run')} going in this panel."]}
    return live


def now_running(trainer, overnight, world, panel):
    """The plain list of what's alive, which is also what the header says."""
    running = []
    if trainer["running"]:
        running.append(f"homeostatic.train {trainer['run']}, update {trainer['done']} of {trainer['total']}")
    if overnight["alive"]:
        running.append("life.overnight, writing a life on Qwen" if overnight["running"] else "life.overnight, alive but quiet")
    running += [f"{job}, on Cosmos" for job in world["jobs"]]
    if panel["running"]:
        running.append(f"Mock life in this panel: {plural(panel['mock_running'], 'run')}")
    return running


def pipeline_lines(collected):
    """The newer parts' lines on the chart, from what the Pipeline view reads."""
    def run_line(run):
        return f"{run['name']}: {run['mode']}, {run['done']} of {run['target']} ticks, {run['state']}."

    def run_short(runs):
        if not runs:
            return "no runs"
        moving = next((run for run in runs if run["state"] == "moving"), None)
        if moving:
            return f"tick {moving['done']} of {moving['target']}"
        real = [run for run in runs if run["mode"] != "mock"]
        return f"{plural(len(real), 'real run')}" if real else f"{plural(len(runs), 'mock run')}"

    agent, mind, gpu, benchmarks, goal = collected["agent"], collected["mind"], collected["gpu"], collected["benchmarks"], collected["goal"]
    real_ticks = lambda part: sum(run["done"] for run in agent["runs"] if run[part] not in (None, "mock"))
    no_worktree = ["The agent loop worktree isn't there to read."] if not agent["available"] else []
    live = {"loop": {"short": run_short(agent["runs"]), "lines": no_worktree + [run_line(run) for run in agent["runs"]]},
            "mind": {"short": run_short(mind["runs"]), "lines": [run_line(run) for run in mind["runs"]] or ["No runs yet."]},
            "agent": {"short": f"{plural(real_ticks('agent'), 'real tick')}", "lines": [f"{plural(real_ticks('agent'), 'tick')} decided by a real model in the loop."]},
            "simworld": {"short": f"{plural(real_ticks('sim'), 'real tick')}", "lines": [f"{plural(real_ticks('sim'), 'tick')} run on real SimWorld in the loop."]},
            "queue": {"short": f"{len(gpu['running'])} on, {len(gpu['waiting'])} waiting", "lines": [
                f"Has a turn: {', '.join(ticket['name'] for ticket in gpu['running']) or 'nothing'}.", f"Waiting: {', '.join(ticket['name'] for ticket in gpu['waiting']) or 'nothing'}.",
                f"Using the GPU outside the queue: {', '.join(job['name'] for job in gpu['outside']) or 'nothing'}.", f"{plural(gpu['finished'], 'job')} finished, {gpu['failed']} failed, in the ledger."]},
            "evals": {"short": f"{plural(benchmarks['real_results'], 'real result')}", "lines": [
                f"{plural(benchmarks['real_results'], 'real result set')}, {plural(benchmarks['exploratory'], 'exploratory check')}, {plural(benchmarks['rows'], 'row')} in all.",
                f"Instruments: {', '.join(benchmarks['instruments']) or 'none'}. Pre-registration: {benchmarks['prereg'] or 'unknown'}."]},
            "thirty": {"short": {"blocked": "not possible yet", "done": "finished", "possible": "not blocked", "unknown": "unknown"}[goal["verdict"]],
                       "lines": [goal["line"]] + ([f"Blocked by: {', '.join(goal['blockers'])}."] if goal["blockers"] else []) + ([f"Can't tell: {', '.join(goal['unknown'])}."] if goal["unknown"] else [])}}
    return live


def snapshot(panel, listing=None, out=HOMEOSTATIC_OUT, overnight_folder=OVERNIGHT, world_folder=WORLD_DATA, paths=PIPELINE_PATHS):
    """Everything measured right now. Flags say what's alive, counts only ever grow while it runs, and live is the text."""
    listing_is_real = listing is None
    listing = ps_listing() if listing_is_real else listing
    now = time.time()
    trainer = trainer_signal(out, listing, now)
    overnight = overnight_signal(overnight_folder, listing, now)
    world = world_signal(world_folder, listing)
    # A real listing has pids, which the queue needs, so it's taken again rather than reused. A test's listing goes straight through.
    collected = pipeline.collect(paths, None if listing_is_real else listing, out)
    measured = pipeline.signals(collected)
    gpu = collected["gpu"]
    extra = [f"{ticket['name']}, its GPU turn" for ticket in gpu["running"]]
    extra += [f"{run['name']}, {run['mode']} loop run" for run in collected["agent"]["runs"] + collected["mind"]["runs"] if run["state"] == "moving"]
    return {
        "running": now_running(trainer, overnight, world, panel) + extra,
        "flags": {**measured["flags"], "trainer.running": trainer["running"] and not trainer.get("stalled", False), "trainer.training": trainer["training"], "trainer.validating": trainer["validating"],
                  "overnight.running": overnight["running"], "world.running": world["running"], "panel.running": panel["running"]},
        "counts": {"trainer.updates": trainer["updates"], "trainer.groups": trainer["groups"], "trainer.lives": trainer["lives"],
                   "overnight.calls": overnight["calls"], "world.clips": world["clips"],
                   "panel.writes": panel["writes"], "panel.events": panel["events"], "panel.choices": panel["choices"], **measured["counts"]},
        "live": {**live_lines(trainer, overnight, world, panel), **pipeline_lines(collected)},
        "active_nodes": sorted(active_nodes(trainer, overnight, world, panel) | pipeline_nodes(measured["flags"])),
    }


def active_nodes(trainer, overnight, world, panel):
    """Nodes doing work right now. Being alive isn't enough: a stalled trainer shows no node at work."""
    nodes = set()
    if trainer["training"]:
        nodes |= {"qwen", "grpo", "sim", "adapter"}
    if trainer["validating"]:
        nodes |= {"qwen", "adapter", "sim", "benchmark"}
    if overnight["running"]:
        nodes |= {"qwen", "tree", "state", "recall", "resolver", "random"}
    if panel["running"]:
        nodes |= {"tree", "state", "resolver", "random"}
    if world["running"]:
        nodes |= {"cosmos", "blend"}
    return nodes


def pipeline_nodes(flags):
    """Which of the newer parts are at work. A mock run lights only the loop, and never a model."""
    lit = {"loop.running": {"loop", "agent"}, "loop.sim_real": {"simworld"}, "loop.wm_real": {"cosmos", "blend"}, "loop.agent_real": {"qwen"},
           "loop.life_real": {"state"}, "mind.running": {"mind"}, "queue.running": {"queue"}, "evals.running": {"evals"}}
    return {node for flag, nodes in lit.items() if flags[flag] for node in nodes}


def catalog():
    return {"statuses": STATUSES, "kinds": KINDS, "sections": PLAN_SECTIONS, "lanes": LANES, "nodes": NODES, "edges": EDGES}


def catalog_and_snapshot(panel):
    return {"catalog": catalog(), **snapshot(panel)}
