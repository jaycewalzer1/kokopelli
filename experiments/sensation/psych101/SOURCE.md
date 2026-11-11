# Psych-101: source and licence

Read on 2026-11-10 by the overnight lane D session, before anything was downloaded. Nothing here was accepted, requested or
signed on the owner's behalf: the training file is public and needs no login, and it was fetched with no token.

## What was downloaded

| | |
|---|---|
| Name | Psych-101 (training set) |
| URL | https://huggingface.co/datasets/marcelbinz/Psych-101 |
| Revision | `611565c66395e2787cd7e3305149bb75dc138024` (the repo's `main` on 2026-11-10, last modified 2024-11-02) |
| File | `prompts_training.jsonl`, 859,179,475 bytes, SHA-256 `7a370a94084acd6f73f20d6559214683cfadcab8a1f69e369df285ba75ccef01` (the Hub's LFS id; `prepare.py download` checks it) |
| Where it is | `out/sensation/psych101/data/raw/` in the main checkout (ignored by git, never committed) |
| Licence | Apache License 2.0, stated twice on the dataset card: `license: apache-2.0` in its header and "Licensing Information: Apache License 2.0" in its body |
| Gated | No (`"gated": false` in the Hub's API answer) |
| What it is | One row per participant per experiment: `text` (the session written out in English, each human choice wrapped in `<<` and `>>`), `experiment`, `participant` (a number). The card says 160 experiments, 60,092 participants, 10,681,650 choices |

## What was not downloaded

| | |
|---|---|
| Name | Psych-101-test (the held-out test set) |
| URL | https://huggingface.co/datasets/marcelbinz/Psych-101-test |
| Licence | Creative Commons Attribution-NoDerivatives 4.0 (`cc-by-nd-4.0`). The card adds: "Private test set for Psych-101. Do not redistribute outside of this repository." |
| Gated | Yes (`"gated": "auto"`): the Hub hands it over only to a logged-in account that has clicked through its terms |
| Status | **Not downloaded, not requested.** Agreeing to its terms is an owner step. Nothing in this folder needs it |

## What the training set's licence allows

Apache-2.0 is a permissive licence. In plain terms:

- **Research use:** allowed. Copy, change, train on and publish results from it.
- **Commercial use:** allowed by the licence text. It grants use "for any purpose", and nothing in it is non-commercial.
- **Conditions if we pass the data (or a changed copy of it) on to someone else:** include a copy of the licence, say which
  files we changed, and keep any attribution notices. We don't redistribute the data: it stays in `out/`.
- **No warranty**, and no right to use the authors' names or marks.

Two things the licence text doesn't settle, both for the owner (plan section 9), neither blocking tonight's research use:

1. **The licence is the compilers' statement about a compilation.** Psych-101 was assembled by the Centaur authors from 160
   experiments run by other labs. The card puts the whole file under Apache-2.0, and the repo has no separate `LICENSE`
   or `NOTICE` file and no per-experiment terms. I did not check the terms each original study was released under. For
   research this is the normal way to use the set. Before a commercial product ships weights trained on it, someone
   should check whether the original studies carry terms the compilation can't override.
2. **Whether a model trained on Apache-2.0 data inherits any obligation** is not something the licence addresses. The
   usual reading is that it doesn't, beyond citing the source. That is a reading, not legal advice.

The base model's own licence (Qwen3-VL-8B-Instruct, Apache-2.0) was already on this Mac and isn't part of this lane.

## Citation

```
@misc{binz2024centaurfoundationmodelhuman,
      title={Centaur: a foundation model of human cognition},
      author={Marcel Binz and Elif Akata and Matthias Bethge and Franziska Brändle and Fred Callaway and Julian Coda-Forno and Peter Dayan and Can Demircan and Maria K. Eckstein and Noémi Éltető and Thomas L. Griffiths and Susanne Haridi and Akshay K. Jagadish and Li Ji-An and Alexander Kipnis and Sreejan Kumar and Tobias Ludwig and Marvin Mathony and Marcelo Mattar and Alireza Modirshanechi and Surabhi S. Nath and Joshua C. Peterson and Milena Rmus and Evan M. Russek and Tankred Saanum and Natalia Scharfenberg and Johannes A. Schubert and Luca M. Schulze Buschoff and Nishad Singhi and Xin Sui and Mirko Thalmann and Fabian Theis and Vuong Truong and Vishaal Udandarao and Konstantinos Voudouris and Robert Wilson and Kristin Witte and Shuchen Wu and Dirk Wulff and Huadong Xiong and Eric Schulz},
      year={2024},
      eprint={2410.20268},
      archivePrefix={arXiv},
      primaryClass={cs.LG},
      url={https://arxiv.org/abs/2410.20268},
}
```

Later published as Binz et al. (2025), "A foundation model to predict and capture human cognition", *Nature*. The card
still cites the preprint above, so that is what is copied here.

## What this folder does with it

`prepare.py` turns sessions into chat rows for mlx-vlm's LoRA trainer and leaves out every experiment about food, hunger,
generosity or social giving (`held_out.yaml`, with the reason for each). No Psych-101 text is in git: the tests use
made-up rows.
