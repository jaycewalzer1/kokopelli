# What the mind loop costs

From `mind_qwen`, the first real Qwen run: 8 ticks with the mock sim and mock world model, in `out/mind/qwen_8`. It took 123 seconds, 117 of them in Qwen. The cost figures are measured. Mock frames are simple diagrams, so real frames may cost more image tokens.

## Measured
| What | Appraisal (8 calls) | Decision (2 calls) |
|---|---|---|
| Seconds per call, mean | 12.6 (11.9–14.2) | 7.9 (7.7–8.0) |
| Of which reloading Qwen | 3.7 (3.4–4.3) | 0, because it's still loaded from the appraisal |
| Prompt tokens, with 6 images | 905 at tick 1, about 1,250 from tick 6 | 1,034 and 1,285 |
| Generation tokens | 48 | 46 and 52 |

- Peak memory was 18.5 GB.
- There were no invalid replies, no retries, and no reply near the 300-token cap.
- Two decisions is too few for a good decision figure. The longer run below replaces it.

## Over a 30-minute run
At 60 ticks, Qwen costs about 15 minutes with a decision every fourth tick, or about 20 minutes with a decision every tick. That's small next to the render, which is days on this Mac.

## What Qwen did
| Measure | Result |
|---|---|
| Feeling | "curious", intensity 0.3, on all 8 ticks |
| Why | The same sentence from tick 3 on, about the images repeating |
| Why names something in view | 0 of 8 |
| Decision points | 2 of 8: first look, and "been a while" |
| Decisions | `look_at` Ana, both times |

- **The flat-reply bug didn't appear here, but it isn't gone.** Every reply in this run was nested correctly, but `wmloop_real_20` got flat replies again from a prompt with a nested example, on most of its first 8 ticks. So the example doesn't prevent them, and the fallback in `kokopelli/mind/actions.py` is needed.
- **The feeling test had nothing to react to.** Frames are labelled diagrams where a few dots drift, and the sim says everything is always in view. So "what's in view changed" never fired, and only the four-tick rule did.
- **The repeated feeling has two possible causes.** Qwen may be responding to frames that barely change, or copying its own last lines, which it sees in the prompt. This run can't separate them. Telling them apart needs frames where something really happens.
- **It misread its situation.** The prompt says "Ana said to be home before dark". Qwen's diary took that to mean Ana is the one coming home, and said she wasn't there, while she was in view and it was looking at her.

## The 90-tick run
`out/mind/qwen_90`, same mock setup: 22 minutes, all but about a minute of it in Qwen. It replaces the figures above where they differ.

| What | Appraisal (90 calls) | Decision (23 calls) |
|---|---|---|
| Seconds per call, mean | 12.2 (11.5–13.8) | 7.0 (3.6–8.5) |
| Of which reloading Qwen | 3.5 | 0 |
| Prompt tokens | 905, reaching about 1,380 | 1,029 to 1,461 |
| Largest reply | 48 tokens | 43 tokens |

There were no invalid replies and no retries. At 60 ticks this is about 14 to 19 minutes of Qwen.

| Result | Value |
|---|---|
| Feeling | "curious", intensity 0.3, on all 90 ticks, with 3 different sentences for why |
| Decision points | First look once, "been a while" 22 times |
| Actions chosen | `wait` 22 times, `look_at` Ana once |
| Replay at temperature 0 | 23 of 23 reproduced, so the rebuilt prompts are right and the noise floor here is 0 |
| Flip: terrified against calm | Action changed on 20 of 23 |
| Flip: content against calm (placebo) | Action changed on 1 of 23 |

**How far the flip result goes.** A feeling written into the prompt does change what Qwen does: calm waited 23 times, while terrified mostly looked at Ana or spoke to her. But it was only one situation, repeated, so 23 decisions are far from 23 independent tests. It also shows Qwen responds to the word in its prompt, not that it has the state the word describes.

**The chain is broken at the first step.** Feelings reach actions, but in this run Qwen never produced a feeling other than "curious" for them to carry. On mock frames this can't say whether that's the frames or copying its own earlier lines.

## Real Cosmos frames: why the feeling sticks
Each moment was appraised three ways: no history, 5 lines of "curious", and 5 lines of "uneasy", with the wording identical apart from the feeling. That's 51 appraisals over 17 moments, in `out/mind/real_frames_first_read.json` and `out/mind/real_frames_20.json`, with the scripts in `out/mind/real_frames_scripts/`.

| History given | Feeling returned |
|---|---|
| 5 lines of "curious" at 0.3 | "curious" at 0.3, 17 of 17 |
| 5 lines of "uneasy" at 0.3 | "uneasy" at 0.3, 17 of 17 |
| None | "curious" 17 of 17, with intensity from 0.3 to 0.7 |

- **The history sets the feeling.** The same frames gave whichever feeling and intensity were planted.
- **Without history it still says "curious".** So removing the history wouldn't be enough.
- **Frames reach the "why" but not the feeling.** At ticks 16 and 20 the picture has decayed badly, and Qwen described it as blurry and dark, some of the time as out of place. The feeling and intensity stayed the same anyway.
- **The diary is stuck too.** From tick 3 of `wmloop_real_20`, its diary line opens with the same words every tick. Its claim that the pigeons and rain have gone isn't something I checked against the frames, and the "why" lines often echo it.

**Limits.** All of this is one scene, the moments overlap between runs, and the three runs share a seed. Nothing in these frames is a real event, and ticks 12, 16 and 20 only show decay. So this shows what happens when history disagrees with the frames, not whether Qwen could respond to a real event.

## Option B: say what changed, then feel
The user chose this, with feelings that move gradually instead of flipping every 30 seconds. Each tick, Qwen first compares the last frame with the new ones, seeing only images. If nothing changed, no feeling is asked for and the last one carries over. If something did, it appraises that change, and `settle()` limits how far the mood moves.

### Noticing: `mind_change_check`, in `out/mind/change_check/results.json`
| Moment | Said something changed | Right answer |
|---|---|---|
| One frame repeated | 0 of 3 | 0 |
| Consecutive Cosmos ticks 1 to 5 | 0 of 4 | 0 |
| Within a clip | 2 of 4 | 2: the mug and the person appear; the candle and blocks don't change within 0.67 s (checked by eye) |
| Cut to a different clip | 3 of 4 | 4: it missed toddler-to-storm-over-wheat |

That's 14 of 15 correct, with one plain miss on a change nobody could miss. A wider check follows below.

### Feeling, once told what changed (16 appraisals, after "curious" or "uneasy" was planted at 0.3)
| Measure | Before option B | Now |
|---|---|---|
| Reply repeats the planted feeling | 34 of 34 | 6 of 16 |
| Reply moves intensity off 0.3 | 0 of 34 | 11 of 16 |

The replies follow the change: "frightened" when the candle goes out, and "surprised" or "startled" when the blocks fall. Some copying remains, mostly with "uneasy": it stayed "uneasy 0.3" on 4 of 8 moments, against "curious" on 2 of 8.

### In the loop: `out/mind/qwen_change_20`, mock frames
- 20 ticks in 3.5 minutes, of which Qwen took 193 s. Checking for change takes about 8.2 s per tick, against 12.2 s for an appraisal before. A quiet tick now costs only that check.
- Nothing changed on any tick, which is right for mock dots, so the feeling stayed "curious 0.3" without being asked again.
- Replay reproduced 5 of 5 decisions.

## Still needed
- A decision on how to unstick the appraisal. See `kokopelli/mind/OPEN_DECISIONS.md`.
- A scene where something actually happens, with re-anchoring so the frames stay clean.

## Known from the code
- Feelings add at most about 1,300 characters to a prompt: 5 feelings, each capped at 30 + 200 characters plus its timestamp. A test holds this at 60 ticks with oversized replies.
- The loop's own notes can add up to 5,000 more, at 5 notes of up to 1,000 characters. Diaries are part of the prompt growth above.
