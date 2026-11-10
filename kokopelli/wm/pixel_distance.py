"""Two crude pixel distances between grayscale frames, with no model: layout (where bright and dark areas sit) and
appearance (the brightness histogram). kokopelli/loop/drift.py scores the world model against the sim with them, and
kokopelli/wm/video_check.py keeps that old score for contrast. numpy only, and Python 3.10 compatible: the SimWorld
venv imports it through the loop.
"""
import numpy as np

SMALL = (64, 36)
LAYOUT_WEIGHT = 0.7


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
