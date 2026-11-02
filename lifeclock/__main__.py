"""Command line: validate, at, run, verify, compare, story."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .clock import MINUTES_PER_DAY, to_t
from .engine import LifeRun
from .store import digests
from .story import render_stack, render_story
from .verify import verify_life
from .world import World


def cmd_validate(args):
    problems = World().validate()
    for p in problems:
        print("PROBLEM", p)
    print(f"{len(problems)} problems")
    return 1 if problems else 0


def cmd_at(args):
    stack = World().at(to_t(args.when))
    print(json.dumps(stack, indent=2) if args.json else render_stack(stack))
    return 0


def cmd_run(args):
    world = World()
    stop = to_t(args.until) // MINUTES_PER_DAY if args.until else None
    chain, complete = LifeRun(world, args.db).run(
        wall_seconds=args.wall_seconds, stop_before_day=stop, heartbeat_seconds=args.heartbeat,
    )
    print(json.dumps({"chain": chain, "complete": complete}))
    return 0


def cmd_verify(args):
    conn = sqlite3.connect(args.db)
    problems, facts = verify_life(conn, deep=not args.shallow)
    if args.expect_wall is not None:
        info = dict(conn.execute("SELECT key, value FROM run_info"))
        elapsed = float(info["wall_finished"]) - float(info["wall_started"])
        facts["wall_elapsed_seconds"] = round(elapsed, 1)
        facts["peak_lag_seconds"] = round(float(info.get("peak_lag_seconds", 0)), 2)
        facts["audits"] = int(info.get("audits", 0))
        facts["audit_failures"] = int(info.get("audit_failures", 0))
        if facts["audits"] == 0:
            problems.append("a paced run performed no audits")
        if facts["audit_failures"]:
            problems.append(f"{facts['audit_failures']} audits failed")
        if abs(elapsed - args.expect_wall) > args.wall_tolerance:
            problems.append(
                f"run took {elapsed:.1f}s of wall time, expected "
                f"{args.expect_wall}s +/- {args.wall_tolerance}s"
            )
    print(json.dumps(facts, indent=2))
    for p in problems[:50]:
        print("PROBLEM", p)
    print(f"{len(problems)} problems")
    if args.out:
        Path(args.out).write_text(json.dumps({"problems": problems, "facts": facts}, indent=2))
    return 1 if problems else 0


def cmd_compare(args):
    a = digests(sqlite3.connect(args.a))
    b = digests(sqlite3.connect(args.b))
    differing = [k for k in a if a[k] != b[k]]
    print(json.dumps({"a": a, "b": b, "differing": differing}, indent=2))
    if differing or not a["complete"]:
        print("MISMATCH:", differing or "incomplete")
        return 1
    print("IDENTICAL")
    return 0


def cmd_story(args):
    conn = sqlite3.connect(args.db) if args.db else None
    text = render_story(World(), conn)
    if args.out:
        Path(args.out).write_text(text)
    else:
        sys.stdout.write(text)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="lifeclock")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check the canon for contradictions")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("at", help="read the full stack at one minute")
    p.add_argument("when", help="YYYY-MM-DDTHH:MM")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_at)

    p = sub.add_parser("run", help="tick the clock across the life; resumes if the db exists")
    p.add_argument("--db", required=True)
    p.add_argument("--wall-seconds", type=float, help="stretch the whole life over this much real time")
    p.add_argument("--until", help="stop before this date")
    p.add_argument("--heartbeat", type=float, default=30.0)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("verify", help="check a finished life against every invariant")
    p.add_argument("--db", required=True)
    p.add_argument("--shallow", action="store_true", help="skip the full replay")
    p.add_argument("--expect-wall", type=float)
    p.add_argument("--wall-tolerance", type=float, default=60.0)
    p.add_argument("--out")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("compare", help="confirm two runs produced the same life")
    p.add_argument("a")
    p.add_argument("b")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("story", help="render the world story as Markdown")
    p.add_argument("--db")
    p.add_argument("--out")
    p.set_defaults(func=cmd_story)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
