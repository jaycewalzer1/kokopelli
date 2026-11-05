"""Join a run's clips into one video. Long runs join in batches, because ffmpeg decodes every input at once."""
import tempfile
from pathlib import Path

from blend import blend

BATCH = 20


def expected_frames(frame_counts, overlap):
    """Each join shares overlap frames, so the result is shorter than the sum by that much per join."""
    return sum(frame_counts) - overlap * (len(frame_counts) - 1)


def stitch(clips, output, overlap, batch=BATCH):
    clips = [Path(clip) for clip in clips]
    if len(clips) <= batch:
        return blend(clips, output, overlap_frames=overlap)
    with tempfile.TemporaryDirectory(prefix="wmloop_", dir=Path(output).parent) as folder:
        parts = []
        for start in range(0, len(clips), batch):
            part = Path(folder) / f"part_{start:05d}.mp4"
            parts.append(stitch(clips[start:start + batch], part, overlap, batch))
        return stitch(parts, output, overlap, batch)
