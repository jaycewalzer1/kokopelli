"""Run the runtime loop with a FeelingAgent. Needs the agent-loop branch on the path:

PYTHONPATH=.claude/worktrees/wm-agent-loop:. .venv/bin/python -m kokopelli.loop.run_mind --ticks 60 --out out/mind/mock_60
"""
import argparse
import json
import time
from collections import Counter
from pathlib import Path

from kokopelli.loop.config import Config
from kokopelli.loop.interfaces import AgentPolicy
from kokopelli.loop.mocks.agent import ScriptedAgent
from kokopelli.loop.run import run

from kokopelli.mind.feeling import APPRAISE, CHANGE, FeelingAgent, read_rows, timeline


class MockMind(AgentPolicy):
    """A fixed pattern of mostly calm with a startle every seventh tick, to exercise the gate. Decisions are scripted."""

    def __init__(self, seed):
        self.scripted = ScriptedAgent(seed)

    def decide(self, agent_input):
        startled = agent_input.tick % 7 == 0
        if agent_input.prompt == CHANGE:
            return json.dumps({"changed": startled, "what": "Something fell over." if startled else ""})
        if APPRAISE not in agent_input.prompt:
            return self.scripted.decide(agent_input)
        return json.dumps({"feeling": "startled" if startled else "calm", "intensity": 0.8 if startled else 0.2,
                           "why": f"I can see {len(agent_input.visible)} things."})


def check_weights(path):
    """Full weights only, such as fused/ from experiments/homeostatic/export.py. A bare adapter would fail much later, inside the model load."""
    folder = Path(path)
    if not (folder / "config.json").exists() or not list(folder.glob("*.safetensors")):
        raise SystemExit(f"{folder} isn't a folder of full weights. An adapter has to be fused first: see experiments/homeostatic/HANDOFF.md.")
    return folder


def measured_qwen(weights=None):
    """The runtime's MLX Qwen agent, but keeping the token counts and load time that llm_model.ask throws away."""
    from kokopelli.loop.adapters.qwen import MAX_TOKENS, MlxQwenAgent, _with_retry_note

    class MeasuredQwen(MlxQwenAgent):
        last_usage = None

        def decide(self, agent_input):
            from kokopelli.wm import llm_model
            from mlx_vlm import generate  # pyright: ignore[reportPrivateImportUsage]  # mlx_vlm doesn't declare its re-exports
            from mlx_vlm.prompt_utils import apply_chat_template
            if self.weights:
                llm_model.LLM_MODEL_WEIGHTS = self.weights
            clock = time.perf_counter()
            model, processor = llm_model.load_llm()
            load_seconds = time.perf_counter() - clock
            images = [str(image) for image in agent_input.images]
            formatted = apply_chat_template(processor, model.config, _with_retry_note(agent_input), num_images=len(images))
            result = generate(model, processor, formatted, image=images or None, max_tokens=MAX_TOKENS, temperature=0.0)  # pyright: ignore[reportArgumentType]  # mlx_vlm's annotations are narrower than what it accepts
            self.last_usage = {"load_seconds": round(load_seconds, 3), "prompt_tokens": result.prompt_tokens,
                               "generation_tokens": result.generation_tokens, "prompt_tps": round(result.prompt_tps, 2),
                               "generation_tps": round(result.generation_tps, 2), "peak_memory_gb": round(result.peak_memory, 2),
                               "images": len(images), "max_tokens": MAX_TOKENS}
            return result.text.strip()

    return MeasuredQwen(str(check_weights(weights)) if weights else None)


def summarize(path):
    rows = read_rows(path)
    appraisals = [row for row in rows if row["kind"] == "appraisal"]
    return {"ticks": len(appraisals), "invalid_appraisals": sum(1 for row in appraisals if not row["feeling"]),
            "changes_noticed": sum(1 for row in appraisals if row.get("change")),
            "unreadable_changes": sum(1 for row in appraisals if row.get("change_raw")),
            "points": dict(Counter(row["point"] or "none" for row in appraisals)),
            "reasons": dict(Counter(row["reason"] for row in appraisals if row["reason"])),
            "feelings": dict(Counter(row["feeling"] for row in appraisals if row["feeling"]))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticks", type=int, default=60)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--agent", choices=["mock", "qwen"], default="mock")
    parser.add_argument("--resume", action="store_true", help="continue from the last finished tick in --out")
    parser.add_argument("--weights", help="a folder of full Qwen weights, such as a training run's fused/")
    args = parser.parse_args()
    inner = measured_qwen(args.weights) if args.agent == "qwen" else MockMind(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    feelings = args.out / "feelings.jsonl"
    config = Config(ticks=args.ticks, seed=args.seed, counterfactual=False, agent=args.agent, agent_weights=args.weights)
    totals = run(config, args.out, agent=FeelingAgent(inner, feelings), resume=args.resume)["run"]["totals"]
    summary = {**summarize(feelings), "invalid_replies": totals["invalid_replies"], "autonomy": totals["autonomy"],
               "seconds": totals["seconds"]}
    (args.out / "mind_summary.json").write_text(json.dumps(summary, indent=2))
    (args.out / "mind_timeline.json").write_text(json.dumps(timeline(feelings), indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
