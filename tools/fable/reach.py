#!/usr/bin/env python3
"""Reachability evidence for dead-code and stale-Markdown candidates (P2-F1).

Read-only. For every tracked .py outside simworld/, vendor/wm_multicontrol_upstream/
and mac_server/, counts the files that name it (dotted module path, repo path,
or its basename as a whole word) across:
  - tracked .py .sh .md .toml .yaml .yml .cfg .ini .txt .json .js .html, Makefile
  - out/ops/gpu_ledger.jsonl (each job's command line)
  - out/**/*.sh, out/**/*.json, out/**/run*.py (found by name, files < 2 MB)
A file is excluded from its own count, and so are its own tests
(test_<stem>*.py). test_*.py files themselves are skipped: unittest finds
them by name. Zero hits = code candidate.

For every tracked .md (same exclusions) it counts files naming its repo path
or its basename.

Usage: python3 tools/fable/reach.py [--md] [--all]
  default: print code files with 0 hits; --all prints every count;
  --md: print Markdown reference counts instead.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = ("simworld/", "vendor/wm_multicontrol_upstream/", "mac_server/", "out/", "models/")
TEXT_EXT = {".py", ".sh", ".md", ".toml", ".yaml", ".yml", ".cfg", ".ini",
            ".txt", ".json", ".js", ".html", ".css"}
MAX_BYTES = 2_000_000
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    return [p for p in out.splitlines() if p]


def corpus(files):
    """{label: text} for every searched file."""
    docs = {}
    for p in files:
        path = ROOT / p
        if (path.suffix in TEXT_EXT or path.name == "Makefile") and path.is_file():
            if path.stat().st_size <= MAX_BYTES:
                docs[p] = path.read_text(errors="replace")
    out_dir = ROOT / "out"
    ledger = out_dir / "ops" / "gpu_ledger.jsonl"
    if ledger.is_file():
        docs["out/ops/gpu_ledger.jsonl"] = ledger.read_text(errors="replace")
    if out_dir.exists():
        for dirpath, _dirs, names in os.walk(out_dir, followlinks=True):
            for n in names:
                if n.endswith((".sh", ".json")) or (n.startswith("run") and n.endswith(".py")):
                    f = Path(dirpath) / n
                    try:
                        if f.stat().st_size <= MAX_BYTES:
                            docs[str(f.relative_to(ROOT))] = f.read_text(errors="replace")
                    except OSError:
                        pass
    return docs


def hits(target, needles, words, docs, own):
    found = []
    for label, text in docs.items():
        if label == target or label in own:
            continue
        if any(n in text for n in needles) or (words and words & docs_words(label, text)):
            found.append(label)
    return found


_WORDS = {}


def docs_words(label, text):
    if label not in _WORDS:
        _WORDS[label] = set(WORD.findall(text))
    return _WORDS[label]


def main():
    show_all = "--all" in sys.argv
    files = tracked()
    docs = corpus(files)
    print(f"# searched {len(docs)} files", file=sys.stderr)
    keep = [p for p in files if not p.startswith(SKIP)]
    if "--md" in sys.argv:
        for p in sorted(x for x in keep if x.endswith(".md")):
            name = Path(p).name
            found = hits(p, (p,), set(), docs, set())
            by_name = [l for l in docs if l != p and name in docs[l]]
            print(f"{len(found):3d} path  {len(by_name):3d} name  {p}"
                  + ("  <- " + ", ".join(found[:4]) if found else ""))
        return
    for p in sorted(x for x in keep if x.endswith(".py")
                    and not Path(x).name.startswith("test_")):
        stem = Path(p).stem
        mod = p[:-3].replace("/", ".")
        if stem == "__init__":
            mod = mod[: -len(".__init__")]
            stem = Path(mod.replace(".", "/")).name
        own = {f for f in files if Path(f).name.startswith(f"test_{stem}")}
        found = hits(p, (mod, p), {stem}, docs, own)
        if show_all or not found:
            print(f"{len(found):3d}  {p}" + ("  <- " + ", ".join(found[:3]) if found else ""))


if __name__ == "__main__":
    main()
