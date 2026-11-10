"""Report what is in out/ and what the retention rule in docs/OUT_LAYOUT.md would let the owner delete.

Read-only: it runs `du`, stats files and reads Markdown/text to find cited paths. It never deletes, moves or writes anything.

    .venv/bin/python ops/out_report.py               # areas, runs over 50 MB, deletion candidates
    .venv/bin/python ops/out_report.py --min-mb 0    # every run
    .venv/bin/python ops/out_report.py --root /Volumes/backup/out

A "run" is any entry one level under an area (out/<area>/<run>). Sizes come from `du -k -d 2`, so the total is du's own figure.
Retention classes (first match wins): cited or golden = keep; smoke = 7 days; intermediate (holds .npy or a frames dir) = 30 days;
anything else = keep until the owner sorts it. Age is days since the newest file in the run changed. Standard library only.
"""
import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SIDECARS = ("run.json", "manifest.json", "meta.json")
# Narrow on purpose: "test" and "probe" also name real inputs and sweeps (filter_test/test_clip_garden, homeostatic/probe-*).
SMOKE = re.compile(r"smoke|scratch|tmp|debug|dry.?run|memtest", re.I)
GOLDEN = re.compile(r"golden", re.I)
LIMIT_DAYS = {"smoke": 7, "intermediate": 30}
CITE = re.compile(r"\bout/([\w.\-]+)(?:/([\w.\-]+))?")
TEXT_SUFFIXES = {".md", ".py", ".sh", ".json", ".txt", ".toml", ".cfg", ".ini", ".mjs", ".js"}
SKIP_TRACKED = ("simworld/", "wm_multicontrol/upstream/")


def du(root):
    """Sizes in KB for root and every entry up to two levels down, from one `du` call."""
    out = subprocess.run(["du", "-k", "-d", "2", str(root)], capture_output=True, text=True).stdout
    sizes = {}
    for line in out.splitlines():
        kb, _, path = line.partition("\t")
        rel = os.path.relpath(path, root)
        sizes[() if rel == "." else tuple(Path(rel).parts)] = int(kb)
    return sizes  # directories only: plain files at depth 1-2 get their figure from file_kb()


def file_kb(path):
    st = os.lstat(path)
    return st.st_blocks * 512 // 1024


def scan(path):
    """Newest file (mtime, relative path), file count, .npy KB, has-frames-dir and sidecar/README presence under path."""
    info = {"newest": (0.0, ""), "files": 0, "npy_kb": 0, "frames": False, "sidecar": False, "readme": False, "md": []}

    def note(entry, rel):
        st = entry.stat(follow_symlinks=False)
        info["files"] += 1
        if entry.name != ".DS_Store" and st.st_mtime > info["newest"][0]:
            info["newest"] = (st.st_mtime, rel)
        if entry.name.endswith(".npy"):
            info["npy_kb"] += st.st_blocks * 512 // 1024
        if entry.name in SIDECARS:
            info["sidecar"] = True
        if entry.name.upper().startswith("README"):
            info["readme"] = True
        if entry.name.endswith(".md") and st.st_size < 1_000_000:
            info["md"].append(entry.path)

    if os.path.islink(path) or not os.path.isdir(path):
        parent = os.path.dirname(path)
        note(next(e for e in os.scandir(parent) if e.path == path), os.path.basename(path))
        return info
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.lower().startswith("frames") or entry.name.lower().endswith("_frames"):
                            info["frames"] = True
                        stack.append(entry.path)
                    else:
                        note(entry, os.path.relpath(entry.path, path))
        except OSError:
            continue
    return info


def cited_paths(root, extra_md):
    """(area, run) pairs and bare areas named as out/<area>/<run> in tracked text files and Markdown inside out/."""
    files = []
    try:
        tracked = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True).stdout.split("\n")
        files = [REPO / f for f in tracked if f and Path(f).suffix in TEXT_SUFFIXES and not f.startswith(SKIP_TRACKED)]
    except OSError:
        pass
    files += [Path(p) for p in extra_md]
    cites = {}
    for f in files:
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        inside = os.path.relpath(f, root).split(os.sep) if str(f).startswith(root + os.sep) else None
        where = "out/" + "/".join(inside) if inside else os.path.relpath(f, REPO)
        for area, run in CITE.findall(text):
            key = (area, run) if run else (area,)
            if inside and list(key) == inside[:len(key)]:
                continue  # a run's own notes don't make it cited
            cites.setdefault(key, where)
    return cites


def classify(area, name, info, cites):
    key = (area, name)
    if key in cites:
        return "keep", f"cited in {cites[key]}"
    if GOLDEN.search(name):
        return "keep", "golden"
    if SMOKE.search(name):
        return "smoke", "name looks like a smoke/test run"
    if info["npy_kb"] or info["frames"]:
        return "intermediate", "holds .npy or frames"
    return "keep", "unclassified (owner decides)"


def human(kb):
    for unit, size in (("G", 1024 ** 2), ("M", 1024)):
        if kb >= size:
            return f"{kb / size:.1f}{unit}"
    return f"{kb}K"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=str(REPO / "out"), help="the out/ directory to report on (default: this repo's)")
    parser.add_argument("--min-mb", type=float, default=50, help="list runs at least this big (default 50; 0 lists all)")
    args = parser.parse_args(argv)
    root = os.path.realpath(args.root)
    started = time.time()
    now = time.time()
    sizes = du(root)

    areas, runs, md = [], [], []
    for entry in sorted(os.scandir(root), key=lambda e: e.name):
        kb = sizes.get((entry.name,)) or file_kb(entry.path)
        info = scan(entry.path)
        md += info["md"]
        areas.append((entry.name, kb, info))
        if entry.is_dir(follow_symlinks=False):
            for sub in sorted(os.scandir(entry.path), key=lambda e: e.name):
                if sub.name == ".DS_Store":
                    continue
                skb = sizes.get((entry.name, sub.name))
                if skb is None:
                    skb = file_kb(sub.path)
                runs.append((entry.name, sub.name, skb, scan(sub.path)))
    cites = cited_paths(root, md)

    def age(info):
        return (now - info["newest"][0]) / 86400 if info["newest"][0] else float("inf")

    print(f"out/ report: {root}")
    print(f"{'area':24} {'size':>7} {'files':>6} {'age_d':>6} {'side':>4} {'rdme':>4}  newest file")
    for name, kb, info in areas:
        print(f"{name:24} {human(kb):>7} {info['files']:>6} {age(info):>6.0f} {'y' if info['sidecar'] else '-':>4} "
              f"{'y' if info['readme'] else '-':>4}  {info['newest'][1][:60]}")

    shown = [r for r in runs if r[2] >= args.min_mb * 1024]
    print(f"\nRuns >= {args.min_mb:g} MB ({len(shown)} of {len(runs)}):")
    print(f"{'area/run':48} {'size':>7} {'npy':>7} {'age_d':>6} {'side':>4} {'class':13} reason")
    candidates = []
    for area, name, kb, info in runs:
        cls, why = classify(area, name, info, cites)
        limit = LIMIT_DAYS.get(cls)
        if limit is not None and age(info) > limit:
            candidates.append((area, name, kb, info, cls, limit))
        if kb >= args.min_mb * 1024:
            print(f"{area + '/' + name:48} {human(kb):>7} {human(info['npy_kb']):>7} {age(info):>6.0f} "
                  f"{'y' if info['sidecar'] else '-':>4} {cls:13} {why}")

    cand_kb = sum(c[2] for c in candidates)
    print(f"\nDeletion candidates by the retention rule ({len(candidates)}, {human(cand_kb)}). Nothing was deleted:")
    for area, name, kb, info, cls, limit in sorted(candidates, key=lambda c: -c[2]):
        print(f"  {human(kb):>7}  out/{area}/{name}  ({cls}, {age(info):.0f} d > {limit} d)")

    top_sum = sum(kb for _, kb, _ in areas)
    total = sizes.get((), top_sum)
    print(f"\nTotal (du -sk): {human(total)} ({total} KB); sum of top-level entries {human(top_sum)} ({top_sum} KB); "
          f"{sum(i['files'] for _, _, i in areas)} files; {time.time() - started:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
