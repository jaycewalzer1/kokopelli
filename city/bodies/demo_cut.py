"""Cut the bodies demo film from a demo_lunch.py run: the director camera's view with burned-in dialogue, the agents'
own views beside it, then a short section with the first-person and world-model films side by side.

    .venv/bin/python city/bodies/demo_cut.py RUN_DIR --out out/bodies/demo/<stamp>/demo_sim_only.mp4 --eyes sim
    .venv/bin/python city/bodies/demo_cut.py RUN_DIR --out out/bodies/demo/<stamp>/demo.mp4 --eyes wm

RUN_DIR is the run folder written by city/bodies/demo_lunch.py: director/f*.png + director/frames.jsonl (director
camera, one per capture tick), captions.jsonl (who said what, sim-time start/end), film/{mara,iris,sim_mara,sim_iris}.mp4,
run.json. --eyes wm puts the world-model films (what each agent actually saw) in the side panels; --eyes sim the sim's own
renders (for a --fake-wm run, whose "painting" is only a blend of the controls). A JSON sidecar is written next to the film.
"""
import argparse
import json
import subprocess
import textwrap
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
MAIN_W, MAIN_H = 1440, 810
SIDE_W = W - MAIN_W
FPS = 24
BG = (14, 15, 17)
INK = (236, 233, 226)
DIM = (150, 150, 150)
COLORS = {"mara": (242, 170, 96), "iris": (120, 196, 232)}
OTHER = (190, 200, 150)
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def font(size, bold=False):
    return ImageFont.truetype(BOLD if bold else FONT, size)


class Film:
    """Random-ish access to an mp4 by frame index (sequential reads, held last frame past the end)."""

    def __init__(self, path):
        self.path = Path(path)
        self.cap = cv2.VideoCapture(str(path)) if self.path.exists() else None
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) if self.cap else 0
        self.pos, self.last = -1, None

    def get(self, i):
        if not self.cap or self.n == 0:
            return None
        i = max(0, min(i, self.n - 1))
        if i < self.pos:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            self.pos = i - 1
        while self.pos < i:
            ok, f = self.cap.read()
            if not ok:
                break
            self.pos += 1
            self.last = f[:, :, ::-1]
        return self.last


def fit(img, w, h):
    return np.array(Image.fromarray(img).resize((w, h), Image.LANCZOS))


def load_rows(run):
    rows = [json.loads(l) for l in (run / "director" / "frames.jsonl").read_text().splitlines() if l.strip()]
    rows.sort(key=lambda r: r["frame"])
    return rows


def load_captions(run):
    p = run / "captions.jsonl"
    caps = [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
    return sorted(caps, key=lambda c: c["start"])


def retime(caps, cps=24.0, gap=0.15):
    """Captions one after another, each on screen long enough to read (cps characters per second, 2.2-12 s). The run's
    own schedule can overlap when a reply spills into the next step; a line never starts before it was said."""
    out, end = [], -1e9
    for c in caps:
        start = max(c["start"], end + gap)
        end = start + min(12.0, max(2.2, len(c["text"]) / cps))
        out.append({**c, "said_at": c["start"], "start": round(start, 3), "end": round(end, 3)})
    return out


def caption_at(caps, t, linger=1.5):
    """The current line (if any) and the one before it."""
    cur, prev = None, None
    for k, c in enumerate(caps):
        nxt = caps[k + 1]["start"] if k + 1 < len(caps) else 1e9
        if c["start"] <= t < min(max(c["end"] + linger, c["end"]), nxt) or (c["start"] <= t < c["end"]):
            cur, prev = c, caps[k - 1] if k else None
    return cur, prev


def draw_caption(d, c, y, size, bright=True, width=W - 160, max_lines=3):
    name_c = COLORS.get(c["who"], OTHER)
    if not bright:
        name_c = tuple(int(v * 0.55) for v in name_c)
    f, fb = font(size), font(size, True)
    name = c["name"] + ":  "
    nw = d.textlength(name, font=fb)
    chars = max(20, int((width - nw) / (size * 0.5)))
    lines = textwrap.wrap(c["text"], chars)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" ,.;:") + " ..."
    d.text((80, y), name, font=fb, fill=name_c)
    for k, line in enumerate(lines):
        d.text((80 + nw, y + k * int(size * 1.25)), line, font=f, fill=INK if bright else DIM)
    return y + len(lines) * int(size * 1.25)


SHOT_NAMES = {"establishing": "wide", "two_shot": "two-shot", "track_mara": "following Mara", "track_iris": "following Iris",
              "ots_mara": "Mara speaking", "ots_iris": "Iris speaking"}


def clock_for(run_meta, t):
    h, m = (int(v) for v in run_meta.get("clock", "12:20").split(":")[:2])
    s = int(t)
    total = h * 3600 + m * 60 + s
    return f"{total // 3600:02d}:{(total // 60) % 60:02d}:{total % 60:02d}"


def main_frame(director_png, row, caps, eyes, eye_labels, run_meta):
    canvas = Image.new("RGB", (W, H), BG)
    img = np.array(Image.open(director_png).convert("RGB"))
    canvas.paste(Image.fromarray(fit(img, MAIN_W, MAIN_H)), (0, 0))
    d = ImageDraw.Draw(canvas)
    # side panels: what each agent sees
    ew, eh = SIDE_W - 24, int((SIDE_W - 24) * 256 / 448)
    y = 16
    for (who, frame), label in zip(eyes, eye_labels):
        d.text((12, 0), "", font=font(10))
        d.text((MAIN_W + 12, y), label, font=font(20, True), fill=COLORS.get(who, OTHER))
        y += 30
        if frame is not None:
            canvas.paste(Image.fromarray(fit(frame, ew, eh)), (MAIN_W + 12, y))
        else:
            d.rectangle([MAIN_W + 12, y, MAIN_W + 12 + ew, y + eh], outline=DIM)
            d.text((MAIN_W + 24, y + eh // 2 - 10), "(not available)", font=font(18), fill=DIM)
        y += eh + 22
    t = row.get("t", 0.0)
    info = [f"sim clock  {clock_for(run_meta, t)}", f"shot  {SHOT_NAMES.get(row.get('shot'), row.get('shot') or '-')}"]
    if row.get("dist_m") is not None:
        info.append(f"apart  {row['dist_m']:.1f} m")
    for k, s in enumerate(info):
        d.text((MAIN_W + 12, y + 6 + k * 30), s, font=font(20), fill=DIM)
    # captions
    cur, prev = caption_at(caps, t)
    d.rectangle([0, MAIN_H, W, H], fill=BG)
    yy = MAIN_H + 22
    n = len(cur["text"]) if cur else 0
    big = 36 if n <= 220 else 30 if n <= 330 else 26
    if prev and cur and n <= 150:   # room for the previous line, dimmed, above a short current one
        yy = draw_caption(d, prev, yy, 26, bright=False, max_lines=1) + 10
    if cur:
        draw_caption(d, cur, yy, big, bright=True, max_lines=5 if big < 36 else 4)
    return np.array(canvas)


def card(lines, sub=()):
    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)
    y = 380
    for k, s in enumerate(lines):
        f = font(64 if k == 0 else 34, k == 0)
        d.text(((W - d.textlength(s, font=f)) / 2, y), s, font=f, fill=INK)
        y += 90 if k == 0 else 50
    y += 30
    for s in sub:
        f = font(24)
        d.text(((W - d.textlength(s, font=f)) / 2, y), s, font=f, fill=DIM)
        y += 36
    return np.array(canvas)


def grid_frame(tiles, labels, cap, prev):
    """rows x 2: tiles = [[tl, tr], [bl, br]] or [[l, r]] (448x256-ish frames), labelled, with the caption below."""
    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)
    rows = len(tiles)
    if rows == 1:
        tw = (W - 3 * 20) // 2
        th = int(tw * 256 / 448)
    else:
        th = 512 - 40
        tw = int(th * 448 / 256)
    x0 = (W - 2 * tw - 20) // 2
    for r in range(rows):
        for c in range(2):
            x, y = x0 + c * (tw + 20), 40 + r * (th + 46)
            lab, who = labels[r][c]
            d.text((x, y - 32), lab, font=font(22, True), fill=COLORS.get(who, OTHER))
            f = tiles[r][c]
            if f is not None:
                canvas.paste(Image.fromarray(fit(f, tw, th)), (x, y))
            else:
                d.rectangle([x, y, x + tw, y + th], outline=DIM)
    yy = 40 + rows * (th + 46) + 2
    if prev and cap:
        yy = draw_caption(d, prev, yy, 22, bright=False) + 6
    if cap:
        draw_caption(d, cap, yy, 28)
    return np.array(canvas)


def writer(path, fps=FPS):
    path.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], stdin=subprocess.PIPE)


def cut(run, out, eyes_kind, grid_s=24.0, title=True, wm_until=None):
    run, out = Path(run), Path(out)
    meta = json.loads((run / "run.json").read_text()) if (run / "run.json").exists() else {}
    rows = load_rows(run)
    caps = retime(load_captions(run))
    film = run / "film"
    if eyes_kind == "wm":
        eye_films = [("mara", Film(film / "mara.mp4")), ("iris", Film(film / "iris.mp4"))]
        eye_labels = ["Mara sees (world model)", "Iris sees (world model)"]
    else:
        eye_films = [("mara", Film(film / "sim_mara.mp4")), ("iris", Film(film / "sim_iris.mp4"))]
        eye_labels = ["Mara's eyes (sim render)", "Iris's eyes (sim render)"]
    sim_m, sim_i = Film(film / "sim_mara.mp4"), Film(film / "sim_iris.mp4")
    after_films = [("mara", Film(film / "sim_mara.mp4")), ("iris", Film(film / "sim_iris.mp4"))]
    after_labels = [f"Mara's eyes (sim; WM until 0:{int(wm_until or 0):02d})",
                    f"Iris's eyes (sim; WM until 0:{int(wm_until or 0):02d})"]
    wm_m, wm_i = Film(film / "mara.mp4"), Film(film / "iris.mp4")
    fps = int(meta.get("fps") or FPS)
    p = writer(out, fps)
    n_written = 0

    def put(frame, times=1):
        nonlocal n_written
        for _ in range(times):
            p.stdin.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())
            n_written += 1

    agent_model = meta.get("agent_model", "Qwen3-VL-8B-Instruct-4bit")
    wm_line = ("world model: Cosmos3-Nano-Sim-Transfer, " + str(meta.get("size", "")) + f" @ {meta.get('fps', '')} fps"
               if not meta.get("fake_world_model") else "world model: not used in this cut (sim renders shown)")
    if title:
        put(card(["Mara and Iris meet for lunch",
                  "two Qwen agents with MetaHuman bodies in the SimWorld village"],
                 [f"minds: {agent_model}, each deciding from its own eyes", wm_line,
                  "bodies: MetaHuman (clay: skin, hair and clothes not installed yet)",
                  datetime.now().strftime("%Y-%m-%d")]), fps * 4)
    for row in rows:
        f = run / "director" / f"f{row['frame']:06d}.png"
        if not f.exists():
            continue
        i = row["frame"]
        if wm_until is not None and eyes_kind == "wm" and row["t"] > wm_until:
            put(main_frame(f, row, caps, [(who, fm.get(i)) for who, fm in after_films], after_labels, meta))
            continue
        eyes = [(who, fm.get(i)) for who, fm in eye_films]
        put(main_frame(f, row, caps, eyes, eye_labels, meta))
    # hold the last frame until the last line has been on screen long enough to read
    if rows and caps and caps[-1]["end"] > rows[-1]["t"]:
        last, dt = rows[-1], 1.0 / fps
        f = run / "director" / f"f{last['frame']:06d}.png"
        held = after_films if (wm_until is not None and eyes_kind == "wm" and last["t"] > wm_until) else eye_films
        labels = after_labels if held is after_films else eye_labels
        eyes = [(who, fm.get(last["frame"])) for who, fm in held]
        t = last["t"]
        while t < caps[-1]["end"] + 0.5 and f.exists():
            t += dt
            put(main_frame(f, {**last, "t": t}, caps, eyes, labels, meta))
    # section 2: the agents' own views, side by side, over the last part of the conversation
    if rows and grid_s > 0:
        put(card(["What each of them saw"] + ([("top: the sim's render of their eyes  ·  bottom: the world model's painting, their only input"
                   + (f"  ·  0:{max(0, int(wm_until - grid_s)):02d}-0:{int(wm_until):02d}" if wm_until else ""))]
                  if eyes_kind == "wm" else ["the sim's render of their eyes (world model faked in this run)"])), fps * 3)
        n = int(grid_s * fps)
        last_talk = max((c["end"] for c in caps), default=rows[-1]["t"])
        if wm_until is not None and eyes_kind == "wm":   # only the part where the painting was still clean
            last_talk = wm_until
        end_i = min(len(rows) - 1, max(n, next((k for k, r in enumerate(rows) if r["t"] >= last_talk), len(rows) - 1)))
        start_i = max(0, end_i - n)
        for k in range(start_i, end_i):
            r = rows[k]
            i = r["frame"]
            cur, prev = caption_at(caps, r["t"])
            if eyes_kind == "wm":
                put(grid_frame([[sim_m.get(i), sim_i.get(i)], [wm_m.get(i), wm_i.get(i)]],
                               [[("Mara: sim eyes (never shown to her)", "mara"), ("Iris: sim eyes (never shown to her)", "iris")],
                                [("Mara: world model (what she saw)", "mara"), ("Iris: world model (what she saw)", "iris")]],
                               cur, prev))
            else:
                put(grid_frame([[sim_m.get(i), sim_i.get(i)]],
                               [[("Mara's eyes (sim render)", "mara"), ("Iris's eyes (sim render)", "iris")]], cur, prev))
    p.stdin.close()
    p.wait()
    side = {"film": str(out), "frames": n_written, "fps": fps, "seconds": round(n_written / fps, 1), "size": [W, H],
            "run_dir": str(run), "eyes": eyes_kind, "world_model_shown_until_s": wm_until, "made_by": "city/bodies/demo_cut.py", "made_at": datetime.now().isoformat(timespec="seconds"),
            "director": "SimCV camera 0 placed per capture tick by city/bodies/demo_lunch.py (shots: wide, follow, two-shot, over-the-shoulder)",
            "captions": "captions.jsonl (each spoken line, timed for SetSpeaking gestures)",
            "agent_model": agent_model, "world_model": None if meta.get("fake_world_model") else meta.get("world_model"),
            "world_model_settings": {k: meta.get(k) for k in ("size", "fps", "window", "sink", "quantize", "denoise_steps", "wm_prompt")},
            "simulator": "SimWorld packaged server (mac_server/Packaged = Packaged_bodies build, MetaHuman bodies, clay)",
            "bodies": "mac_server/Config/Bodies.json: GEN_BP_Humanoid_0 = mara, GEN_BP_Humanoid_1 = iris, residents by id",
            "run": meta}
    out.with_name(out.name + ".json").write_text(json.dumps(side, indent=1, default=str))
    return side


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run")
    ap.add_argument("--out", required=True)
    ap.add_argument("--eyes", choices=("wm", "sim"), default="wm")
    ap.add_argument("--grid-s", type=float, default=24.0)
    ap.add_argument("--no-title", action="store_true")
    ap.add_argument("--wm-until", type=float, help="show the world-model films only up to this sim second, sim renders after")
    a = ap.parse_args()
    s = cut(a.run, a.out, a.eyes, a.grid_s, not a.no_title, a.wm_until)
    print(json.dumps({k: s[k] for k in ("film", "frames", "seconds")}))
