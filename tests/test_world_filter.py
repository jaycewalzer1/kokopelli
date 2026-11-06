"""The parts of the filter that decide what the model sees. It loads no models."""
import unittest

import mlx.core as mx
import numpy as np

from world_filter import chunk_windows, guided, latent_frames, noisy_mask, pack_positions


class ChunkTest(unittest.TestCase):
    def test_each_chunk_overlaps_the_last_by_the_conditioning_frames(self):
        self.assertEqual(chunk_windows(38, 16, 5), [(0, 16), (11, 27), (22, 38)])

    def test_no_chunk_runs_past_the_control_video(self):
        self.assertTrue(all(end <= 40 for _, end in chunk_windows(40, 16, 5)))

    def test_impossible_sizes_fail(self):
        with self.assertRaises(ValueError):
            chunk_windows(10, 16, 5)
        with self.assertRaises(ValueError):
            chunk_windows(40, 5, 5)

    def test_five_frames_cover_two_latent_frames(self):
        self.assertEqual([latent_frames(n) for n in (0, 1, 5, 9)], [0, 1, 2, 3])


class PositionTest(unittest.TestCase):
    def test_control_and_target_share_positions_and_text_comes_once(self):
        ids = mx.arange(3 * 7, dtype=mx.float32).reshape(3, 1, 7)
        packed = np.array(pack_positions(ids, 3))
        self.assertEqual(packed.shape, (3, 1, 11))
        self.assertTrue(np.array_equal(packed[:, :, :3], np.array(ids)[:, :, :3]))
        self.assertTrue(np.array_equal(packed[:, :, 3:7], packed[:, :, 7:11]))


class MaskTest(unittest.TestCase):
    def test_only_unconditioned_target_tokens_get_the_timestep(self):
        mask = np.array(noisy_mask(grid_t=4, spatial=2, conditioned=2, with_control=True)).ravel()
        self.assertEqual(mask.tolist(), [0] * 8 + [0] * 4 + [1] * 4)

    def test_without_control_only_the_target_is_masked(self):
        mask = np.array(noisy_mask(grid_t=4, spatial=2, conditioned=0, with_control=False)).ravel()
        self.assertEqual(mask.tolist(), [1] * 8)


class GuidanceTest(unittest.TestCase):
    def test_guidance_of_one_returns_the_full_prediction(self):
        full, without, uncond = mx.array([3.0]), mx.array([1.0]), mx.array([0.0])
        self.assertEqual(guided(full, without, uncond, 1.0, 1.0).item(), 3.0)

    def test_control_guidance_pushes_away_from_no_control(self):
        self.assertEqual(guided(mx.array([3.0]), mx.array([1.0]), mx.array([0.0]), 1.0, 1.5).item(), 4.0)

    def test_nested_order_matches_diffusers(self):
        # control_cond = 1 + 1.5 * (3 - 1) = 4, then 0 + 3 * (4 - 0) = 12.
        self.assertEqual(guided(mx.array([3.0]), mx.array([1.0]), mx.array([0.0]), 3.0, 1.5).item(), 12.0)

    def test_without_the_control_pass_it_is_plain_guidance(self):
        self.assertEqual(guided(mx.array([3.0]), None, mx.array([1.0]), 2.0, 1.0).item(), 5.0)


if __name__ == "__main__":
    unittest.main()
