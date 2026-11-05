"""One report per run, as markdown and standalone HTML: tables, CI plots, per-template results, parse failures,
guardrail deltas, human norms, and pass or fail against the pre-registration.

Run:  python -m benchmarks.report benchmarks/results/<run_id>

The HTML follows DESIGN.md and inlines its tokens. The rule is one clay element and one gold hairline per page. So the
clay marks only the key arm on the first chart, and the gold hairline is only the human norm on that same chart.
"""
import argparse
import html
import json
from pathlib import Path

import numpy as np
import pandas as pd

from benchmarks import stats
from benchmarks.registry import instrument_entries, load_contrasts, load_norms
from benchmarks.run import read_results

KEY_ARM = "lived"
ARM_ORDER = ["base", "lived", "described", "shuffled", "flipped_lived", "rendered_lived"]
INVALID_WARNING = 0.05

CSS = """
:root { color-scheme: light dark; --surface-100: #F3EEE6; --surface-200: #EAE3D8; --umber: #3B2A22; --hairline: #CFC4B4; --ink: #2B1E18; --ink-muted: #6E6056; --clay: #8F4739; --gold: #9A7B40; --danger: #9E2A22; --sage: #5E6B4E; --slate: #4F5F6B;
  --font-serif: "Fraunces", Georgia, serif; --font-sans: "Work Sans", system-ui, sans-serif; --font-mono: "JetBrains Mono", ui-monospace, monospace;
  --space-2: 8px; --space-4: 16px; --space-6: 24px; --space-12: 48px; --radius-none: 0px; --radius-sm: 2px; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --surface-100: #14100D; --surface-200: #1E1814; --umber: #33271F; --hairline: #3A302A; --ink: #EDE5DA; --ink-muted: #A89A8C; --clay: #C07A62; --gold: #C4A66B; --danger: #E8877C; --sage: #9AA88A; --slate: #8E9EAA; } }
:root[data-theme="dark"] { --surface-100: #14100D; --surface-200: #1E1814; --umber: #33271F; --hairline: #3A302A; --ink: #EDE5DA; --ink-muted: #A89A8C; --clay: #C07A62; --gold: #C4A66B; --danger: #E8877C; --sage: #9AA88A; --slate: #8E9EAA; color-scheme: dark; }
:root[data-theme="light"] { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--surface-100); color: var(--ink); font-family: var(--font-sans); font-size: 16px; line-height: 24px; }
main { max-width: 960px; margin: 0 auto; padding: var(--space-12) var(--space-6); }
h1, h2, p { margin: 0; }
h1 { font: 300 40px/44px var(--font-serif); overflow-wrap: anywhere; }
h2 { font: 400 28px/34px var(--font-serif); margin-bottom: var(--space-4); }
p { max-width: 65ch; }
.eyebrow { display: block; font: 400 11px/16px var(--font-mono); text-transform: uppercase; letter-spacing: 0.12em; color: var(--ink-muted); overflow-wrap: anywhere; }
.ruled { padding-bottom: var(--space-2); margin-bottom: var(--space-2); border-bottom: 1px solid var(--hairline); }
.small { font: 400 13px/18px var(--font-sans); color: var(--ink-muted); }
section { margin-top: var(--space-12); }
.card { background: var(--surface-200); border: 1px solid var(--hairline); padding: var(--space-4); margin-top: var(--space-4); }
.alert { border-left: 1px solid var(--ink-muted); padding-left: var(--space-4); margin-top: var(--space-4); }
.scroll { overflow-x: auto; margin-top: var(--space-4); }
table { border-collapse: collapse; width: 100%; font: 400 13px/20px var(--font-mono); }
th { text-align: left; font: 400 11px/16px var(--font-mono); text-transform: uppercase; letter-spacing: 0.12em; color: var(--ink-muted); }
th, td { padding: var(--space-2); border-bottom: 1px solid var(--hairline); vertical-align: top; white-space: nowrap; }
td.wrap { white-space: normal; min-width: 168px; }
.sub { display: block; color: var(--ink-muted); }
.mark { display: inline-block; width: 8px; height: 8px; margin-right: var(--space-2); border: 1px solid var(--ink-muted); }
.mark.pass { background: var(--sage); border-color: var(--sage); }
.chart { margin-top: var(--space-4); }
.row { display: grid; grid-template-columns: 112px 1fr 104px; gap: var(--space-2); align-items: center; min-height: 32px; }
.row .name, .row .value { font: 400 13px/20px var(--font-mono); overflow-wrap: anywhere; }
.row .value { text-align: right; }
.track { position: relative; height: 24px; border-bottom: 1px solid var(--hairline); }
.ci { position: absolute; top: 12px; height: 1px; background: var(--ink); }
.dot { position: absolute; top: 9px; width: 7px; height: 7px; margin-left: -3px; background: var(--ink); }
.ci.key, .dot.key { background: var(--clay); }
.norm { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--gold); }
.norm.quiet { background: var(--ink-muted); }
.axis { display: flex; justify-content: space-between; font: 400 11px/16px var(--font-mono); color: var(--ink-muted); }
.axis-row { display: grid; grid-template-columns: 112px 1fr 104px; gap: var(--space-2); }
footer { margin-top: var(--space-12); padding-top: var(--space-4); border-top: 1px solid var(--hairline); }
@media (max-width: 600px) {
  main { padding: var(--space-6) var(--space-4); }
  h1 { font-size: 32px; line-height: 36px; }
  .row, .axis-row { grid-template-columns: 104px 1fr 48px; }
}
"""


def fmt(value, digits=2):
    if value is None or value != value:
        return "-"
    return f"{value:.{digits}f}"


def _sorted_arms(table):
    rank = {arm: i for i, arm in enumerate(ARM_ORDER)}
    return table.assign(_r=table.arm.map(lambda a: rank.get(a, 99))).sort_values(["_r", "arm"]).drop(columns="_r")


def _human_lines(norms):
    if not norms:
        return []
    lines = [{"label": n["label"], "value": n["mean"], "sd": n.get("sd"), "n": n.get("n"), "source": n["source"], "primary": n["id"] == norms.get("primary")}
             for n in norms.get("norms", [])]
    return lines


def collect(out):
    """Compute everything a report needs. Both formats draw from this, so they can't disagree."""
    out = Path(out)
    rows = read_results(out)
    if not rows:
        raise FileNotFoundError(f"No results in {out}")
    record = json.loads((out / "run_record.json").read_text())
    frame = stats.to_frame(rows)
    entries = instrument_entries()
    instruments = sorted(frame.instrument.unique(), key=lambda name: list(entries).index(name) if name in entries else 99)
    contrasts = stats.evaluate_contrasts(frame, load_contrasts())
    contrasts = contrasts[contrasts.status != "not run"]
    return {"record": record, "frame": frame, "instruments": instruments, "entries": entries,
            "arms": stats.arm_table(frame), "templates": stats.template_table(frame), "seeds": stats.seed_table(frame),
            "failures": stats.parse_failures(rows), "contrasts": contrasts, "n_rows": len(rows),
            "sanity": _sanity(rows), "consistency": _consistency(rows)}


def _sanity(rows):
    """Share of no-rare-event travel items answered correctly, per arm."""
    table = [{"arm": r["arm"], "correct": r["extras"]["sanity_correct"]} for r in rows if r["valid"] and r["extras"].get("sanity")]
    return pd.DataFrame(table).groupby("arm", as_index=False).correct.mean() if table else pd.DataFrame()


def _consistency(rows):
    """Rates per arm, plus the pre-registered sensitivity check: mean safe choices with inconsistent ladders left out."""
    table = [{"arm": r["arm"], "multiple": r["extras"]["multiple_switching"], "dominated": r["extras"]["dominated"], "consistent": r["extras"]["consistent"],
              "safe_all": r["score"], "safe_consistent": r["score"] if r["extras"]["consistent"] else None}
             for r in rows if r["valid"] and r["instrument"] == "holt_laury"]
    if not table:
        return pd.DataFrame()
    frame = pd.DataFrame(table)
    frame["safe_consistent"] = pd.to_numeric(frame["safe_consistent"])
    return frame.groupby("arm", as_index=False).mean()


def _warnings(data):
    notes = []
    record = data["record"]
    if not record.get("real"):
        notes.append("Mock run: these numbers come from a pretend model and say nothing about any real model.")
    if record.get("exploratory"):
        notes.append("Exploratory run: a base-model check, not a test of any hypothesis.")
    if not data["failures"].empty:
        high = data["failures"][data["failures"].invalid_rate > INVALID_WARNING]
        for _, row in high.iterrows():
            notes.append(f"{row.instrument} / {row.arm}: {row.invalid_rate:.0%} of answers were invalid, above the {INVALID_WARNING:.0%} warning line.")
    stubs = [name for name in data["instruments"] if name == "near_errand"]
    if stubs:
        notes.append("near_errand is a stub: its shortcut rate comes from one text prompt, not from an agent acting in a world.")
    return notes


# ---------- markdown ----------

def _md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def _contrast_cells(row):
    return [row["id"], f"{row['a']} - {row['b']}", row["instrument"], fmt(row["difference"], 3), f"[{fmt(row['ci_low'], 3)}, {fmt(row['ci_high'], 3)}]",
            fmt(row["d"]), fmt(row["p"], 4), fmt(row["p_holm"], 4), f"{row['seeds_right']}/{row['seeds_total']}" if row["kind"] == "difference" else "-", row["status"]]


CONSISTENCY_HEADERS = ["arm", "multiple switching", "dominated", "consistent", "safe choices, all", "safe choices, consistent only"]


def _consistency_rows(data):
    return [[r.arm, fmt(r.multiple), fmt(r.dominated), fmt(r.consistent), fmt(r.safe_all), fmt(r.safe_consistent)] for _, r in data["consistency"].iterrows()]


CONTRAST_HEADERS = ["contrast", "arms", "instrument", "difference", "95% CI", "d", "p", "p (Holm)", "seeds right", "status"]


def to_markdown(data):
    record = data["record"]
    parts = [f"# Evaluation report: {record['run_id']}", "",
             f"Backend {record['backend']}. Commit {record['sessions'][-1]['git']['commit'][:10]}. {data['n_rows']} results.", ""]
    parts += [f"**Note:** {note}\n" for note in _warnings(data)]
    if not data["contrasts"].empty:
        parts += ["## Pre-registered contrasts", "", _md_table(CONTRAST_HEADERS, [_contrast_cells(r) for _, r in data["contrasts"].iterrows()]), ""]
    for name in data["instruments"]:
        parts += [f"## {name}", ""]
        arms = _sorted_arms(data["arms"][data["arms"].instrument == name])
        parts.append(_md_table(["arm", "n", "mean", "sd", "95% CI"], [[r.arm, r.n, fmt(r["mean"], 3), fmt(r.sd), f"[{fmt(r.ci_low, 3)}, {fmt(r.ci_high, 3)}]"] for _, r in arms.iterrows()]))
        lines = _human_lines(load_norms(name))
        if lines:
            parts += ["", "Human norms:", "", _md_table(["group", "mean", "sd", "n", "source"], [[l["label"], l["value"], l["sd"] or "-", l["n"] or "-", l["source"]] for l in lines])]
        templates = _sorted_arms(data["templates"][data["templates"].instrument == name])
        parts += ["", "Per template:", "", _md_table(["template", "arm", "n", "mean", "95% CI"], [[r.template, r.arm, r.n, fmt(r["mean"], 3), f"[{fmt(r.ci_low, 3)}, {fmt(r.ci_high, 3)}]"] for _, r in templates.sort_values("template").iterrows()]), ""]
    if not data["consistency"].empty:
        parts += ["## Holt-Laury consistency", "", _md_table(CONSISTENCY_HEADERS, _consistency_rows(data)), ""]
    if not data["sanity"].empty:
        parts += ["## Travel sanity items", "", _md_table(["arm", "share correct"], [[r.arm, fmt(r.correct)] for _, r in data["sanity"].iterrows()]), ""]
    parts += ["## Parse failures", "", _md_table(["instrument", "arm", "n", "retried", "invalid", "invalid rate"], [[r.instrument, r.arm, r.n, r.retried, r.invalid, fmt(r.invalid_rate, 3)] for _, r in data["failures"].iterrows()]), ""]
    parts += ["## Run record", "", f"Sampling: `{json.dumps(record['sampling'])}`", "", f"Item hashes: `{json.dumps(record['item_hashes'])}`", "", f"Pre-registration: `{json.dumps(record['prereg'])}`", ""]
    return "\n".join(parts)


# ---------- html ----------

def _e(value):
    return html.escape(str(value))


def _table(headers, rows):
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(cell if str(cell).startswith("<td") else f"<td>{_e(cell)}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _chart(arms, norm_lines, use_accents):
    """Each arm's mean and CI as a row, built with HTML, so labels stay readable at any width."""
    values = list(arms.ci_low) + list(arms.ci_high) + [line["value"] for line in norm_lines]
    low, high = float(np.nanmin(values)), float(np.nanmax(values))
    pad = max((high - low) * 0.1, 1e-6)
    low, high = low - pad, high + pad
    def x(value):
        return (value - low) / (high - low) * 100
    primary = next((line for line in norm_lines if line["primary"]), None)
    norm = ""
    if primary:
        kind = "norm" if use_accents else "norm quiet"
        norm = f'<span class="{kind}" style="left:{x(primary["value"]):.2f}%" title="{_e(primary["label"])}"></span>'
    rows = []
    for _, row in arms.iterrows():
        key = " key" if use_accents and row.arm == KEY_ARM else ""
        rows.append(f'<div class="row"><span class="name">{_e(row.arm)}</span><div class="track">{norm}'
                    f'<span class="ci{key}" style="left:{x(row.ci_low):.2f}%;width:{max(x(row.ci_high) - x(row.ci_low), 0.3):.2f}%"></span>'
                    f'<span class="dot{key}" style="left:{x(row["mean"]):.2f}%"></span></div>'
                    f'<span class="value">{fmt(row["mean"])}</span></div>')
    axis = f'<div class="axis-row"><span></span><div class="axis"><span>{fmt(low)}</span><span>{fmt(high)}</span></div><span></span></div>'
    caption = f'<p class="small">Square: mean. Line: 95% bootstrap interval.{" Vertical line: " + _e(primary["label"]) + "." if primary else ""}</p>'
    return f'<div class="chart">{"".join(rows)}{axis}</div>{caption}'


def _status_cell(status):
    mark = "pass" if status.startswith("pass") else ""
    return f'<td class="wrap"><span class="mark {mark}"></span>{_e(status)}</td>'


def to_html(data):
    record = data["record"]
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
             f'<title>Evaluation Report</title><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400&family=Work+Sans:wght@400;500&family=JetBrains+Mono:wght@400&display=swap"><style>{CSS}</style></head><body><main>',
             f'<span class="eyebrow ruled">Kokopelli evaluation report</span><h1>{_e(record["run_id"])}</h1>',
             f'<p class="small" style="margin-top:8px">Backend {_e(record["backend"])}, commit {_e(record["sessions"][-1]["git"]["commit"][:10])}, {data["n_rows"]} results.</p>']
    for note in _warnings(data):
        parts.append(f'<div class="alert"><p>{_e(note)}</p></div>')

    if not data["contrasts"].empty:
        # Status comes right after the name, so it's visible without scrolling at any width.
        cells = []
        for _, row in data["contrasts"].iterrows():
            values = _contrast_cells(row)
            name = f'<td>{_e(row["id"])}<span class="sub">{_e(values[1])}</span></td>'
            cells.append([name, _status_cell(row["status"])] + values[3:-1])
        parts.append(f'<section><span class="eyebrow ruled">Against the pre-registration</span><h2>Contrasts</h2>{_table(["contrast", "status"] + CONTRAST_HEADERS[3:-1], cells)}'
                     '<p class="small" style="margin-top:8px">Difference is the first arm minus the second. Holm-corrected p-values cover the difference contrasts together.</p></section>')

    accents_used = False
    for name in data["instruments"]:
        arms = _sorted_arms(data["arms"][data["arms"].instrument == name])
        entry = data["entries"].get(name, {})
        norms = load_norms(name)
        lines = _human_lines(norms)
        # Accents go on the first chart with a human norm, or there'd be more than one clay or gold mark on the page.
        accents = bool(lines) and not accents_used
        accents_used = accents_used or accents
        role = "Guardrail" if entry.get("role") == "guardrail" else f"{entry.get('transfer', '')} transfer"
        parts.append(f'<section><span class="eyebrow ruled">{_e(role)}</span><h2>{_e(name)}</h2>')
        parts.append(_chart(arms, lines, accents))
        parts.append(_table(["arm", "n", "mean", "sd", "95% CI"], [[r.arm, r.n, fmt(r["mean"], 3), fmt(r.sd), f"[{fmt(r.ci_low, 3)}, {fmt(r.ci_high, 3)}]"] for _, r in arms.iterrows()]))
        if lines:
            parts.append('<div class="card"><span class="eyebrow">Human norms, for scale</span>' + _table(["group", "mean", "sd", "n", "source"], [
                [f"<td class=\"wrap\">{_e(l['label'])}</td>", l["value"], l["sd"] or "-", l["n"] or "-", f"<td class=\"wrap\">{_e(l['source'])}</td>"] for l in lines]) + '</div>')
        templates = data["templates"][data["templates"].instrument == name]
        if templates.template.nunique() > 1:
            ordered = _sorted_arms(templates).sort_values("template", kind="stable")
            parts.append('<p class="small" style="margin-top:16px">Per template</p>' + _table(["template", "arm", "n", "mean", "95% CI"], [[r.template, r.arm, r.n, fmt(r["mean"], 3), f"[{fmt(r.ci_low, 3)}, {fmt(r.ci_high, 3)}]"] for _, r in ordered.iterrows()]))
        parts.append('</section>')

    if not data["consistency"].empty:
        parts.append('<section><span class="eyebrow ruled">Holt-Laury</span><h2>Consistency</h2>' + _table(CONSISTENCY_HEADERS, _consistency_rows(data)) + '<p class="small" style="margin-top:8px">The last two columns are a sensitivity check: if they tell different stories, inconsistent answers are driving the result.</p></section>')
    if not data["sanity"].empty:
        parts.append('<section><span class="eyebrow ruled">Travel</span><h2>Sanity items</h2>' + _table(["arm", "share correct"], [[r.arm, fmt(r.correct)] for _, r in data["sanity"].iterrows()]) + '</section>')
    parts.append('<section><span class="eyebrow ruled">Data quality</span><h2>Parse failures</h2>' + _table(["instrument", "arm", "n", "retried", "invalid", "rate"], [[r.instrument, r.arm, r.n, r.retried, r.invalid, fmt(r.invalid_rate, 3)] for _, r in data["failures"].iterrows()]) + '</section>')
    parts.append(f'<footer><span class="eyebrow ruled">Run record</span><p class="small" style="overflow-wrap:anywhere">Sampling: {_e(json.dumps(record["sampling"]))}</p><p class="small" style="overflow-wrap:anywhere;margin-top:8px">Pre-registration: {_e(json.dumps(record["prereg"]))}</p></footer>')
    parts.append('</main></body></html>')
    return "".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run")
    args = parser.parse_args()
    data = collect(args.run)
    out = Path(args.run)
    (out / "report.md").write_text(to_markdown(data))
    (out / "report.html").write_text(to_html(data))
    print(f"Wrote {out / 'report.md'} and {out / 'report.html'}")


if __name__ == "__main__":
    main()
