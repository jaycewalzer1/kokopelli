"""The 5 s bridge run the user chose: Cosmos3-Nano-Sim-Transfer, blur control V2 (NVIDIA "high", down/up 16),
832x480, first 150 frames of out/filter_test/test_clip, prompt variant a. Queued through ops/gpu.py.

    .venv/bin/python -I city/wm/run_bridge_final.py
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from world_transfer import transfer_video  # noqa: E402

MODEL = "Cosmos3-Nano-Sim-Transfer"
CONTROL = ROOT / "out/city_wm/bridge/controls/832x480/blur_v2_high.mp4"
OUT = ROOT / "out/city_wm/bridge/final/bridge_5s_simtransfer_blur_v2.mp4"
VARIANT = "a_faithful_photoreal"


def main():
    variants = json.loads((ROOT / "city/wm/prompts/bridge.json").read_text())["variants"]
    prompt = next(v["prompt"] for v in variants if v["id"] == VARIANT)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"model: {MODEL} | control: blur v2 high | 832x480 | 150 frames | prompt {VARIANT}", flush=True)
    t = time.time()
    transfer_video(prompt, {"blur": str(CONTROL)}, str(OUT), size="832x480", frames=150, seed=2025)
    side = Path(str(OUT) + ".json")
    meta = json.loads(side.read_text())
    meta.update(prompt_variant=VARIANT, chosen_by="user", control_variant="blur_v2_high")
    side.write_text(json.dumps(meta, indent=1))
    print(f"done in {time.time() - t:.0f}s: {OUT} (model {meta.get('model')}, peak {meta.get('peak_gb')} GB)", flush=True)


if __name__ == "__main__":
    main()
