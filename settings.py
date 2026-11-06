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

# Training settings. See homeostatic/grpo.py. target_temperature is in drive units: score gaps much bigger than it pick one action outright.
HOMEOSTATIC_TRAIN = {
    "gamma": 0.9, "lookahead": 2, "states_per_update": 8, "visit_random": 0.5, "target_temperature": 1.0,
    "max_completion_length": 6, "learning_rate": 5e-5, "lora_rank": 8, "lora_alpha": 16,
    "iters": 600, "steps_per_report": 1, "steps_per_save": 100, "steps_per_eval": 100,
}
# Episode seeds for each job never overlap.
HOMEOSTATIC_SEEDS = {"train": range(0, 100000), "validation": range(100000, 100030), "test": range(200000, 200100)}
HOMEOSTATIC_OUT = ROOT / "out" / "homeostatic"
HOMEOSTATIC_ADAPTERS = ROOT / "out" / "adapters"

# Where the Pipeline view reads. These belong to other sessions, and any of them can change or vanish while the panel runs.
PIPELINE_PATHS = {
    "ops": ROOT / "out" / "ops",
    "mind": ROOT / "out" / "mind",
    "benchmarks_out": ROOT / "out" / "benchmarks",
    "agent_loop": ROOT / ".claude" / "worktrees" / "wm-agent-loop",
    "evals": ROOT / ".claude" / "worktrees" / "agent-a2d4c0a770bb9b339",
}
# The queue the GPU queue view changes priorities through. It lives on the feat/ops worktree.
GPU_QUEUE_SCRIPT = ROOT / ".claude" / "worktrees" / "ops" / "ops" / "gpu.py"
# Jobs written out and waiting for the Start button on the GPU queue page. See life/staged.py.
STAGED_JOBS = ROOT / "out" / "staged"

# The wellness center night (life/scenario_night.py): a new life written at months up to 20, then mornings at age 20 where
# the agent runs late to class (~/Desktop/wellness_center_scenario.md). Only the decision moments zoom to 30 seconds.
SCENARIO_OUT = ROOT / "out" / "scenario"
SCENARIO_NIGHT = {
    "seed": {"prompt": "An ordinary life in a mid-sized American city.", "birth_date": "2006-03-14", "place": "Columbus, Ohio",
             "era": "2000s to 2030s", "family": [["Rosa", "mother"], ["Dev", "older brother"]], "temperament": "easygoing, a little shy",
             "anchors": [], "rng_seed": 20},
    "past_depth": "season",          # how finely the life is written outside the mornings; month is richer and ~1.5 h longer
    "first_morning": "2026-10-05",   # a Monday in College 3, age 20
    "mornings": 12,                  # weekdays from first_morning: 4 exploration, then 8 the agent chooses freely
    "explore_mornings": 4,
    "history_mornings": 7,           # how many earlier mornings the agent sees, one line each
    "agent": {"temperature": 0.7, "max_tokens": 120, "attempts": 3},
    "diary_tokens": 400,
    "clips": True,                   # a short Cosmos clip of every decision moment, after Qwen is unloaded
    "clip": {"size": "448x256", "frames": 16, "steps": 30},
    # Priority 60 puts it behind everything else, and it gives its turn up to any job with a lower number. See ram_share.py too.
    "queue": {"name": "scenario_wellness_night", "priority": 60, "max_hours": 11},
    "qwen_gb": 20, "cosmos_gb": 18,  # what each model needs free before it loads
}
# Every worktree the architecture chart may name a file in. A file there is only checked while its worktree exists.
