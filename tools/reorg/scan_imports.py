"""List how tracked Python files import the repo's own modules, grouped by form. Read-only helper for the reorg."""
import ast, collections, subprocess, sys

SKIP = ("simworld/", "mac_server/", "wm_multicontrol/upstream/", "vendor/")
files = [f for f in subprocess.check_output(["git", "ls-files", "*.py"], text=True).split() if not f.startswith(SKIP)]
import os
tops = {f.split("/")[0] for f in files if "/" in f} | {f[:-3] for f in files if "/" not in f}
# sibling-style imports: a module named like a file in the importer's own folder
forms = collections.Counter(); samples = collections.defaultdict(list); sibling = collections.defaultdict(set)
for f in files:
    try: tree = ast.parse(open(f).read())
    except SyntaxError as e: print("SYNTAX", f, e); continue
    here = {n[:-3] for n in os.listdir(os.path.dirname(f) or ".") if n.endswith(".py")} | {n for n in os.listdir(os.path.dirname(f) or ".") if os.path.isdir(os.path.join(os.path.dirname(f) or ".", n))}
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import): names = [("import", a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module: names = [("from", node.module)]
        elif isinstance(node, ast.ImportFrom) and node.level: forms["relative"] += 1
        for kind, name in names:
            top = name.split(".")[0]
            if top in tops:
                forms[(kind, top)] += 1
                if len(samples[(kind, top)]) < 2: samples[(kind, top)].append(f"{f}:{node.lineno} {name}")
            elif "/" in f and top in here and top not in sys.stdlib_module_names:
                sibling[os.path.dirname(f)].add(top)
for k, v in sorted(forms.items(), key=str): print(v, k, samples.get(k, ""))
print("SIBLING-STYLE (folder: modules imported by bare name)")
for d, m in sorted(sibling.items()): print(" ", d, sorted(m))
