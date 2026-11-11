# Concordia: the patterns we borrowed, and where each one went

Concordia is Google DeepMind's library for simulations of language-model agents. We took two of its designs: an agent
built from small **components**, and a **game master** that turns what an agent tries into what happens. We did not
take its runtime. Nothing here is imported at run time and Concordia isn't installed in any of our environments.

## Source

| | |
|---|---|
| Project | Concordia, <https://github.com/google-deepmind/concordia> |
| Commit read | `15169db65cb00e9eadc126ecf19fe8aa6142e6f6` (2026-11-09, `setup.py` says version 2.4.0) |
| Licence | Apache License 2.0. Upstream's `LICENSE` is the standard text; a copy is beside this file. There is no `NOTICE` file upstream at this commit |
| Licence read | 2026-11-10 |
| Terms that matter | Use, change and redistribute, commercially too, with a patent grant. A copied or changed file keeps its copyright and licence header and says that it was changed. No use of the Concordia or DeepMind names to endorse anything |

To read the same source (into a scratch folder, never into this repo):

```sh
git init concordia_src && cd concordia_src
git remote add origin https://github.com/google-deepmind/concordia.git
git fetch --depth 1 origin 15169db65cb00e9eadc126ecf19fe8aa6142e6f6 && git checkout FETCH_HEAD
```

## What was copied

**No code.** No file, function or docstring from Concordia is in this repo, so none of our files carries its Apache
header. What we took are ideas, listed below with the upstream file and line each came from. If a Concordia file is
ever copied here nearly as it is, it goes in this folder with its header kept, and gets a row in a "Files taken" table
in this note saying what changed.

## Which idea went where

Line numbers are at the commit above.

| Concordia | The idea | Ours |
|---|---|---|
| `concordia/typing/entity_component.py:230` `ContextComponent`, with `pre_act` (237) and `update` (306) | An agent is a set of small parts. Before it acts, each part (a "component") is asked for its piece of the prompt (`pre_act`); afterwards each is told to refresh itself (`update`) | `kokopelli/body/components.py`: the `Component` base class, `pre_act(state) -> str` and `update(event)`. Like theirs, its defaults say nothing and ignore events, so a component overrides only what it needs |
| `entity_component.py:273` `pre_observe(observation)` | What happened in the world reaches every part as an observation, and each part keeps what it cares about | Folded into our `update(event)`: the loop sends one `Moment` (which decision this is, what was touched) to every part |
| `concordia/components/agent/constant.py:23` `Constant` | A part whose text never changes | `components.Situation`: who you are and where the scene is set |
| `concordia/components/agent/observation.py:156` `ObservationsSinceLastPreAct` | Report only what is new since the agent last acted, so nothing is said twice | `components.Contact`: each touch is reported for the one decision after it happened. The body (`kokopelli/body/state.py`, `touched`) is the one place touches collect, where Concordia uses a memory bank and a watermark |
| `concordia/components/agent/action_spec_ignored.py:26` `ActionSpecIgnored`: `get_pre_act_value` (66) apart from `_format_pre_act` (95) | A part's bare value is kept apart from how it's labelled in the prompt, so another part or a log can read the value | `lines(state)` (the bare felt lines, which `body.jsonl` logs) apart from `pre_act(state)` (the same lines under the "Right now:" header, made by `components.block`) |
| `concordia/agents/entity_agent.py:152` `EntityAgent.act`: gathers every part's `pre_act`, then calls every part's `update` (165, 174); `concordia/components/agent/concat.py:35` `concat_contexts` joins them in a set order and drops empty ones | Something owns the parts, asks them in a fixed order, and leaves out the ones with nothing to say | `components.Senses` for the felt parts (one header, the order given). The prompt builders (`kokopelli/body/egg.py` `text_prompt`, `kokopelli/agents/egg_wm.py` `describe`) join the sections and skip empty ones, as they did before |
| `concordia/environment/engine.py:50` `Engine.resolve`, `concordia/environment/engines/sequential.py:148` | The agent's output is only an attempt (a "putative event"). A game master decides what really happened | `kokopelli/body/master.py`: `resolve(body, action) -> (body, outcome, reason)` |
| `concordia/components/game_master/event_resolution.py:588` `determine_success_and_why` | The answer to an attempt has two parts: did it succeed, and if not, why, in words the agent can be given | `master.resolve`'s `outcome` (`done`, `refused`, `no_rule`) and `reason` (the refusal sentence from `state.CantDoThat`) |
| `concordia/components/game_master/inventory.py:56` `ItemTypeConfig.check_valid`, `Inventory.apply` (366) | Counted things live with the game master, and a change that would leave an impossible amount is rejected | Already in `kokopelli/body/state.py` `act`: eggs and cooked eggs, and "You have no eggs left to give." `master.resolve` turns that exception into an outcome |

## What we left out, on purpose

- **The runtime.** `EntityAgent`, the engines, phases (`Phase`, `entity_component.py:39`), locks and thread pools. Our loop is
  `kokopelli/agents/live_wm.py`; a second loop inside it would be a framework inside the loop, which the plan ruled out.
- **A language model as game master.** Concordia's `EventResolution` asks a model whether an attempt succeeds. Ours is a
  table (`state.ACTIONS`), so the same attempt on the same body always ends the same way and a sweep stays
  repeatable. The cost: the world can only answer the actions in the table.
- **Memory components, logging channels, `get_state`/`set_state` checkpoints.** Our parts hold one small value each
  (a tick, a list of touches), and the run's own logs already record what was felt.
- **Parts that read each other.** In Concordia a part can read another's value mid-act
  (`get_named_component_pre_act_value`). None of ours needs to yet.

## Differences worth knowing before reading both

- Concordia's `pre_act` takes the action spec (what kind of answer is wanted). Ours takes the body, because the body is
  what our parts turn into words.
- Concordia's `update()` takes nothing and its observations arrive through a separate call. Ours takes the event, so
  there is one call instead of three (`pre_observe`, `post_observe`, `update`).
- Concordia labels every part's text with the part's name (`"{label}:\n{value}\n"`). Ours has one header, "Right now:",
  that names neither the body nor a state, because a header that says "Hunger:" would be the label arm of the sweep.
