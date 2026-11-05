"""Write a short AI summary and a success rating for a finished GPU queue job, for the panel's GPU tab.

    python3 ops/summarize.py --id TICKET_ID      # one job; gpu.py runs this when a job finishes
    python3 ops/summarize.py --recent 10         # the last 10 finished jobs that have no summary yet

It reads the job's ledger events, its log and its --output files, and asks Claude (`claude -p`, no tools) to say
what happened and rate it against what the job's --about said it would do. Results go to out/ops/results/<id>.json,
and the newest is copied to out/ops/results/latest.json. The rating judges whether the experiment answered its
question, not whether the answer was good news: a clean run that shows training failed can still rate 5.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gpu  # noqa: E402

RESULTS = gpu.STATE / "results"
MODEL = os.environ.get("KOKOPELLI_SUMMARY_MODEL", "sonnet")
LOG_HEAD, LOG_TAIL = 1500, 6000
TEXT_TYPES = {".md", ".json", ".jsonl", ".txt", ".csv", ".log", ".yaml"}
TEXT_EACH, TEXT_TOTAL, FILES_LISTED = 3000, 20000, 40
RATINGS = {5: "answered its question", 4: "mostly answered it", 3: "partly answered it",
           2: "ran, but the answer can't be used", 1: "failed"}

PROMPT = """You are summarizing one finished experiment from a research project's GPU queue, for the project owner,
who will read it on a dashboard. Use only the evidence below. Never invent a number; if the evidence can't show
something, say so.

Reply with JSON only, no code fence, in this shape:
{{"summary": "2 to 4 plain sentences: what it ran, what came out, and what that means",
  "rating": 1-5,
  "rating_reason": "one sentence",
  "key_numbers": ["up to 5 short facts with numbers, copied from the evidence"],
  "caveats": ["up to 3 short limits, such as one seed or mock inputs"]}}

The rating is how well the experiment did what its description says it set out to do, not whether the result was
good news. A clean run that shows an idea failed can rate 5.
5 = {r5}; 4 = {r4}; 3 = {r3}; 2 = {r2}; 1 = {r1} (crashed, timed out, or produced nothing).
If the description is "none given", there's nothing to judge against: set "rating" to null and say so in
"rating_reason", unless the job crashed or produced nothing, which is a 1.

EVIDENCE
{evidence}
"""


def ledger():
    return [json.loads(line) for line in gpu.LEDGER.read_text().splitlines() if line.strip()]


def job_events(job_id):
    return [event for event in ledger() if event.get("id") == job_id]


def read_text(path, limit, tail=False):
    try:
        data = Path(path).read_bytes()
    except OSError:
        return ""
    data = data[-limit:] if tail else data[:limit]
    return data.decode("utf-8", "replace").replace("\r", "\n")


def describe_outputs(outputs):
    """A listing of each output, plus the text of its newest small text files, within a fixed budget."""
    lines, budget = [], TEXT_TOTAL
    for output in outputs:
        path = Path(output)
        if not path.exists():
            lines.append(f"- {output}: doesn't exist")
            continue
        files = [path] if path.is_file() else sorted((p for p in path.rglob("*") if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
        lines.append(f"- {output}: {len(files)} file(s)")
        for file in files[:FILES_LISTED]:
            lines.append(f"  - {file.relative_to(path) if file != path else file.name} ({file.stat().st_size} bytes)")
        for file in [f for f in files if f.suffix in TEXT_TYPES][:4]:
            if budget <= 0:
                break
            text = read_text(file, min(TEXT_EACH, budget), tail=file.suffix in {".jsonl", ".log"})
            budget -= len(text)
            lines.append(f"  Contents of {file.name}{' (end)' if file.suffix in {'.jsonl', '.log'} else ''}:\n{text}")
    return "\n".join(lines)


def guessed_outputs(queued):
    """For jobs queued before --output was required: command arguments that name an existing folder under out/ or runs/."""
    cwd = Path(queued.get("cwd") or gpu.ROOT)
    found = []
    for arg in queued.get("command", []):
        for piece in arg.split("="):
            if re.match(r"(\./)?(out|runs)/", piece) and (cwd / piece).is_dir():
                found.append(str((cwd / piece).resolve()))
    return found[:3]


def evidence(events):
    merged = {}
    for event in events:
        merged.update(event)
    queued = next((e for e in events if e["event"] == "queued"), {})
    log = merged.get("log")
    parts = [f"Name: {merged.get('name')}",
             f"Description: {queued.get('about') or 'none given (queued before descriptions were required)'}",
             f"Command: {' '.join(queued.get('command', []))}",
             f"Where: {merged.get('where', 'local')}",
             f"Exit code: {merged.get('exit_code')}{' (timed out)' if merged.get('timed_out') else ''}",
             f"Ran for: {round(merged.get('seconds', 0) / 60, 1)} min; peak memory {merged.get('peak_rss_gb')} GB"]
    outputs = queued.get("outputs") or guessed_outputs(queued)
    label = "Outputs" if queued.get("outputs") else "Outputs (guessed from the command, since none were listed)"
    parts.append(f"{label}:\n" + (describe_outputs(outputs) if outputs else "none found"))
    if log:
        parts.append(f"Log start:\n{read_text(log, LOG_HEAD)}\n\nLog end:\n{read_text(log, LOG_TAIL, tail=True)}")
    return merged, queued, "\n\n".join(parts)


def ask(prompt):
    claude = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    result = subprocess.run([claude, "-p", "--model", MODEL, "--no-session-persistence", "--tools", "", "--output-format", "text"],
                            input=prompt, capture_output=True, text=True, timeout=300)
    match = re.search(r"\{.*\}", result.stdout, re.S)
    if result.returncode or not match:
        raise RuntimeError(f"claude exited {result.returncode}: {(result.stderr or result.stdout)[-300:]}")
    reply = json.loads(match.group(0))
    rating = reply.get("rating")
    if rating is None:
        return {**reply, "rating": None, "rating_label": "not rated: no description to judge it against"}
    if int(rating) not in RATINGS:
        raise ValueError(f"rating out of range: {rating}")
    return {**reply, "rating": int(rating), "rating_label": RATINGS[int(rating)]}


def summarize(job_id):
    events = job_events(job_id)
    finished = next((e for e in events if e["event"] == "finished"), None)
    if not finished:
        raise SystemExit(f"{job_id} hasn't finished")
    merged, queued, text = evidence(events)
    prompt = PROMPT.format(evidence=text, **{f"r{k}": v for k, v in RATINGS.items()})
    record = {"id": job_id, "name": merged.get("name"), "about": queued.get("about"), "outputs": queued.get("outputs") or guessed_outputs(queued),
              "log": merged.get("log"), "exit_code": merged.get("exit_code"), "seconds": merged.get("seconds"),
              "finished_at": finished["at"], "summarized_at": time.time(), "model": MODEL}
    try:
        record.update(ask(prompt))
    except Exception as error:  # The tab still gets a card, marked as unsummarized, rather than nothing.
        record.update({"summary": None, "rating": None, "error": f"{type(error).__name__}: {error}"})
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{job_id}.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(record, indent=1))
    os.replace(temp, path)
    newest = max(RESULTS.glob("*-*.json"), key=lambda p: json.loads(p.read_text()).get("finished_at", 0))
    shutil.copyfile(newest, RESULTS / "latest.json")
    return record


def recent(count):
    finished = [e for e in ledger() if e["event"] == "finished"]
    todo = [e["id"] for e in finished if not (RESULTS / f"{e['id']}.json").exists()][-count:]
    for job_id in todo:
        record = summarize(job_id)
        print(f"{record['name']}: {record.get('rating')} {record.get('rating_label', record.get('error', ''))}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--id")
    group.add_argument("--recent", type=int)
    args = parser.parse_args()
    if args.id:
        record = summarize(args.id)
        print(json.dumps({k: record.get(k) for k in ("name", "rating", "rating_label", "summary", "error")}, indent=1))
    else:
        recent(args.recent)


if __name__ == "__main__":
    main()
