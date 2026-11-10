"""Run the agent in a world model. See kokopelli/loop/README.md."""
import argparse
import json
import sys
import time
from dataclasses import fields
from pathlib import Path

from kokopelli.loop import checkpoint, replay
from kokopelli.loop.adapters.life_db import LifeContext, copy_database
from kokopelli.loop.autonomy import counterfactual
from kokopelli.loop.config import WM_PRESETS, Config
from kokopelli.loop.event_log import JsonlLog
from kokopelli.loop.leak_guard import LeakError
from kokopelli.loop.loop import Loop
from kokopelli.loop.mocks.agent import NullAgent, ScriptedAgent
from kokopelli.loop.mocks.context import MockContext
from kokopelli.loop.mocks.sim import MockSim
from kokopelli.loop.mocks.world_model import MockWorldModel
from kokopelli.loop.stitch import stitch

RUNS = Path("runs")
LOW_MEMORY_WEIGHTS = "models/Qwen3-VL-8B-Instruct-4bit"
BACKENDS = {"mock": {"sim": "mock", "wm": "mock", "agent": "mock", "context": "mock", "wm_preset": "mock"},
            "real": {"sim": "simworld", "wm": "cosmos_server", "agent": "qwen", "context": "life", "wm_preset": "gpu_full"}}


def make_sim(config):
    if config.sim == "mock":
        return MockSim()
    from kokopelli.loop.adapters.simworld_bridge import make_simworld
    return make_simworld(config)


def make_world_model(config):
    if config.wm == "mock":
        return MockWorldModel()
    if config.wm == "cosmos_server":
        from kokopelli.loop.adapters.cosmos_server import CosmosServerWorldModel
        return CosmosServerWorldModel(config.wm_url, config.wm_settings["size"], config.wm_settings["steps"], negative_prompt(), config.wm_filter or "depth")
    from kokopelli.loop.adapters.cosmos import CosmosWorldModel
    return CosmosWorldModel(config.wm_settings["size"], config.wm_settings["steps"], config.wm_quantize)


def negative_prompt():
    """What the model README sends with every request, if the weights are here to read it from."""
    from kokopelli.settings import WORLD_MODEL_WEIGHTS
    path = WORLD_MODEL_WEIGHTS / "assets" / "negative_prompt.json"
    return json.dumps(json.loads(path.read_text())) if path.exists() else None


def make_agent(config, out=None):
    agent = _inner_agent(config)
    if not config.mind:
        return agent
    # The feeling loop from kokopelli/mind/. It wraps any agent and keeps its own record, which survives a resume.
    from kokopelli.mind.feeling import FeelingAgent
    return FeelingAgent(agent, Path(out) / "feelings.jsonl")  # pyright: ignore[reportArgumentType]  # run() always passes out


def _inner_agent(config):
    if config.agent == "mock":
        return ScriptedAgent(config.seed)
    if config.agent == "null":
        return NullAgent()
    from kokopelli.loop.adapters.qwen import MlxQwenAgent, ServerQwenAgent
    return ServerQwenAgent(config.agent_url, config.agent_model) if config.agent_url else MlxQwenAgent(config.agent_weights)


def make_context(config, out):
    if config.context == "mock":
        return MockContext()
    copy = out / "life_copy.db"
    if not copy.exists():
        copy_database(config.life_db, copy)
    return LifeContext(copy, config.life_run, config.start_time)


def git_commit():
    import subprocess
    run = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return run.stdout.strip() or None


def finish(config, out, sim_factory, log):
    """The parts that look at the whole run: the joined video, and what a do-nothing agent would have done."""
    clips = [out / chunk["clip"] for tick in replay.summarize(out)["ticks"] for chunk in tick["chunks"]]
    if clips:
        try:
            final = stitch(clips, out / "final.mp4", 0 if config.wm_filter else config.cond_frames)
            log.append("stitched", None, {"video": str(Path(final).relative_to(out)), "clips": len(clips)})
        except Exception as error:  # The run's data is already safe, so a failed join shouldn't look like a failed run.
            log.append("stitched", None, {"video": None, "error": str(error)[-300:]})
    if config.counterfactual and config.sim == "mock":
        start = replay.load(out, verify=False)
        first = next(event for event in start if event["kind"] == "sim_reset")["data"]["state"]["sim_time"]
        log.append("counterfactual", None, counterfactual(sim_factory, config, first, replay.trajectory(out)))
    summary = replay.summarize(out)
    log.append("run_end", None, summary["run"]["totals"])
    return summary


def run(config, out, sim=None, world_model=None, agent=None, context=None, resume=False):
    """Run or continue a run in out. The pieces can be passed in, which is how the tests break things on purpose."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps(config.to_dict(), indent=2))
    log = JsonlLog(out / "events.jsonl")
    context = context or make_context(config, out)
    loop = Loop(config, out, sim or make_sim(config), world_model or make_world_model(config), agent or make_agent(config, out), context, log)
    saved = checkpoint.load(out) if resume else None
    try:
        if resume and saved:
            loop.resume(saved)
        else:
            log.append("run_start", None, {"config": config.to_dict(), "seed": config.seed, "git": git_commit(), "started": time.time()})
            loop.start()
        loop.run()
        return finish(config, out, lambda: make_sim(config), log)
    finally:
        loop.sim.close()
        log.close()


def config_from(args):
    backend = BACKENDS[args.backend]
    values = {**backend, "seed": args.seed, "ticks": args.ticks, "drift_control": not args.no_drift_control,
              "counterfactual": not args.no_counterfactual, "mind": args.mind}
    for name in ("sim", "wm", "agent", "context", "wm_preset", "start_time", "life_db", "life_run", "agent_url", "drift_threshold", "agent_weights", "wm_quantize", "wm_url", "cond_frames", "wm_filter"):
        value = getattr(args, name)
        if value is not None:
            values[name] = value
    if args.low_memory:
        values["wm_preset"], values["wm_quantize"] = "tiny", 8
        values.setdefault("agent_weights", LOW_MEMORY_WEIGHTS)
    if args.sim_settings:
        values["sim_settings"] = json.loads(args.sim_settings)
    if values["sim"] == "mock" and values["wm"] == "cosmos":
        # Re-anchoring would paste the mock's grid into real video. Scores are still logged, but mean little here.
        values["drift_control"] = False
    if values.get("wm_filter"):
        if values["wm"] == "cosmos":
            sys.exit("--wm-filter needs Cosmos3-Nano-Sim-Transfer, which has no Mac port. Use --wm cosmos_server or --wm mock")
        values["drift_control"] = False
        if args.wm_preset is None:
            values["wm_preset"] = "filter" if values["wm"] == "cosmos_server" else "filter_mock"
    if values["wm"] == "cosmos_server":
        values["cond_frames"] = 1
        if not values.get("wm_url"):
            sys.exit("--wm cosmos_server needs --wm-url")
    if values["context"] == "life" and not values.get("life_db"):
        sys.exit("--context life needs --life-db")
    return Config(**values)


def apply_new_addresses(config, args):
    """A job that restarts after preemption gets new ports, so a resume takes the servers' current addresses."""
    if args.wm_url:
        config.wm_url = args.wm_url
    if args.agent_url:
        config.agent_url = args.agent_url
    if args.sim_settings:
        config.sim_settings = {**config.sim_settings, **json.loads(args.sim_settings)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticks", type=int, default=5, help="each is 30 sim-seconds; 60 is the full half hour")
    parser.add_argument("--backend", choices=BACKENDS, default="mock")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--resume", metavar="RUN_ID", help="continue a run from its last finished tick")
    parser.add_argument("--no-drift-control", action="store_true")
    parser.add_argument("--no-counterfactual", action="store_true")
    parser.add_argument("--out", type=Path, help="default: runs/<run_id>/")
    parser.add_argument("--sim", choices=["mock", "simworld"])
    parser.add_argument("--wm", choices=["mock", "cosmos", "cosmos_server"])
    parser.add_argument("--agent", choices=["mock", "null", "qwen"])
    parser.add_argument("--context", choices=["mock", "life"])
    parser.add_argument("--wm-preset", choices=WM_PRESETS)
    parser.add_argument("--start-time", help="ISO time the half hour starts")
    parser.add_argument("--life-db", help="life tree database; a run copies it and never writes to the original")
    parser.add_argument("--life-run", type=int)
    parser.add_argument("--agent-url", help="an OpenAI-style server such as vLLM, instead of local MLX")
    parser.add_argument("--drift-threshold", type=float)
    parser.add_argument("--low-memory", action="store_true", help="smaller clips, 8-bit Cosmos, 4-bit Qwen; see kokopelli/loop/README.md")
    parser.add_argument("--agent-weights", help="a folder of Qwen weights to use instead of the full ones")
    parser.add_argument("--cond-frames", type=int, help="how many frames each chunk continues from")
    parser.add_argument("--mind", action="store_true", help="wrap the agent in the feeling loop from kokopelli/mind/")
    parser.add_argument("--sim-settings", help="SimWorldConfig fields as JSON, such as the port")
    parser.add_argument("--wm-url", help="a vLLM-Omni server running Cosmos, for --wm cosmos_server")
    parser.add_argument("--wm-filter", choices=["depth", "seg"], help="render every frame in the sim and have the world model repaint them, using this as the control video")
    parser.add_argument("--wm-quantize", type=int, choices=[8], help="load Cosmos in 8 bits")
    args = parser.parse_args()

    RUNS.mkdir(exist_ok=True)
    (RUNS / ".gitignore").write_text("*\n")
    if args.resume:
        out = Path(args.resume) if Path(args.resume).is_dir() else RUNS / args.resume
        known = {field.name for field in fields(Config)}
        config = Config(**{k: v for k, v in json.loads((out / "config.json").read_text()).items() if k in known})
        config.ticks = max(config.ticks, args.ticks) if "--ticks" in sys.argv else config.ticks
        apply_new_addresses(config, args)
    else:
        config = config_from(args)
        out = args.out or RUNS / f"wmloop_{time.strftime('%Y%m%d_%H%M%S')}_seed{config.seed}"
    try:
        summary = run(config, out, resume=bool(args.resume))
    except LeakError as error:
        sys.exit(f"LEAK ALARM, run stopped: {error}")
    totals = summary["run"]["totals"]
    print(f"{out}: {totals['ticks']} ticks, {totals['reanchors']} re-anchors, autonomy {totals['autonomy']}, "
          f"{totals['invalid_replies']} invalid replies, {totals['seconds'].get('total', 0):.1f}s")
    print(f"View it with: python -m kokopelli.loop.viewer {out}")


if __name__ == "__main__":
    main()
