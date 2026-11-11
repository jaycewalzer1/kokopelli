"""The pilot job's logic, and the whole job run twice on a tiny random model. No real weights are loaded, seconds.

The tiny model is Qwen-shaped (two small layers), quantized to 4 bits like the real base and written to a folder that
mlx-vlm's own loader opens, with the real tokenizer linked in. So the job's path is the real one end to end: load,
attach the adapter, train, fuse both ways, write the folder, load the folder again. Only the numbers are meaningless.
"""
import json
import tempfile
import unittest
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import numpy as np
from mlx_vlm import generate, load
from mlx_vlm.models.qwen3_vl import Model, ModelConfig
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.trainer.peft.lora_layers import LoRALinear
from mlx_vlm.utils import save_weights

from experiments.homeostatic.export import fuse_into
from experiments.sensation.psych101 import prepare, train_pilot
from experiments.sensation.psych101.tests.test_prepare import made_up_file, rulings

BITS = {"group_size": 64, "bits": 4, "mode": "affine"}


def tiny_base(folder):
    """A folder like models/Qwen3-VL-8B-Instruct-4bit, a few megabytes of random weights."""
    folder = Path(folder)
    folder.mkdir(parents=True)
    config = json.loads((train_pilot.BASE / "config.json").read_text())
    config["text_config"] |= {"hidden_size": 64, "num_hidden_layers": 2, "intermediate_size": 128, "num_attention_heads": 2,
                              "num_key_value_heads": 2, "head_dim": 32, "max_position_embeddings": 4096}
    config["vision_config"] |= {"depth": 2, "hidden_size": 64, "intermediate_size": 128, "num_heads": 2, "out_hidden_size": 64,
                                "deepstack_visual_indexes": [0, 1], "num_position_embeddings": 64}
    config["quantization"] = config["quantization_config"] = BITS
    mx.random.seed(0)
    model = Model(ModelConfig.from_dict(config))
    nn.quantize(model, group_size=64, bits=4, class_predicate=lambda path, module: (
        isinstance(module, nn.Linear) and path.startswith("language_model") and module.weight.shape[-1] % 64 == 0))
    mx.eval(model.parameters())
    save_weights(folder, model)
    (folder / "config.json").write_text(json.dumps(config))
    for path in train_pilot.BASE.iterdir():   # the tokenizer, chat template and sampling defaults are the real ones
        if path.is_file() and path.suffix != ".safetensors" and path.name not in ("config.json", "model.safetensors.index.json"):
            (folder / path.name).symlink_to(path)
    return folder


class SizingTest(unittest.TestCase):
    def test_the_rows_follow_from_the_measured_rate(self):
        fit = train_pilot.rows_that_fit(tokens_per_second=500, seconds=1500, mean_tokens=750, available=5000, cap=3000)
        self.assertEqual((fit["rows"], fit["limited_by"]), (1000, "the time"))
        self.assertIn("500 tokens/s x 1500 s / 750 tokens per row = 1000 rows", fit["arithmetic"])

    def test_it_never_asks_for_more_rows_than_exist_or_than_the_cap(self):
        self.assertEqual(train_pilot.rows_that_fit(500, 1500, 750, available=600, cap=3000)["limited_by"], "the rows prepared")
        self.assertEqual(train_pilot.rows_that_fit(500, 1500, 750, available=5000, cap=100)["rows"], 100)
        self.assertEqual(train_pilot.rows_that_fit(500, 0, 750, available=5000, cap=100)["rows"], 0)

    def test_the_first_report_is_left_out_of_the_rate_because_it_holds_the_warm_up(self):
        reports = [{"end_to_end_tokens_per_second": rate} for rate in (10, 100, 110, 120)]
        self.assertEqual(train_pilot.measured_rate(reports), 110)
        self.assertEqual(train_pilot.measured_rate(reports[:2]), 55)
        with self.assertRaises(ValueError):
            train_pilot.measured_rate([{"train_loss": 1.0}])

    def test_kept_share_reads_as_all_none_or_cant_tell(self):
        self.assertEqual(train_pilot.kept_share(base=2.0, adapter=1.5, fused=1.5), 1.0)
        self.assertEqual(train_pilot.kept_share(base=2.0, adapter=1.5, fused=2.0), 0.0)
        self.assertIsNone(train_pilot.kept_share(base=2.0, adapter=2.0004, fused=1.9))

    def test_a_held_out_experiment_in_the_rows_stops_the_job(self):
        lists = {"held_out": {"lab2020dictator": "giving"}, "kept_after_review": {}}
        train_pilot.check_rows([{"experiment": "lab2023shapes/exp1.csv"}], lists)
        with self.assertRaises(SystemExit):
            train_pilot.check_rows([{"experiment": "lab2023shapes/exp1.csv"}, {"experiment": "lab2020dictator/exp1.csv"}], lists)


class Holder(nn.Module):
    """One adapted 4-bit layer, the smallest thing the two ways of fusing can be compared on."""

    def __init__(self, update=2e-4):
        super().__init__()
        mx.random.seed(3)
        plain = nn.Linear(128, 64, bias=False)
        self.layer = LoRALinear.from_base(nn.QuantizedLinear.from_linear(plain, 64, 4), r=2, scale=2.0)
        self.layer.lora_b = mx.random.normal(self.layer.lora_b.shape) * update
        mx.eval(self.parameters())


class FuseTest(unittest.TestCase):
    """Why the job measures the fused weights: an update far smaller than a 4-bit step doesn't survive being rounded."""

    def setUp(self):
        mx.random.seed(4)
        self.inputs = mx.random.normal((16, 128))
        adapted = Holder()
        self.target = np.array(adapted.layer(self.inputs))
        self.change = np.linalg.norm(self.target - np.array(adapted.layer.linear(self.inputs)))

    def miss(self, model):
        return np.linalg.norm(np.array(model.layer(self.inputs).astype(mx.float32)) - self.target) / self.change

    def test_float_fusing_keeps_a_small_update(self):
        model = Holder()
        self.assertEqual(train_pilot.fuse_float(model), 1)
        self.assertIsInstance(model.layer, nn.Linear)
        self.assertEqual(model.layer.weight.dtype, mx.float32)
        self.assertLess(self.miss(model), 0.01)

    def test_fusing_back_to_4_bits_loses_most_of_it(self):
        model = Holder()
        fuse_into(model)
        self.assertIsInstance(model.layer, nn.QuantizedLinear)
        self.assertGreater(self.miss(model), 0.5)


class PilotJobTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.base = tiny_base(root / "base")
        cls.held = rulings(root)
        cls.data = root / "data"
        prepare.convert(made_up_file(root, people=80), cls.data, cls.held, per_session=2, max_chars=300, pilot_per_experiment=12)
        settings = train_pilot.SETTINGS | {"rank": 2, "alpha": 4.0, "learning_rate": 2e-2, "max_seq_length": 512}
        common = dict(data=cls.data, base=cls.base, minutes=0.05, probe=8, cap=20, validation_rows=6, settings=settings,
                      held_out_path=cls.held)
        # keep=2 can't be met, so the adapted layers stay floats; keep=-1000 accepts whatever rounding to 4 bits leaves.
        cls.floats = train_pilot.run(out=root / "floats", keep=2.0, **common)
        cls.rounded = train_pilot.run(out=root / "rounded", keep=-1000.0, **common)
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_it_trains_on_a_prefix_sized_by_the_probe_and_says_how(self):
        training = self.floats["training"]
        self.assertEqual((training["rows"], training["steps"], training["limited_by"]), (20, 20, "the cap"))
        self.assertIn("tokens/s x 3 s /", training["sizing"])
        self.assertGreater(training["probe_tokens_per_second"], 0)
        self.assertEqual(training["experiments_covered"], 3)

    def test_the_sidecar_names_the_model_the_data_and_the_settings(self):
        record = json.loads((self.root / "floats" / "run.json").read_text())
        self.assertTrue(record["finished"] and record["real"])
        self.assertEqual(record["model"]["id"], "Qwen/Qwen3-VL-8B-Instruct")
        self.assertEqual(record["model"]["quantization"], BITS)
        self.assertEqual(record["model"]["weights"], str(self.base))
        self.assertEqual(record["data"]["revision"], prepare.REVISION)
        for key in ("rank", "learning_rate", "rows", "steps", "targets", "seed"):
            self.assertIn(key, record["training"])
        self.assertEqual(record["adapter"]["sha256"], train_pilot.sha256(self.root / "floats" / "adapters.safetensors"))
        self.assertEqual(json.loads((self.root / "floats" / "fused" / "run.json").read_text()), record)

    def test_training_moved_the_loss(self):
        losses = self.floats["validation_loss"]
        self.assertGreater(abs(losses["base"] - losses["adapter"]), 1e-3)

    def test_the_float_folder_gives_the_adapters_loss(self):
        losses, fused = self.floats["validation_loss"], self.floats["fused"]
        self.assertTrue(fused["variant"].startswith("mixed"))
        self.assertAlmostEqual(losses["fused_folder"], losses["adapter"], delta=0.02)
        self.assertAlmostEqual(fused["folder_keeps"], 1.0, delta=0.1)

    def test_the_float_folder_loads_as_an_ordinary_model_with_only_the_adapted_layers_changed(self):
        model, _ = load(str(self.root / "floats" / "fused"))
        kinds = {name.rsplit(".", 1)[-1]: type(module).__name__ for name, module in model.named_modules()
                 if name.startswith("language_model") and isinstance(module, nn.Linear | nn.QuantizedLinear)}
        self.assertEqual((kinds["q_proj"], kinds["v_proj"], kinds["k_proj"], kinds["o_proj"]),
                         ("Linear", "Linear", "QuantizedLinear", "QuantizedLinear"))
        self.assertFalse(any(hasattr(module, "lora_a") for _, module in model.named_modules()))
        sampling = (self.root / "floats" / "fused" / "generation_config.json").read_text()
        self.assertEqual(sampling, (train_pilot.BASE / "generation_config.json").read_text())   # what the backend's check compares

    def test_the_float_folder_answers_a_prompt_the_way_the_sweep_asks(self):
        # The sweep generates with a cache, one token at a time; float layers among 4-bit ones must not trip that path.
        model, processor = load(str(self.root / "floats" / "fused"))
        prompt = apply_chat_template(processor, model.config, "Teo asks for one of your two eggs. What do you do?", num_images=0)
        mx.random.seed(1)
        result = generate(model, processor, prompt, max_tokens=6, temperature=0.7)
        self.assertEqual(result.generation_tokens, 6)

    def test_the_4_bit_folder_gives_the_loss_measured_before_it_was_written(self):
        losses, fused = self.rounded["validation_loss"], self.rounded["fused"]
        self.assertTrue(fused["variant"].startswith("4-bit"))
        self.assertAlmostEqual(losses["fused_folder"], losses["fused_requantized"], delta=1e-3)
        model, _ = load(str(self.root / "rounded" / "fused"))
        self.assertIsInstance(model.language_model.model.layers[0].self_attn.q_proj, nn.QuantizedLinear)

    def test_both_runs_trained_the_same_adapter(self):
        self.assertEqual(self.floats["adapter"]["sha256"], self.rounded["adapter"]["sha256"])


if __name__ == "__main__":
    unittest.main()
