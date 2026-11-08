"""A world model with no model in it: it redraws the sim, wandering further off over time so drift control has work to do."""
import random

import numpy as np
from PIL import Image, ImageDraw

from runtime.frames import load_rgb, read_clip, write_clip
from runtime.interfaces import WorldModel

DRIFT_PER_CHUNK = 0.002
ANCHOR_PULL = 0.25


class MockWorldModel(WorldModel):
    def __init__(self):
        self.drift = 0.0

    def render_chunk(self, request):
        if request.control:
            return self._filter(request)
        draw = random.Random(f"{request.seed}:{request.tick}:{request.chunk}")
        # A sim frame among the conditioning frames pulls the result back, as a re-anchor should.
        if any(frame.source == "sim" for frame in request.cond):
            self.drift *= ANCHOR_PULL
        self.drift += DRIFT_PER_CHUNK * draw.uniform(0.6, 1.4)
        target = load_rgb(request.target.rgb)
        new = max(1, request.frames - len(request.cond))
        drawn = [self._frame(target, request, i, new) for i in range(new)]
        cond = [load_rgb(frame.path) for frame in request.cond]
        return write_clip([*cond, *drawn], request.output)

    def _filter(self, request):
        # Repaints the control video and nothing else, so nothing can build up from one chunk to the next.
        return write_clip([np.asarray(frame // 2 + 40, np.uint8) for frame in read_clip(request.control)], request.output)

    def _frame(self, target, request, index, total):
        # Sliding the picture sideways breaks layout agreement, which is the error drift control looks for.
        shift = int(self.drift * target.shape[1] * (index + 1) / total)
        image = Image.fromarray(np.roll(target, shift, axis=1))
        ImageDraw.Draw(image).text((6, 4), f"MOCK WM  tick {request.tick}.{request.chunk}  drift {self.drift:.2f}", fill=(43, 30, 24))
        return np.asarray(image)

    def get_state(self):
        return {"drift": self.drift}

    def set_state(self, state):
        self.drift = state.get("drift", 0.0)
