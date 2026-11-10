"""Check that eval prompts didn't leak into training text.

If an eval item, or something close to it, appears in what an arm trained on, a shift on that item could just be
memorization. Two checks run, and either failure stops the run loudly:

1. Word n-gram overlap. An n-gram is a run of n consecutive words. We ask what share of an item's 5-word runs appear
   anywhere in the training text. This catches copying.
2. Near-duplicate similarity. Each text becomes a vector and we compare vectors by cosine similarity (1.0 = same
   direction). The default "embedding" just counts hashed character 3-grams, which catches light edits and rewordings
   that reuse most of the words. It does NOT understand meaning, so a true paraphrase with new words gets through.
   Pass a real embedder as `embed` to catch those (see HANDOFF.md).
"""
import argparse
import glob
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np

from experiments.benchmarks.core import REPO

NGRAM = 5
OVERLAP_LIMIT = 0.20    # Share of an item's n-grams found in training.
# Measured on a lottery sentence: unrelated text 0.05, a true paraphrase 0.36, a 3-word edit 0.76, a 1-word edit 0.96.
COSINE_LIMIT = 0.70
_DIMENSIONS = 2**14
_WORD = re.compile(r"[a-z0-9$.%]+")


class LeakageError(RuntimeError):
    pass


def words(text):
    return _WORD.findall(text.lower())


def ngrams(text, n=NGRAM):
    tokens = words(text)
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def char_hash_embed(texts):
    """A simple lexical vector per text: counts of hashed character 3-grams, scaled to length 1."""
    vectors = np.zeros((len(texts), _DIMENSIONS), dtype=np.float32)
    for row, text in enumerate(texts):
        clean = " ".join(words(text))
        for i in range(len(clean) - 2):
            bucket = int.from_bytes(hashlib.md5(clean[i:i + 3].encode()).digest()[:4], "big") % _DIMENSIONS
            vectors[row, bucket] += 1
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


def _chunks(text, size=80, step=40):
    """Split training text into overlapping windows, so one matching passage isn't diluted by a whole long diary."""
    tokens = words(text)
    if len(tokens) <= size:
        return [" ".join(tokens)] if tokens else []
    return [" ".join(tokens[i:i + size]) for i in range(0, len(tokens) - size + step, step)]


def check_texts(eval_texts, training_texts, overlap_limit=OVERLAP_LIMIT, cosine_limit=COSINE_LIMIT, embed=char_hash_embed):
    """Compare {eval id: text} with {training source: text}. Returns a list of hits. An empty list means clean."""
    hits = []
    training_grams = {source: ngrams(text) for source, text in training_texts.items()}
    chunks = [(source, chunk) for source, text in training_texts.items() for chunk in _chunks(text)]
    chunk_vectors = embed([chunk for _, chunk in chunks]) if chunks else None
    eval_ids = list(eval_texts)
    eval_vectors = embed([eval_texts[i] for i in eval_ids]) if chunks and eval_ids else None

    for row, eval_id in enumerate(eval_ids):
        grams = ngrams(eval_texts[eval_id])
        for source, seen in training_grams.items():
            if grams:
                overlap = len(grams & seen) / len(grams)
                if overlap >= overlap_limit:
                    hits.append({"eval_id": eval_id, "source": source, "check": "ngram_overlap", "value": round(overlap, 3)})
        if chunk_vectors is not None:
            similarity = chunk_vectors @ eval_vectors[row]
            best = int(np.argmax(similarity))
            if similarity[best] >= cosine_limit:
                hits.append({"eval_id": eval_id, "source": chunks[best][0], "check": "near_duplicate", "value": round(float(similarity[best]), 3)})
    return hits


def rendered_prompts(instruments):
    """Every prompt each prompt-based instrument can produce, in both option orders."""
    prompts = {}
    for instrument in instruments:
        if instrument.kind != "prompt":
            continue
        for item in instrument.items:
            for template in instrument.templates:
                for order in (list(instrument.options), list(reversed(instrument.options))):
                    key = f"{instrument.name}/{instrument.item_id(item)}/{template}/{','.join(order)}"
                    prompts[key] = instrument.build_prompt(item, template, order)
    return prompts


def read_training_text(path):
    """Text from a .txt, .md or .jsonl file. For JSONL, all string values are joined."""
    path = Path(path)
    if path.suffix == ".jsonl":
        parts = []
        for line in path.read_text().splitlines():
            if line.strip():
                record = json.loads(line)
                parts.extend(_strings(record))
        return "\n".join(parts)
    return path.read_text()


def _strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for child in value.values() for text in _strings(child)]
    if isinstance(value, list):
        return [text for child in value for text in _strings(child)]
    return []


def training_files(arm, seed):
    """Files an arm's config points to. Returns (files found, patterns that matched nothing)."""
    found, missing = [], []
    for pattern in arm.training_text:
        pattern = pattern.format(seed=seed)
        full = pattern if Path(pattern).is_absolute() else str(REPO / pattern)
        matches = [path for path in sorted(glob.glob(full)) if Path(path).is_file()]
        found.extend(matches)
        if not matches:
            missing.append(pattern)
    return found, missing


def check_arms(arms, seeds, instruments, **limits):
    """Run the check for every arm and seed. Returns (hits, patterns with no files)."""
    prompts = rendered_prompts(instruments)
    hits, missing_patterns = [], []
    for arm in arms:
        for seed in seeds:
            files, missing = training_files(arm, seed)
            missing_patterns.extend(f"{arm.name}: {pattern}" for pattern in missing)
            for hit in check_texts(prompts, {path: read_training_text(path) for path in files}, **limits):
                hits.append({"arm": arm.name, "seed": seed, **hit})
    return hits, missing_patterns


def main():
    from experiments.benchmarks.registry import load_arm, load_instrument
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--arms", nargs="+", required=True)
    parser.add_argument("--instruments", nargs="+", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[0])
    args = parser.parse_args()
    hits, missing = check_arms([load_arm(a) for a in args.arms], args.seeds, [load_instrument(i) for i in args.instruments])
    for pattern in missing:
        print(f"WARNING: no training text found for {pattern}", file=sys.stderr)
    if hits:
        print(json.dumps(hits, indent=2))
        print(f"LEAKAGE: {len(hits)} eval prompts overlap training text.", file=sys.stderr)
        sys.exit(3)
    print("No leakage found.")


if __name__ == "__main__":
    main()
