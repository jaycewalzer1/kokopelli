#!/usr/bin/env python
"""Wave 2 (integration) evidence: MetaHuman bodies on the SimWorld server (port 9004 only).

    simworld/.venv/bin/python -m tools.bodies.wave2_renders evidence [--port 9004] [--out DIR] [--label editor]
    simworld/.venv/bin/python -m tools.bodies.wave2_renders perf --max-near 3 [--port 9004] [--pid PID] [--out DIR]

evidence: close-up, mid and aerial renders; a first-person approach (mara's eye camera while she and iris walk
towards each other across the near/far switch), every step with lit + seg (object_mask) + depth, so the frames
before, during and after the 0.4 s fade are all there; a contact sheet; render.json.
perf: 8 residents lined up (a spawned close camera makes all of them want near, so max_near decides how many get
the High body), then the aerial view: GPU ms (CITY_manager frame stats) and capture ms; the server process's peak
RSS is sampled throughout (pass --pid). Writes perf_maxnear<N>.json; the caller relaunches the server with a
Bodies.json whose max_near is N (-bodies=<path>).
Expects a built city (tools/city_build/build_city.py --port 9004).
"""
import argparse
import io
import json
import math
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from tools.bodies.wave1_renders import AGENT, PED, Conn  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out" / "bodies" / "renders" / "wave2"
A, B = "GEN_BP_Humanoid_0", "GEN_BP_Humanoid_1"  # mara, iris (Bodies.json actors)
OX, OY = 20300, 15800  # street spot in front of the street_fern view (as wave 1)
ASSETS = {
    "bodies_json": "mac_server/Config/Bodies.json",
    "meshes": "/Game/Characters/Bodies/<id>/{High,Low}/<id>_{high,low}/{Body,Face}/SKM_MHC_<id>_{Body,Face}Mesh "
              "(MetaHuman Creator, agent A, wave 1; migrated by tools/bodies/migrate_bodies.sh; Common shared)",
    "people": ["mara", "iris", "ana", "tomas", "wen", "priya", "kai"],
    "anim": "/Game/Characters/Anim/ABP_Body (parent /Script/SimWorld.SWBodyAnimInstance); clips MM_Idle, "
            "MF_Unarmed_Walk_Fwd, MF_Unarmed_Jog_Fwd (UE 5.8 Third Person template)",
    "fallback": "/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple",
    "city": "data/city/world.json via tools/city_build/build_city.py",
}


def core_data_installed():
    opt = Path("/Users/Shared/Epic Games/UE_5.8/Engine/Plugins/MetaHuman/MetaHumanCharacter/Content/Optional")
    return (opt / "TextureSynthesis").exists() or (opt / "BodyTextures").exists()


class Server:
    def __init__(self, port):
        self.c = Conn(port)

    def __call__(self, cmd):
        return self.c(cmd)

    def j(self, cmd):
        return json.loads(self.c(cmd))

    def loc(self, n):
        return [float(v) for v in self.c(f"vget /object/{n}/location").split()]

    def cam(self, cam, pose, fov=None):
        x, y, z, p, yaw = pose
        if fov:
            self.c(f"vset /camera/{cam}/fov {fov}")
        self.c(f"vset /camera/{cam}/location {x} {y} {z}")
        self.c(f"vset /camera/{cam}/rotation {p} {yaw} 0")

    def capture(self, cam, path, kinds=("lit",)):
        got = {}
        for k in kinds:
            if k == "lit":
                p = path.with_suffix(".png")
                self.c(f"vget /camera/{cam}/lit {p}")
                got[k] = p.name if p.exists() else None
            elif k == "seg":
                p = path.with_name(path.name + "_seg.png")
                data = self.c(f"vget /camera/{cam}/object_mask png")
                if isinstance(data, bytes):
                    p.write_bytes(data)
                got[k] = p.name if p.exists() else None
            elif k == "depth":
                p = path.with_name(path.name + "_depth")
                data = self.c(f"vget /camera/{cam}/depth npy")
                if isinstance(data, bytes):
                    d = np.load(io.BytesIO(data))
                    np.save(p.with_suffix(".npy"), d.astype(np.float32))
                    v = np.clip(d, 0, 6000)
                    img = (255 * (1 - np.log1p(v) / np.log1p(6000))).astype(np.uint8)
                    Image.fromarray(img).save(p.with_suffix(".png"))
                    got[k] = p.with_suffix(".npy").name
        return got


def clear(s, names):
    for n in names:
        s(f"vset /object/{n}/destroy")
    s("vset /action/clean_garbage")


def wait_tier(s, name, want, timeout=20):
    t = time.time()
    while time.time() - t < timeout:
        d = s.j(f"vbp {name} GetBodyDebug")
        if d["tier"] == want and not d["fading"]:
            return d
        time.sleep(0.2)
    return s.j(f"vbp {name} GetBodyDebug")


def evidence(a):
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    s = Server(a.port)
    frames = []

    def note(name, cam, got, extra=None):
        rec = {"frame": name, "camera": cam, **got, "bodies": s.j("vget /bodies"), "t": round(time.time(), 3)}
        rec.update(extra or {})
        frames.append(rec)
        print(name, got)

    people = [A, B] + [f"GEN_BP_Pedestrian_W2_{i}" for i in range(6)]
    clear(s, people + [f"GEN_BP_Pedestrian_Perf{i}" for i in range(8)])
    s("vset /action/tick_intervel 0")
    s("vset /action/game/resume")
    s(f"vset /objects/spawn_bp_asset {AGENT} {A}")
    s(f"vset /object/{A}/location {OX} {OY} 400")
    s(f"vset /object/{A}/rotation 0 0 0")
    time.sleep(2.5)
    ground = s.loc(A)[2] - 90
    # park camera 0 looking at the sky while it isn't the shot, so it never pulls anyone near by accident
    sky = (OX, OY, ground + 5000, 89, 0)

    s("vset /camera/0/size 832 480")
    # 1. close-up and mid of mara (near), then each resident at mid range
    s(f"vbp {A} SetBody mara")
    s.cam(0, (OX + 95, OY - 20, ground + 158, -3, 168), fov=40)
    d = wait_tier(s, A, "near")
    note("closeup_mara", 0, s.capture(0, out / "closeup_mara", ("lit", "seg", "depth")), {"debug": d})
    s.cam(0, (OX + 330, OY - 120, ground + 140, -6, 160), fov=60)
    time.sleep(0.5)
    note("mid_mara", 0, s.capture(0, out / "mid_mara", ("lit", "seg", "depth")))
    s(f"vbp {A} SetMaxSpeed 140")
    s(f"vbp {A} MoveForward")
    time.sleep(1.2)
    s("vset /action/game/pause")
    p = s.loc(A)
    s.cam(0, (p[0] + 120, p[1] - 330, ground + 140, -6, 110), fov=60)
    note("mid_mara_walk", 0, s.capture(0, out / "mid_mara_walk", ("lit", "seg", "depth")))
    s("vset /action/game/resume")
    s(f"vbp {A} StopAgent")
    clear(s, [A])

    ids = ["iris", "ana", "tomas", "wen", "priya", "kai"]
    heights = {"iris": 174, "ana": 162, "tomas": 178, "wen": 166, "priya": 160, "kai": 138}
    for i, pid in enumerate(ids):
        n = people[2 + i]
        s(f"vset /objects/spawn_bp_asset {PED} {n}")
        s(f"vset /object/{n}/location {OX + i * 90} {OY} 400")
        s(f"vset /object/{n}/rotation 0 180 0")
        s(f"vbp {n} SetBody {pid}")
    time.sleep(2.0)
    s.cam(0, (OX + 225, OY + 520, ground + 150, -6, -90), fov=60)
    for n in people[2:]:
        wait_tier(s, n, "near", timeout=10)  # max_near caps how many; the rest stay far
    note("mid_residents", 0, s.capture(0, out / "mid_residents", ("lit", "seg", "depth")))
    for i, pid in enumerate(ids):
        s.cam(0, (OX + i * 90 - 95, OY - 45, ground + heights[pid] - 12, -6, 25), fov=35)
        time.sleep(1.2)
        note(f"closeup_{pid}", 0, s.capture(0, out / f"closeup_{pid}"))
    # 2. aerial with the six residents in it (all far at that distance)
    s.cam(0, (OX + 225, OY - 4000, ground + 2500, -32, 90), fov=60)
    time.sleep(1.5)
    note("aerial_residents", 0, s.capture(0, out / "aerial_residents", ("lit", "seg", "depth")))
    s.cam(0, (30000, 82000, 33000, -32, 270), fov=75)
    time.sleep(1.0)
    note("aerial_overview", 0, s.capture(0, out / "aerial_overview"))
    clear(s, people[2:])

    # 3. first person: mara and iris walk towards each other from 50 m; mara's eye camera (camera 1) watches iris
    s.cam(0, sky)
    s(f"vset /objects/spawn_bp_asset {AGENT} {A}")
    # along +y from the street spot: open street for 50 m (x +-25 m from it runs into buildings)
    s(f"vset /object/{A}/location {OX - 40} {OY - 2500} 400")
    s(f"vset /object/{A}/rotation 0 90 0")
    s(f"vset /objects/spawn_bp_asset {AGENT} {B}")
    s(f"vset /object/{B}/location {OX + 40} {OY + 2500} 400")
    s(f"vset /object/{B}/rotation 0 -90 0")
    time.sleep(3.0)
    cams = s("vget /cameras").split()
    cam_a = 1  # first agent's eye camera
    for c in (1, 2):
        s(f"vset /camera/{c}/size 832 480")
    print("cameras", cams, "iris tier", s.j(f"vbp {B} GetBody"))
    dt = 0.05
    s("vset /action/game/pause")
    s(f"vset /action/tick_intervel {dt}")
    s(f"vbp {A} SetMaxSpeed 150")
    s(f"vbp {B} SetMaxSpeed 150")
    s(f"vbp {A} MoveForward")
    s(f"vbp {B} MoveForward")
    approach = []
    step = 0
    switch_step = None
    while True:
        s("vset /action/tick")
        step += 1
        d = s.j(f"vbp {B} GetBodyDebug")
        pa, pb = s.loc(A), s.loc(B)
        dist = math.dist(pa[:2], pb[:2])
        rec = {"step": step, "t_sim": round(step * dt, 2), "dist_m": round(dist / 100, 2), "iris_tier": d["tier"],
               "iris_body": d["body"], "fading": d["fading"], "fade": round(d["fade"], 3), "px": round(d["px"], 1),
               "visible_meshes": d["visible_meshes"]}
        if d["fading"] and switch_step is None:
            switch_step = step
        # dense capture from 34 m to 20 m (the switch is at ~26 m for a 174 cm person at 416 px focal)
        if 2000 <= dist <= 3400 and step % 2 == 0 or d["fading"]:
            name = f"fp_{step:04d}"
            rec.update(s.capture(cam_a, out / name, ("lit", "seg", "depth")))
            rec["frame"] = name
        approach.append(rec)
        if dist < 400 or step > 600:
            break
    s(f"vbp {A} StopAgent")
    s(f"vbp {B} StopAgent")
    s.capture(cam_a, out / "fp_close", ("lit", "seg", "depth"))
    s("vset /action/tick_intervel 0")
    s("vset /action/game/resume")
    (out / "approach.json").write_text(json.dumps({"dt_s": dt, "switch_step": switch_step, "steps": approach}, indent=1))
    clear(s, [A, B])

    sidecar = {
        "made": datetime.now().isoformat(timespec="seconds"),
        "by": "tools/bodies/wave2_renders.py evidence (wave 2 integration)",
        "server": f"mac_server {a.label} on port {a.port}",
        "models": "none (no ML models; Unreal renders only)",
        "assets": ASSETS,
        "core_data_installed": core_data_installed(),
        "look": "skin/hair/clothes from MetaHuman Creator Core Data" if core_data_installed() else
                "grey clay: MetaHuman Creator Core Data not installed (no skin tone, hair, brows or clothes)",
        "approach": {"file": "approach.json", "switch_step": switch_step, "dt_s": dt,
                     "camera": "camera 1 = mara's eye camera (GEN_BP_Humanoid_0), 832x480"},
        "frames": frames,
    }
    (out / "render.json").write_text(json.dumps(sidecar, indent=1))
    contact_sheet(out, approach, switch_step)
    print("wrote", out)


def contact_sheet(out, approach, switch_step):
    tiles = []
    for name in ["closeup_mara", "mid_mara", "mid_mara_walk", "mid_residents", "aerial_residents", "aerial_overview"]:
        tiles.append((out / f"{name}.png", name))
    for pid in ["iris", "ana", "tomas", "wen", "priya", "kai"]:
        tiles.append((out / f"closeup_{pid}.png", f"closeup_{pid}"))
    shot = [r for r in approach if "frame" in r]
    if switch_step is not None:
        before = [r for r in shot if r["step"] < switch_step][-2:]
        during = [r for r in shot if r["fading"]]
        during = [during[0], during[len(during) // 2], during[-1]] if during else []
        after = [r for r in shot if r["step"] > switch_step and not r["fading"]][:2]
        pick = before + during + after
    else:
        pick = shot[:: max(1, len(shot) // 6)][:6]
    rows_fp = []
    crop = (416 - 52 + 8, 240 - 30 + 10, 416 + 52 + 8, 240 + 30 + 10)  # iris, 4x zoom of the frame centre
    for r in pick:
        lab = f"{r['frame']} {r['dist_m']}m {r['iris_tier']}{' fade {:.2f}'.format(r['fade']) if r['fading'] else ''} (4x crop)"
        rows_fp.append([(out / f"{r['frame']}.png", lab, crop), (out / f"{r['frame']}_seg.png", "seg (4x crop)", crop),
                        (out / f"{r['frame']}_depth.png", "depth (4x crop)", crop)])
    if pick:
        tiles.append((out / f"{pick[0]['frame']}.png", f"first person {pick[0]['frame']} (full frame, mara's eyes)"))
    tiles.append((out / "fp_close.png", "first person, 4 m"))
    W, H = 416, 240
    cols = 6
    top_rows = math.ceil(len(tiles) / cols)
    sheet = Image.new("RGB", (W * cols, H * (top_rows + len(rows_fp) // 2 + len(rows_fp) % 2)), "white")
    draw = ImageDraw.Draw(sheet)

    def put(path, label, x, y, box=None):
        if path.exists():
            im = Image.open(path).convert("RGB")
            if box:
                im = im.crop(box).resize((W, H), Image.NEAREST)
            im.thumbnail((W, H))
            sheet.paste(im, (x, y))
        draw.rectangle([x, y, x + W - 1, y + 14], fill=(0, 0, 0))
        draw.text((x + 3, y + 1), label, fill=(255, 255, 255))

    for i, (p, lab) in enumerate(tiles):
        put(p, lab, (i % cols) * W, (i // cols) * H)
    for i, trio in enumerate(rows_fp):
        y = (top_rows + i // 2) * H
        for k, (p, lab, box) in enumerate(trio):
            put(p, lab, ((i % 2) * 3 + k) * W, y, box)
    sheet.save(out / "contact_sheet.png")


def rss_sampler(pid, stop, peak):
    while not stop.is_set():
        try:
            kb = int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)]).strip() or 0)
            peak["rss_gb"] = max(peak.get("rss_gb", 0), kb / 1e6)
        except (subprocess.CalledProcessError, ValueError):
            pass
        stop.wait(1.0)


def perf(a):
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    s = Server(a.port)
    stop, peak = threading.Event(), {}
    th = threading.Thread(target=rss_sampler, args=(a.pid, stop, peak), daemon=True) if a.pid else None
    if th:
        th.start()
    have_manager = "CITY_manager" in s("vget /objects").split()
    names = [f"GEN_BP_Pedestrian_Perf{i}" for i in range(8)]
    clear(s, names)
    ids = ["mara", "iris", "ana", "tomas", "wen", "priya", "kai", "ana"]
    bx, by = 30000, 30000
    for i, n in enumerate(names):
        s(f"vset /objects/spawn_bp_asset {PED} {n}")
        s(f"vset /object/{n}/location {bx + i * 80} {by} 400")
        s(f"vset /object/{n}/rotation 0 -90 0")
        s(f"vbp {n} SetBody {ids[i]}")
    time.sleep(2.0)
    ground = s.loc(names[0])[2] - 90
    # a free capture camera 7 m in front of the line: every person > 28 px, so max_near decides
    s("vset /cameras/spawn").strip()
    ncam = len(s("vget /cameras").split()) - 1
    s.cam(ncam, (bx + 280, by - 700, ground + 120, 0, 90), fov=90)
    t = time.time()
    while time.time() - t < 30:
        tiers = s.j("vget /bodies")
        near = sum(1 for n in names if tiers.get(n, {}).get("tier") == "near")
        fading = any(tiers.get(n, {}).get("fading") for n in names)
        if near >= min(a.max_near, 8) and not fading:
            break
        time.sleep(0.5)
    tiers = s.j("vget /bodies")
    counts = {}
    for n in names:
        counts[tiers[n]["tier"]] = counts.get(tiers[n]["tier"], 0) + 1
    s(f"vset /camera/{ncam}/size 832 480")
    s(f"vget /camera/{ncam}/lit {out / f'perf_line_maxnear{a.max_near}.png'}")
    res = {"max_near": a.max_near, "tiers": counts, "per_person": {n: tiers[n] for n in names}}
    def gpu_busy():
        try:
            o = subprocess.check_output(["ioreg", "-r", "-c", "IOAccelerator", "-d", "1"]).decode()
            return int(o.split('"Device Utilization %"=')[1].split(",")[0].split("}")[0])
        except Exception:  # noqa: BLE001
            return None

    def measure(n):
        if have_manager:
            s("vbp CITY_manager ResetFrameStats")
        t = time.time()
        for _ in range(n):
            s("vget /camera/0/lit png")
        dt = (time.time() - t) / n
        stats = json.loads(json.loads(s("vbp CITY_manager GetFrameStats"))["Stats"]) if have_manager else {}
        return stats.get("gpu_ms"), dt * 1000

    def footprint():
        """Physical footprint (incl. Metal/unified allocations) and its peak since launch, from vmmap."""
        if not a.pid:
            return {}
        try:
            o = subprocess.run(["vmmap", "--summary", str(a.pid)], capture_output=True, timeout=180).stdout.decode()
        except Exception as ex:  # noqa: BLE001
            return {"error": repr(ex)}
        units = {"K": 2**-20, "M": 2**-10, "G": 1.0}
        got = {}
        for line in o.splitlines():
            if line.startswith("Physical footprint"):
                key = "phys_footprint_peak" if "peak" in line else "phys_footprint"
                v = line.split(":")[1].strip()
                got[key] = round(float(v[:-1]) * units.get(v[-1], 2**-30), 2)
        return got

    res["memory_gb_settled"] = footprint()
    res["gpu_busy_pct_before"] = gpu_busy()
    for view, pose, fov in (("aerial", (30000, 82000, 33000, -32, 270), 75),
                            ("street", (bx + 280, by - 700, ground + 120, 0, 90), 90)):
        s.cam(0, pose, fov=fov)
        s("vset /camera/0/size 1280 720")
        s(f"vget /camera/0/lit {out / f'perf_{view}_maxnear{a.max_near}.png'}")
        shown, hidden = [], []
        for _ in range(a.rounds):  # interleaved A/B so other GPU users (training jobs) hit both sides alike
            for n in names:
                s(f"vset /object/{n}/show")
            shown.append(measure(a.captures))
            for n in names:
                s(f"vset /object/{n}/hide")
            hidden.append(measure(a.captures))
        for n in names:
            s(f"vset /object/{n}/show")
        med = lambda xs, i: round(float(np.median([x[i] for x in xs if x[i] is not None])), 2) if xs else None  # noqa: E731
        res[view] = {"gpu_ms_people": med(shown, 0), "gpu_ms_hidden": med(hidden, 0),
                     "gpu_ms_delta": round(med(shown, 0) - med(hidden, 0), 2) if have_manager else None,
                     "capture_ms_people": med(shown, 1), "capture_ms_hidden": med(hidden, 1),
                     "rounds_people": shown, "rounds_hidden": hidden}
        print(view, {k: v for k, v in res[view].items() if not k.startswith("rounds")})
    res["gpu_busy_pct_after"] = gpu_busy()
    time.sleep(2.0)
    stop.set()
    if th:
        th.join(timeout=30)
    res["memory_gb_end"] = footprint()
    res["peak_rss_gb"] = round(peak.get("rss_gb", 0), 2)
    res["pid"] = a.pid
    res["method"] = ("8 residents (7 MetaHumans + ana twice) lined up 80 cm apart; a spawned camera 7 m away makes all "
                     f"want near, max_near caps it. GPU: CITY_manager GetFrameStats gpu_ms, median over {a.rounds} interleaved "
                     f"rounds of {a.captures} back-to-back 1280x720 lit captures from camera 0 with the 8 people shown vs hidden "
                     "(aerial_overview 300,820,330 m pitch -32; street = the line-up view 7 m away); window minimized. "
                     "gpu_busy_pct = IOAccelerator Device Utilization sampled before/after (other jobs on the GPU). "
                     "Memory: `vmmap --summary` physical footprint and its peak for the server process (includes Metal/unified "
                     "allocations, which ps RSS misses), launched fresh for this max_near")
    res["assets"] = ASSETS
    res["core_data_installed"] = core_data_installed()
    res["made"] = datetime.now().isoformat(timespec="seconds")
    (out / f"perf_maxnear{a.max_near}.json").write_text(json.dumps(res, indent=1, default=list))
    clear(s, names)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("part", choices=["evidence", "perf", "sheet"])
    ap.add_argument("--port", type=int, default=9004)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--label", default="editor-game")
    ap.add_argument("--max-near", type=int, default=3)
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--captures", type=int, default=10)
    ap.add_argument("--rounds", type=int, default=4)
    a = ap.parse_args()
    if a.port in (9001, 9003):
        sys.exit("bodies work runs on 9004 only")
    if a.part == "evidence":
        evidence(a)
    elif a.part == "perf":
        perf(a)
    else:
        ap_json = json.loads((Path(a.out) / "approach.json").read_text())
        contact_sheet(Path(a.out), ap_json["steps"], ap_json["switch_step"])


if __name__ == "__main__":
    main()
