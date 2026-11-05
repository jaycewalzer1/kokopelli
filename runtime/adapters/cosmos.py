"""The world model as a backend, using the existing Cosmos calls. Runs where world_model.py runs: Apple silicon."""
import tempfile
from pathlib import Path

from runtime.frames import load_rgb, resized, write_clip
from runtime.interfaces import WorldModel


class CosmosWorldModel(WorldModel):
    def __init__(self, size, steps, quantize=0):
        self.size, self.steps = size, steps
        # Storing weights in 8 bits instead of 16 saves memory at some cost to the picture.
        self.extra = ("--quantize", str(quantize)) if quantize else ()

    def render_chunk(self, request):
        from world_model import _generate  # Imported here so mock runs don't need the runner installed.

        settings = (self.size, request.frames, self.steps, request.seed)
        if not request.cond:
            return str(_generate("txt2video.py", request.prompt, request.output, *settings, self.extra))
        if len(request.cond) == 1:
            extra = ("--image", str(Path(request.cond[0].path).resolve()), *self.extra)
            return str(_generate("img2video.py", request.prompt, request.output, *settings, extra))
        # The runner takes conditioning frames as the end of a video, so a re-anchored set goes in as a short clip.
        with tempfile.TemporaryDirectory(prefix="wmloop_") as folder:
            clip = write_clip([resized(load_rgb(frame.path), self.size) for frame in request.cond], Path(folder) / "cond.mp4")
            extra = ("--video", str(Path(clip).resolve()), "--cond-frames", str(len(request.cond)), *self.extra)
            return str(_generate("img2video.py", request.prompt, request.output, *settings, extra))
