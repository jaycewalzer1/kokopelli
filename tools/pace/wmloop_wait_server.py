#!/usr/bin/env python
"""Wait until UnrealCV says hello on a port. Exit 0 when ready, 1 on timeout, with the reason."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from kokopelli.loop.adapters.simworld_wire import SimWorldError, wait_for_server  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    try:
        hello = wait_for_server(args.host, args.port, args.timeout)
    except SimWorldError as e:
        if not args.quiet:
            print(f"Not ready after {args.timeout}s: {e}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"Ready on port {args.port}: {hello!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
