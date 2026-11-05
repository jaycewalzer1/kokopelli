"""The runner: results format, resume, retries, refusals, the pre-registration guard, freezing, and leakage."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from benchmarks import freeze, leakage, noise_check, prereg, run
from benchmarks.backends.base import GenRequest, adapter_hash, read_fake_marker
from benchmarks.backends.mock import MockBackend
from benchmarks.guardrails import IFEval, MMLU
from benchmarks.holt_laury import HoltLaury
from benchmarks.lotteries import Lotteries
from benchmarks.mid_travel import generate as travel
from benchmarks.registry import load_arm, load_instrument, load_norms

FIXTURES = Path(__file__).parent / "fixtures"
FIELDS = {"arm", "instrument", "item_id", "template", "seed", "sample", "option_order", "raw_output", "parsed_choice", "valid", "latency_s", "model_id", "adapter_path", "adapter_hash", "sampling"}


class Temp(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="evals_")
        self.addCleanup(self.folder.cleanup)
        self.tmp = Path(self.folder.name)
        self.out = self.tmp / "run"

    def run_mock(self, *extra, arms=("fake_base",), instruments=("holt_laury",), samples=3):
        return run.main(["--arms", *arms, "--instruments", *instruments, "--samples", str(samples), "--out", str(self.out), *extra])


class ResultsFormat(Temp):
    def test_all_fields_and_summary(self):
        self.assertEqual(self.run_mock(), 0)
        rows = run.read_results(self.out)
        self.assertEqual(len(rows), 3 * 3)  # 1 item x 3 templates x 3 samples
        self.assertLessEqual(FIELDS, set(rows[0]))
        self.assertEqual(rows[0]["sampling"]["temperature"], 0.7)
        summary = pd.read_parquet(self.out / "summary.parquet")
        self.assertEqual(summary.n.sum(), 9)

    def test_run_record_has_what_reproduction_needs(self):
        self.run_mock()
        record = json.loads((self.out / "run_record.json").read_text())
        self.assertEqual(len(record["sessions"][0]["git"]["commit"]), 40)
        self.assertEqual(len(record["item_hashes"]["holt_laury"]), 64)
        self.assertEqual(record["sampling"]["top_k"], 20)
        self.assertIn("base", " ".join(record["arms"]))

    def test_fake_adapter_hash_and_config_reach_results(self):
        self.run_mock(arms=("fake_lived",))
        self.assertIn("fake_adapter_risky", run.read_results(self.out)[0]["adapter_path"])

    def test_all_instruments_run_end_to_end(self):
        """The phase 2 gate, with throwaway travel items."""
        draft = self.tmp / "travel.jsonl"
        items, _ = travel.generate(travel._mock_write)
        draft.write_text("\n".join(json.dumps(item) for item in items))
        code = self.run_mock("--items-override", f"mid_travel={draft}", arms=("fake_base", "fake_lived"),
                             instruments=("holt_laury", "lotteries", "mid_travel", "near_errand", "ifeval", "mmlu"), samples=2)
        self.assertEqual(code, 0)
        rows = run.read_results(self.out)
        self.assertEqual({r["instrument"] for r in rows}, {"holt_laury", "lotteries", "mid_travel", "near_errand", "ifeval", "mmlu"})
        self.assertTrue((self.out / "summary.parquet").exists())
        from benchmarks import report
        data = report.collect(self.out)
        self.assertIn("mid_travel", report.to_markdown(data))
        self.assertIn("near_errand is a stub", report.to_html(data))


class Resume(Temp):
    def test_second_run_adds_nothing(self):
        self.run_mock()
        first = (self.out / "results.jsonl").read_text()
        self.assertEqual(self.run_mock(), 0)
        self.assertEqual((self.out / "results.jsonl").read_text(), first)

    def test_more_samples_only_adds_new_keys(self):
        self.run_mock(samples=2)
        first = run.read_results(self.out)
        self.run_mock(samples=4)
        rows = run.read_results(self.out)
        self.assertEqual(rows[:len(first)], first)
        self.assertEqual(len(rows), 12)
        self.assertEqual(len({run.result_key(row) for row in rows}), 12)

    def test_torn_last_line_is_redone(self):
        self.run_mock()
        path = self.out / "results.jsonl"
        lines = path.read_text().splitlines()
        path.write_text("\n".join(lines[:-1]) + "\n" + lines[-1][:30])
        self.assertEqual(self.run_mock(), 0)
        rows = run.read_results(self.out)
        self.assertEqual(len(rows), 9)
        self.assertEqual(len({run.result_key(row) for row in rows}), 9)

    def test_time_budget_stops_cleanly_and_resume_finishes(self):
        with mock.patch("benchmarks.run.time.time", side_effect=_clock_jumping_after(3)):
            code = self.run_mock("--minutes", "1", samples=5)
        self.assertEqual(code, run.EXIT_MORE_TO_DO)
        partial = len(run.read_results(self.out))
        self.assertGreater(partial, 0)
        self.assertLess(partial, 15)
        self.assertEqual(self.run_mock(samples=5), 0)
        self.assertEqual(len(run.read_results(self.out)), 15)

    def test_changed_sampling_is_refused(self):
        self.run_mock()
        self.assertEqual(self.run_mock("--temperature", "1.0"), run.EXIT_REFUSED)

    def test_new_arm_can_join_an_existing_run(self):
        self.run_mock()
        self.assertEqual(self.run_mock(arms=("fake_null",)), 0)
        self.assertEqual({r["arm"] for r in run.read_results(self.out)}, {"fake_base", "fake_null"})


def _clock_jumping_after(calls):
    """A pretend clock that passes any time budget after a few reads."""
    state = {"calls": 0}
    def clock():
        state["calls"] += 1
        return 1000.0 if state["calls"] <= calls else 1_000_000.0
    return clock


class Retry(Temp):
    def test_failure_then_success_is_valid_with_two_attempts(self):
        rows = self._run_with(["nonsense", '{"choice": "A"}'])
        self.assertTrue(rows[0]["valid"])
        self.assertEqual(rows[0]["attempts"], 2)
        self.assertEqual(rows[0]["failed_outputs"][0]["raw"], "nonsense")

    def test_two_failures_are_recorded_as_invalid(self):
        rows = self._run_with(["nonsense", "more nonsense"])
        self.assertFalse(rows[0]["valid"])
        self.assertIsNone(rows[0]["score"])
        self.assertEqual(rows[0]["raw_output"], "more nonsense")
        self.assertTrue(rows[0]["invalid_reason"])

    def test_retries_at_most_once(self):
        calls = []
        self._run_with(["nonsense", "more", "never used"], calls)
        self.assertEqual(len(calls), 2)

    def test_retry_has_a_new_seed(self):
        calls = []
        self._run_with(["nonsense", "more"], calls)
        self.assertNotEqual(calls[0], calls[1])

    def _run_with(self, answers, seeds=None):
        script = iter(answers)
        def fake_batch(backend, requests):
            from benchmarks.backends.base import GenResult
            if seeds is not None:
                seeds.extend(request.seed for request in requests)
            return [GenResult(next(script), 0.0) for _ in requests]
        lot = Lotteries()
        lot.items = lot.items[:1]
        lot.templates = lot.templates[:1]
        with mock.patch.object(MockBackend, "generate_batch", fake_batch), mock.patch("benchmarks.run.load_instrument", return_value=lot):
            self.run_mock(instruments=("lotteries",), samples=1)
        return run.read_results(self.out)


class PromptsAcrossArms(Temp):
    def test_every_arm_sees_the_same_prompt_and_order(self):
        arm_a, arm_b = load_arm("fake_base"), load_arm("fake_lived")
        hl = HoltLaury()
        for sample in range(10):
            order_a, request_a = run.make_request(arm_a, hl, hl.items[0], "percent", 0, sample, {})
            order_b, request_b = run.make_request(arm_b, hl, hl.items[0], "percent", 0, sample, {})
            self.assertEqual(request_a.prompt, request_b.prompt)
            self.assertEqual(order_a, order_b)

    def test_both_orders_occur_in_a_run(self):
        self.run_mock(samples=20)
        self.assertEqual({row["option_order"] for row in run.read_results(self.out)}, {"safe,risky", "risky,safe"})

    def test_banned_word_stops_the_run(self):
        lot = Lotteries()
        lot.build_prompt = lambda *args: "Should you take the shortcut?"
        with mock.patch("benchmarks.run.load_instrument", return_value=lot):
            self.assertEqual(self.run_mock(instruments=("lotteries",)), run.EXIT_REFUSED)


class Refusals(Temp):
    def real(self, *arms, instruments=("holt_laury",), extra=()):
        return run.main(["--backend", "llm_model", "--arms", *arms, "--instruments", *instruments, "--samples", "1", "--out", str(self.out), *extra])

    def test_real_backend_needs_real_flag(self):
        self.assertEqual(self.real("base"), run.EXIT_REFUSED)

    def test_real_flag_needs_real_backend(self):
        self.assertEqual(self.run_mock("--real"), run.EXIT_REFUSED)

    def test_draft_prereg_blocks_a_real_run(self):
        self.assertEqual(self.real("base", extra=("--real",)), run.EXIT_REFUSED)

    def test_exploratory_cant_use_an_adapter(self):
        self.assertEqual(self.real("lived", extra=("--real", "--exploratory")), run.EXIT_REFUSED)

    def test_prompt_prefix_only_exploratory(self):
        arm = load_arm("base_bold")
        self.assertTrue(arm.prompt_prefix)
        self.assertEqual(self.real("base_bold", extra=("--real",)), run.EXIT_REFUSED)

    def test_stub_refused_for_real(self):
        self.assertEqual(self.real("base", instruments=("near_errand",), extra=("--real", "--exploratory")), run.EXIT_REFUSED)

    def test_item_override_refused_for_real(self):
        path = self.tmp / "x.jsonl"
        items, _ = travel.generate(travel._mock_write)
        path.write_text("\n".join(json.dumps(item) for item in items))
        self.assertEqual(self.real("base", instruments=("mid_travel",), extra=("--real", "--exploratory", "--items-override", f"mid_travel={path}")), run.EXIT_REFUSED)

    def test_fake_adapter_refused_by_real_backends(self):
        from benchmarks.backends.api import APIBackend
        with self.assertRaisesRegex(ValueError, "fake"):
            APIBackend("http://127.0.0.1:1/v1").prepare_arm(load_arm("fake_lived"), 0)

    def test_api_refuses_an_adapter_it_cant_name(self):
        """Otherwise the base model would answer under the adapter arm's label."""
        from benchmarks.backends.api import APIBackend
        arm = load_arm("lived")
        arm.api_model = None
        with self.assertRaisesRegex(ValueError, "no api_model"):
            APIBackend("http://127.0.0.1:1/v1").prepare_arm(arm, 0)

    def test_llm_model_backend_refuses_adapters(self):
        from benchmarks.backends.llm_model_backend import LLMModelBackend
        backend = LLMModelBackend.__new__(LLMModelBackend)
        with self.assertRaisesRegex(ValueError, "base model"):
            backend.prepare_arm(load_arm("lived"), 0)


class LLMBackendSampling(Temp):
    def make(self, config):
        from benchmarks.backends.llm_model_backend import LLMModelBackend
        backend = LLMModelBackend.__new__(LLMModelBackend)
        backend.weights = self.tmp
        (self.tmp / "generation_config.json").write_text(json.dumps(config))
        return backend

    def test_records_the_checkpoint_values(self):
        effective = self.make({"top_p": 0.8, "top_k": 20, "repetition_penalty": 1.0}).effective_sampling({"temperature": 0.7, "top_p": 0.8, "top_k": 20, "max_tokens": 8})
        self.assertEqual((effective["top_p"], effective["top_k"]), (0.8, 20))
        self.assertIn("mx.random.seed", effective["seed_method"])

    def test_refuses_a_top_p_it_cant_set(self):
        with self.assertRaisesRegex(ValueError, "can't set top_p"):
            self.make({"top_p": 0.8, "top_k": 20}).effective_sampling({"temperature": 0.7, "top_p": 0.5, "max_tokens": 8})


class PreregGuard(Temp):
    def setUp(self):
        super().setUp()
        self.prereg, self.contrasts, self.lock, self.log = self.tmp / "PREREG.md", self.tmp / "c.yaml", self.tmp / "lock.json", self.tmp / "amend.jsonl"
        self.prereg.write_text("# Plan\nSTATUS: DRAFT\n")
        self.contrasts.write_text("contrasts: []\n")
        self.paths = {"prereg": self.prereg, "contrasts": self.contrasts, "lock_path": self.lock}

    def finalize(self):
        self.prereg.write_text("# Plan\nApproved.\n")
        prereg.lock(self.prereg, self.contrasts, self.lock)

    def check(self, reason=None):
        return prereg.check(reason, amendments=self.log, **self.paths)

    def test_draft_refuses(self):
        with self.assertRaisesRegex(prereg.PreregError, "DRAFT"):
            self.check()

    def test_draft_cant_be_locked(self):
        with self.assertRaisesRegex(prereg.PreregError, "DRAFT"):
            prereg.lock(self.prereg, self.contrasts, self.lock)

    def test_unlocked_refuses(self):
        self.prereg.write_text("Approved.\n")
        with self.assertRaisesRegex(prereg.PreregError, "No lock"):
            self.check()

    def test_unchanged_passes(self):
        self.finalize()
        self.assertFalse(self.check()["amended"])

    def test_changed_prereg_refuses(self):
        self.finalize()
        self.prereg.write_text("# Plan\nApproved, with a tweak.\n")
        with self.assertRaisesRegex(prereg.PreregError, "changed after"):
            self.check()

    def test_changed_contrasts_refuses(self):
        self.finalize()
        self.contrasts.write_text("contrasts: [changed]\n")
        with self.assertRaisesRegex(prereg.PreregError, "changed after"):
            self.check()

    def test_amendment_is_logged_and_then_passes(self):
        self.finalize()
        self.prereg.write_text("# Plan\nApproved, with a tweak.\n")
        result = self.check("Fixed a typo")
        self.assertTrue(result["amended"])
        entry = json.loads(self.log.read_text().splitlines()[0])
        self.assertEqual(entry["reason"], "Fixed a typo")
        self.assertNotEqual(entry["from"]["prereg_sha256"], entry["to"]["prereg_sha256"])
        self.assertFalse(self.check()["amended"])

    def test_second_lock_refuses(self):
        self.finalize()
        with self.assertRaisesRegex(prereg.PreregError, "already exists"):
            prereg.lock(self.prereg, self.contrasts, self.lock)

    def test_real_prereg_is_still_a_draft(self):
        self.assertIn(prereg.DRAFT_MARK, prereg.PREREG.read_text())
        self.assertFalse(prereg.LOCK.exists())


class Freezing(Temp):
    def setUp(self):
        super().setUp()
        self.draft, self.target, self.manifest = self.tmp / "draft.jsonl", self.tmp / "items" / "v1.jsonl", self.tmp / "frozen.json"
        self.draft.write_text('{"id": "throwaway"}\n')

    def test_freeze_records_the_hash_and_verifies(self):
        digest = freeze.freeze("x", self.draft, self.target, self.manifest)
        self.assertEqual(len(digest), 64)
        self.assertEqual(freeze.verify(self.manifest), [])

    def test_never_refreezes(self):
        freeze.freeze("x", self.draft, self.target, self.manifest)
        with self.assertRaisesRegex(freeze.FreezeError, "never regenerated"):
            freeze.freeze("x", self.draft, self.target, self.manifest)

    def test_edit_is_detected(self):
        freeze.freeze("x", self.draft, self.target, self.manifest)
        self.target.write_text('{"id": "edited"}\n')
        self.assertIn("changed", freeze.verify(self.manifest)[0])

    def test_nothing_real_has_been_frozen(self):
        self.assertFalse(freeze.MANIFEST.exists())
        self.assertFalse(freeze.FROZEN_FILES["mid_travel"].exists())

    def test_generator_refuses_the_frozen_name(self):
        with mock.patch.object(sys, "argv", ["generate", "--backend", "mock", "--out", str(self.tmp / "mid_travel_v1.jsonl")]), self.assertRaises(SystemExit):
            travel.main()

    def test_generator_refuses_to_overwrite(self):
        with mock.patch.object(sys, "argv", ["generate", "--backend", "mock", "--out", str(self.draft)]), self.assertRaises(SystemExit):
            travel.main()

    def test_generator_writes_a_throwaway_marked_file(self):
        out = self.tmp / "evals_items.jsonl"
        with mock.patch.object(sys, "argv", ["generate", "--backend", "mock", "--out", str(out)]):
            travel.main()
        meta = json.loads(out.read_text().splitlines()[0])["_meta"]
        self.assertIn("THROWAWAY", meta["writer_model"])
        self.assertFalse(meta["verified"])


class Leakage(Temp):
    PROMPT = "Option A: 80% chance of winning four dollars. Option B: three dollars for certain, with no chance of nothing."

    def test_clean(self):
        self.assertEqual(leakage.check_texts({"item": self.PROMPT}, {"diary": "Today the weather was mild, and I bought some bread at the shop on the corner."}), [])

    def test_copied_item_fails(self):
        hits = leakage.check_texts({"item": self.PROMPT}, {"diary": "Long ago. " + self.PROMPT + " Then I went home."})
        self.assertIn("ngram_overlap", {hit["check"] for hit in hits})

    def test_lightly_edited_item_is_a_near_duplicate(self):
        edited = self.PROMPT.replace("winning", "getting").replace("certain", "sure").replace("Option", "Choice")
        hits = leakage.check_texts({"item": self.PROMPT}, {"lesson": edited})
        self.assertIn("near_duplicate", {hit["check"] for hit in hits})

    def test_known_limit_a_true_paraphrase_gets_through(self):
        """The default embedder is lexical. This pins that limit, so nobody assumes the check is stronger than it is."""
        paraphrase = "You could pick a sure three dollars, or take a gamble with an eighty percent shot at four dollars."
        self.assertEqual(leakage.check_texts({"item": self.PROMPT}, {"lesson": paraphrase}), [])

    def test_a_copy_in_a_long_text_isnt_diluted(self):
        filler = " ".join(f"word{i}" for i in range(5000))
        hits = leakage.check_texts({"item": self.PROMPT}, {"diary": filler + " " + self.PROMPT + " " + filler})
        self.assertTrue(hits)

    def test_a_custom_embedder_can_be_used(self):
        import numpy as np
        hits = leakage.check_texts({"item": "aaa bbb"}, {"src": "ccc ddd"}, embed=lambda texts: np.ones((len(texts), 4)) / 2)
        self.assertEqual(hits[0]["check"], "near_duplicate")

    def test_real_prompts_dont_trip_on_innocent_text(self):
        hits = leakage.check_texts(leakage.rendered_prompts([HoltLaury(), Lotteries()]), {"diary": "I walked to the market and it rained. The bread was warm and the shopkeeper smiled at me as I left."})
        self.assertEqual(hits, [])

    def _arm_with_training(self, text):
        training = self.tmp / "training.txt"
        training.write_text(text)
        arm = load_arm("fake_lived")
        arm.training_text = [str(training)]
        return arm

    def test_planted_leak_fails_the_gate(self):
        hl = HoltLaury()
        leaked = hl.build_prompt(hl.items[0], "percent", ["safe", "risky"])
        hits, _ = leakage.check_arms([self._arm_with_training("Earlier I saw this: " + leaked)], [0], [hl])
        self.assertTrue(hits)
        self.assertEqual(hits[0]["arm"], "fake_lived")

    def test_planted_leak_stops_a_run_loudly(self):
        hl = HoltLaury()
        arm = self._arm_with_training(hl.build_prompt(hl.items[0], "percent", ["safe", "risky"]))
        with mock.patch("benchmarks.run.load_arm", return_value=arm):
            self.assertEqual(self.run_mock(arms=("fake_lived",)), run.EXIT_LEAK)
        self.assertFalse((self.out / "results.jsonl").exists())

    def test_jsonl_training_text_is_read(self):
        path = self.tmp / "t.jsonl"
        path.write_text(json.dumps({"messages": [{"role": "user", "content": "hello there"}]}) + "\n")
        self.assertIn("hello there", leakage.read_training_text(path))

    def test_missing_training_files_are_reported(self):
        files, missing = leakage.training_files(load_arm("lived"), 0)
        self.assertEqual(files, [])
        self.assertTrue(missing)


class Guardrails(Temp):
    """The reader runs on trimmed real output from lm-eval, so it can't drift from the harness's actual format."""

    def test_reads_real_ifeval_output(self):
        rows = IFEval().read_samples(FIXTURES / "lm_eval_real")
        self.assertEqual(len(rows), 3)
        self.assertTrue(rows[0][0].startswith("ifeval"))
        self.assertTrue(all(points in (0.0, 100.0) for _, points, _ in rows))

    def test_reads_real_mmlu_output(self):
        guardrail = MMLU()
        rows = guardrail.read_samples(FIXTURES / "lm_eval_real_mmlu")
        self.assertEqual(len(rows), 3)
        self.assertIn("mmlu_abstract_algebra_generative", rows[0][0])

    def test_missing_output_is_loud(self):
        with self.assertRaises(FileNotFoundError):
            IFEval().read_samples(self.tmp)

    def test_command_targets_the_endpoint(self):
        command = MMLU().command("http://x/v1", "lived_seed0", self.tmp)
        joined = " ".join(command)
        self.assertIn("base_url=http://x/v1/chat/completions,model=lived_seed0", joined)
        self.assertIn("--limit 6", joined)
        self.assertIn("--log_samples", joined)

    def test_mock_shift_shows_up(self):
        arm = load_arm("fake_base")
        arm.mock = {"guardrail_shift_points": 20.0}
        from benchmarks.backends.mock import MockBackend as M
        shifted = IFEval().run_harness(arm, 0, M(), self.tmp)
        arm.mock = {}
        arm.name = "other"
        plain = IFEval().run_harness(arm, 0, M(), self.tmp)
        mean = lambda rows: sum(r[1] for r in rows) / len(rows)
        self.assertGreater(mean(shifted), mean(plain) + 5)


class VLLMWithFakeLibrary(Temp):
    """vLLM isn't installed here, so this fake only checks that our calls are shaped as intended, not that vLLM accepts them."""

    def setUp(self):
        super().setUp()
        self.calls = []
        test = self
        class FakeLLM:
            def __init__(self, **kwargs):
                test.llm_kwargs = kwargs
            def generate(self, prompts, params, lora_request=None, use_tqdm=False):
                test.calls.append((prompts, params, lora_request))
                return [types.SimpleNamespace(outputs=[types.SimpleNamespace(text=' {"choice": "A"} ')]) for _ in prompts]
        class FakeTokenizer:
            def apply_chat_template(self, messages, tokenize, add_generation_prompt):
                return "<chat>" + messages[0]["content"]
        vllm = types.ModuleType("vllm")
        vllm.LLM = FakeLLM
        vllm.SamplingParams = lambda **kwargs: kwargs
        lora = types.ModuleType("vllm.lora")
        request = types.ModuleType("vllm.lora.request")
        request.LoRARequest = lambda **kwargs: kwargs
        transformers = types.ModuleType("transformers")
        transformers.AutoTokenizer = types.SimpleNamespace(from_pretrained=lambda name: FakeTokenizer())
        patcher = mock.patch.dict(sys.modules, {"vllm": vllm, "vllm.lora": lora, "vllm.lora.request": request, "transformers": transformers})
        patcher.start()
        self.addCleanup(patcher.stop)
        from benchmarks.backends.vllm import VLLMBackend
        self.backend = VLLMBackend(model="Qwen/x")

    def adapter(self):
        folder = self.tmp / "adapter_seed0"
        folder.mkdir(exist_ok=True)
        (folder / "adapter_config.json").write_text("{}")
        (folder / "adapter_model.safetensors").write_bytes(b"weights")
        arm = load_arm("lived")
        arm.adapter = str(self.tmp / "adapter_seed{seed}")
        return arm

    def request(self):
        return GenRequest("prompt", {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "max_tokens": 16}, seed=2**40)

    def test_lora_turned_on_at_load(self):
        self.assertTrue(self.llm_kwargs["enable_lora"])

    def test_adapter_is_sent_with_each_request_and_base_sends_none(self):
        info = self.backend.prepare_arm(self.adapter(), 0)
        self.assertEqual(len(info["adapter_hash"]), 64)
        self.backend.generate_batch([self.request()])
        self.assertIn("adapter_seed0", self.calls[0][2]["lora_path"])
        self.backend.prepare_arm(load_arm("base"), 0)
        self.backend.generate_batch([self.request()])
        self.assertIsNone(self.calls[1][2])

    def test_sampling_params_and_chat_template(self):
        self.backend.prepare_arm(load_arm("base"), 0)
        result = self.backend.generate_batch([self.request()])
        prompts, params, _ = self.calls[0]
        self.assertEqual(prompts[0], "<chat>prompt")
        self.assertEqual(params[0]["top_p"], 0.8)
        self.assertLess(params[0]["seed"], 2**31)
        self.assertEqual(result[0].text, '{"choice": "A"}')

    def test_refuses_unconverted_adapter(self):
        arm = self.adapter()
        (self.tmp / "adapter_seed0" / "adapter_config.json").unlink()
        with self.assertRaisesRegex(FileNotFoundError, "PEFT"):
            self.backend.prepare_arm(arm, 0)

    def test_refuses_fake_adapter(self):
        with self.assertRaisesRegex(ValueError, "fake"):
            self.backend.prepare_arm(load_arm("fake_lived"), 0)


class Adapters(unittest.TestCase):
    def test_marker(self):
        self.assertEqual(read_fake_marker(load_arm("fake_lived").adapter_for(0))["risk_tilt"], 0.5)
        self.assertIsNone(read_fake_marker(None))

    def test_seed_in_path(self):
        self.assertTrue(load_arm("lived").adapter_for(3).endswith("out/adapters/lived/seed3"))

    def test_no_weights_means_no_hash(self):
        self.assertIsNone(adapter_hash(load_arm("fake_lived").adapter_for(0)))


class Registry(unittest.TestCase):
    def test_all_real_arms_load(self):
        for name in ("base", "lived", "described", "shuffled", "flipped_lived", "rendered_lived"):
            self.assertEqual(load_arm(name).name, name)

    def test_norms_verified_or_absent(self):
        self.assertTrue(all(norm["verified"] for norm in load_norms("holt_laury")["norms"]))
        self.assertIsNone(load_norms("mid_travel"))

    def test_a_new_instrument_needs_only_a_config_entry_and_a_class(self):
        entries = {"holt_laury": {"class": "benchmarks.lotteries:Lotteries"}}
        with mock.patch("benchmarks.registry.instrument_entries", return_value=entries):
            self.assertIsInstance(load_instrument("holt_laury"), Lotteries)


class NoiseCheck(Temp):
    def test_mock_spread_is_usable(self):
        self.run_mock(arms=("base",), instruments=("holt_laury", "lotteries"), samples=30)
        summary = noise_check.analyze(self.out)
        self.assertEqual(summary["holt_laury_verdict"].split(":")[0], "USABLE SPREAD")
        self.assertEqual(summary["n_results"], 90 + 540)

    def _frame(self, modal, switching):
        return pd.DataFrame([{"modal_share": modal, "multiple_switching": switching}] * 3)

    def test_identical_answers_say_so(self):
        self.assertTrue(noise_check.verdict_holt_laury(self._frame(1.0, 0.0)).startswith("NEAR-IDENTICAL"))

    def test_noise_says_so(self):
        self.assertTrue(noise_check.verdict_holt_laury(self._frame(0.1, 0.9)).startswith("PURE NOISE"))

    def test_floor_says_so(self):
        table = pd.DataFrame([{"modal_share": 0.85, "multiple_switching": 0.0, "at_floor_0_safe": 0.85, "at_ceiling_10_safe": 0.0}] * 3)
        self.assertTrue(noise_check.verdict_holt_laury(table).startswith("FLOOR"))

    def test_rows_pilot_runs_end_to_end_and_gives_a_curve(self):
        self.run_mock(instruments=("holt_laury_rows",), samples=20)
        curves = noise_check.analyze(self.out)["holt_laury_rows"]
        self.assertEqual(len(curves), 6)
        pooled = lambda row: [c["safe_rate_by_row"][row] for c in curves if c["safe_rate_by_row"][row] is not None]
        self.assertGreater(sum(pooled(1)) / len(pooled(1)), sum(pooled(10)) / len(pooled(10)))

    def test_verdicts_ignore_persona_controls(self):
        """Fake arms are ignored here too: a folder with no plain base arm has nothing to give a verdict on."""
        self.run_mock(arms=("fake_base",), instruments=("holt_laury",), samples=5)
        self.assertEqual(noise_check.analyze(self.out)["holt_laury_verdict"], "NOT MEASURED")

    def test_position_comes_before_floor(self):
        """The real base model's pattern: 0 safe choices, but only because it picks A on every row."""
        table = pd.DataFrame([{"modal_share": 0.6, "multiple_switching": 0.0, "at_floor_0_safe": 0.6, "at_ceiling_10_safe": 0.0, "position_gap": 8.5}] * 3)
        self.assertTrue(noise_check.verdict_holt_laury(table).startswith("POSITION BIAS"))

    def test_empty_says_not_measured(self):
        self.assertEqual(noise_check.verdict_holt_laury(pd.DataFrame()), "NOT MEASURED")

    def test_position_bias_says_so(self):
        table = pd.DataFrame([{"underweighting_rate": 0.5, "chose_listed_first": 0.95}] * 3)
        self.assertTrue(noise_check.verdict_lotteries(table).startswith("POSITION BIAS"))


if __name__ == "__main__":
    unittest.main()
