"""Guardrails: standard ML benchmarks that should NOT move. We wrap lm-evaluation-harness rather than reimplement it.

The harness runs on its own against an OpenAI-style server, so this code builds its command, runs it, and copies its
per-question scores into our results format. Scores are in points (0 to 100) so "within 1 point of base" reads directly.

The mock backend writes files in the harness's real output format and sends them through the same reader.
tests/fixtures/lm_eval_samples_*.jsonl hold trimmed real output from lm-eval, to keep that reader honest.
"""
import glob
import json
import os
import random
import shutil
from pathlib import Path

from benchmarks.core import Instrument, stable_int

LM_EVAL_ENV = "EVALS_LM_EVAL"


class Guardrail(Instrument):
    kind = "harness"
    far_or_mid = False
    templates = ("harness",)
    tasks = ()
    limit = None            # Questions per task. None means all.
    metric_key = ""
    mock_rate = 0.7
    mock_questions = 200    # About as many as the real task, so mock intervals are a fair size.

    def load_items(self):
        meta = {"verified": True, "items": "Owned by lm-evaluation-harness. Its results file records the dataset hashes.",
                "tasks": list(self.tasks), "limit": self.limit, "metric": self.metric_key}
        return meta, []

    def command(self, base_url, model, out_dir):
        """The exact command line. The dry run prints this same list."""
        command = [
            os.environ.get(LM_EVAL_ENV) or "lm-eval", "run",
            "--model", "local-chat-completions",
            "--model_args", f"base_url={base_url.rstrip('/')}/chat/completions,model={model},num_concurrent=1,max_retries=3,tokenized_requests=False",
            "--tasks", *self.tasks,
            "--apply_chat_template", "--log_samples", "--seed", "0",
            "--output_path", str(out_dir),
        ]
        if self.limit:
            command += ["--limit", str(self.limit)]
        return command

    def read_samples(self, out_dir):
        """Read every samples_*.jsonl below out_dir into [(item id, score in points, raw output)]."""
        rows = []
        for path in sorted(glob.glob(str(Path(out_dir) / "**" / "samples_*.jsonl"), recursive=True)):
            task = Path(path).name.split("samples_")[1].rsplit("_", 1)[0]
            for line in Path(path).read_text().splitlines():
                record = json.loads(line)
                if self.metric_key not in record:
                    raise ValueError(f"{path} has no {self.metric_key}. Keys: {sorted(record)}")
                raw = record.get("filtered_resps") or [""]
                rows.append((f"{task}:{record['doc_id']}", float(record[self.metric_key]) * 100, str(raw[0])))
        if not rows:
            raise FileNotFoundError(f"No samples_*.jsonl found under {out_dir}")
        return rows

    def _write_mock_samples(self, out_dir, arm, seed, shift_points):
        """Write fake results in the harness's real file format."""
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        rng = random.Random(stable_int("mock_guardrail", self.name, arm.name, seed))
        rate = self.mock_rate + shift_points / 100
        path = Path(out_dir) / f"samples_{self.tasks[0]}_2000-01-01T00-00-00.jsonl"
        with path.open("w") as file:
            for doc_id in range(self.mock_questions):
                correct = rng.random() < rate
                file.write(json.dumps({"doc_id": doc_id, "filtered_resps": ["mock"], self.metric_key: float(correct)}) + "\n")

    def run_harness(self, arm, seed, backend, out_dir):
        """Run the harness for one arm and seed, and return [(item id, points, raw output)]."""
        out_dir = Path(out_dir) / "lm_eval" / self.name / f"{arm.name}_seed{seed}"
        if not backend.is_real:
            self._write_mock_samples(out_dir, arm, seed, (arm.mock or {}).get("guardrail_shift_points", 0.0))
            return self.read_samples(out_dir)

        program = self.command("http://unused", "unused", out_dir)[0]
        if not shutil.which(program):
            raise FileNotFoundError(f"Can't find {program}. Install lm-eval[api,ifeval] in a separate venv and set {LM_EVAL_ENV} to its lm-eval path.")
        backend.run_harness_command(arm, lambda base_url, model: self.command(base_url, model, out_dir))
        return self.read_samples(out_dir)

    def score(self, parsed, item, order):
        raise NotImplementedError("Guardrails are scored by the harness.")


class IFEval(Guardrail):
    name = "ifeval"
    metric = "ifeval_points"
    higher_means = "follows instructions better"
    tasks = ("ifeval",)
    metric_key = "prompt_level_strict_acc"
    mock_rate = 0.75
    mock_questions = 541


class MMLU(Guardrail):
    name = "mmlu"
    metric = "mmlu_points"
    higher_means = "knows more"
    # The generative version, because a chat endpoint can't score multiple-choice log-likelihoods.
    # 57 subjects at 6 questions each gives 342 questions.
    tasks = ("mmlu_generative",)
    limit = 6
    metric_key = "exact_match"
    mock_rate = 0.65
    mock_questions = 342
