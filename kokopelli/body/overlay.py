"""The viewer's side of the hunger video: the painted film with the true body state next to what the agent felt, and
the three levels side by side.

    .venv/bin/python -m kokopelli.body.overlay one out/sensation/videos/<run>/starving
    .venv/bin/python -m kokopelli.body.overlay triptych out/sensation/videos/<run>     # full, half, starving left to right

The agent never sees this panel. It shows what the sim knows (food, energy, warmth as numbers, the healthy range as two
gold ticks) beside what reached the agent (the felt cue, or nothing), and what it chose. The gap between the number and
the felt line is the point of the benchmark.

Frame i of a painted film is sim time i / fps (live_wm.py captures at video rate from t = 0), so body.jsonl lines up
with the film by time: each frame shows the latest body line at or before it.

Colours are DESIGN.md's dark theme, so the panel reads as part of the dev panel. No CPU-heavy work beyond decode,
draw and encode; never a GPU job.
"""
import argparse
import json
import subprocess
import textwrap
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

LEVEL_ORDER = ("full", "half", "starving")
PANEL_W = 420
PAD = 24
# DESIGN.md section 1, dark theme.
BG, SURFACE, HAIR = (20, 16, 13), (30, 24, 20), (58, 48, 42)
INK, MUTED, CLAY, GOLD = (237, 229, 218), (168, 154, 140), (192, 122, 98), (196, 166, 107)
RANGE = (40, 80)
SANS = ("WorkSans-Regular.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc",
        "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
MONO = ("JetBrainsMono-Regular.ttf", "/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/SFNSMono.ttf",
        "DejaVuSansMono.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
SERIF = ("Fraunces-Light.ttf", "/System/Library/Fonts/Supplemental/Georgia.ttf", "DejaVuSerif.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf")


def _font(candidates, size):
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


class Fonts:
    def __init__(self):
        self.eyebrow, self.mono = _font(MONO, 11), _font(MONO, 13)
        self.body, self.title = _font(SANS, 15), _font(SERIF, 30)


def probe(path: str | Path) -> tuple[int, int, float, int]:
    """(width, height, fps, frames) of a video."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                          "stream=width,height,r_frame_rate,nb_read_packets", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True)
    s = json.loads(out.stdout)["streams"][0]
    num, den = (int(n) for n in s["r_frame_rate"].split("/"))
    return int(s["width"]), int(s["height"]), num / den, int(s.get("nb_read_packets") or 0)


def body_at(lines: list[dict], t: float) -> dict:
    """The latest body line at or before time t (the first one before the film starts)."""
    chosen = lines[0]
    for line in lines:
        if line["t"] <= t + 1e-6:
            chosen = line
        else:
            break
    return chosen


def describe_action(action: dict | None) -> str:
    if not action:
        return "Nothing yet."
    kind = str(action.get("type"))
    if kind == "say":
        return f"Says: \"{action.get('text', '')}\""
    if kind == "give":
        return "Gives Teo an egg."
    return {"cook": "Cooks an egg.", "eat": "Eats.", "wait": "Waits."}.get(kind, kind)


def panel(height, title, line, fonts, final=None):
    """One side panel, drawn for one body line. Cached by the caller: it only changes once per sim step."""
    img = Image.new("RGB", (PANEL_W, height), BG)
    d = ImageDraw.Draw(img)
    d.line([(0, 0), (0, height)], fill=HAIR, width=1)
    x, y = PAD, PAD
    d.text((x, y), "HUNGER LEVEL", font=fonts.eyebrow, fill=MUTED)
    y += 18
    d.line([(x, y), (PANEL_W - PAD, y)], fill=GOLD, width=1)   # the one gold hairline
    y += 8
    d.text((x, y), title, font=fonts.title, fill=INK)
    y += 48
    d.text((x, y), f"TRUE STATE  ·  VIEWER ONLY  ·  {line.get('clock', '')[:5]}", font=fonts.eyebrow, fill=MUTED)
    y += 22
    bx = x + 120
    width = PANEL_W - PAD - bx
    for name in ("food", "energy", "warmth"):
        value = float(line[name])
        d.text((x, y), name, font=fonts.mono, fill=INK)
        d.text((x + 70, y), f"{value:5.1f}", font=fonts.mono, fill=INK)
        by = y + 9
        d.line([(bx, by), (bx + width, by)], fill=HAIR, width=1)
        for edge in RANGE:
            ex = bx + width * edge / 100
            d.line([(ex, by - 5), (ex, by + 5)], fill=GOLD, width=1)
        vx = bx + width * value / 100
        d.line([(bx, by), (vx, by)], fill=INK, width=2)
        y += 26
    d.text((x, y), f"eggs {line.get('eggs', 0)}   cooked {line.get('cooked', 0)}", font=fonts.mono, fill=MUTED)
    y += 30
    d.line([(x, y), (PANEL_W - PAD, y)], fill=HAIR, width=1)
    y += 14
    d.text((x, y), "WHAT REACHES THE AGENT", font=fonts.eyebrow, fill=MUTED)
    y += 20
    felt = line.get("felt") or []
    for sentence in felt or ["Nothing. The body is quiet."]:
        for wrapped in textwrap.wrap(sentence, 44):
            d.text((x, y), wrapped, font=fonts.body, fill=INK if felt else MUTED)
            y += 21
        y += 4
    y += 10
    d.line([(x, y), (PANEL_W - PAD, y)], fill=HAIR, width=1)
    y += 14
    d.text((x, y), "LAST CHOICE", font=fonts.eyebrow, fill=MUTED)
    y += 20
    for wrapped in textwrap.wrap(describe_action(line.get("last_action")), 44)[:4]:
        d.text((x, y), wrapped, font=fonts.body, fill=INK)
        y += 21
    outcome = final or line.get("outcome")
    if outcome:
        y = max(y + 12, height - PAD - 20)
        d.text((x, y), f"OUTCOME  {outcome.upper()}", font=fonts.mono, fill=CLAY)   # the one clay element
    return np.asarray(img)


def overlay(run_dir: str | Path, out: str | Path | None = None, title: str | None = None) -> Path:
    """Painted film + panel. Returns the path of overlay.mp4 next to the film."""
    run = Path(run_dir).resolve()
    film = run / "world_model.mp4"
    lines = [json.loads(line) for line in (run / "body.jsonl").read_text().splitlines() if line.strip()]
    result = json.loads((run / "egg.json").read_text()) if (run / "egg.json").exists() else {}
    title = title or result.get("level", run.name)
    w, h, fps, _ = probe(film)
    out = Path(out or run / "overlay.mp4")
    fonts, cache = Fonts(), {}
    reader = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(film), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                              stdout=subprocess.PIPE)
    writer = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w + PANEL_W}x{h}",
                               "-r", f"{fps:g}", "-i", "-", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(out)],
                              stdin=subprocess.PIPE)
    assert reader.stdout is not None and writer.stdin is not None   # both were opened with a pipe just above
    frame_bytes, k = w * h * 3, 0
    try:
        while True:
            raw = reader.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            line = body_at(lines, k / fps)
            key = (line["t"], line.get("outcome"))
            if key not in cache:
                cache[key] = panel(h, title, line, fonts, final=None)
            frame = np.concatenate([np.frombuffer(raw, np.uint8).reshape(h, w, 3), cache[key]], axis=1)
            writer.stdin.write(frame.tobytes())
            k += 1
    finally:
        writer.stdin.close()
        writer.wait()
        reader.wait()
    if k == 0:
        raise RuntimeError(f"no frames read from {film}")
    sidecar = {"made_by": "kokopelli/body/overlay.py", "source": str(film), "frames": k, "fps": fps, "panel_px": PANEL_W,
               "level": result.get("level"), "arm": result.get("arm"), "outcome": result.get("outcome"),
               "world_model": result.get("world_model"), "quantize": result.get("quantize"), "size": result.get("size"),
               "agent_model": result.get("agent_model")}
    out.with_name(out.name + ".json").write_text(json.dumps(sidecar, indent=1))
    return out


def with_voice(video: str | Path, voice: str | Path, out: str | Path | None = None) -> Path:
    """The same video with the inner-voice track muxed in (kokopelli/body/voice.py). The picture is copied, not re-encoded."""
    out = Path(out or Path(video).with_name(Path(video).stem + "_voice.mp4"))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(voice), "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "128k", "-map", "0:v:0", "-map", "1:a:0", str(out)], check=True)
    return out


def triptych(folder: str | Path, out: str | Path | None = None, levels: tuple = LEVEL_ORDER) -> Path:
    """The levels' overlay videos side by side, left to right as in `levels`. Shorter ones hold their last frame."""
    folder = Path(folder)
    videos = [folder / level / "overlay.mp4" for level in levels]
    missing = [str(v) for v in videos if not v.exists()]
    if missing:
        raise FileNotFoundError(f"run kokopelli.body.overlay one on these first: {missing}")
    info = [probe(v) for v in videos]
    height = min(i[1] for i in info)
    longest = max(i[3] / i[2] for i in info if i[2])
    inputs = sum((["-i", str(v)] for v in videos), [])
    chains = ";".join(f"[{k}:v]scale=-2:{height},tpad=stop_mode=clone:stop_duration=36000[v{k}]" for k in range(len(videos)))
    graph = f"{chains};{''.join(f'[v{k}]' for k in range(len(videos)))}hstack=inputs={len(videos)}[out]"
    out = Path(out or folder / "hunger_triptych.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[out]", "-t", f"{longest:.3f}",
                    "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(out)], check=True)
    outcomes = {}
    for level in levels:
        path = folder / level / "egg.json"
        outcomes[level] = json.loads(path.read_text()).get("outcome") if path.exists() else None
    out.with_name(out.name + ".json").write_text(json.dumps(
        {"made_by": "kokopelli/body/overlay.py triptych", "levels": list(levels), "outcomes": outcomes,
         "sources": [str(v.resolve()) for v in videos], "seconds": round(longest, 2)}, indent=1))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    one = sub.add_parser("one")
    one.add_argument("run")
    one.add_argument("--voice", help="a voice.wav to mux in (default: the run's own voice.wav, if there is one)")
    tri = sub.add_parser("triptych")
    tri.add_argument("folder")
    args = ap.parse_args()
    if args.command == "one":
        made = overlay(args.run)
        voice = Path(args.voice) if args.voice else Path(args.run).resolve() / "voice.wav"
        print(made)
        if voice.exists():
            print(with_voice(made, voice))
    else:
        print(triptych(args.folder))


if __name__ == "__main__":
    main()
