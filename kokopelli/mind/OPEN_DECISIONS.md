# Open decisions

These are the user's to make. Each default was chosen so overnight work could continue, and is cheap to change.

| Decision | Default for now | Why it matters |
|---|---|---|
| Is the teacher gone? | Yes. The user wrote "scratch that" and described this loop, so nothing here writes questions. | If the teacher stays, it would sit next to the appraisal step and read the same input. |
| What makes a decision point? | A fixed rule in `decision_point`: first look, strong feeling, a change in view, something changed, a changed feeling, or four quiet ticks. | Other options are the script marking them, or the model judging them. This one can be checked, but can't notice anything subtle. |
| What separates big from small? | Big means intensity of at least 0.7, and it only adds a line to the prompt. | A real difference might be more context, or more time to think. |
| Feel and decide in one call or two? | Separate, so the feeling is formed before the decision: say what changed, then feel only if something did, then decide. | More calls on eventful ticks, fewer on quiet ones, and one call could justify a decision it had already made. |
| How fast can a mood move? | 0.15 of intensity per tick, and a different feeling only takes over once the old one has faded to 0.3. Happy at 0.9 takes 4 ticks to fade, so 2 minutes. | The user chose "say what changed, then update", and continuous rather than flipping every 30 seconds. The numbers are a first guess. Slower feels steadier, but reacts late. |
| Can a shock override the slow mood? | Not the mood, but it can make the moment "big". A strong reply gets the big note in the decision prompt while the mood still moves slowly. | Without this, nothing would ever count as big, because the mood takes several ticks to rise. |
| Does feeling change the world? | No. It only reaches the agent's own later prompts, and is never a score. | If it ever feeds a reward, the agent can earn that reward just by claiming to feel fine. |

## Not decided, and expensive to undo
- **Where the continuous 30 minutes gets rendered.** On this Mac it would take days, and nothing here assumes an answer.
- **Which situation the agent is in.** Runs so far use the mock sim's bench, door and ball, not the egg scene.

## Known gaps
- `visible` comes from the sim, not from what the world model drew, so the agent can be told about something the frames don't show. Fixing this belongs in `kokopelli/loop/`.
- The appraisal prompt is made by cutting the loop's prompt at `DECIDE_MARK`. If that wording changes in `kokopelli/loop/prompt_builder.py`, it stops working. A proper hook for this would need to go through `kokopelli/loop/HANDOFF.md`.
- The loop's log records a `wait` on a quiet tick the same as a real choice to wait. Only `feelings.jsonl` shows which was which, through `decided`.
- Nothing shows that training on the homeostatic world moves the agent in a healthier direction here, because the loop has no variables to keep in range. `kokopelli.loop.mind_check --replay` can only show whether replies stay valid and whether behaviour moved.
- A resumed run repeats any tick after the last checkpoint and replaces what that tick felt, so `feelings.jsonl` is rewritten on that one occasion. Everything else only appends.
