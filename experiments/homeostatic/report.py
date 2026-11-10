"""Write report.md from finished results. It only states what the saved episodes show."""
import json
from pathlib import Path

from experiments.homeostatic.benchmark import paired_difference
from kokopelli.settings import HOMEOSTATIC_OUT

COLUMNS = [("mean_drive", "mean drive"), ("in_range", "all in range"), ("above", "any above"), ("below", "any below"), ("deaths", "died"),
           ("idle_when_healthy", "idle if healthy"), ("invalid", "invalid"), ("discounted_return", "return")]
COMPARE = [("mean_drive", "lower is better"), ("in_range", "higher is better"), ("above", "overshoot: lower is better")]
ORDER = ["random", "idle", "greedy", "planner", "base", "base-told"]
BASELINE_NOTES = {
    "random": "picks any action", "idle": "never acts", "greedy": "knows the true effects, looks one turn ahead",
    "planner": "knows the true effects, looks four turns ahead (approximate ceiling)", "base": "Qwen3-VL-8B, no training",
    "base-told": "Qwen3-VL-8B, no training, every effect written in its prompt"}


def load_results(out, split):
    results = {}
    for path in sorted((Path(out) / "results").glob(f"*-{split}.json")):
        results[path.name[:-len(f"-{split}.json")]] = json.loads(path.read_text())
    return results


def ordered(names):
    return [name for name in ORDER if name in names] + sorted(name for name in names if name not in ORDER)


def table(results):
    lines = ["| policy | " + " | ".join(label for _, label in COLUMNS) + " |", "|---|" + "---|" * len(COLUMNS)]
    for name in ordered(results):
        cells = [results[name]["summary"][key] for key, _ in COLUMNS]
        lines.append(f"| {name} | " + " | ".join("n/a" if cell is None else f"{cell:.2f}" for cell in cells) + " |")
    return lines


def comparison(results, first, second):
    lines = []
    for metric, direction in COMPARE:
        found = paired_difference(results[first]["episodes"], results[second]["episodes"], metric)
        clear = "clear" if found["low"] > 0 or found["high"] < 0 else "not clear"
        lines.append(f"- {first} minus {second}, {metric} ({direction}): {found['difference']:+.2f} "
                     f"[{found['low']:+.2f}, {found['high']:+.2f}], {clear}")
    return lines


def write_report(out=HOMEOSTATIC_OUT):
    lines = ["# Homeostatic post-training results", "",
             "Each row is the same held-out lives. Trained rows use the adapter that scored best on separate validation lives.",
             "Intervals are 95% paired bootstrap over lives. 'Clear' means the interval excludes zero; it isn't corrected for how many comparisons appear here.", ""]
    for note in ORDER:
        lines.append(f"- {note}: {BASELINE_NOTES[note]}")
    for split, title in (("train", "Healthy ranges like the ones trained on"), ("ood", "Healthy ranges never trained on")):
        results = load_results(out, split)
        if not results:
            continue
        lines += ["", f"## {title}", "", *table(results), ""]
        trained = [name for name in results if name not in ORDER]
        for name in trained:
            if "base" in results:
                lines += comparison(results, name, "base")
            if "base-told" in results:
                lines += comparison(results, name, "base-told")
        for name in (name for name in trained if name.startswith("homeostatic")):
            for control in ("maximize", "shuffled"):
                other = name.replace("homeostatic", control)
                if other in results:
                    lines += comparison(results, name, other)
    text = "\n".join(lines) + "\n"
    (Path(out) / "report.md").write_text(text)
    return text


if __name__ == "__main__":
    print(write_report())
