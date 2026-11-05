"""How far the world model has wandered from the sim, and when to pull it back.

Both measures run on pixels with no extra model, so they are cheap and work anywhere. They are also crude: the sim and
the world model can look different while agreeing on layout. Depth and segmentation agreement would be better, but a
generated frame has neither, so that needs an estimator model. `estimate_maps` is where one plugs in.
"""
import numpy as np
from PIL import Image

from runtime.frames import load_rgb

SMALL = (64, 36)
LAYOUT_WEIGHT = 0.7
estimate_maps = None


def _gray(path):
    image = Image.fromarray(load_rgb(path)).convert("L").resize(SMALL, Image.BILINEAR)
    return np.asarray(image, dtype=np.float64)


def layout_distance(a, b):
    """0 when bright and dark areas line up, 1 when they don't. Correlation ignores overall brightness."""
    a, b = a - a.mean(), b - b.mean()
    scale = np.sqrt((a * a).sum() * (b * b).sum())
    return 1.0 if scale == 0 else float(1 - max(0.0, (a * b).sum() / scale))


def appearance_distance(a, b):
    """0 when the brightness histograms match. A stand-in for embedding similarity, which needs a model."""
    ha = np.histogram(a, bins=16, range=(0, 255))[0] / a.size
    hb = np.histogram(b, bins=16, range=(0, 255))[0] / b.size
    return float(np.abs(ha - hb).sum() / 2)


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
