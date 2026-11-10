"""The fast pass of the reorganization: every file move in one go, then the import and path rewrites.

    python3 tools/reorg/migrate.py moves      git mv everything to the new layout (once)
    python3 tools/reorg/migrate.py rewrite    rewrite imports, `-m` launches and repo paths in tracked text (safe to rerun)
    python3 tools/reorg/migrate.py rewrite --dry   print what would change

Kept after the reorg as the record of what moved where. See docs/REORG_PLAN.md and docs/log/reorg/PROGRESS.md.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Folder or file moves, in order. A destination ending in "/" means "into this folder, same name".
MOVES = [
    # the library
    ("core/settings.py", "kokopelli/settings.py"),
    ("core/ram_share.py", "kokopelli/ops/ram_share.py"),
    ("ops/*", "kokopelli/ops/"),
    ("cloud", "kokopelli/ops/cloud"),
    ("core/*", "kokopelli/wm/"),
    ("mind", "kokopelli/mind"),
    ("runtime", "kokopelli/loop"),
    ("homeostatic/watch.py", "life/watch.py"),
    ("life", "kokopelli/life"),
    ("city/agents", "kokopelli/agents"),
    ("city/wm", "kokopelli/wm/controls"),
    # hand-run tools
    ("city/ue", "tools/city_build"),
    ("city/bodies", "tools/bodies"),
    ("city/realism", "tools/realism"),
    ("city/source_arena.py", "tools/moodboard/source_arena.py"),
    ("city/source_commons.py", "tools/moodboard/source_commons.py"),
    ("city/source_tiktok.py", "tools/moodboard/source_tiktok.py"),
    ("city/VIBE.md", "tools/moodboard/VIBE.md"),
    ("scripts/fable", "tools/fable"),
    ("scripts/pace", "tools/pace"),
    # data
    ("city/world.json", "data/city/world.json"),
    # experiments
    ("wm_multicontrol/upstream", "vendor/wm_multicontrol_upstream"),
    ("benchmarks", "experiments/benchmarks"),
    ("exp1", "experiments/exp1"),
    ("homeostatic", "experiments/homeostatic"),
    ("filter_test", "experiments/filter_test"),
    ("wm_multicontrol", "experiments/wm_multicontrol"),
    ("runs/commons", "experiments/commons/results"),
    ("Kokopelli_Perspectives (2).pdf", "docs/Kokopelli_Perspectives.pdf"),
]
REMOVED = ["city/world_varied.json",  # byte-identical to world.json
           "blend.py", "edges.py", "llm_model.py", "ram_share.py", "settings.py", "world_filter.py", "world_model.py",
           "world_multicontrol_base.py", "world_stream.py", "world_stream_multi.py", "world_transfer.py", "world_transfer_multi.py"]

# Old module name -> new module name; the longest matching prefix wins.
MODULES = {
    "core.settings": "kokopelli.settings", "core.ram_share": "kokopelli.ops.ram_share", "core": "kokopelli.wm",
    "ops": "kokopelli.ops", "cloud": "kokopelli.ops.cloud",
    "mind": "kokopelli.mind", "runtime": "kokopelli.loop",
    "life": "kokopelli.life", "homeostatic.watch": "kokopelli.life.watch", "homeostatic": "experiments.homeostatic",
    "exp1": "experiments.exp1", "benchmarks": "experiments.benchmarks",
    "city.agents": "kokopelli.agents", "city.wm": "kokopelli.wm.controls", "city.ue": "tools.city_build", "city.bodies": "tools.bodies",
    # the root stand-ins, imported by bare name
    "settings": "kokopelli.settings", "ram_share": "kokopelli.ops.ram_share",
    **{name: f"kokopelli.wm.{name}" for name in ("blend", "edges", "llm_model", "world_filter", "world_model", "world_multicontrol_base",
                                                 "world_stream", "world_stream_multi", "world_transfer", "world_transfer_multi")},
}
BARE = {"settings", "ram_share", "blend", "edges", "llm_model", "world_filter", "world_model", "world_multicontrol_base", "world_stream",
        "world_stream_multi", "world_transfer", "world_transfer_multi"}
TOPS = sorted({name.split(".")[0] for name in MODULES} - BARE) + ["city"]

# Old repo path -> new repo path, longest first. Matched only at the start of a path (not after a letter, "/", "." or "-").
PATHS = [
    ("core/settings.py", "kokopelli/settings.py"), ("core/ram_share.py", "kokopelli/ops/ram_share.py"), ("core/", "kokopelli/wm/"),
    ("ops/", "kokopelli/ops/"), ("cloud/", "kokopelli/ops/cloud/"), ("mind/", "kokopelli/mind/"),
    ("runtime/", "kokopelli/loop/"),
    ("homeostatic/watch.py", "kokopelli/life/watch.py"), ("life/", "kokopelli/life/"),
    ("city/agents/", "kokopelli/agents/"), ("city/wm/", "kokopelli/wm/controls/"), ("city/ue/", "tools/city_build/"),
    ("city/bodies/", "tools/bodies/"), ("city/realism/", "tools/realism/"), ("city/source_", "tools/moodboard/source_"),
    ("city/VIBE.md", "tools/moodboard/VIBE.md"), ("city/moodboard", "data/moodboard"),
    ("city/world_varied.json", "data/city/world.json"), ("city/world.json", "data/city/world.json"),
    ("scripts/fable/", "tools/fable/"), ("scripts/pace/", "tools/pace/"),
    ("wm_multicontrol/upstream", "vendor/wm_multicontrol_upstream"), ("wm_multicontrol/", "experiments/wm_multicontrol/"),
    ("benchmarks/", "experiments/benchmarks/"), ("exp1/", "experiments/exp1/"), ("homeostatic/", "experiments/homeostatic/"),
    ("filter_test/", "experiments/filter_test/"), ("runs/commons", "experiments/commons/results"),
]
# Text that is history or belongs to someone else: never rewritten.
SKIP = ("docs/", "ops/", "data/", "simworld/", "mac_server/", "vendor/", "tools/reorg/", "CLAUDE.md", "DESIGN.md", "uv.lock", "experiments/commons/results/")
TEXT = (".py", ".sh", ".md", ".toml", ".yaml", ".yml", ".json", ".js", ".html", ".css", ".txt", ".sbatch", ".cfg", "Makefile", ".gitignore")
NOT_MODULE = re.compile(r"\.(py|json|md|txt|log|mp4|png|jpg|db|sh|yaml|yml|csv|js|html|css|npz|safetensors|jsonl)$")


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def new_module(name):
    """The new dotted name for an old one, or None when it isn't one of ours."""
    parts = name.split(".")
    for cut in range(len(parts), 0, -1):
        head = ".".join(parts[:cut])
        if head in MODULES:
            return ".".join([MODULES[head], *parts[cut:]])
    return None


def real_module(fresh):
    """Whether a new dotted name points at a file or folder that exists, judged on its first three parts at most.

    Keeps look-alikes such as the signal name "mind.running" or a made-up "core.x" in a test from being renamed."""
    parts = fresh.split(".")
    for cut in range(min(len(parts), 4), 1, -1):
        base = ROOT.joinpath(*parts[:cut])
        if base.is_dir() or base.with_suffix(".py").is_file():
            return cut >= min(len(parts), 3) or base.with_suffix(".py").is_file()
    return False


def moves():
    for source, target in MOVES:
        sources = sorted(ROOT.glob(source)) if "*" in source else [ROOT / source]
        for path in sources:
            if not path.exists() or not git("ls-files", str(path.relative_to(ROOT))).strip():
                continue                                    # nothing tracked here (already moved, or only ignored files)
            destination = ROOT / target / path.name if target.endswith("/") else ROOT / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            git("mv", str(path.relative_to(ROOT)), str(destination.relative_to(ROOT)))
            print(f"moved {path.relative_to(ROOT)} -> {destination.relative_to(ROOT)}")
    for name in REMOVED:
        if (ROOT / name).exists():
            git("rm", "-q", name)
            print(f"removed {name}")
    for package in ("kokopelli", "kokopelli/mind", "kokopelli/agents", "kokopelli/wm/controls"):
        marker = ROOT / package / "__init__.py"
        if not marker.exists():
            marker.write_text("")
            git("add", str(marker.relative_to(ROOT)))


def rewrite_python(line):
    """One line of Python with its imports of our own modules renamed."""
    def from_import(match):
        fresh = new_module(match[2])
        return f"{match[1]}from {fresh} import" if fresh else match[0]
    line = re.sub(r"^(\s*)from ([\w.]+) import", from_import, line)
    # `from core import ram_share` and `from homeostatic import watch`: the name moved to another package than its old siblings.
    line = re.sub(r"^(\s*)from kokopelli\.wm import (settings|ram_share)\s*$",
                  lambda m: f"{m[1]}from kokopelli{'.ops' if m[2] == 'ram_share' else ''} import {m[2]}\n", line)
    line = re.sub(r"^(\s*)from experiments\.homeostatic import watch\s*$", r"\1from kokopelli.life import watch\n", line)

    def plain_import(match):
        name, alias = match[2], match[3] or ""
        fresh = new_module(name)
        if not fresh:
            return match[0]
        if "." not in name and not alias:                   # `import settings` -> `from kokopelli import settings`, same local name
            head, _, tail = fresh.rpartition(".")
            return f"{match[1]}from {head} import {tail}"
        if "." not in name and alias:
            head, _, tail = fresh.rpartition(".")
            return f"{match[1]}from {head} import {tail}{alias}"
        return f"{match[1]}import {fresh}{alias}"
    line = re.sub(r"^(\s*)import ((?:" + "|".join(sorted(BARE | set(TOPS))) + r")(?:\.\w+)*)( as \w+)?\s*$",
                  lambda m: plain_import(m) + "\n", line)

    def dotted_string(match):
        if NOT_MODULE.search(match[2]):
            return match[0]
        fresh = new_module(match[2])
        return f"{match[1]}{fresh}" if fresh and real_module(fresh) else match[0]
    return re.sub(r"""(["'])((?:""" + "|".join(TOPS) + r""")(?:\.[A-Za-z_]\w*)+)(?=["'.: ])""", dotted_string, line)


def rewrite_text(line):
    """`-m package.module` launches and repo paths, in any kind of file."""
    def launch(match):
        fresh = new_module(match[2])
        return f"{match[1]}{fresh}" if fresh and real_module(fresh) else match[0]
    line = re.sub(r"""(-m["',\s]+)((?:""" + "|".join(TOPS) + r""")(?:\.\w+)*)\b""", launch, line)
    for old, new in PATHS:
        line = re.sub(r"(?<![\w/.\-])" + re.escape(old), new, line)
        line = re.sub(r"(\$\{?[A-Za-z_]+\}?/)" + re.escape(old), lambda m, new=new: m[1] + new, line)   # behind a shell variable: $K/ops/gpu.py
    return line


def rewrite(dry):
    changed = 0
    for name in git("ls-files").splitlines():
        if name.startswith(SKIP) or not name.endswith(TEXT):
            continue
        path = ROOT / name
        if not path.is_file():
            continue
        try:
            before = path.read_text()
        except UnicodeDecodeError:
            continue
        after = []
        for line in before.splitlines(keepends=True):
            # experiments/commons imports its own siblings by bare name, and one of them is called life.py
            fresh = rewrite_python(line) if name.endswith(".py") and not name.startswith("experiments/commons/") else line
            fresh = rewrite_text(fresh)
            if fresh != line and dry:
                print(f"{name}: {line.rstrip()}\n{' ' * len(name)}  {fresh.rstrip()}")
            after.append(fresh)
        after = "".join(after)
        if after != before:
            changed += 1
            if not dry:
                path.write_text(after)
    print(f"{changed} files {'would change' if dry else 'changed'}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["moves"]:
        moves()
    elif sys.argv[1:2] == ["rewrite"]:
        rewrite("--dry" in sys.argv)
    else:
        sys.exit(__doc__)
