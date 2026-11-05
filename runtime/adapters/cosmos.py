"""The world model as a backend, using the existing Cosmos calls. Runs where world_model.py runs: Apple silicon."""
import os
import tempfile
from pathlib import Path

from runtime.frames import load_rgb, write_clip
from runtime.interfaces import WorldModel


class CosmosWorldModel(WorldModel):
    def __init__(self, size, steps):
        self.size, self.steps = size, steps

    def render_chunk(self, request):
        import world_model  # Imported here so mock runs don't need the runner installed.

        settings = {"size": self.size, "frames": request.frames, "steps": self.steps, "seed": request.seed}
        if len(request.cond) == 1:
            return str(world_model.image_to_video(request.prompt, request.cond[0].path, request.output, **settings))
        # The runner takes conditioning frames as the end of a video, so a re-anchored set goes in as a short clip.
        with tempfile.TemporaryDirectory(prefix="wmloop_") as folder:
            clip = write_clip([load_rgb(frame.path) for frame in request.cond], Path(folder) / "cond.mp4")
            return str(world_model.continue_video(request.prompt, clip, request.output, cond_frames=len(request.cond), **settings))
