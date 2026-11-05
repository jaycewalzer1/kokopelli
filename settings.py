"""Which models this repo uses and where they live."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent

WORLD_MODEL = "nvidia/Cosmos3-Nano"
LLM_MODEL = "Qwen/Qwen3-VL-8B-Instruct"

WORLD_MODEL_WEIGHTS = ROOT / "models" / WORLD_MODEL.split("/")[1]
WORLD_MODEL_RUNNER = Path.home() / "cosmos3" / "cosmos3-mlx"
LLM_MODEL_WEIGHTS = ROOT / "models" / LLM_MODEL.split("/")[1]

LIFE_DB = ROOT / "out" / "life.db"
LIFE_DEMO_DB = ROOT / "out" / "demo.db"
LIFE_DEMO_WRITES = 8000

# The life a new database starts with, and what the New run form starts from.
LIFE_DEFAULT_SEED = {
    "prompt": "An ordinary life in a mid-sized American city.", "birth_date": "1990-03-14", "place": "Atlanta, Georgia",
    "era": "1990s to 2020", "family": [["Ana", "mother"], ["Ben", "father"]], "temperament": "curious, cautious",
    "anchors": [["1995-10-10T10:20:30", "a storm knocks out the power"]], "rng_seed": 7,
}

# Developmental stage is a function of age, not a tree level. Each row applies until until_age.
LIFE_STAGES = [
    {"name": "toddler", "until_age": 4, "memory_strength": 0.2, "planning_horizon": "minutes",
     "action_space": ["play", "cry", "follow", "explore"], "theory_of_mind": 0.1, "hot_cognition": 0.9},
    {"name": "early_child", "until_age": 7, "memory_strength": 0.4, "planning_horizon": "hours",
     "action_space": ["play", "ask", "share", "refuse", "copy"], "theory_of_mind": 0.4, "hot_cognition": 0.8},
    {"name": "child", "until_age": 12, "memory_strength": 0.6, "planning_horizon": "days",
     "action_space": ["practice", "ask", "share", "refuse", "hide", "join"], "theory_of_mind": 0.7, "hot_cognition": 0.6},
    {"name": "adolescent", "until_age": 18, "memory_strength": 0.8, "planning_horizon": "months",
     "action_space": ["study", "rebel", "confide", "withdraw", "risk", "join"], "theory_of_mind": 0.85, "hot_cognition": 0.8},
    {"name": "young_adult", "until_age": 31, "memory_strength": 0.9, "planning_horizon": "years",
     "action_space": ["work", "study", "commit", "leave", "confide", "save", "risk"], "theory_of_mind": 0.95, "hot_cognition": 0.4},
]

# The deepest level a node opens children down to: the first row whose salience it meets.
LIFE_DEPTH_BY_SALIENCE = [(0.97, "sec30"), (0.93, "min15"), (0.85, "hour"), (0.0, "day")]
LIFE_ESCALATION_ODDS = 0.02

# How the panel groups years into stages. For display only: a year joins the hub for the age it starts at.
LIFE_DISPLAY_HUBS = [
    {"name": "Early childhood", "from_age": 2, "until_age": 6},
    {"name": "Middle childhood", "from_age": 6, "until_age": 12},
    {"name": "Adolescence", "from_age": 12, "until_age": 18},
    {"name": "Young adulthood", "from_age": 18, "until_age": 31},
]

# What the model sees of the past. See life/memory.py.
LIFE_MEMORY = {"recent_same_level": 3, "recent_coarser": 1, "vivid": 3, "vivid_floor": 0.25}
LIFE_LLM = {"temperature": 0.7, "max_tokens": 600, "attempts": 3}
# Left alone, the model keeps rewriting its last scene. The code picks what each stretch turns toward, and the model writes it.
LIFE_FOCUS = ["family at home", "health or the body", "someone new", "a change in routine", "something being learned", "money or work in the household",
              "the neighborhood", "friends or other children", "a trip or a change of place", "a relative", "school or care", "news from outside"]

# An unattended run. A skim stops at months, so a whole life is about 1,000 writes rather than 25,000.
LIFE_TRIAL = {"skim_deepest": "month", "skim_share": 0.6, "second_life_share": 0.15, "slice_ages": [3, 6, 10, 15, 25],
              "trial_day_calls": 16, "max_crashes": 5}
LIFE_TRIAL_SEEDS = [LIFE_DEFAULT_SEED, {
    "prompt": "A life in a small coastal town.", "birth_date": "1984-08-02", "place": "Rockland, Maine",
    "era": "1980s to 2010s", "family": [["Mara", "mother"], ["Tom", "grandfather"]], "temperament": "restless, talkative",
    "anchors": [["1993-01-20T08:30:00", "a winter storm floods the family's street"]], "rng_seed": 11,
}]

LIFE_BUDGET = {"generator_calls": 2000, "seconds": 120}
LIFE_WARN_SIMULATED_DAYS = 365

# The life homeostatic training happens in. See homeostatic/world.py. Effects are in variable order, and the model isn't told them.
HOMEOSTATIC_WORLD = {
    "variables": ["security", "belonging", "ambition", "energy"],
    "actions": {
        "work": [9, -2, 2, 0], "study": [0, -2, 2, -4], "commit": [0, 2, -3, -2], "leave": [-6, -6, 8, 6],
        "confide": [1, 6, -1, -3], "save": [6, 0, -4, 1], "risk": [3, 2, 12, 0], "rest": [-1, -1, -3, 12], "idle": [0, 0, 0, 0],
    },
    # What an action does a turn later. This is why choosing by the next turn alone fails: risk looks free until it lands.
    "later": {"work": [0, 0, 0, -8], "study": [0, 0, 8, 0], "commit": [5, 8, 0, 0], "risk": [-14, 0, 0, -6]},
    "drift": [-1, -1, -1, -2],
    "noise": 1.5,
    "bounds": [0, 100],
    "start": [25, 75],
    # Where a healthy range is centered. The ood split is never trained on.
    "setpoints": {"train": [[35, 65]], "ood": [[22, 35], [65, 78]]},
    "half_width": 8,
    "horizon": 10,
    "death_drive": 150,
}

# GRPO settings. Qwen replies work or rest nearly every time at temperature 1, and a group of identical replies teaches nothing,
# so rollouts sample hotter than the distribution the loss differentiates. That trades strict on-policy updates for exploration.
HOMEOSTATIC_TRAIN = {
    "gamma": 0.9, "lookahead": 2, "group_size": 6, "states_per_update": 3, "invalid_penalty": 5.0,
    "max_completion_length": 6, "temperature": 2.0, "learning_rate": 1e-4, "lora_rank": 8, "lora_alpha": 16,
    "iters": 150, "steps_per_report": 1, "steps_per_save": 25, "steps_per_eval": 25,
}
# Episode seeds for each job never overlap.
HOMEOSTATIC_SEEDS = {"train": range(0, 100000), "validation": range(100000, 100030), "test": range(200000, 200100)}
HOMEOSTATIC_OUT = ROOT / "out" / "homeostatic"
