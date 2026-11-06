#!/usr/bin/env python
"""Re-render the bridge walk (out/filter_test/test_clip/) from its recorded camera poses, without the agent.

    simworld/.venv/bin/python -I city/realism/replay_bridge.py --port 9003 --label before [--frames 0:300:30] [--modes rgb]

Camera 0 is put at each frame's camera extrinsics from poses.jsonl (location cm, pitch/yaw/roll deg), 90 deg FOV,
1280x720, and rgb (lit png), depth (npy, cm) and segmentation (object_mask png) are saved untouched, frame-aligned
with the original clip. The original capture ran with no weather manager, so its "14:00" never moved the sun: the
server's default sun is the same light. Differences from the original: no agent body (so no walker shadow on the deck).

Writes out/city_realism/<label>/{rgb,depth,segmentation}/NNNN.*, rgb.mp4 (30 fps, CRF 16, like the original),
poses.jsonl (the frames used) and capture.json.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIP = ROOT / "out" / "filter_test" / "test_clip"
OUT = ROOT / "out" / "city_realism"
MODES = {"rgb": ("lit", "png", "rgb"), "depth": ("depth", "npy", "depth"), "seg": ("object_mask", "png", "segmentation")}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=9003)
    ap.add_argument("--label", required=True, help="output folder under out/city_realism/")
    ap.add_argument("--frames", default="0:300:1", help="start:stop:step over poses.jsonl")
    ap.add_argument("--modes", default="rgb,depth,seg")
    ap.add_argument("--settle", type=float, default=3.0, help="seconds before the first frame (exposure, Lumen history)")
    ap.add_argument("--step-wait", type=float, default=0.1, help="seconds between moving the camera and capturing")
    args = ap.parse_args()
    if args.port == 9001:
        sys.exit("9001 is the user's live server; use your own instance")

    from unrealcv import Client
    import warnings
    warnings.filterwarnings("ignore")
    c = Client(("127.0.0.1", args.port))
    if not c.connect(timeout=5):
        sys.exit("cannot connect")

    def req(cmd, timeout=60):
        return c.request(cmd, timeout=timeout)

    a, b, s = (int(x) for x in args.frames.split(":"))
    poses = [json.loads(line) for line in (CLIP / "poses.jsonl").read_text().splitlines()][a:b:s]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    out = OUT / args.label
    for m in modes:
        (out / MODES[m][2]).mkdir(parents=True, exist_ok=True)

    req("vset /action/game/resume")
    req("vset /camera/0/size 1280 720")
    req("vset /camera/0/fov 90")
    t0 = time.time()
    for k, p in enumerate(poses):
        ext = p["state"]["camera"]["extrinsics"]
        loc, rot = ext["location_cm"], ext["rotation_deg"]
        req(f"vset /camera/0/location {loc['x']:.3f} {loc['y']:.3f} {loc['z']:.3f}")
        req(f"vset /camera/0/rotation {rot['pitch']:.4f} {rot['yaw']:.4f} {rot['roll']:.4f}")
        time.sleep(args.settle if k == 0 else args.step_wait)
        for m in modes:
            view, fmt, folder = MODES[m]
            data = req(f"vget /camera/0/{view} {fmt}")
            if not isinstance(data, (bytes, bytearray)) or len(data) < 64:
                sys.exit(f"frame {p['frame']} {m}: bad reply {str(data)[:120]!r}")
            (out / folder / f"{p['frame']:04d}.{fmt}").write_bytes(data)
        if k % 30 == 0:
            print(f"frame {p['frame']:4d}  {time.time() - t0:6.1f}s", flush=True)

    (out / "poses.jsonl").write_text("".join(json.dumps(p) + "\n" for p in poses))
    (out / "capture.json").write_text(json.dumps({
        "source_poses": str(CLIP / "poses.jsonl"), "frames": args.frames, "count": len(poses), "fps": 30,
        "size": [1280, 720], "fov_deg": 90, "server_port": args.port, "camera_id": 0, "modes": modes,
        "note": "camera replay of the recorded poses, no agent body; depth in cm float32 as the server returns it",
        "seconds": round(time.time() - t0, 1)}, indent=1))
    if "rgb" in modes and s == 1:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "30", "-start_number", str(a), "-i", str(out / "rgb" / "%04d.png"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", str(out / "rgb.mp4")], check=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
