"""Replay a run in the browser, from its log and the files beside it. Reads only; there is nothing to edit."""
import argparse
import json
import mimetypes
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from runtime import replay

STATIC = Path(__file__).with_name("static")
DESIGN_CSS = Path(__file__).parent.parent / "life" / "static" / "design.css"
PAGES = {"/": STATIC / "viewer.html", "/viewer.css": STATIC / "viewer.css", "/viewer.js": STATIC / "viewer.js", "/design.css": DESIGN_CSS}


def make_handler(run_dir):
    run_dir = Path(run_dir).resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, body, content_type):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            if path == "/api/run":
                return self._send(json.dumps({"name": run_dir.name, **replay.summarize(run_dir)}).encode(), "application/json")
            if path in PAGES:
                return self._send(PAGES[path].read_bytes(), mimetypes.guess_type(PAGES[path].name)[0] or "text/html")
            if path.startswith("/files/"):
                target = (run_dir / path[len("/files/"):]).resolve()
                # A path with ../ in it must not reach anything outside the run.
                if target.is_file() and target.is_relative_to(run_dir):
                    return self._send(target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            self.send_error(404)

    return Handler


def serve(run_dir, port=8791, tries=20):
    handler = make_handler(run_dir)
    for candidate in range(port, port + tries):
        try:
            return ThreadingHTTPServer(("127.0.0.1", candidate), handler)
        except OSError:
            continue
    raise SystemExit(f"no free port from {port} to {port + tries - 1}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="a run folder")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not (args.run / "events.jsonl").exists():
        raise SystemExit(f"{args.run} has no events.jsonl")
    server = serve(args.run, args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Replaying {args.run} at {url}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
