"""Screenshot a report for DESIGN.md's section 8 checklist: both themes, at desktop width and at 375px.

Run:  python -m experiments.benchmarks.report_screenshots experiments/benchmarks/results/<run_id>/report.html <folder for images>
Headless Chrome's window can't go below 500px, so the 375px views put the page in an iframe. This also measures
whether the page scrolls sideways at 375px, which it mustn't.
"""
import argparse
import html
import re
import subprocess
import tempfile
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HEIGHT = 2400


def chrome(*args, profile):
    return subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={profile}", *args],
                          capture_output=True, text=True, timeout=120)


def overflow_at_375(page, folder, profile):
    """How many pixels wider than 375 the page is. srcdoc makes the iframe same-origin, so a script can measure it."""
    probe = (f'<!doctype html><body><iframe id="f" width="375" height="800" srcdoc="{html.escape(page, quote=True)}"></iframe><pre id="o"></pre>'
             '<script>document.getElementById("f").onload=function(){var d=this.contentDocument.documentElement;'
             'document.getElementById("o").textContent="scrollWidth="+d.scrollWidth+" clientWidth="+d.clientWidth;};</script>')
    path = folder / "probe.html"
    path.write_text(probe)
    dom = chrome("--virtual-time-budget=5000", "--dump-dom", f"file://{path}", profile=profile).stdout
    match = re.search(r"scrollWidth=(\d+) clientWidth=(\d+)", dom)
    return int(match.group(1)) - int(match.group(2)) if match else None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    page = args.report.read_text()
    with tempfile.TemporaryDirectory(prefix="evals_chrome_") as temp:
        folder, profile = Path(temp), Path(temp) / "profile"
        for theme in ("light", "dark"):
            themed = page.replace('<html lang="en">', f'<html lang="en" data-theme="{theme}">')
            (folder / f"{theme}.html").write_text(themed)
            (folder / f"{theme}_375.html").write_text(
                f'<!doctype html><body style="margin:0"><iframe src="{theme}.html" width="375" height="{HEIGHT}" style="border:0"></iframe>')
            chrome(f"--window-size=1200,{HEIGHT}", f"--screenshot={args.out / f'{theme}.png'}", f"file://{folder / f'{theme}.html'}", profile=profile)
            chrome(f"--window-size=500,{HEIGHT}", f"--screenshot={args.out / f'{theme}_375.png'}", f"file://{folder / f'{theme}_375.html'}", profile=profile)
            print(theme, "sideways overflow at 375px:", overflow_at_375(themed, folder, profile), "px")
    print("Images in", args.out)


if __name__ == "__main__":
    main()
