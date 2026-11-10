"""P4-A: compare machine readings during 150-frame Variant A 8-bit paints.

Read-only. Reads out/ops/job_logs/*.metrics.jsonl, the paint sidecars and the
GPU ledger, and prints one row per paint for the paint window only (a job that
also captured is cut to its last `seconds` from the sidecar).
"""
import json
import statistics as st
import sys
from pathlib import Path

K = Path(__file__).resolve().parents[2]
LOGS = K / "out/ops/job_logs"
PAINTS = [  # (label, job log stem, sidecar)
    ("a4_full_8bit", "20261108-181845-wmmc_a4_full_8bit",
     "out/wm_multicontrol/a4_full_8bit/a4_full_8bit.mp4.json"),
    ("demo_flyover3", "20261109-122104-wmdemo_flyover3",
     "out/city_wm/demo_flyover/demo_flyover_wm.mp4.json"),
    ("still_B", "20261110-114922-fable_p3c_still_B",
     "out/wm_multicontrol/fable_still_B/fable_still_B.mp4.json"),
    ("still_C", "20261110-120302-fable_p3c_still_C",
     "out/wm_multicontrol/fable_still_C/fable_still_C.mp4.json"),
]


def ledger():
    for line in (K / "out/ops/gpu_ledger.jsonl").open():
        try:
            yield json.loads(line)
        except ValueError:
            pass


def finished(stem):
    for e in ledger():
        if e.get("event") == "finished" and e.get("log", "").endswith(stem + ".log"):
            return e
    return None


def others(start, end, name):
    """Other queue jobs whose run overlapped [start, end]."""
    starts, out = {}, []
    for e in ledger():
        if e.get("event") == "started":
            starts[e["id"]] = e["at"]
        elif e.get("event") == "finished" and e["id"] in starts and e["name"] != name:
            s = starts[e["id"]]
            if s < end and e["at"] > start:
                out.append(f'{e["name"]}({int(min(end, e["at"]) - max(start, s))}s)')
    return out


def q(xs, f):
    xs = [x for x in xs if x is not None]
    return round(f(xs), 1) if xs else None


def main():
    hdr = ("paint", "frames", "paint_s", "denoise_s", "decode_s", "encode_s",
           "watts_mean", "busy_mean", "temp_mean", "temp_max", "s>=95C",
           "swap_start", "swap_max", "other_ram_mean", "overlap")
    rows = [hdr]
    for label, stem, side in PAINTS:
        sc = json.loads((K / side).read_text())
        fin = finished(stem)
        end = fin["at"]
        start = end - sc["seconds"]
        ms = [json.loads(x) for x in (LOGS / f"{stem}.metrics.jsonl").open()]
        ms = [m for m in ms if start <= m["at"] <= end and "watts" in m]
        temps = [m["gpu_temp"] for m in ms]
        step = (ms[-1]["at"] - ms[0]["at"]) / max(1, len(ms) - 1)
        t = sc["timing"]
        rows.append((
            label, sc["frames"], sc["seconds"], t["denoise_s"], t["decode_s"], t["encode_s"],
            q([m["watts"] for m in ms], st.mean), q([m["gpu_busy"] for m in ms], st.mean),
            q(temps, st.mean), q(temps, max), int(sum(step for x in temps if x >= 95)),
            round(ms[0]["swap_gb"], 1), q([m["swap_gb"] for m in ms], max),
            q([m["ram_gb"] - m["job_gb"] for m in ms], st.mean),
            " ".join(others(start, end, fin["name"])) or "-",
        ))
    w = sys.stdout.write
    w("| " + " | ".join(map(str, rows[0])) + " |\n|" + "---|" * len(hdr) + "\n")
    for r in rows[1:]:
        w("| " + " | ".join(map(str, r)) + " |\n")


if __name__ == "__main__":
    main()
