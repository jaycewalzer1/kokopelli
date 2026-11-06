"""Variant B's pieces that decide what the model computes. Tiny random tensors only; no checkpoint is loaded.

Run from the repo root (the venv has no pytest, and its own `tests` package shadows ours as a module name):
  PYTHONPATH=.:~/cosmos3/cosmos3-mlx ~/cosmos3/cosmos3-mlx/.venv/bin/python -m unittest discover -s tests -p test_wm_multicontrol_b.py
"""
import unittest

import mlx.core as mx
import numpy as np

from world_multicontrol_base import (forward, guided, multi_control_attention, normalise_weights, parse_pairs,
                                     query_blocks, sdpa, shared_positions, vision_positions)


def same(a, b):
    return np.array_equal(np.array(a.astype(mx.float32)), np.array(b.astype(mx.float32)))


class WeightTest(unittest.TestCase):
    def test_weights_are_divided_by_their_sum(self):
        self.assertEqual(normalise_weights([1, 3]), [0.25, 0.75])
        self.assertEqual(normalise_weights([0.5, 0.5]), [0.5, 0.5])
        self.assertEqual(normalise_weights([2.0]), [1.0])

    def test_negative_or_zero_sum_weights_fail(self):
        for bad in ([-1, 2], [0, 0], []):
            with self.assertRaises(ValueError):
                normalise_weights(bad)

    def test_unknown_hints_are_refused(self):
        self.assertEqual(parse_pairs(["blur=a.mp4", "seg=b=c.mp4"], "control"), {"blur": "a.mp4", "seg": "b=c.mp4"})
        with self.assertRaises(SystemExit):
            parse_pairs(["rgb=a.mp4"], "control")


class PositionTest(unittest.TestCase):
    def test_vision_positions_follow_text_margin_and_fps(self):
        pos = np.array(vision_positions(10, 3, 2, 4, 30.0))
        self.assertEqual(pos.shape, (3, 3 * 2 * 4))
        np.testing.assert_allclose(pos[0, ::8], [15010, 15010.8, 15011.6], rtol=0, atol=1e-3)
        np.testing.assert_array_equal(pos[1, :8], [0, 0, 0, 0, 1, 1, 1, 1])
        np.testing.assert_array_equal(pos[2, :8], [0, 1, 2, 3, 0, 1, 2, 3])

    def test_at_24_fps_they_match_cosmos3_mlx(self):
        try:
            from cosmos3_mlx.pipeline import Cosmos3GenerationPipeline
        except ImportError:
            self.skipTest("cosmos3_mlx not on PYTHONPATH")
        theirs = Cosmos3GenerationPipeline._build_position_ids(None, 37, 5, 8, 14)
        self.assertTrue(same(theirs[:, 0, 37:], vision_positions(37, 5, 8, 14, 24.0)))

    def test_controls_repeat_the_targets_positions(self):
        from world_filter import pack_positions
        target = vision_positions(7, 2, 3, 3, 24.0)
        layout = shared_positions(target, 3)
        self.assertEqual(layout.shape, (3, 3 * 18))
        for i in range(3):
            self.assertTrue(same(layout[:, i * 18:(i + 1) * 18], target))
        text = mx.broadcast_to(mx.arange(7, dtype=mx.float32)[None], (3, 7))
        full = mx.concatenate([text, target], axis=1)[:, None]
        self.assertTrue(same(pack_positions(full, 7)[:, 0, 7:], shared_positions(target, 2)))


class GuidanceTest(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.full, self.uncond, self.nc = (rng.normal(size=(4, 6)) for _ in range(3))

    def test_control_guidance_one_is_plain_text_cfg(self):
        np.testing.assert_allclose(guided(self.full, self.uncond, self.nc, 3.0, 1.0),
                                   self.uncond + 3.0 * (self.full - self.uncond))

    def test_final_control_increment_is_g_plus_gc_minus_one(self):
        g, gc = 3.0, 1.5
        increment = guided(self.full, self.uncond, self.nc, g, gc) - guided(self.nc, self.uncond, self.nc, g, gc)
        np.testing.assert_allclose(increment, (g + gc - 1.0) * (self.full - self.nc), atol=1e-12)

    def test_upstream_formula(self):
        g, gc = 3.0, 1.5
        mixed = self.nc + (1 + (gc - 1) / g) * (self.full - self.nc)
        np.testing.assert_allclose(guided(self.full, self.uncond, self.nc, g, gc), self.uncond + g * (mixed - self.uncond))

    def test_no_negative_branch_and_bad_combination(self):
        np.testing.assert_allclose(guided(self.full, None, self.nc, 1.0, 2.0), self.nc + 2.0 * (self.full - self.nc))
        with self.assertRaises(ValueError):
            guided(self.full, self.uncond, self.nc, 0.0, 1.5)


def rand(*shape, dtype=mx.bfloat16):
    return mx.random.normal(shape).astype(dtype)


class AttentionTest(unittest.TestCase):
    def setUp(self):
        mx.random.seed(3)

    def test_blocks_cover_queries_and_fold_short_tails(self):
        self.assertEqual(query_blocks(203, 64), [(0, 64), (64, 128), (128, 203)])
        self.assertEqual(query_blocks(200, 64), [(0, 64), (64, 128), (128, 200)])
        self.assertEqual(query_blocks(50, 64), [(0, 50)])
        self.assertEqual(query_blocks(50, 0), [(0, 50)])

    def test_chunked_attention_is_bit_identical(self):
        for dtype in (mx.float32, mx.bfloat16):
            q, k, v = rand(1, 8, 203, 32, dtype=dtype), rand(1, 2, 300, 32, dtype=dtype), rand(1, 2, 300, 32, dtype=dtype)
            whole = sdpa(q, k, v, 0)
            for chunk in (32, 50, 64, 100):
                self.assertTrue(same(sdpa(q, k, v, chunk), whole), (dtype, chunk))

    def test_one_control_is_plain_two_way_attention(self):
        n, L = 24, 9
        q, k, v = rand(1, 8, 2 * n, 32), rand(1, 2, 2 * n, 32), rand(1, 2, 2 * n, 32)
        tk, tv = rand(1, 2, L, 32), rand(1, 2, L, 32)
        plain = mx.fast.scaled_dot_product_attention(q, mx.concatenate([tk, k], 2), mx.concatenate([tv, v], 2),
                                                      scale=32 ** -0.5)
        self.assertTrue(same(multi_control_attention(q, k, v, tk, tv, 1, [1.0]), plain))

    def test_two_identical_controls_equal_one(self):
        n, L = 40, 9
        ctrl, tgt = [rand(1, h, n, 32) for h in (8, 2, 2)], [rand(1, h, n, 32) for h in (8, 2, 2)]
        tk, tv = rand(1, 2, L, 32), rand(1, 2, L, 32)
        one = multi_control_attention(*[mx.concatenate([c, t], 2) for c, t in zip(ctrl, tgt)], tk, tv, 1, [1.0], 32)
        two = multi_control_attention(*[mx.concatenate([c, c, t], 2) for c, t in zip(ctrl, tgt)], tk, tv, 2, [0.5, 0.5], 32)
        self.assertEqual(two.shape, (1, 8, 3 * n, 32))
        self.assertTrue(same(two[:, :, :n], one[:, :, :n]))
        self.assertTrue(same(two[:, :, n:2 * n], one[:, :, :n]))
        self.assertTrue(same(two[:, :, 2 * n:], one[:, :, n:]))

    def test_target_is_the_weighted_sum_of_passes(self):
        n, L = 16, 5
        q, k, v = rand(1, 8, 3 * n, 32), rand(1, 2, 3 * n, 32), rand(1, 2, 3 * n, 32)
        tk, tv = rand(1, 2, L, 32), rand(1, 2, L, 32)
        out = multi_control_attention(q, k, v, tk, tv, 2, [0.25, 0.75])
        passes = []
        for i in range(2):
            kk = mx.concatenate([tk, k[:, :, i * n:(i + 1) * n], k[:, :, 2 * n:]], 2)
            vv = mx.concatenate([tv, v[:, :, i * n:(i + 1) * n], v[:, :, 2 * n:]], 2)
            passes.append(mx.fast.scaled_dot_product_attention(q[:, :, 2 * n:], kk, vv, scale=32 ** -0.5))
            ctrl = mx.fast.scaled_dot_product_attention(q[:, :, i * n:(i + 1) * n], kk, vv, scale=32 ** -0.5)
            np.testing.assert_allclose(np.array(out[:, :, i * n:(i + 1) * n].astype(mx.float32)),
                                       np.array(ctrl.astype(mx.float32)), atol=2e-2)
        np.testing.assert_allclose(np.array(out[:, :, 2 * n:].astype(mx.float32)),
                                   np.array((0.25 * passes[0] + 0.75 * passes[1]).astype(mx.float32)), atol=2e-2)


class TinyGenerator:
    """world_transfer.Generator's layout with random weights: real head shapes (32 x 128, hidden 4096, since
    Generator.__call__ hardcodes them), 2 layers and a 64-wide MLP, so it builds in a second."""

    def __init__(self, layers=2, mlp=64):
        from world_transfer import Generator
        mx.random.seed(11)
        lin = lambda o, i: (lambda w: (lambda x: x @ w.T))(rand(o, i) * (i ** -0.5))
        self.gen = Generator.__new__(Generator)
        self.gen.layers = [dict(q=lin(4096, 4096), k=lin(1024, 4096), v=lin(1024, 4096), o=lin(4096, 4096),
                                gate=lin(mlp, 4096), up=lin(mlp, 4096), down=lin(4096, mlp),
                                ln1=1 + 0.1 * rand(4096), ln2=1 + 0.1 * rand(4096), qn=1 + 0.1 * rand(128),
                                kn=1 + 0.1 * rand(128)) for _ in range(layers)]
        self.gen.g = {"proj_in.weight": rand(4096, 192) * 0.07, "proj_in.bias": rand(4096) * 0.01,
                      "proj_out.weight": rand(192, 4096) * 0.015, "proj_out.bias": rand(192) * 0.01,
                      "norm_moe_gen.weight": 1 + 0.1 * rand(4096),
                      "time_embedder.linear_1.weight": rand(4096, 256) * 0.06, "time_embedder.linear_1.bias": rand(4096) * 0.01,
                      "time_embedder.linear_2.weight": rand(4096, 4096) * 0.015, "time_embedder.linear_2.bias": rand(4096) * 0.01}
        self.text = [(rand(1, 8, 7, 128), rand(1, 8, 7, 128)) for _ in range(layers)]


class ForwardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from world_transfer import Rope
        cls.tiny = TinyGenerator()
        cls.n = 2 * 2 * 3                     # 2 latents of a 2 x 3 patch grid
        cls.cos, cls.sin = Rope().tables(vision_positions(7, 2, 2, 3, 30.0))
        mx.random.seed(5)
        cls.ctrl_a, cls.ctrl_b, cls.target = (rand(1, cls.n, 192) for _ in range(3))

    def run_forward(self, controls, weights, sigma=0.7):
        tokens = mx.concatenate(controls + [self.target], axis=1)
        return forward(self.tiny.gen, tokens, self.cos, self.sin, self.tiny.text, len(controls), weights, sigma, 32)

    def test_one_control_matches_world_transfer_generator(self):
        """Without a timestep (Generator would stamp every token), N=1 is Generator.__call__ over [ctrl | target]."""
        tokens = mx.concatenate([self.ctrl_a, self.target], axis=1)
        cos2, sin2 = (mx.concatenate([t, t], axis=1) for t in (self.cos, self.sin))
        ref, _ = self.tiny.gen(tokens, cos2, sin2, [[kv] for kv in self.tiny.text])
        ours = forward(self.tiny.gen, tokens, self.cos, self.sin, self.tiny.text, 1, [1.0], None)
        np.testing.assert_allclose(np.array(ours), np.array(ref[:, self.n:]), atol=1e-6)

    def close(self, a, b):
        """MLX's GEMM picks its kernel by row count, so the same rows in a longer sequence round differently in bf16
        (measured: ~0.003 mean, 0.023 max here, against 0.14+ for a real change of control). Same-length comparisons
        below are bit-exact; across lengths only this tolerance holds."""
        d = mx.abs(a - b)
        return float(d.mean()) < 0.01 and float(d.max()) < 0.05

    def test_two_identical_controls_equal_one(self):
        self.assertTrue(self.close(self.run_forward([self.ctrl_a, self.ctrl_a], [0.5, 0.5]), self.run_forward([self.ctrl_a], [1.0])))

    def test_a_zero_weight_control_leaves_no_trace(self):
        zero = self.run_forward([self.ctrl_a, self.ctrl_b], [1.0, 0.0])
        self.assertTrue(same(zero, self.run_forward([self.ctrl_a, self.ctrl_a], [0.5, 0.5])))   # same length: exact
        self.assertTrue(self.close(zero, self.run_forward([self.ctrl_a], [1.0])))
        self.assertFalse(self.close(self.run_forward([self.ctrl_a, self.ctrl_b], [0.5, 0.5]), zero))

    def test_weights_change_the_target_and_no_control_differs(self):
        ab = self.run_forward([self.ctrl_a, self.ctrl_b], [0.5, 0.5])
        self.assertEqual(ab.shape, (1, self.n, 192))
        self.assertFalse(same(ab, self.run_forward([self.ctrl_a], [1.0])))
        self.assertFalse(same(self.run_forward([], []), self.run_forward([self.ctrl_a], [1.0])))


if __name__ == "__main__":
    unittest.main()
