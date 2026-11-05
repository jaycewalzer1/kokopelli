"""The before-and-after command on mock with a fake adapter, and the weights setting on a tiny real model."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from benchmarks import before_after, prereg, run
from benchmarks.core import REPO
from benchmarks.registry import Arm, load_arm

FIXTURES = Path(__file__).parent / "fixtures"
QWEN = REPO / "models" / "Qwen3-VL-8B-Instruct"


class Temp(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="evals_")
        self.addCleanup(self.folder.cleanup)
        self.tmp = Path(self.folder.name)
        self.out = self.tmp / "ba"

    def call(self, *extra, adapter="fake_adapter_risky", instruments=("holt_laury", "lotteries"), samples=30, seeds=("0", "1", "2")):
        return before_after.main(["--after-adapter", str(FIXTURES / adapter), "--name", "trained", "--instruments", *instruments, "--seeds", *seeds,
                                  "--samples", str(samples), "--out", str(self.out), *extra])

    def summary(self):
        return json.loads((self.out / "before_after.json").read_text())


class BeforeAfterOnMock(Temp):
    def test_finds_the_planted_change(self):
        self.assertEqual(self.call(), 0)
        summary = self.summary()
        self.assertTrue(summary["comparable"])
        by_name = {row["instrument"]: row for row in summary["instruments"]}
        self.assertLess(by_name["holt_laury"]["difference"], -0.5)
        self.assertGreater(by_name["lotteries"]["difference"], 0.1)
        self.assertLess(by_name["holt_laury"]["p_holm"], 0.05)
        self.assertEqual(set(by_name["holt_laury"]["difference_per_seed"]), {"0", "1", "2"})

    def test_no_change_isnt_reported_as_one(self):
        self.assertEqual(self.call(adapter="fake_adapter_null"), 0)
        for row in self.summary()["instruments"]:
            self.assertGreaterEqual(row["p_holm"], 0.05, row["instrument"])

    def test_both_sides_get_the_same_prompts_keys_and_orders(self):
        self.call(samples=5)
        rows = run.read_results(self.out)
        side = {arm: {run.result_key(r)[1:]: r["option_order"] for r in rows if r["arm"] == arm} for arm in ("base", "trained")}
        self.assertEqual(side["base"], side["trained"])
        self.assertTrue(side["base"])

    def test_guardrail_deltas(self):
        self.assertEqual(self.call(instruments=("holt_laury", "ifeval", "mmlu"), samples=3), 0)
        guardrails = {row["instrument"]: row for row in self.summary()["guardrails"]}
        self.assertEqual(set(guardrails), {"ifeval", "mmlu"})
        for row in guardrails.values():
            self.assertLess(row["ci_95"][0], row["ci_95"][1])
            self.assertEqual(row["margin_points"], 1.0)
        self.assertIn(self.summary()["guardrails_ok"], (True, False))

    def test_writes_a_report_and_saves_the_arms(self):
        self.call(samples=3)
        self.assertTrue((self.out / "report.html").exists())
        arm = yaml.safe_load((self.out / "arms" / "trained.yaml").read_text())
        self.assertIn("fake_adapter_risky", arm["adapter"])

    def test_resumes_without_repeating(self):
        self.call(samples=3)
        first = (self.out / "results.jsonl").read_text()
        self.assertEqual(self.call(samples=3), 0)
        self.assertEqual((self.out / "results.jsonl").read_text(), first)

    def test_a_different_adapter_in_the_same_folder_is_refused(self):
        self.call(samples=3)
        self.assertEqual(self.call(adapter="fake_adapter_null", samples=3), run.EXIT_REFUSED)

    def test_unfinished_sides_arent_comparable(self):
        self.call(samples=3)
        rows = (self.out / "results.jsonl").read_text().splitlines()
        (self.out / "results.jsonl").write_text("\n".join(rows[:-2]) + "\n")
        self.assertFalse(before_after.compare(self.out, "trained", n_perm=9)["comparable"])

    def test_time_budget_passes_through(self):
        with mock.patch("benchmarks.run.time.time", side_effect=_jumping_clock(3)):
            self.assertEqual(self.call("--minutes", "1", samples=5), run.EXIT_MORE_TO_DO)
        self.assertFalse((self.out / "before_after.json").exists())

    def test_fake_weights_work_too(self):
        code = before_after.main(["--after-weights", str(FIXTURES / "fake_adapter_risky"), "--name", "trained", "--instruments", "holt_laury", "--seeds", "0", "1", "2", "--samples", "30", "--out", str(self.out)])
        self.assertEqual(code, 0)
        self.assertLess(self.summary()["instruments"][0]["difference"], -0.5)

    def test_base_is_a_reserved_name(self):
        with self.assertRaises(SystemExit):
            before_after.main(["--after-adapter", "x", "--name", "base", "--seeds", "0", "--out", str(self.out)])


def _jumping_clock(calls):
    state = {"calls": 0}
    def clock():
        state["calls"] += 1
        return 1000.0 if state["calls"] <= calls else 1_000_000.0
    return clock


class RealRunsStayGated(Temp):
    """The pipeline can call this now, but real runs wait for the owner's approval."""

    def real(self, **patches):
        return before_after.main(["--after-weights", str(self.tmp), "--name", "homeostatic", "--instruments", "holt_laury", "--seeds", "0", "--samples", "1", "--backend", "llm_model", "--real", "--out", str(self.out)])

    def test_refused_while_prereg_is_a_draft(self):
        self.assertIn(prereg.DRAFT_MARK, prereg.PREREG.read_text())
        self.assertEqual(self.real(), run.EXIT_REFUSED)

    def test_refused_when_locked_but_arm_isnt_registered(self):
        with mock.patch("benchmarks.run.prereg.check", return_value={"amended": False}):
            self.assertEqual(self.real(), run.EXIT_REFUSED)
        self.assertFalse((self.out / "results.jsonl").exists())

    def test_exploratory_refuses_weights(self):
        arm = Arm(name="x", model="m", weights="somewhere")
        with mock.patch("benchmarks.run.load_arm", return_value=arm):
            code = run.main(["--backend", "llm_model", "--real", "--exploratory", "--arms", "x", "--instruments", "holt_laury", "--out", str(self.out)])
        self.assertEqual(code, run.EXIT_REFUSED)

    def test_no_homeostatic_arm_was_added(self):
        self.assertFalse((REPO / "benchmarks" / "configs" / "arms" / "homeostatic.yaml").exists())
        self.assertNotIn("homeostatic", (REPO / "benchmarks" / "configs" / "contrasts.yaml").read_text())
        self.assertNotIn("homeostatic", prereg.PREREG.read_text())


def _tiny_model():
    import mlx.core as mx
    from mlx_vlm.models.qwen3_vl import Model, ModelConfig
    config = json.loads((QWEN / "config.json").read_text())
    config["skip_vision"] = True
    config["text_config"] |= {"hidden_size": 32, "num_hidden_layers": 2, "intermediate_size": 64, "num_attention_heads": 2,
                              "num_key_value_heads": 2, "head_dim": 16, "max_position_embeddings": 2048}
    model = Model(ModelConfig.from_dict(config))
    mx.eval(model.parameters())
    return model, config


def _tiny_folder(path, seed):
    """A folder shaped like fused/ from homeostatic.export: Qwen's tokenizer and settings around tiny random weights."""
    import mlx.core as mx
    from mlx_vlm.utils import save_weights
    path.mkdir(parents=True)
    for source in QWEN.iterdir():
        if source.is_file() and not source.name.endswith(".safetensors") and source.name != "model.safetensors.index.json":
            shutil.copy(source, path / source.name)
    mx.random.seed(seed)
    model, config = _tiny_model()
    (path / "config.json").write_text(json.dumps(config))
    save_weights(path, model, donate_weights=True)


@unittest.skipUnless((QWEN / "config.json").exists(), "Needs Qwen's config and tokenizer, though not its weights.")
class WeightsSettingOnATinyModel(Temp):
    """Goes through the real llm_model.ask with no mocks. Tiny random weights, so the text is nonsense but its source is checkable."""

    def setUp(self):
        super().setUp()
        self.a, self.b = self.tmp / "fused_a", self.tmp / "fused_b"
        _tiny_folder(self.a, 1)
        _tiny_folder(self.b, 2)
        from benchmarks.backends.llm_model_backend import LLMModelBackend
        self.backend = LLMModelBackend()
        self.addCleanup(self.backend.close)
        self.request = dict(sampling={"temperature": 0.0, "max_tokens": 12})

    def answer(self, folder):
        from benchmarks.backends.base import GenRequest
        self.backend.prepare_arm(Arm(name="x", model="m", weights=str(folder)), 0)
        return self.backend.generate_batch([GenRequest("Hello there", seed=1, **self.request)])[0].text

    def test_each_folder_really_answers(self):
        first = self.answer(self.a)
        self.assertNotEqual(first, self.answer(self.b))
        self.assertEqual(first, self.answer(self.a))

    def test_results_name_and_hash_the_weights(self):
        info = self.backend.prepare_arm(Arm(name="x", model="m", weights=str(self.a)), 0)
        self.assertEqual(info["adapter_path"], str(self.a))
        self.assertEqual(len(info["adapter_hash"]), 64)
        other = self.backend.prepare_arm(Arm(name="x", model="m", weights=str(self.b)), 0)
        self.assertNotEqual(info["adapter_hash"], other["adapter_hash"])

    def test_seed_makes_sampling_repeatable(self):
        from benchmarks.backends.base import GenRequest
        self.backend.prepare_arm(Arm(name="x", model="m", weights=str(self.a)), 0)
        sampled = dict(sampling={"temperature": 1.0, "max_tokens": 12})
        once = self.backend.generate_batch([GenRequest("Hello there", seed=7, **sampled)])[0].text
        again = self.backend.generate_batch([GenRequest("Hello there", seed=7, **sampled)])[0].text
        other = self.backend.generate_batch([GenRequest("Hello there", seed=8, **sampled)])[0].text
        back = self.backend.generate_batch([GenRequest("Hello there", seed=7, **sampled)])[0].text
        self.assertEqual(once, again)
        self.assertNotEqual(once, other)
        self.assertEqual(once, back)  # A different draw in between mustn't matter.

    def test_first_sample_after_a_load_is_repeatable_too(self):
        """Layer setup uses random numbers. If that happened after seeding, only the first sample would differ."""
        from benchmarks.backends.base import GenRequest
        sampled = dict(sampling={"temperature": 1.0, "max_tokens": 12})
        arm = Arm(name="x", model="m", weights=str(self.a))
        self.backend.prepare_arm(arm, 0)
        first = self.backend.generate_batch([GenRequest("Hello there", seed=7, **sampled)])[0].text
        self.backend.llm_model.unload()
        self.assertEqual(first, self.backend.generate_batch([GenRequest("Hello there", seed=7, **sampled)])[0].text)

    def test_base_arm_points_back_at_base_and_close_restores(self):
        import llm_model
        self.backend.prepare_arm(Arm(name="x", model="m", weights=str(self.a)), 0)
        self.assertEqual(llm_model.LLM_MODEL_WEIGHTS, self.a)
        self.backend.prepare_arm(Arm(name="base", model="m"), 0)
        self.assertEqual(llm_model.LLM_MODEL_WEIGHTS, QWEN)
        self.backend.prepare_arm(Arm(name="x", model="m", weights=str(self.a)), 0)
        self.backend.close()
        self.assertEqual(llm_model.LLM_MODEL_WEIGHTS, QWEN)

    def test_seed_in_the_weights_path(self):
        (self.tmp / "seed0").symlink_to(self.a)
        info = self.backend.prepare_arm(Arm(name="x", model="m", weights=str(self.tmp / "seed{seed}")), 0)
        self.assertTrue(info["adapter_path"].endswith("seed0"))

    def test_refuses_things_that_arent_full_weights(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        with self.assertRaisesRegex(FileNotFoundError, "full weights"):
            self.backend.prepare_arm(Arm(name="x", model="m", weights=str(empty)), 0)

    def test_refuses_fake_marker(self):
        with self.assertRaisesRegex(ValueError, "fake"):
            self.backend.prepare_arm(load_arm("fake_lived").__class__(name="x", model="m", weights=str(FIXTURES / "fake_adapter_risky")), 0)

    def test_refuses_different_sampling_defaults(self):
        config = json.loads((self.a / "generation_config.json").read_text())
        config["top_k"] = 5
        (self.a / "generation_config.json").write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, "comparable"):
            self.backend.prepare_arm(Arm(name="x", model="m", weights=str(self.a)), 0)

    def test_still_refuses_an_adapter(self):
        with self.assertRaisesRegex(ValueError, "Fuse"):
            self.backend.prepare_arm(load_arm("lived"), 0)

    @unittest.skipUnless(os.environ.get("EVALS_LM_EVAL"), "Needs lm-eval from a separate venv, and downloads a small dataset.")
    def test_real_lm_eval_through_the_local_endpoint(self):
        from benchmarks.guardrails import MMLU
        guardrail = MMLU()
        guardrail.tasks, guardrail.limit = ("mmlu_abstract_algebra_generative",), 2
        arm = Arm(name="x", model="m", weights=str(self.a))
        self.backend.prepare_arm(arm, 0)
        rows = guardrail.run_harness(arm, 0, self.backend, self.tmp)
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[0][0].startswith("mmlu_abstract_algebra_generative:"))

    def test_local_endpoint_serves_an_outside_tool(self):
        """A stand-in for lm-eval, in another process, calling the local server the way the guardrail wrapper will."""
        client = self.tmp / "client.py"
        client.write_text(
            "import json, sys, urllib.request\n"
            "body = json.dumps({'model': 'x', 'messages': [{'role': 'user', 'content': 'Hello there'}], 'max_tokens': 8, 'temperature': 0}).encode()\n"
            "request = urllib.request.Request(sys.argv[1] + '/chat/completions', body, {'Content-Type': 'application/json'})\n"
            "reply = json.load(urllib.request.urlopen(request, timeout=120))\n"
            "open(sys.argv[2], 'w').write(reply['choices'][0]['message']['content'])\n")
        output = self.tmp / "reply.txt"
        arm = Arm(name="x", model="m", weights=str(self.a))
        self.backend.prepare_arm(arm, 0)
        self.backend.run_harness_command(arm, lambda url, model: [sys.executable, str(client), url, str(output)])
        self.assertTrue(output.read_text().strip())


if __name__ == "__main__":
    unittest.main()
