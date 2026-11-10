"""P4-C: 8-bit vs 4-bit gen weights on the bridge clip. CPU only, read-only on the videos.

Per paint: wall and stage seconds and MLX peak from its sidecar, the job's peak footprint and swap from the ledger,
core/video_check scores (median mosaic and drift over the clip, bad windows, first failure), and PSNR against the
original a4_full_8bit result (same seed, same controls), so the effect of 4-bit on the picture is a number.
    .venv/bin/python scripts/fable/p4_c_compare.py > out/fable/P4/bits/compare.md
"""
import json
import sys
from pathlib import Path

import numpy as np

K = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(K))
from core import video_check as vc  # noqa: E402

BRIDGE = K / "out/city_wm/bridge/controls/832x480/blur.mp4"
REF = K / "out/wm_multicontrol/a4_full_8bit/a4_full_8bit.mp4"
PAINTS = [("a4_full_8bit (2026-11-08, battery)", REF, "wmmc_a4_full_8bit"),
          ("bridge_8bit (this session)", K / "out/fable/P4/bits/bridge_8bit.mp4", "fable_P4_bridge_8bit"),
          ("bridge_4bit (LOWERED PRECISION)", K / "out/fable/P4/bits/bridge_4bit.mp4", "fable_P4_bridge_4bit")]


def ledger_finished(name):
    last = {}
    for line in (K / "out/ops/gpu_ledger.jsonl").open():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("event") == "finished" and e.get("name") == name and not e.get("dry_run"):
            last = e
    return last


def psnr(a, b):
    total, n = 0.0, 0
    for x, y in zip(vc.read_frames(str(a)), vc.read_frames(str(b)), strict=False):
        m = min(len(x), len(y))
        total += float(((x[:m].astype(np.float32) - y[:m].astype(np.float32)) ** 2).mean()) * m
        n += m
    mse = total / max(n, 1)
    return round(10 * np.log10(255 ** 2 / mse), 2) if mse else float("inf")


def main():
    hdr = ("paint", "seconds", "denoise_s", "decode_s", "encode_s", "mlx_peak_gb", "job_peak_gb", "swap_max_gb",
           "watts_mean", "mosaic_med", "drift_med", "bad_windows", "first_failure_t", "psnr_vs_a4_full_8bit_db")
    print("| " + " | ".join(hdr) + " |\n|" + "---|" * len(hdr))
    for label, path, job in PAINTS:
        if not path.exists():
            print(f"| {label} | missing: {path.relative_to(K)} |")
            continue
        sc = json.loads(Path(str(path) + ".json").read_text())
        t, fin = sc.get("timing", {}), ledger_finished(job)
        rows = vc.score_video(str(path), str(BRIDGE), stride=2)
        wins = vc.windows(rows, 30)
        fail = vc.first_failure(wins)
        med = vc.judge(rows)
        print("| " + " | ".join(str(x) for x in (
            label, sc["seconds"], t.get("denoise_s"), t.get("decode_s"), t.get("encode_s"), sc.get("peak_gb"),
            fin.get("peak_job_gb"), fin.get("peak_swap_gb"), fin.get("watts_mean"), med["mosaic"], med["drift"],
            f"{sum(1 for w in wins if w['bad'])}/{len(wins)}", fail["t"] if fail else "-",
            "ref" if path == REF else psnr(REF, path))) + " |")


if __name__ == "__main__":
    main()
