"""How far the world model has wandered from the sim, and when to pull it back.

Both measures run on pixels with no extra model, so they are cheap and work anywhere. They are also crude: the sim and
the world model can look different while agreeing on layout. Depth and segmentation agreement would be better, but a
generated frame has neither, so that needs an estimator model. `estimate_maps` is where one plugs in.
"""
import numpy as np
from PIL import Image

from kokopelli.loop.frames import load_rgb
from kokopelli.wm.pixel_distance import LAYOUT_WEIGHT, SMALL, appearance_distance, layout_distance

estimate_maps = None


def _gray(path):
    image = Image.fromarray(load_rgb(path)).convert("L").resize(SMALL, Image.BILINEAR)
    return np.asarray(image, dtype=np.float64)


def score(wm_frame, sim_frame):
    a, b = _gray(wm_frame), _gray(sim_frame)
    layout, appearance = layout_distance(a, b), appearance_distance(a, b)
    return {"score": round(LAYOUT_WEIGHT * layout + (1 - LAYOUT_WEIGHT) * appearance, 4), "layout": round(layout, 4),
            "appearance": round(appearance, 4), "depth_seg": None, "key_objects": None}


def reanchor_reason(drift_score, seconds_since_anchor, config):
    """Return why to re-anchor now, or None."""
    if not config.drift_control:
        return None
    if drift_score >= config.drift_threshold:
        return "threshold"
    if seconds_since_anchor >= config.reanchor_every:
        return "scheduled"
    return None


def anchored(cond, sim_frame_path, frame_type):
    """Replace the oldest conditioning frame with a sim render, keeping the order of the rest."""
    return [frame_type(sim_frame_path, "sim"), *cond[1:]]
