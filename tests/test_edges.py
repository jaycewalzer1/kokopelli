"""Edge maps, on drawn frames. It loads no models."""
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from core.edges import edge_clip, edge_frame, read_frames, write_frames


def square(shift=0, brightness=1.0):
    frame = np.full((256, 448, 3), 40, dtype=np.uint8)
    frame[80:180, 100 + shift:220 + shift] = (230, 200, 60)
    return (frame * brightness).astype(np.uint8)


class EdgeFrameTest(unittest.TestCase):
    def test_edges_follow_the_outline_and_leave_flat_areas_black(self):
        edges = edge_frame(square())
        self.assertEqual(edges.shape, (256, 448, 3))
        self.assertTrue(edges[:, 95:105].any())
        self.assertFalse(edges[100:160, 130:190].any())
        self.assertFalse(edges[:, 300:].any())
        self.assertEqual(set(np.unique(edges)), {0, 255})

    def test_edges_move_with_the_object(self):
        moved = edge_frame(square(shift=40))
        self.assertFalse(moved[:, 90:110].any())
        self.assertTrue(moved[:, 135:145].any())

    def test_a_small_brightness_change_barely_moves_the_edges(self):
        # What the fixed thresholds are for: a flicker in the sim's light shouldn't become a flicker in the control video.
        same = edge_frame(square()) == edge_frame(square(brightness=0.95))
        self.assertGreater(same.mean(), 0.99)

    def test_faint_noise_makes_no_edges(self):
        noise = np.random.default_rng(0).normal(0, 3, (256, 448, 3))
        self.assertFalse(edge_frame((40 + noise).clip(0, 255).astype(np.uint8)).any())


class EdgeClipTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.video = write_frames([square(shift=i * 4) for i in range(16)], self.folder / "sim.mp4")

    def test_a_clip_keeps_its_frame_count_and_size(self):
        frames = read_frames(edge_clip(self.video, self.folder / "edges.mp4"))
        self.assertEqual(len(frames), 16)
        self.assertEqual(frames[0].shape, (256, 448, 3))

    def test_part_of_a_clip_can_be_taken(self):
        self.assertEqual(len(read_frames(edge_clip(self.video, self.folder / "last.mp4", start=11, count=5))), 5)

    def test_asking_past_the_end_fails_instead_of_returning_fewer_frames(self):
        with self.assertRaises(ValueError):
            edge_clip(self.video, self.folder / "bad.mp4", start=14, count=5)

    def test_thin_edges_survive_encoding(self):
        frames = read_frames(edge_clip(self.video, self.folder / "edges.mp4"))
        expected = cv2.cvtColor(edge_frame(read_frames(self.video)[0]), cv2.COLOR_RGB2GRAY) > 127
        found = cv2.cvtColor(frames[0], cv2.COLOR_RGB2GRAY) > 127
        self.assertGreater((expected & found).sum() / expected.sum(), 0.9)


if __name__ == "__main__":
    unittest.main()
