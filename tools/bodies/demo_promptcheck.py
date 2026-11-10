"""Before the world-model demo run: replay real decision prompts from a lunch run through Qwen, with demo_lunch.py's format
note added, and count how many replies parse and pass lunch_wm's checks (especially "say" with its words in "text").

    .venv/bin/python -m tools.bodies.demo_promptcheck out/bodies/demo/runs/sim --samples 3 --out out/bodies/demo/promptcheck.json
"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
from tools.bodies import demo_lunch as D  # noqa: E402

L = D.L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--per-mind", type=int, default=4)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    run = Path(a.run)
    events = [json.loads(l) for l in (run / "events.jsonl").read_text().splitlines() if l.strip()]
    decisions = [e for e in events if e["kind"] == "decision"]
    picked = []
    for mind in ("iris", "mara"):
        picked += [e for e in decisions if e["mind"] == mind][-a.per_mind:]
    brain = L.QwenBrain(L.ROOT / "models" / "Qwen3-VL-8B-Instruct-4bit")
    results, ok, says, bad = [], 0, 0, 0
    for e in picked:
        prompt = e["prompt"] + D.L.FORMAT_NOTE
        for k in range(a.samples):
            raw = brain.ask(prompt, e["frame"])
            row = {"mind": e["mind"], "step": e["step"], "sample": k, "raw": raw}
            try:
                thought, act, diary = L.parse_reply(raw)
                if act.get("type") == "say" and not str(act.get("text", "")).strip():
                    raise ValueError("say needs text")
                row["action"] = act
                ok += 1
                says += act.get("type") == "say"
            except Exception as ex:
                row["error"] = str(ex)
                bad += 1
            results.append(row)
            print(json.dumps({k2: row.get(k2) for k2 in ("mind", "step", "action", "error")}), flush=True)
    summary = {"replies": len(results), "valid": ok, "invalid": bad, "say": says,
               "model": "Qwen3-VL-8B-Instruct-4bit", "format_note": D.L.FORMAT_NOTE, "run": str(run), "results": results}
    Path(a.out).write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: summary[k] for k in ("replies", "valid", "invalid", "say")}))


if __name__ == "__main__":
    main()
