#!/usr/bin/env python
"""Wave 1 (agent B) renders and perf of Manny-bodied people on the SimWorld server (test game on port 9004).

    ~/Desktop/kokopelli/simworld/.venv/bin/python city/bodies/wave1_renders.py [--port 9004] [--build-city]

Writes out/bodies/renders/wave1_server/: idle / walk / talk / sit / carry of an agent (GEN_BP_Humanoid_0 -> mara, which
falls back to manny until agent A's MetaHumans land) in first and third person; idle / walk of a resident
(GEN_BP_Pedestrian_0 -> ana -> manny); the near/far stand-ins side by side; perf.json (aerial view, 0 / 2 / 8 bodies);
render.json sidecar (assets, body + tier per person per frame, camera poses).
"""
import argparse
import json
import math
import socket
import struct
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out" / "bodies" / "renders" / "wave1_server"
MAGIC = 0x9E2B83C1
AGENT = "/Game/TrafficSystem/Pedestrian/Base_User_Agent.Base_User_Agent_C"
PED = "/Game/TrafficSystem/Pedestrian/Base_Pedestrian.Base_Pedestrian_C"
MUG = "/Game/InteractableAsset/Cup/BP_Mug.BP_Mug_C"
COUCH = "/Game/CityDatabase/blueprints/BP_Couch.BP_Couch_C"
A, R = "GEN_BP_Humanoid_0", "GEN_BP_Pedestrian_0"


class Conn:
    def __init__(self, port):
        for _ in range(40):  # stray second listeners on the port (crashed editors) never handshake: retry
            self.s = socket.create_connection(("127.0.0.1", port), timeout=3)
            try:
                self.recv()
                break
            except (OSError, ConnectionError):
                self.s.close()
        self.s.settimeout(120)
        self.id = 0

    def recvn(self, n):
        b = b""
        while len(b) < n:
            c = self.s.recv(n - len(b))
            if not c:
                raise ConnectionError("closed")
            b += c
        return b

    def recv(self):
        _, n = struct.unpack("<II", self.recvn(8))
        return self.recvn(n)

    def __call__(self, cmd):
        self.id += 1
        p = b"%d:%s" % (self.id, cmd.encode())
        self.s.sendall(struct.pack("<II", MAGIC, len(p)) + p)
        body = self.recv().split(b":", 1)[1]
        try:
            return body.decode()
        except UnicodeDecodeError:
            return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9004)
    ap.add_argument("--build-city", action="store_true")
    ap.add_argument("--perf-captures", type=int, default=20)
    a = ap.parse_args()
    if a.port in (9001, 9003):
        sys.exit("bodies work runs on 9004 only")
    if a.build_city:
        subprocess.check_call([sys.executable, str(ROOT / "city/ue/build_city.py"), "--port", str(a.port)], cwd=ROOT)
    OUT.mkdir(parents=True, exist_ok=True)
    c = Conn(a.port)
    frames = []

    def loc(n):
        return [float(v) for v in c(f"vget /object/{n}/location").split()]

    def shot(name, cam=0, pose=None, size=(832, 480)):
        if pose:
            x, y, z, p, yaw = pose
            c("vset /camera/0/fov 75")
            c(f"vset /camera/0/location {x} {y} {z}")
            c(f"vset /camera/0/rotation {p} {yaw} 0")
        c(f"vset /camera/{cam}/size {size[0]} {size[1]}")
        time.sleep(0.2)
        path = OUT / f"{name}.png"
        r = c(f"vget /camera/{cam}/lit {path}")
        frames.append({"frame": name, "camera": cam, "pose": pose, "ok": path.exists(),
                       "bodies": json.loads(c("vget /bodies")), "t": round(time.time(), 3)})
        print(name, "ok" if path.exists() else r)

    for n in (A, R, "GEN_BP_Couch_W1", "BP_Mug_C_W1"):
        c(f"vset /object/{n}/destroy")
    c("vset /action/clean_garbage")
    c("vset /action/game/resume")

    # Street spot in front of the street_fern view (city/ue/render_views.py), metres -> cm.
    ox, oy = 20300, 15800
    c(f"vset /objects/spawn_bp_asset {AGENT} {A}")
    c(f"vset /object/{A}/location {ox} {oy} 400")
    c(f"vset /object/{A}/rotation 0 0 0")
    c(f"vset /objects/spawn_bp_asset {PED} {R}")
    c(f"vset /object/{R}/location {ox + 250} {oy + 150} 400")
    c(f"vset /object/{R}/rotation 0 180 0")
    time.sleep(3.0)
    pa, pr = loc(A), loc(R)
    ground = pa[2] - 90

    def third(target, dist=330, side=-1, h=150, yaw_off=35):
        """Camera dist cm from target, yaw_off degrees off its facing, looking at its chest."""
        t = loc(target)
        tyaw = float(c(f"vget /object/{target}/rotation").split()[1])
        ang = math.radians(tyaw + side * yaw_off)
        x, y = t[0] + dist * math.cos(ang), t[1] + dist * math.sin(ang)
        z = ground + h
        yaw = math.degrees(math.atan2(t[1] - y, t[0] - x))
        pitch = math.degrees(math.atan2((t[2] + 10) - z, math.hypot(t[0] - x, t[1] - y)))
        return (x, y, z, pitch, yaw)

    # idle
    shot("agent_idle_3p", pose=third(A))
    shot("agent_idle_1p", cam=1)
    shot("resident_idle_3p", pose=third(R))
    # walk (mid-stride: both walking)
    c(f"vbp {A} SetMaxSpeed 150"); c(f"vbp {R} SetMaxSpeed 120")
    c(f"vbp {A} MoveForward"); c(f"vbp {R} MoveForward")
    time.sleep(1.1)
    c("vset /action/game/pause")
    shot("agent_walk_3p", pose=third(A, side=1, yaw_off=70))
    shot("agent_walk_1p", cam=1)
    shot("resident_walk_3p", pose=third(R, side=1, yaw_off=70))
    c("vset /action/game/resume")
    c(f"vbp {A} StopAgent"); c(f"vbp {R} StopPedestrian")
    time.sleep(0.5)
    # talk
    c(f"vbp {A} SetSpeaking 4")
    time.sleep(0.8)
    shot("agent_talk_3p", pose=third(A, yaw_off=20))
    # sit: couch right behind the agent
    pa = loc(A)
    c(f"vset /objects/spawn_bp_asset {COUCH} GEN_BP_Couch_W1")
    c(f"vset /object/GEN_BP_Couch_W1/location {pa[0] - 75} {pa[1]} {ground}")
    time.sleep(0.5)
    print("sit", c(f"vbp {A} SitDown"))
    time.sleep(1.2)
    shot("agent_sit_3p", pose=third(A, yaw_off=40))
    shot("agent_sit_1p", cam=1)
    c(f"vbp {A} StandUp")
    c("vset /object/GEN_BP_Couch_W1/destroy")
    time.sleep(1.0)
    # carry: mug in front, pick it up
    pa = loc(A)
    c(f"vset /objects/spawn_bp_asset {MUG} BP_Mug_C_W1")
    c(f"vset /object/BP_Mug_C_W1/location {pa[0] + 55} {pa[1] + 12} {ground}")
    time.sleep(0.5)
    print("pick", c(f"vbp {A} PickUp BP_Mug_C_W1"))
    time.sleep(0.35)
    shot("agent_reach_3p", pose=third(A, side=-1, yaw_off=80))
    time.sleep(1.2)
    shot("agent_carry_3p", pose=third(A, side=-1, yaw_off=50, dist=250))
    c(f"vset /camera/1/rotation -35 {float(c(f'vget /object/{A}/rotation').split()[1])} 0")
    shot("agent_carry_1p_lookdown", cam=1)
    c(f"vbp {A} DropOff")
    c("vset /object/BP_Mug_C_W1/destroy")

    # near / far stand-ins side by side (same pose source, different meshes)
    c(f"vbp {R} SetBody standin_near")
    pr = loc(R)
    c("vset /camera/0/fov 75")
    c(f"vset /camera/0/location {pr[0] - 400} {pr[1]} {ground + 150}")
    c("vset /camera/0/rotation -5 0 0")
    time.sleep(1.5)
    shot("standin_near_3p")
    c(f"vset /camera/0/location {pr[0] - 4500} {pr[1]} {ground + 150}")
    time.sleep(1.5)
    shot("standin_far_from_45m")
    c(f"vbp {R} SetBody ana")

    # perf: aerial overview (render_views.py) with 0 / 2 / 8 people in view, GPU ms from CITY_manager frame stats
    perf = {"method": "camera 0 at aerial_overview (300,820,330 m, pitch -32, yaw 270, fov 75); window minimized, so "
                      "frames render only the captures: %d lit 1280x720 captures back to back; gpu_ms = "
                      "CITY_manager GetFrameStats average over those frames; capture_ms = wall time per capture" % a.perf_captures}
    have_manager = "CITY_manager" in c("vget /objects").split()
    c(f"vset /object/{A}/destroy"); c(f"vset /object/{R}/destroy"); c("vset /action/clean_garbage")
    people = []
    for count in (0, 2, 8):
        while len(people) < count:
            i = len(people)
            n = f"GEN_BP_Pedestrian_Perf{i}"
            c(f"vset /objects/spawn_bp_asset {PED} {n}")
            c(f"vset /object/{n}/location {30000 + (i % 4) * 300} {30000 + (i // 4) * 300} 400")
            people.append(n)
        time.sleep(2.0)
        c("vset /camera/0/fov 75")
        c("vset /camera/0/location 30000 82000 33000")
        c("vset /camera/0/rotation -32 270 0")
        c("vset /camera/0/size 1280 720")
        c(f"vget /camera/0/lit {OUT / f'perf_aerial_{count}.png'}")
        if have_manager:
            c("vbp CITY_manager ResetFrameStats")
        t = time.time()
        for _ in range(a.perf_captures):
            c("vget /camera/0/lit png")
        dt = (time.time() - t) / a.perf_captures
        stats = json.loads(json.loads(c("vbp CITY_manager GetFrameStats"))["Stats"]) if have_manager else {}
        perf[f"{count}_bodies"] = {"capture_ms": round(dt * 1000, 2), **stats, "tiers": json.loads(c("vget /bodies"))}
        print(count, "bodies", perf[f"{count}_bodies"].get("gpu_ms"), "gpu ms,", round(dt * 1000, 1), "ms/capture")
    for n in people:
        c(f"vset /object/{n}/destroy")
    c("vset /action/clean_garbage")
    (OUT / "perf.json").write_text(json.dumps(perf, indent=1))

    sidecar = {
        "made": datetime.now().isoformat(timespec="seconds"),
        "by": "city/bodies/wave1_renders.py (agent B, wave 1)",
        "server": f"mac_server editor-game on port {a.port}",
        "models": "none (no ML models; Unreal renders only)",
        "assets": {
            "bodies_json": "mac_server/Config/Bodies.json",
            "meshes": ["/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple (fallback for mara/ana)",
                       "/Game/Characters/Mannequins/Meshes/SKM_Quinn_Simple (standin_near)"],
            "material": "/Game/Characters/Anim/M_BodyStandIn (flat tint + BodyFade dither)",
            "anim": "/Game/Characters/Anim/ABP_Body (parent /Script/SimWorld.SWBodyAnimInstance); clips MM_Idle, "
                    "MF_Unarmed_Walk_Fwd, MF_Unarmed_Jog_Fwd from the UE 5.8 Third Person template",
            "city": "city/world.json via city/ue/build_city.py",
        },
        "frames": frames,
    }
    (OUT / "render.json").write_text(json.dumps(sidecar, indent=1))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
