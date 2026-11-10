"""Blend world model clips into one video with crossfades."""
import subprocess
from pathlib import Path

FPS = 24


def _run(command):
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def probe(path):
    """Return (width, height, frame count)."""
    out = _run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,nb_read_frames", "-of", "csv=p=0", str(path)])
    return tuple(int(n) for n in out.strip().strip(",").split(","))


def blend(clips, output, overlap_frames=12):
    """Crossfade clips in order. Each join shortens the result by overlap_frames."""
    if not clips:
        raise ValueError("no clips to blend")
    if overlap_frames < 1:
        raise ValueError("overlap_frames must be at least 1")
    probes = [probe(clip) for clip in clips]
    if len({p[:2] for p in probes}) > 1:
        raise ValueError(f"clips differ in size: {sorted({p[:2] for p in probes})}")
    if len(clips) > 1 and min(p[2] for p in probes) < 2 * overlap_frames:
        raise ValueError(f"every clip needs at least {2 * overlap_frames} frames for this overlap")

    inputs = [arg for clip in clips for arg in ("-i", str(clip))]
    filters = [f"[{i}:v]fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[v{i}]" for i in range(len(clips))]
    last, end = "v0", probes[0][2]
    for i in range(1, len(clips)):
        end -= overlap_frames
        filters.append(f"[{last}][v{i}]xfade=transition=fade:duration={overlap_frames / FPS}"
                       f":offset={end / FPS}[x{i}]")
        last, end = f"x{i}", end + probes[i][2]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filters), "-map", f"[{last}]",
          "-r", str(FPS), "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(output)])
    return output
