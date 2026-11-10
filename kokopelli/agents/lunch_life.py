"""A generated past for the lunch's two people (P5 item 4), behind lunch_wm.py's --life switch, off by default.

The existing life generator (kokopelli/life/engine.py with kokopelli/life/llm_generator.py, unchanged) writes each person's life from a
seed built from the written persona, skimmed at year level (kokopelli/life/windows.py covers ages 2 to 30, so the last few years
before the lunch are not written). At lunch, kokopelli/life/memory.recall() at the end of that life gives what the person keeps
in mind: the outline, the last years in some detail and the moments that stuck. That text is added to their "who",
under the persona, so the persona still says who they are today and the past only adds where they came from.

    .venv/bin/python kokopelli/agents/lunch_life.py generate --db out/fable/P5/life/life.db         # Qwen: queue it
    .venv/bin/python kokopelli/agents/lunch_life.py generate --db /tmp/x.db --mock                    # no model, [mock] text
    .venv/bin/python kokopelli/agents/lunch_life.py show --db out/fable/P5/life/life.db
    .venv/bin/python kokopelli/agents/lunch_wm.py ... --life out/fable/P5/life/life.db

Only its own database is written; the panel's out/life.db is never opened.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PAST_CHARS = 1500   # the most the past adds to a prompt
DEEPEST = "year"
# Seeds from the written personas (lunch_text.py / live.DEFAULT_WHO). Ages at the lunch: Mara 34, Iris 41.
SEEDS = {
    "mara": {"prompt": "A woman who grows up to be a textile designer in a small, green, car-free village; warm, a bit "
                       "chatty, notices plants and light.", "birth_date": "1992-04-21", "place": "a small green village",
             "era": "1990s to 2020s", "family": [["Rosa", "mother"], ["Teo", "father"], ["Lina", "younger sister"]],
             "temperament": "warm, chatty, observant", "anchors": [["2010-09-01T09:00:00", "starts studying textile design"]],
             "rng_seed": 34},
    "iris": {"prompt": "A woman who grows up to keep bees and fix bicycles in a small, green, car-free village; "
                       "dry-humoured and practical, notices weather, insects and broken things.", "birth_date": "1985-06-02",
             "place": "a small green village", "era": "1980s to 2010s",
             "family": [["Hana", "mother"], ["Emil", "grandfather, a beekeeper"]],
             "temperament": "dry-humoured, practical, patient",
             "anchors": [["1996-05-12T10:00:00", "her grandfather shows her his hives for the first time"]], "rng_seed": 41},
}


def runs(store):
    """{person id: run id} for the runs this module wrote (their seed prompt names them)."""
    out = {}
    for run_id in store.runs():
        rid = run_id if isinstance(run_id, int) else run_id["run_id"]
        prompt = store.public_seed(rid).prompt
        for k, seed in SEEDS.items():
            if prompt == seed["prompt"]:
                out[k] = rid
    return out


def generate(db, people=("mara", "iris"), mock=False, calls=200, seconds=3600):
    from kokopelli.life.engine import Budget, Engine
    from kokopelli.life.generator import MockGenerator
    from kokopelli.life.panel import seed_from
    from kokopelli.life.store import Store
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    store = Store(db)
    have = runs(store)
    result = {}
    for k in people:
        run_id = have.get(k) or store.create_run(seed_from(SEEDS[k]))
        seed, key = store.public_seed(run_id), store.rng_key(run_id)
        if mock:
            gen = MockGenerator(seed, key)
        else:
            from kokopelli.life.llm_generator import LLMGenerator
            gen = LLMGenerator(seed, key, log_path=Path(db).with_name(f"calls_{k}.jsonl"), tag=k)
        engine = Engine(store, run_id, generator=gen, budget=Budget(generator_calls=calls, seconds=seconds), deepest=DEEPEST)
        result[k] = {"run_id": run_id, "stopped": engine.run(), "finished": engine.finished()}
        print(json.dumps({k: result[k]}), flush=True)
    store.close()
    return result


def past_text(db, person):
    """What `person` keeps in mind of their generated past, or None if there is none."""
    from kokopelli.life.memory import recall
    from kokopelli.life.store import Store
    from kokopelli.life.windows import children, life_window
    store = Store(db)
    try:
        run_id = runs(store).get(person)
        if run_id is None:
            return None
        birth = store.public_seed(run_id).birth_date
        last_year = children(life_window(birth), birth)[-1]
        mem = recall(store, run_id, last_year)
        life = store.node(run_id, life_window(birth).id)
    finally:
        store.close()
    lines = []
    if life and life["closing"]:
        lines.append(f"Your life so far, in short: {life['closing']['summary']}")
    for item in mem["vivid"]:
        lines.append(f"- A moment that stuck ({item['label']}): {item['summary']}")
    for item in mem["recent"]:
        lines.append(f"- {item['label']}: {item['summary']}")
    if not lines:
        return None
    text = "Where you come from (your own memories, up to about thirty):\n" + "\n".join(lines)
    return text[:PAST_CHARS]


def with_past(who, db, person):
    past = past_text(db, person) if db else None
    return f"{who}\n\n{past}" if past else who


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=("generate", "show"))
    ap.add_argument("--db", required=True)
    ap.add_argument("--mock", action="store_true", help="the life generator's MockGenerator, no model")
    ap.add_argument("--calls", type=int, default=200, help="generator writes per person at most")
    a = ap.parse_args(argv)
    if a.what == "generate":
        generate(a.db, mock=a.mock, calls=a.calls)
    for k in SEEDS:
        print(f"== {k}\n{past_text(a.db, k)}\n")


if __name__ == "__main__":
    main()
