"""P4-A/B1: a profile.json from p4_profile.py as Markdown tables: seconds per stage per push, and the stage sum against
the push's wall time measured around it by the caller.
    python3 tools/fable/p4_profile_table.py out/fable/P4/profile/profile.json [out/fable/P4/profile_shm/profile.json]
"""
import json
import sys

ORDER = ["client_write_controls", "read_controls", "encode", "weights_load", "control_branches", "denoise_0", "denoise_1",
         "denoise_2", "denoise_3", "history_store", "decode", "write_frames", "client_read_frames", "client_video_check"]
HANDOFF = ("client_write_controls", "read_controls", "write_frames", "client_read_frames")


def stages(push):
    return {**push["worker"], **{k: v for k, v in push["client"].items() if k != "client_call"}}


def table(path):
    d = json.load(open(path))
    pushes = d["pushes"]
    print(f"\n`{path}`: {d['model']}, {d['size']}, {d['quantize']}-bit, shm={d.get('shm', False)}, {d['seconds']} s total\n")
    cols = [f"{p['push']} {p['stream']}" for p in pushes]
    print("| stage | " + " | ".join(cols) + " |\n|---|" + "---|" * len(cols))
    seen = ORDER + sorted({k for p in pushes for k in stages(p)} - set(ORDER))
    for k in seen:
        print(f"| {k} | " + " | ".join(f"{stages(p).get(k, 0):.3f}" for p in pushes) + " |")
    for label, f in (("**stage sum**", lambda p: p["stage_sum_s"]), ("**wall (caller)**", lambda p: p["wall_s"]),
                     ("unnamed (wall - sum)", lambda p: p["unnamed_s"]),
                     ("sum / wall", lambda p: f"{100 * p['stage_sum_s'] / p['wall_s']:.1f}%" if p["wall_s"] else "-"),
                     ("frame handoff (4 stages)", lambda p: round(sum(stages(p).get(k, 0) for k in HANDOFF), 3)),
                     ("s per latent (worker)", lambda p: p["s_per_latent"]), ("MLX peak GB", lambda p: p["peak_gb"])):
        print(f"| {label} | " + " | ".join(str(f(p)) for p in pushes) + " |")


if __name__ == "__main__":
    for path in sys.argv[1:]:
        table(path)
