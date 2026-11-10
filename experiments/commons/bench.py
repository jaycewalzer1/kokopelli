"""Throughput of batched Qwen at game-sized prompts: seconds per call for batch 1 and 7."""
import json
import sys
import time
from pathlib import Path

import llm
import sim

out = Path(sys.argv[1])
config = sim.load_config()
budget = llm.Budget(out.parent / "bench_spend.json", 50)
model = llm.MlxModel(config, budget)
filler = "The village keeps its nets by the north shore and the road runs past the mill and the old bridge. "
rows = []
for size in (1, 7):
    for repeats, tokens in ((10, 60), (18, 60), (18, 110)):
        reqs = [("Reply with one JSON object only.", f"Person {i}. " + filler * (repeats + i) + 'Say something short. Reply as {"say": "..."}') for i in range(size)]
        start = time.monotonic()
        texts = model.ask(reqs, tokens, 1)
        rows.append({"batch": size, "input_tokens_each": model.count(reqs[0][1]), "max_tokens": tokens, "seconds": time.monotonic() - start, "sample": texts[-1][:120], "distinct": len(set(texts))})
        print(rows[-1], flush=True)
out.write_text(json.dumps({"model": config["llm"]["weights"], "rows": rows}, indent=1))
