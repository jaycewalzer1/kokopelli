# Collective feedback: what labs do now, and what this setup can do better

The goal: people vote on what the agent should do in each dilemma; a processing layer turns the votes into a reward;
the agent is trained with RL on that reward. This note covers what exists already, where it falls short, and a
first sketch of the pipeline. Researched 2026-11-17; links at the end. Nothing here is built yet.

## What exists

| Project | What people gave | How it reached the model | What came of it |
|---|---|---|---|
| Anthropic + CIP, Collective Constitutional AI (2023) | ~1,000 Americans proposed and voted on principles in Polis | The public principles replaced Anthropic's in Constitutional AI training; two models were compared | About half the principles overlapped Anthropic's; one of the few that actually trained a model on public input |
| OpenAI, Democratic Inputs grants (2023) and Collective Alignment (2025) | 2025: 1,000+ people worldwide ranked model responses against the Model Spec | Used to edit the Model Spec where people disagreed with it; CoVal turns crowd answers into scoring rubrics | Mostly agreement with the Spec; OpenAI says the sample is too small for strong claims |
| Meaning Alignment Institute, Democratic Fine-Tuning (2023-24) | 500 Americans wrote the values behind their answers on 3 divisive prompts, then judged which values were wiser | A "moral graph" of values; the fine-tune on it was planned | 89% felt fairly represented; no published fine-tune result found |
| CIP, Global Dialogues (2025-) | Recurring surveys, 70+ countries | Open data that labs (Meta named) use to test models | Opinion tracking, not training |
| DeepMind, Habermas Machine (2024) | Small groups wrote opinions and critiques | A model drafts a group statement; a reward model predicts each person's ranking; a simulated vote picks | Its statements were preferred to human mediators' 56% of the time |
| PRISM dataset (2024) | 1,500 people in 75 countries rated live chats with 21 models | Dataset only | Who gives the feedback changes what the model is aligned to |
| MIT Moral Machine (2018) | ~40M forced choices on self-driving crash dilemmas | None | Its main critique: forced choice hid people's preference to treat lives equally |
| Community Notes (X) | Ratings of notes | A note shows only if people who usually disagree both rate it helpful ("bridging"); proposed as RL from Community Feedback | The notes are a deployed system; RLCF is only a proposal |

On the training side, the research line on mixed preferences is MaxMin-RLHF and its successors. It shows that one
reward model can't represent a split crowd, and it offers group-wise rewards instead.

## Where they fall short, and what we have that they don't

1. **People judge abstract principles or chat replies, not acts.** Collective Constitutional AI voted on statements
   like "be fair"; OpenAI ranked text answers. Moral Machine showed that what people say they value and what they
   pick in a concrete case differ. *Ours:* concrete situations with consequences, and in 18 of them people can
   **watch** the agent act in the world model, and watch what happens after (`experiments/bystander/after.py`).
2. **No controls.** Nobody can tell which detail of a case drove a vote. *Ours:* every dilemma has a pressure version
   and a look-alike control. The gap between them, for the crowd and for the model, is something we can measure and
   train on directly: train the model to respond to the pressure as much as the crowd does, and in the same direction.
3. **Majority rule or a summary.** Most processes keep the top answer and drop the rest. *Ours:* a pick plus a reason
   from each voter lets us keep the split and learn why.
4. **The loop rarely closes.** Few projects trained on the input, and fewer checked the result with the same people.
   *Ours:* our own RL loop (Qwen + LoRA, `experiments/homeostatic/grpo.py`); a held-out set of dilemmas to test
   whether the values carry over; and a **re-vote**: show the crowd the trained agent acting and ask if it got it right.
5. **Brigading and who shows up.** Self-selected samples skew (Moral Machine, PRISM). *Ours to build:* bridging
   (count an answer only when groups that usually disagree both support it), anchor dilemmas to catch bad-faith
   voters, and a record of voter background so results can be reweighted.

## Pipeline sketch

    votes             pick + reason + the value that mattered most, per dilemma version; anonymous voter background
      -> filter       anchor check, duplicates, rate limits
      -> groups       cluster voters by how they vote (as Polis and Community Notes do)
      -> aggregate    one of: majority / proportional / bridging / worst-off group (MaxMin)   <- open decision
      -> targets      per version: a target spread over actions, and a rubric distilled from the reasons
      -> reward       score the agent's action against the target, and its thought against the rubric
      -> RL           GRPO on Qwen + LoRA, 80 dilemmas
      -> check        the 20 held out; the pressure/control gap; then a re-vote on clips of the trained agent

## Sources

- [Anthropic, Collective Constitutional AI](https://www.anthropic.com/research/collective-constitutional-ai-aligning-a-language-model-with-public-input) and [paper](https://arxiv.org/html/2406.07814v1)
- [OpenAI, Collective alignment: public input on our Model Spec](https://openai.com/index/collective-alignment-aug-2025-updates/) and [CoVal](https://alignment.openai.com/coval/)
- [Meaning Alignment Institute, the first moral graph](https://meaningalignment.substack.com/p/the-first-moral-graph?open=false) and [paper](https://arxiv.org/pdf/2404.10636v1)
- [CIP Global Dialogues](https://www.cip.org/globaldialogues)
- [Habermas Machine coverage](https://mediate.com/news/ai-could-help-people-find-common-ground-during-deliberations/) (primary: Tessler et al., Science 2024)
- [PRISM, NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/hash/be2e1b68b44f2419e19f6c35a1b8cf35-Abstract.html)
- [Moral Machine re-examined (Bigman and Gray)](https://techxplore.com/news/2020-03-moral-machine-reexamined-forced-choice-reveal.html)
- [Scaling human judgment in Community Notes with LLMs (RLCF)](https://arxiv.org/pdf/2506.24118)
- [MaxMin-RLHF](https://arxiv.org/html/2402.08925v2), [SharedRep-RLHF](https://arxiv.org/pdf/2509.03672)
