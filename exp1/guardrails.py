"""After a life: did training hurt general ability? Base model vs the trained adapter, on the same questions.

Both checks run in process with the policy's own model, toggling the adapter off for the base. They're paired (same
questions both ways), so the difference is much less noisy than either score.
    mmlu     a fixed random subset of MMLU test questions, scored by which answer letter gets the most probability
    ifeval   a fixed subset of IFEval prompts, keeping only prompts whose every instruction type is verified below; strict
             prompt-level accuracy (all instructions followed). These verifiers are ours, written from IFEval's rules, so
             the score is for this before/after comparison only and isn't comparable to published IFEval numbers.
A check is flagged when the adapter scores more than 1 point (of 100) below base.

lm-evaluation-harness (benchmarks/guardrails in the evals worktree) is the proper version; it needs lm-eval and a server,
neither of which this Mac has set up.
"""
import json
import re

import mlx.core as mx
import numpy as np

FLAG_POINTS = 1.0
LETTERS = "ABCD"


# ----- MMLU -----
def mmlu_items(n, seed=0):
    from datasets import load_dataset
    data = load_dataset("cais/mmlu", "all", split="test")
    picks = np.random.default_rng(seed).choice(len(data), size=n, replace=False)
    return [data[int(k)] for k in sorted(picks)]


def _mmlu_prompt(item):
    choices = "\n".join(f"{letter}. {text}" for letter, text in zip(LETTERS, item["choices"]))
    return (f"The following is a multiple choice question about {item['subject'].replace('_', ' ')}.\n\n"
            f"{item['question']}\n{choices}\n\nAnswer with the letter only.")


def mmlu_correct(policy, items):
    from mlx_vlm.prompt_utils import apply_chat_template
    letter_ids = [policy.tokenizer.encode(letter, add_special_tokens=False)[0] for letter in LETTERS]
    out = []
    for item in items:
        text = apply_chat_template(policy.processor, policy.model.config, [{"role": "user", "content": _mmlu_prompt(item)}])
        ids = mx.array([policy.tokenizer.encode(text, add_special_tokens=False)])
        output = policy.model(ids, None, mx.ones_like(ids))
        logits = getattr(output, "logits", output)[0, -1]
        out.append(int(np.argmax(np.array(logits[mx.array(letter_ids)].astype(mx.float32)))) == item["answer"])
    return out


# ----- IFEval -----
def _words(text):
    return re.findall(r"\b\w+\b", text)


def _compare(count, relation, target):
    return count < target if relation == "less than" else count >= target


def _strip_fence(text):
    text = text.strip()
    text = re.sub(r"^```(json|JSON)?\s*", "", text)
    return re.sub(r"\s*```$", "", text)


def _is_json(text):
    try:
        json.loads(_strip_fence(text))
        return True
    except ValueError:
        return False


CHECKS = {
    "punctuation:no_comma": lambda r, k: "," not in r,
    "change_case:english_lowercase": lambda r, k: r == r.lower() and r.strip() != "",
    "change_case:english_capital": lambda r, k: r == r.upper() and r.strip() != "",
    "change_case:capital_word_frequency": lambda r, k: _compare(len([w for w in _words(r) if w.isupper()]), k["capital_relation"], k["capital_frequency"]),
    "length_constraints:number_words": lambda r, k: _compare(len(_words(r)), k["relation"], k["num_words"]),
    "length_constraints:number_paragraphs": lambda r, k: len([p for p in re.split(r"\s?\*\*\*\s?", r) if p.strip()]) == k["num_paragraphs"],
    "detectable_format:number_highlighted_sections": lambda r, k: len(re.findall(r"\*[^\n\*]+\*", r)) >= k["num_highlights"],
    "detectable_format:number_bullet_lists": lambda r, k: len(re.findall(r"^\s*[\*\-]\s+\S", r, re.M)) == k["num_bullets"],
    "detectable_format:title": lambda r, k: bool(re.search(r"<<[^\n]+>>", r)),
    "detectable_format:json_format": lambda r, k: _is_json(r),
    "detectable_content:postscript": lambda r, k: bool(re.search(r"\s*" + re.escape(k["postscript_marker"].lower()) + r".*$", r.lower(), re.M)),
    "detectable_content:number_placeholders": lambda r, k: len(re.findall(r"\[.*?\]", r)) >= k["num_placeholders"],
    "startend:quotation": lambda r, k: len(r.strip()) > 1 and r.strip()[0] == '"' and r.strip()[-1] == '"',
    "startend:end_checker": lambda r, k: r.strip().lower().endswith(k["end_phrase"].strip().lower()),
    "keywords:existence": lambda r, k: all(re.search(re.escape(word), r, re.I) for word in k["keywords"]),
    "keywords:forbidden_words": lambda r, k: not any(re.search(r"\b" + re.escape(word) + r"\b", r, re.I) for word in k["forbidden_words"]),
    "keywords:frequency": lambda r, k: _compare(len(re.findall(r"\b" + re.escape(k["keyword"]) + r"\b", r, re.I)), k["relation"], k["frequency"]),
    "keywords:letter_frequency": lambda r, k: _compare(r.lower().count(k["letter"].lower()), k["let_relation"], k["let_frequency"]),
    "combination:repeat_prompt": lambda r, k: r.strip().lower().startswith(k["prompt_to_repeat"].strip().lower()),
}


def ifeval_items(n, seed=0):
    from datasets import load_dataset
    data = [row for row in load_dataset("google/IFEval", split="train") if all(i in CHECKS for i in row["instruction_id_list"])]
    picks = np.random.default_rng(seed).choice(len(data), size=min(n, len(data)), replace=False)
    return [data[int(k)] for k in sorted(picks)]


def follows(item, response):
    return all(CHECKS[name](response, {key: value for key, value in kwargs.items() if value is not None})
               for name, kwargs in zip(item["instruction_id_list"], item["kwargs"]))


def ifeval_correct(policy, items, max_tokens=400):
    from mlx_vlm import generate
    from mlx_vlm.prompt_utils import apply_chat_template
    out = []
    for item in items:
        text = apply_chat_template(policy.processor, policy.model.config, [{"role": "user", "content": item["prompt"]}])
        response = generate(policy.model, policy.processor, text, max_tokens=max_tokens, temperature=0.0, verbose=False).text
        out.append(follows(item, response))
    return out


# ----- both -----
def paired(name, base, trained):
    base, trained = np.array(base, float) * 100, np.array(trained, float) * 100
    diff = trained - base
    se = float(diff.std(ddof=1) / np.sqrt(len(diff))) if len(diff) > 1 else None
    return {"check": name, "questions": len(diff), "base_points": round(float(base.mean()), 2),
            "trained_points": round(float(trained.mean()), 2), "difference": round(float(diff.mean()), 2),
            "difference_se": None if se is None else round(se, 2), "flagged": bool(diff.mean() < -FLAG_POINTS)}


def run(policy, checks, mmlu_n=200, ifeval_n=30, seed=0):
    results = []
    for name in checks:
        if name == "mmlu":
            items, scorer = mmlu_items(mmlu_n, seed), mmlu_correct
        elif name == "ifeval":
            items, scorer = ifeval_items(ifeval_n, seed), ifeval_correct
        else:
            raise ValueError(f"unknown guardrail {name}")
        trained = scorer(policy, items)
        with policy.without_adapter():
            base = scorer(policy, items)
        results.append(paired(name, base, trained))
    return results
