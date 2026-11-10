"""Package-to-package import graph of the repo, from the source alone (standard library ast).

    python3 tools/reorg/import_graph.py                 # print the table
    python3 tools/reorg/import_graph.py > docs/log/imports-before.txt

A "package" is the first folder under the repo root (life, mind, runtime, ...); files at the root
are grouped as "(root)". Each import of a repo module counts once per importing file, so an edge
`life -> homeostatic  3` means three files in life/ import something from homeostatic/. Imports
inside functions count too. Root stand-ins (`import settings`, `import world_transfer`, ...) are
resolved to the package they alias, using their own `import core.x` line, and listed separately.
Bare sibling imports (`import lunch_wm` after a sys.path.insert) are resolved against the
importing file's own folder. Vendored and generated trees are left out.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXCLUDE = ("simworld/", "mac_server/", "wm_multicontrol/upstream/", ".claude/")
ROOT_PKG = "(root)"


def tracked_py() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / p for p in out.splitlines() if not p.startswith(EXCLUDE)]


def package_of(rel: Path) -> str:
    return rel.parts[0] if len(rel.parts) > 1 else ROOT_PKG


def root_aliases(files: list[Path]) -> dict[str, str]:
    """Root stand-in module name -> the package it aliases (read from its `import core.x` / run_module line)."""
    aliases = {}
    for f in files:
        if f.parent != ROOT:
            continue
        for node in ast.walk(ast.parse(f.read_text(), str(f))):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if "." in a.name and (ROOT / a.name.split(".")[0]).is_dir():
                        aliases[f.stem] = a.name.split(".")[0]
    return aliases


def imported_names(tree: ast.AST) -> list[tuple[str, int]]:
    """(module name, relative level) for every import statement."""
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [(a.name, 0) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append((node.module or "", node.level))
    return names


def resolve(name: str, level: int, rel: Path, top_dirs: set[str], root_mods: set[str]) -> str | None:
    """Package a module name lands in, or None when it is not repo code."""
    if level:                              # relative import: same package
        return package_of(rel)
    head = name.split(".")[0]
    if head in top_dirs:
        return head
    if head in root_mods:
        return ROOT_PKG                    # resolved further through the alias table
    sibling = ROOT / rel.parent / f"{head}.py"
    if rel.parent != Path(".") and (sibling.exists() or (ROOT / rel.parent / head).is_dir()):
        return package_of(rel)             # bare sibling import after a sys.path.insert
    return None


def main() -> int:
    files = tracked_py()
    top_dirs = {p.relative_to(ROOT).parts[0] for p in files if len(p.relative_to(ROOT).parts) > 1}
    root_mods = {p.stem for p in files if p.parent == ROOT}
    aliases = root_aliases(files)

    edges: Counter[tuple[str, str]] = Counter()
    via_alias: Counter[tuple[str, str, str]] = Counter()
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
        for name, level in imported_names(tree):
            dst = resolve(name, level, rel, top_dirs, root_mods)
            head = name.split(".")[0]
            if dst == ROOT_PKG and not level and head in aliases and src_pkg != ROOT_PKG:
                via_alias[(src_pkg, head, aliases[head])] += 1
                dst = aliases[head]
            if dst is None or dst == src_pkg or dst in seen:
                continue
            seen.add(dst)
            edges[(src_pkg, dst)] += 1
            if len(examples[(src_pkg, dst)]) < 3:
                examples[(src_pkg, dst)].append(str(rel))

    print("# Package-to-package imports (tools/reorg/import_graph.py)")
    print("# count = files in the source package that import the target package (root stand-ins resolved)")
    print()
    print(f"{'from':<14} {'to':<14} {'files':>5}  examples")
    for (a, b), n in sorted(edges.items()):
        print(f"{a:<14} {b:<14} {n:>5}  {', '.join(examples[(a, b)])}")

    print()
    print("# Cycles (both directions present)")
    cycles = sorted({tuple(sorted(e)) for e in edges if (e[1], e[0]) in edges})
    for a, b in cycles:
        print(f"{a} <-> {b}   ({a} -> {b}: {edges[(a, b)]}, {b} -> {a}: {edges[(b, a)]})")
    if not cycles:
        print("(none)")

    print()
    print("# Imports through root stand-ins (package, stand-in, real package): import statements")
    for (a, mod, real), n in sorted(via_alias.items()):
        print(f"{a:<14} {mod:<26} -> {real:<10} {n:>4}")

    print()
    print(f"# {len(files)} files scanned; excluded: {', '.join(EXCLUDE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
