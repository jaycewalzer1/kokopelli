"""Handing a run to the agent loop and benchmarks, on a tiny random model. No real weights are loaded."""
import json
import tempfile
import unittest
from pathlib import Path

import mlx.core as mx
import numpy as np
from mlx.utils import tree_flatten
from mlx_vlm.trainer.common.utils import save_trainable_weights
from mlx_vlm.trainer.peft.utils import apply_lora_layers, get_peft_model

from homeostatic.export import NotBetter, arm_config, best_validation, export, fuse_into, gate, sha256, write_full_weights
from core.settings import ROOT
from tests.test_homeostatic_grpo import tiny_model

REFERENCE = {"base": {"mean_drive": 29.4}, "idle": {"mean_drive": 25.2}}


def check(drive, invalid=0.0, iteration=25):
    return {"iteration": iteration, "mean_drive": drive, "invalid": invalid, "in_range": 0.1}


def nudged_adapter(model):
    """Give every adapter a non-zero update, since a fresh one changes nothing and couldn't show fusing worked."""
    for name, value in tree_flatten(model.trainable_parameters()):
        if name.endswith("lora_b"):
            parent = model
            parts = name.split(".")
            for part in parts[:-1]:
                parent = parent[int(part)] if part.isdigit() else getattr(parent, part)
            parent.lora_b = mx.random.normal(value.shape) * 0.01
    mx.eval(model.parameters())


class GateTest(unittest.TestCase):
    def test_a_run_that_beats_both_baselines_passes_with_its_best_check(self):
        self.assertEqual(gate([check(24.0), check(12.0, iteration=50), check(20.0, iteration=75)], REFERENCE)["iteration"], 50)

    def test_beating_the_untrained_model_alone_isnt_enough(self):
        with self.assertRaisesRegex(NotBetter, "idle"):
            gate([check(26.0)], REFERENCE)

    def test_matching_a_baseline_doesnt_count(self):
        with self.assertRaises(NotBetter):
            gate([check(25.2)], REFERENCE)

    def test_a_model_that_stopped_answering_cant_pass_by_looking_idle(self):
        # The 5e-4 run: every reply invalid, scoring what idling scores. It must not count even if that's low.
        self.assertIsNone(best_validation([check(1.0, invalid=1.0)]))
        with self.assertRaisesRegex(NotBetter, "valid"):
            gate([check(1.0, invalid=1.0)], REFERENCE)
        self.assertEqual(gate([check(1.0, invalid=1.0), check(20.0)], REFERENCE)["mean_drive"], 20.0)

    def test_no_baselines_is_refused_rather_than_assumed(self):
        with self.assertRaises(NotBetter):
            gate([check(1.0)], {})

    def test_export_refuses_before_loading_any_model(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            folder = out / "runs" / "failed"
            folder.mkdir(parents=True)
            (folder / "validation.jsonl").write_text(json.dumps(check(40.0)) + "\n")
            (out / "baselines-validation.json").write_text(json.dumps(REFERENCE))
            with self.assertRaises(NotBetter):
                export(folder, out, load=lambda *a, **k: self.fail("loaded a model"))
            self.assertFalse((out / "handoff.json").exists())
            self.assertFalse((folder / "fused").exists())


class FuseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        mx.random.seed(0)
        self.model = get_peft_model(tiny_model(), rank=2, alpha=4, dropout=0.0, verbose=False)
        nudged_adapter(self.model)
        self.ids = mx.array([[1, 2, 3, 4, 5]])

    def logits(self, model):
        model.eval()
        return np.array(model(self.ids).logits.astype(mx.float32))

    def test_fused_weights_give_the_same_outputs_with_no_adapter_left(self):
        before = self.logits(self.model)
        self.assertGreater(fuse_into(self.model), 0)
        self.assertFalse(any("lora" in name for name, _ in tree_flatten(self.model.parameters())))
        self.assertTrue(np.allclose(before, self.logits(self.model), atol=1e-3))

    def test_the_folder_loads_as_an_ordinary_model_with_the_same_outputs(self):
        base = self.root / "base"
        base.mkdir()
        (base / "config.json").write_text("{}")
        (base / "tokenizer.json").write_text("{}")
        (base / "model-00001-of-00004.safetensors").write_text("old weights")
        (base / "model.safetensors.index.json").write_text("{}")
        before = self.logits(self.model)
        fuse_into(self.model)
        write_full_weights(self.model, base, self.root / "fused")
        made = {path.name for path in (self.root / "fused").iterdir()}
        self.assertTrue({"config.json", "tokenizer.json"} <= made)
        self.assertNotIn("model-00001-of-00004.safetensors.old", made)
        self.assertFalse((self.root / "fused.building").exists())
        mx.random.seed(99)
        fresh = tiny_model()
        self.assertFalse(np.allclose(before, self.logits(fresh), atol=1e-3))
        for path in (self.root / "fused").glob("*.safetensors"):
            self.assertNotEqual(path.read_bytes()[:11], b"old weights")
            fresh.load_weights(str(path), strict=False)
        self.assertTrue(np.allclose(before, self.logits(fresh), atol=1e-3))

    def test_a_saved_adapter_fuses_to_the_same_outputs_as_the_trained_one(self):
        before = self.logits(self.model)
        save_trainable_weights(self.model, self.root / "best.safetensors")
        mx.random.seed(0)
        restored = apply_lora_layers(tiny_model(), self.root / "best.safetensors")
        fuse_into(restored)
        self.assertTrue(np.allclose(before, self.logits(restored), atol=1e-3))


class ArmTest(unittest.TestCase):
    def test_arm_follows_the_benchmarks_format_and_path_convention(self):
        arm = arm_config("homeostatic", 2, ROOT / "out" / "adapters")
        self.assertEqual(arm["adapter"], "out/adapters/homeostatic/seed{seed}")
        self.assertEqual(arm["training_text"], ["out/adapters/homeostatic/seed{seed}/training_text/*"])
        self.assertEqual(arm["seed"], 2)

    def test_hash_identifies_the_exact_adapter(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "x"
            path.write_bytes(b"abc")
            self.assertEqual(sha256(path), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


if __name__ == "__main__":
    unittest.main()
