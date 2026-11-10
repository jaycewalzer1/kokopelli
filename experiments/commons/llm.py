"""The model behind the agents, with retries and a spending limit that stops calls before they go over it."""
import json
import os
import sys
import time
from pathlib import Path


class BudgetExhausted(RuntimeError):
    pass


class Budget:
    """Spend so far, kept in a file replaced atomically so a crash can't lose or tear it."""

    def __init__(self, path, limit, input_price=0.0, output_price=0.0):
        self.path, self.limit, self.input_price, self.output_price = Path(path), limit, input_price, output_price
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {"usd": 0.0, "calls": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0}

    def cost(self, input_tokens, output_tokens):
        return (input_tokens * self.input_price + output_tokens * self.output_price) / 1e6

    def require(self, input_tokens, output_tokens):
        """Refuse a call whose worst-case cost would pass the limit."""
        if self.state["usd"] + self.cost(input_tokens, output_tokens) > self.limit:
            raise BudgetExhausted(f"${self.state['usd']:.2f} spent of ${self.limit:.2f}")

    def add(self, calls, input_tokens, output_tokens, seconds):
        self.state["usd"] += self.cost(input_tokens, output_tokens)
        self.state["calls"] += calls
        self.state["input_tokens"] += input_tokens
        self.state["output_tokens"] += output_tokens
        self.state["seconds"] += seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state))
        os.replace(temporary, self.path)


class MlxModel:
    """Qwen through mlx_vlm. Asks that happen at the same moment in the game go in one batch."""

    def __init__(self, config, budget, log=print):
        self.config, self.budget, self.log = config["llm"], budget, log
        self.loaded = None

    def _load(self):
        if self.loaded is None:
            from mlx_vlm import load
            self.loaded = load(self.config["weights"])
        return self.loaded

    def count(self, text):
        return len(self._load()[1].tokenizer.encode(text))

    def ask(self, requests, max_tokens, seed):
        """requests is a list of (system, user). Returns one text per request, in order."""
        import mlx.core as mx
        from mlx_vlm.prompt_utils import apply_chat_template
        from mlx_vlm.sample_utils import make_sampler
        model, processor = self._load()
        batch_generate = sys.modules["mlx_vlm.generate"].batch_generate  # the package exports a function with the module's name
        prompts = [apply_chat_template(processor, model.config, [{"role": "system", "content": s}, {"role": "user", "content": u}]) for s, u in requests]
        input_tokens = sum(self.count(p) for p in prompts)
        self.budget.require(input_tokens, max_tokens * len(prompts))
        for attempt in range(self.config["attempts"]):
            try:
                started = time.monotonic()
                mx.random.seed(seed)
                result = batch_generate(model, processor, prompts=prompts, max_tokens=max_tokens, sampler=make_sampler(temp=self.config["temperature"], top_p=self.config["top_p"]))
                output_tokens = sum(self.count(t) for t in result.texts)
                self.budget.add(len(prompts), input_tokens, output_tokens, time.monotonic() - started)
                return [t.strip() for t in result.texts]
            except Exception as error:  # the runtime raises several unrelated types when memory runs short
                if attempt == self.config["attempts"] - 1:
                    raise
                wait = self.config["backoff_seconds"] * 2 ** attempt
                self.log(f"llm: attempt {attempt + 1} failed ({error}); waiting {wait}s")
                time.sleep(wait)
