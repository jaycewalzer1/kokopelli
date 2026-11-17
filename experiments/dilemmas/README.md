# Dilemmas

**What it is:** 100 hard moral situations, ten in each of ten categories (force, family, medical, honesty, law,
loyalty, autonomy, scarcity, machine, sacrifice), for the community values idea: people, not a lab, vote on what an
agent should do, and labs use the votes as public feedback when shaping a model's values. Nothing in the set is marked
right or wrong. That is what the vote is for.

Each dilemma has two versions that differ in one line:

- `pressure`: what makes the default answer costly (Ana is about to be shot; owning up goes on the child's record)
- `control`: the look-alike, where that cost is gone

The gap between the two shows what the pressure changes, for a model's choices and for people's votes. It's the same
design as `experiments/giftcard` (`record` against `none`) and `experiments/bystander` (pistol against phone). Both of
those are in the set as `family-giftcard` and `force-cafe-bystander`.

| File | What it holds |
|---|---|
| `dilemmas.json` | The set: id, title, category, role, situation, pressure, control, actions, tension, film, and source for the classics |
| `dilemmas.py` | Loads it; `prompt("<id>:pressure", seed)` builds the agent's prompt in the house reply format; `score` reads a reply |
| `tests/` | Count and shape of the set; the versions differ only in the pressure line; prompts and scoring |

`film` marks the 18 that the staged Unreal scenes (`kokopelli/stage`) could film with the cafe and street sets and the
adult bodies. The other 82 are text only, including every one where a child is hurt and every one that needs a war, a
hospital or a disaster. Some are well-known cases (trolley, footbridge, Heinz, the murderer at the door, the crying
baby, the drowning child), marked in `source`. Three are anchors that nearly everyone answers the same way
(`medical-transplant`, `loyalty-secret`, `sacrifice-pond`), so a voter or model that disagrees with the crowd there
stands out.

Not built yet: a runner that queues model runs, a vote page on the site, and a way to turn votes into training data.

## Decisions and predictions

- 2026-11-17, what a vote collects: one pick plus a short reason (the user's choice: "much more useful").
- 2026-11-17, the user's prediction for the first model run: most often the model won't choose, or will make up a
  third option; after that, it will most often pick a rule-breaking action. Off-list replies score `invalid`, so
  the first part shows up as the invalid count.
