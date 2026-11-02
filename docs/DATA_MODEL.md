# Data model

Early design, and meant to be argued with. Sizes below are measured from one full run of the current life.

## The hierarchy

```
Life story     authored    1
Segments       authored    9, ending where development ends, not on birthdays
Statements     authored    what she holds to be true, each with a held interval
Plans          authored    versioned intentions tied to statements
---------------------------------------------------------------------------
Year           derived     83
Season         derived     331
Month          derived     991
Week           derived     4,305
Day            derived     30,127
Hour           derived     read from the day's strip
Minute         derived     43,381,588 lived, one code per minute
```

## Decisions

### 1. One integer clock
`t` is minutes since the world epoch (1900-01-01). Every level is a half-open interval `[start_t, end_t)` on it. Time starts at the world's epoch, not at birth, so more lives can share one timeline later.

### 2. Levels are joined by time, not by a strict tree
The levels you listed look nested, but the real calendar is not a tree:

| Pair | Nests? | Why |
|---|---|---|
| Day in month, month in season, day in week | Yes | Checked by `verify` |
| Week in month or year | No | 1948-W53 runs into January 1949 |
| Season in year | No | Winter crosses New Year |
| Year in segment | No | Segments end on life events |

So `parent_key` means only "the span holding my start", and weeks have no parent. The question "what contains this?" is answered by an interval lookup at `t`. Each level must separately cover the whole life with no gap or overlap.

### 3. Expansion is a pure function of a path
Randomness comes from `hash(seed, "day/1975-09-02/sky")`, not from a stream. That gives us:
- **Random access.** Any minute can be read directly, without simulating what came before.
- **Local edits.** Changing one event leaves other days as they were.
- **Resume and replay.** Generation doesn't depend on process history, which the one-hour test relies on.

### 4. What is stored and what is derived

| Tier | Holds | Storage | Measured |
|---|---|---|---|
| Canon | World, people, segments, statements, plans, events | `canon/world.json` in git | 46 events, 15 plan versions |
| Spans | Life through day: payload plus time-use rollup | `spans` rows | 13.9 MB, of which day payloads are the most |
| Strips | Hour and minute: 1440 activity codes per day | `day_strips`, zlib | **1.5 MB** for all 43M minutes |
| Moments | Sparse minutes carrying authored detail | `moments` | 46 rows |
| Micro-action | What exactly is happening within the activity | Not stored; computed from `t` | 0 |

A row per minute would be 43M rows. Strips compress to about 0.035 bytes per minute because a life is long runs of the same thing. Next time we save space, it should come from day payloads, which repeat the same residence and household strings. Lanes could replace that repetition.

### 5. What she knows is separate from what happened
This is the part most likely to matter for a synthetic mind, and it has already caught a bug. The first version showed her 1951 self the statement "My left leg is not going to do what it did", a year before polio.

There are two scopes:

- **Narrator scope:** spans and events. A 1996 year payload knows the wreck is found in July, even when read in January.
- **Character scope:** `statements_held_at(t)` and `plans_believed_at(t)`, which return only what she holds at that minute.

Anything acting as Nell must read character scope only. Nothing in the schema enforces that yet.

Plans are bitemporal. `[believed_from, believed_until)` is when she held the plan, and `target_t` is the time it's about. Versions are never overwritten, so "What did she think would happen in 1980, as of 1970?" has an answer. `p_find_tomas` shows why:

| Version | Held | Plan | Outcome |
|---|---|---|---|
| v1 | 1957-1966 | Get someone with a boat to look | Revised |
| v2 | 1966-1984 | Run the lines myself, search by 1980 | Revised |
| v3 | 1984-1996 | Finish the chart, then search where it points | Achieved at 13:18 on 1996-07-23 |

A milestone with no event is a plan that never came true. That gap between plan and life is the raw material of the story.

### 6. Rollups flow up, constraints flow down
- **Down:** canon sets lanes, lanes pick a schedule, the schedule fills a strip, and events overwrite the strip at their exact minute.
- **Up:** minute counts sum into day, week, month, season, year, segment, and life. All seven totals must agree activity by activity.

### 7. Lanes hold slow-changing state
Role, residence, and household are step functions over time, so nothing needs a daily copy to answer "where did she live?". New slow state, like health or money, should start as a lane.

### 8. Stable identifiers
Spans use natural keys, `(life_id, level, key)`, such as `(nell-varga, week, 1948-W53)`. A regenerated database keeps the same addresses. Activity codes are positions in a list, so **new activities must be appended**, never inserted.

## Tables

| Table | Key | Purpose |
|---|---|---|
| `spans` | life, level, key | Life, segment, year, season, month, week, day |
| `day_strips` | life, day | Compressed activity codes for each minute |
| `moments` | life, t | Sparse minutes with authored detail |
| `statements` | life, id | Beliefs and vows with a held interval |
| `plan_versions` | life, plan, version | Bitemporal plans |
| `milestones` | life, plan, version, ordinal | Due dates, linked to the event if they happened |
| `events` | life, id | Canon events |
| `checkpoint` | single row | Resume state, written in the same transaction as the data |
| `run_info`, `telemetry` | | Wall-clock facts, excluded from digests |

## What this doesn't model yet

- **Causality.** Events are authored. Nothing makes polio follow from the world, and days can't change the life above them.
- **World state.** There's weather and a calendar, but no persistent objects, places with state, or other simulated people.
- **Inner state.** Mood, memory decay, and health aren't represented. Her knowledge is a list of authored statements.
- **Authored hours.** Below the day level, life comes from templates plus jitter. It's consistent, but it doesn't read as lived experience yet.

## Open questions

1. **Does the top-down story stay fixed?** Today it's fate: events are canon and days fill in beneath them. If we want emergence, then a day has to be able to change a plan. That would turn canon into an initial plan, and the store into an append-only event log. This is the biggest decision ahead.
2. **Is one life the unit, or the world?** The schema supports many `life_id`s, but `people` are only names so far.
3. **What resolution does a "world model" need?** If minutes eventually become video or simulation, `moments` is the natural place to store a rendered scene, created on demand and then kept.
4. **What gets remembered?** A memory table separate from `events`, with what she recalls and how wrong it has become, would extend the character scope naturally.
