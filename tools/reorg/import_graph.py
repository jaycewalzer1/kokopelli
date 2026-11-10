"""Package-to-package import graph of the repo, from the source alone (standard library ast).

    python3 tools/reorg/import_graph.py                          # print the table
    python3 tools/reorg/import_graph.py > docs/log/imports-after-phase3.txt

A "package" is a subpackage of the library (kokopelli.wm, kokopelli.loop, ...; kokopelli/settings.py is
kokopelli.settings), an experiment (experiments.exp1, ...), or the first folder under the repo root for everything
else (tools, tests, ...). Each import of a repo module counts once per importing file, so an edge
`kokopelli.life -> experiments.exp1  1` means one file in kokopelli/life/ imports something from experiments/exp1/.
Imports inside functions count too, and `from kokopelli import settings` lands in kokopelli.settings. Bare sibling
imports (`import lunch_wm` after a sys.path.insert) are resolved against the importing file's own folder. Vendored and
generated trees are left out.

The last section lists the edges that go the wrong way under the import contracts in pyproject.toml
([tool.importlinter]), including the allowed ones; `lint-imports` is the check that enforces them.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXCLUDE = ("simworld/", "mac_server/", "vendor/", ".claude/")
ROOT_PKG = "(root)"
TWO_LEVEL = ("kokopelli", "experiments")   # packages split one level further
LAYERS = ["kokopelli.wm", "kokopelli.mind", "kokopelli.loop", "kokopelli.agents"]   # low to high
LIBRARY_ONLY = ("experiments", "tools", "tests")                                   # the library never imports these


def tracked_py() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / p for p in out.splitlines() if not p.startswith(EXCLUDE)]


def package_of(rel: Path) -> str:
    """Package of a file, from its path relative to the root."""
    parts = rel.parts
    if len(parts) == 1:
        return ROOT_PKG
    if parts[0] in TWO_LEVEL:
        second = parts[1] if len(parts) > 2 else Path(parts[1]).stem
        return parts[0] if second == "__init__" else f"{parts[0]}.{second}"
    return parts[0]


def imported_modules(tree: ast.AST, rel: Path) -> list[str]:
    """Dotted module names for every import statement; relative imports made absolute, `from a import b` as a.b."""
    names = []
    here = list(rel.with_suffix("").parts)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                module = ".".join(here[:-node.level] + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            names += [f"{module}.{a.name}" for a in node.names]
    return names


def resolve(name: str, rel: Path, top_dirs: set[str]) -> str | None:
    """Package a module name lands in, or None when it is not repo code."""
    parts = name.split(".")
    if parts[0] in top_dirs:
        if parts[0] in TWO_LEVEL and len(parts) > 1:
            # `from kokopelli import settings` names kokopelli.settings; a name that is neither folder nor module stays at the top
            if (ROOT / parts[0] / parts[1]).is_dir() or (ROOT / parts[0] / f"{parts[1]}.py").exists():
                return f"{parts[0]}.{parts[1]}"
        return parts[0]
    if rel.parent != Path(".") and ((ROOT / rel.parent / f"{parts[0]}.py").exists() or (ROOT / rel.parent / parts[0]).is_dir()):
        return package_of(rel)             # bare sibling import after a sys.path.insert
    return None


def wrong_way(src: str, dst: str) -> str | None:
    """Why an edge breaks a contract, or None."""
    if src.startswith("kokopelli") and dst.split(".")[0] in LIBRARY_ONLY:
        return "library imports outside the library"
    if src == "kokopelli.ops" and dst.startswith("kokopelli") and dst != "kokopelli.ops":
        return "ops imports the rest of the library"
    if src in LAYERS and dst in LAYERS and LAYERS.index(dst) > LAYERS.index(src):
        return "lower layer imports a higher one"
    return None


def main() -> int:
    files = tracked_py()
    top_dirs = {p.relative_to(ROOT).parts[0] for p in files if len(p.relative_to(ROOT).parts) > 1}

    edges: Counter[tuple[str, str]] = Counter()
    examples: dict[tuple[str, str], list[str]] = defaultdict(list)
    for f in files:
        rel = f.relative_to(ROOT)
        src_pkg = package_of(rel)
        try:
            tree = ast.parse(f.read_text(), str(f))
        except SyntaxError as e:
            print(f"# skipped {rel}: {e}", file=sys.stderr)
            continue
        seen: set[str] = set()
        for name in imported_modules(tree, rel):
            dst = resolve(name, rel, top_dirs)
            if dst is None or dst == src_pkg or dst in seen:
                continue
            seen.add(dst)
            edges[(src_pkg, dst)] += 1
            if len(examples[(src_pkg, dst)]) < 3:
                examples[(src_pkg, dst)].append(str(rel))

    width = max(len(p) for e in edges for p in e) + 1
    print("# Package-to-package imports (tools/reorg/import_graph.py)")
    print("# count = files in the source package that import the target package")
    print()
    print(f"{'from':<{width}} {'to':<{width}} {'files':>5}  examples")
    for (a, b), n in sorted(edges.items()):
        print(f"{a:<{width}} {b:<{width}} {n:>5}  {', '.join(examples[(a, b)])}")

    print()
    print("# Cycles (both directions present)")
    cycles = sorted({tuple(sorted(e)) for e in edges if (e[1], e[0]) in edges})
    for a, b in cycles:
        print(f"{a} <-> {b}   ({a} -> {b}: {edges[(a, b)]}, {b} -> {a}: {edges[(b, a)]})")
    if not cycles:
        print("(none)")

    print()
    print(f"# Wrong-way edges (layers low to high: {' -> '.join(LAYERS)}); allowed ones are listed in pyproject.toml")
    bad = [(a, b, why) for (a, b) in sorted(edges) if (why := wrong_way(a, b))]
    for a, b, why in bad:
        print(f"{a} -> {b}   {why}: {', '.join(examples[(a, b)])}")
    if not bad:
        print("(none)")

    print()
    print(f"# {len(files)} files scanned; excluded: {', '.join(EXCLUDE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
