"""The dev panel: a small local server over the store. It has no route that edits a written node."""
import argparse
import json
import os
import sys
import threading
import time
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from exp1 import panel as exp1_panel
from homeostatic import watch
from life import architecture, city, city_live, gpu_queue, moodboard, staged, world_runs
from life.engine import Budget, Engine
from life.seed import LifeSeed
from life.store import OrderError, Store
from life.windows import age_at, children, find, hub_at, life_window, stage_at
from settings import (LIFE_BUDGET, LIFE_DB, LIFE_DEFAULT_SEED, LIFE_DEMO_DB, LIFE_DEMO_WRITES, LIFE_DISPLAY_HUBS,
                      LIFE_WARN_SIMULATED_DAYS, ROOT)

STATIC = Path(__file__).with_name("static")
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
STATE_KINDS = {"moved", "person_met", "relationship_changed", "money_changed", "skill_changed"}


def divergences(opening, closing):
    """Pressures that went against their odds: likely ones that never came, unlikely ones that did."""
    outcomes = {pressure["id"]: pressure["outcome"] for pressure in closing["pressures"]}
    found = []
    for pressure in opening["pressures"]:
        arose = outcomes[pressure["id"]] != "didnt_arise"
        if arose != (pressure["odds"] >= 0.5):
            found.append({**pressure, "outcome": outcomes[pressure["id"]]})
    return found


def slot(window, birth):
    """A calendar position, which exists whether or not a node has been written there."""
    age = age_at(birth, window.start)
    described = {"id": window.id, "parent": window.parent_id, "index": window.index, "level": window.level,
                 "label": window.label, "start": window.start.isoformat(), "end": window.end.isoformat(),
                 "age": round(age, 2), "stage": stage_at(age)["name"]}
    if window.level == "year":
        described["hub"] = hub_at(age)
    return described


def feed_event(write):
    """One stored write, in the vocabulary the panel draws from."""
    seq = write["seq"]
    if write["write"] == "opening":
        return {"seq": seq, "type": "node_opened", "id": write["node_id"], "parent": write["parent_id"],
                "level": write["level"], "label": write["label"], "start": write["start_t"], "age": round(write["age"], 2),
                "salience": write["salience"], "limit": write["depth_limit"], "summary": write["opening"]["setting"]}
    if write["write"] == "closing":
        return {"seq": seq, "type": "node_closed", "id": write["node_id"], "summary": write["closing"]["summary"],
                "diverged": len(divergences(write["opening"], write["closing"]))}
    kind, data = write["kind"], write["data"]
    if kind == "escalated":
        return {"seq": seq, "type": "node_escalated", "id": write["node_id"], "to": data["to"]}
    if kind == "choice_point":
        return {"seq": seq, "type": "choice_point", "id": write["node_id"], "options": data["options"]}
    if kind == "choice":
        return {"seq": seq, "type": "agent_action", "id": write["node_id"], **data}
    if kind in STATE_KINDS:
        return {"seq": seq, "type": "state_change", "id": write["node_id"], "kind": kind, "data": data}
    return {"seq": seq, "type": kind, "id": write["node_id"], "data": data}


def seed_from(body):
    family = tuple({"name": name, "relationship": relationship} for name, relationship in body.get("family", []))
    anchors = tuple({"at": at, "text": text} for at, text in body.get("anchors", []))
    return LifeSeed(body.get("prompt", ""), date.fromisoformat(body["birth_date"]), body.get("place", ""),
                    body.get("era", ""), family, body.get("temperament", ""), anchors,
                    int(body.get("rng_seed", 0)), body.get("hidden_target") or None)


def ui_version():
    """Changes when a static file does, which tells an open page to reload itself."""
    return max(path.stat().st_mtime for path in STATIC.iterdir())


class Runners:
    """The background runs. Each has its own database connection, since a run outlives the request that started it."""

    def __init__(self, db):
        self.db = db
        self.lock = threading.Lock()
        self.active = {}
        self.latest = {}

    def is_running(self, run_id):
        return run_id in self.active

    def step(self, run_id, budget):
        with self.lock:
            if self.is_running(run_id):
                raise OrderError("this run is already running")
            store = Store(self.db)
            try:
                result = Engine(store, run_id, budget=budget).step()
            finally:
                store.close()
            # A step's one-call budget says nothing about the budget left for a run, so it isn't reported.
            self.latest[run_id] = {"reason": "stepped", "budget": None}
            return result

    def start(self, run_id, budget, until, step_delay):
        with self.lock:
            if self.is_running(run_id):
                raise OrderError("this run is already running")
            stop = threading.Event()
            self.active[run_id] = stop
            self.latest[run_id] = {"reason": "running", "budget": budget}
        threading.Thread(target=self._work, args=(run_id, budget, until, step_delay, stop), daemon=True).start()

    def _work(self, run_id, budget, until, step_delay, stop):
        store = Store(self.db)
        try:
            reason = Engine(store, run_id, budget=budget).run(stop=stop, until=until, step_delay=step_delay)
        except Exception as error:
            reason = f"error: {error}"
        finally:
            store.close()
        with self.lock:
            del self.active[run_id]
            self.latest[run_id] = {"reason": reason, "budget": budget}

    def stop(self, run_id):
        with self.lock:
            if run_id in self.active:
                self.active[run_id].set()

    def status(self, run_id):
        latest = self.latest.get(run_id, {"reason": None, "budget": None})
        budget = latest["budget"]
        return {"running": self.is_running(run_id), "reason": latest["reason"],
                "budget": budget.remaining() if budget else dict(LIFE_BUDGET),
                "budget_total": budget.generator_calls if budget else LIFE_BUDGET["generator_calls"]}


class Api:
    def __init__(self, store, runners, watching=False):
        self.store, self.runners, self.watching = store, runners, watching

    def _real_calls(self, run_id):
        # The panel only ever writes mock content itself, so writes are model calls only when it's watching.
        if not self.watching:
            return 0
        counts = self.store.counts(run_id)
        return counts["opened"] + counts["closed"]

    def runs(self, params):
        return [{"run_id": run["run_id"], "fork_of": run["fork_of"], "fork_node": run["fork_node"],
                 "prompt": json.loads(run["seed"])["prompt"]} for run in self.store.runs()]

    def status(self, params):
        run_id = int(params["run"])
        seed = self.store.public_seed(run_id)
        life = self.store.node(run_id, life_window(seed.birth_date).id)
        return {**self.runners.status(run_id), "seed": seed.to_dict(), "last_seq": self.store.last_seq(run_id),
                "counts": self.store.counts(run_id), "real_llm_calls": self._real_calls(run_id), "watching": self.watching,
                "ui_version": ui_version(),
                "finished": life is not None and life["closing"] is not None}

    def feed(self, params):
        writes = self.store.writes(int(params["run"]), after_seq=int(params.get("after", 0)))
        return [feed_event(write) for write in writes]

    def calendar(self, params):
        """Calendar slots. With no nodes given: the life, its years, and each year's seasons."""
        birth = self.store.public_seed(int(params["run"])).birth_date
        if "nodes" in params:
            windows = [find(node_id, birth) for node_id in params["nodes"].split(",")]
            return {window.id: [slot(child, birth) for child in children(window, birth)] for window in windows}
        life = life_window(birth)
        years = children(life, birth)
        table = {life.id: [slot(year, birth) for year in years]}
        table.update({year.id: [slot(season, birth) for season in children(year, birth)] for year in years})
        return {"life": slot(life, birth), "hubs": LIFE_DISPLAY_HUBS, "children": table}

    def node(self, params):
        run_id = int(params["run"])
        birth = self.store.public_seed(run_id).birth_date
        window = find(params["node"], birth)
        node = self.store.node(run_id, window.id)
        detail = slot(window, birth)
        detail["status"] = "unopened" if node is None else "closed" if node["closing"] else "open"
        detail["opening"] = node and node["opening"]
        detail["closing"] = node and node["closing"]
        detail["divergences"] = divergences(node["opening"], node["closing"]) if node and node["closing"] else []
        detail["events"] = self.store.events(run_id, start=window.start.isoformat(), end=window.end.isoformat(), limit=200)
        return detail

    def defaults(self, params):
        return LIFE_DEFAULT_SEED

    def training_runs(self, params):
        return {"runs": watch.list_runs(), "ui_version": ui_version()}

    def training_run(self, params):
        return {**watch.describe_run(params["name"]), "baselines": watch.baselines(), "results": watch.held_out_results()}

    def exp1_runs(self, params):
        return {"runs": exp1_panel.listing(), "ui_version": ui_version()}

    def exp1_run(self, params):
        return exp1_panel.describe(params["name"])

    def exp1_arms(self, params):
        return exp1_panel.arms()

    def architecture(self, params):
        panel = architecture.panel_signal(self.store, len(self.runners.active))
        return {**architecture.catalog_and_snapshot(panel), "ui_version": ui_version()}

    def queue(self, params):
        return {**gpu_queue.collect(), "staged": staged.listing(), "ui_version": ui_version()}

    def queue_start(self, body):
        return staged.start(body["name"])

    def queue_move(self, body):
        return gpu_queue.move(body["id"], body["priority"])

    def queue_cancel(self, body):
        return gpu_queue.cancel(body["id"])

    def queue_past(self, params):
        return gpu_queue.past_page(int(params.get("offset", 0)), int(params.get("limit", gpu_queue.LEDGER_SHOWN)))

    def queue_log(self, params):
        return gpu_queue.job_log(params["id"])

    def queue_where(self, body):
        return gpu_queue.send(body["id"], body["where"])

    def queue_default(self, body):
        return gpu_queue.set_default(body["where"])

    def moodboard(self, params):
        return {**moodboard.board(), "ui_version": ui_version()}

    def worlds(self, params):
        return {**world_runs.collect(), "ui_version": ui_version()}

    def city(self, params):
        data = city.world()
        return {"world": data, "checks": city.checks(data), "ui_version": ui_version()}

    def city_live_runs(self, params):
        return {**city_live.listing(), "ui_version": ui_version()}

    def city_live_run(self, params):
        return city_live.run(params["run"])

    def moodboard_add(self, body):
        return moodboard.add(body["data"], body.get("title", ""), body.get("source", ""), body.get("origin"))

    def moodboard_update(self, body):
        return moodboard.update(body["id"], body)

    def new_run(self, body):
        return {"run_id": self.store.create_run(seed_from(body))}

    def step(self, body):
        return {"result": self.runners.step(int(body["run"]), Budget(generator_calls=1))}

    def run(self, body):
        run_id, until = int(body["run"]), body.get("until")
        if until and not body.get("confirmed"):
            days = self._simulated_days_to(run_id, until)
            if days > LIFE_WARN_SIMULATED_DAYS:
                return {"warn": f"That simulates about {days} days of life."}
        budget = Budget(generator_calls=body.get("generator_calls"), seconds=body.get("seconds"))
        self.runners.start(run_id, budget, until, float(body.get("step_delay", 0)))
        return {"started": True}

    def _simulated_days_to(self, run_id, until):
        birth = self.store.public_seed(run_id).birth_date
        cursor = self.store.cursor(run_id)
        start = find(cursor["node_id"], birth).start if cursor else life_window(birth).start
        return (find(until, birth).end - start).days

    def stop(self, body):
        self.runners.stop(int(body["run"]))
        return {"stopped": True}

    def fork(self, body):
        return {"run_id": self.store.fork(int(body["run"]), body["node"])}


class Handler(BaseHTTPRequestHandler):
    GET = {"/api/runs": "runs", "/api/status": "status", "/api/feed": "feed", "/api/calendar": "calendar",
           "/api/node": "node", "/api/defaults": "defaults", "/api/training/runs": "training_runs", "/api/training/run": "training_run",
           "/api/exp1/runs": "exp1_runs", "/api/exp1/run": "exp1_run", "/api/exp1/arms": "exp1_arms",
           "/api/architecture": "architecture", "/api/queue": "queue", "/api/queue/log": "queue_log", "/api/queue/past": "queue_past", "/api/moodboard": "moodboard",
           "/api/worlds": "worlds", "/api/city": "city",
           "/api/city-live/runs": "city_live_runs", "/api/city-live/run": "city_live_run"}
    POST = {"/api/runs": "new_run", "/api/step": "step", "/api/run": "run", "/api/stop": "stop", "/api/fork": "fork"}
    # These change real jobs, so unlike the mock buttons they work while watching, and only for this panel's own page.
    QUEUE_POST = {"/api/queue/move": "queue_move", "/api/queue/cancel": "queue_cancel", "/api/queue/where": "queue_where",
                  "/api/queue/default": "queue_default", "/api/queue/start": "queue_start"}
    # These save pictures to disk, so they too only take requests from this panel's own page.
    MOODBOARD_POST = {"/api/moodboard/add": "moodboard_add", "/api/moodboard/update": "moodboard_update"}

    def log_message(self, *args):
        pass

    def _send(self, code, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _call(self, name, argument):
        store = Store(self.server.db)
        try:
            self._send(200, getattr(Api(store, self.server.runners, self.server.watching), name)(argument))
        except (OrderError, KeyError, ValueError, NotImplementedError) as error:
            self._send(400, {"error": str(error)})
        finally:
            store.close()

    def _static(self, name):
        # Only a bare file name directly inside the static folder can be served.
        path = STATIC / Path(name).name
        if Path(name).name != name or path.suffix not in CONTENT_TYPES or not path.is_file():
            return self._send(404, {"error": "not found"})
        self._send(200, path.read_bytes(), CONTENT_TYPES[path.suffix])

    def _queue_output(self, query):
        # The file is found again from the job's own outputs, so a request names a job and a number, never a path.
        try:
            path, content_type = gpu_queue.output_file(query["id"][0], int(query["n"][0]))
            size = path.stat().st_size
        except (KeyError, IndexError, TypeError, ValueError, OSError):
            return self._send(404, {"error": "not found"})
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        # Streamed, so a long video isn't read into memory at once.
        with open(path, "rb") as file:
            while chunk := file.read(1 << 20):
                self.wfile.write(chunk)

    def _world_video(self, query):
        # The id is looked up in a fresh listing of runs, so a request can't name any other file.
        try:
            path = world_runs.video_file(query["id"][0])
            size = path.stat().st_size
        except (KeyError, IndexError, OSError):
            return self._send(404, {"error": "not found"})
        # Browsers seek in a video by asking for byte ranges, and Safari won't play one at all without them.
        start, end = 0, size - 1
        wanted = self.headers.get("Range", "")
        if wanted.startswith("bytes="):
            first, _, last = wanted.removeprefix("bytes=").split(",")[0].partition("-")
            try:
                start, end = (size - int(last), size - 1) if not first else (int(first), min(int(last), size - 1) if last else size - 1)
            except ValueError:
                start = size
            if not 0 <= start <= end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        self.send_response(206 if wanted.startswith("bytes=") else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if wanted.startswith("bytes="):
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with open(path, "rb") as file:
            file.seek(start)
            left = end - start + 1
            while left and (chunk := file.read(min(1 << 20, left))):
                self.wfile.write(chunk)
                left -= len(chunk)

    def _moodboard_image(self, query):
        try:
            path, content_type = moodboard.image_file(query["id"][0])
            body = path.read_bytes()
        except (KeyError, IndexError, OSError):
            return self._send(404, {"error": "not found"})
        self._send(200, body, content_type)

    def _city_live_frame(self, query):
        # A run id and a frame name, each checked against the run's own frames folder, never a path.
        try:
            body = city_live.frame_file(query["run"][0], query["name"][0]).read_bytes()
        except (KeyError, IndexError, OSError):
            return self._send(404, {"error": "not found"})
        self._send(200, body, "image/png")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            return self._static("index.html")
        if url.path == "/training":
            return self._static("training.html")
        if url.path == "/exp1":
            return self._static("exp1.html")
        if url.path == "/architecture":
            return self._static("architecture.html")
        if url.path == "/queue":
            return self._static("queue.html")
        if url.path == "/api/queue/output":
            return self._queue_output(parse_qs(url.query))
        if url.path == "/worlds":
            return self._static("worlds.html")
        if url.path == "/api/worlds/video":
            return self._world_video(parse_qs(url.query))
        if url.path == "/moodboard":
            return self._static("moodboard.html")
        if url.path == "/api/moodboard/image":
            return self._moodboard_image(parse_qs(url.query))
        if url.path == "/city-live":
            return self._static("city-live.html")
        if url.path == "/api/city-live/frame":
            return self._city_live_frame(parse_qs(url.query))
        if url.path.startswith("/static/"):
            return self._static(url.path.removeprefix("/static/"))
        if url.path not in self.GET:
            return self._send(404, {"error": "not found"})
        self._call(self.GET[url.path], {key: values[0] for key, values in parse_qs(url.query).items()})

    def _from_this_page(self):
        """Any website open in the browser can send a request to 127.0.0.1. A page of this panel names it as its own Origin,
        under a local Host, which a site renaming itself to 127.0.0.1 can't fake. JSON makes the browser ask first, and nothing here answers."""
        host = self.headers.get("Host", "")
        local = host in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")
        return local and self.headers.get("Origin") == f"http://{host}" and self.headers.get("Content-Type", "").startswith("application/json")

    def do_POST(self):
        if self.path in self.QUEUE_POST:
            if not self._from_this_page():
                return self._send(403, {"error": "Only this panel's own page can change the queue."})
            return self._call(self.QUEUE_POST[self.path], json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}"))
        if self.path in self.MOODBOARD_POST:
            if not self._from_this_page():
                return self._send(403, {"error": "Only this panel's own page can change the moodboard."})
            return self._call(self.MOODBOARD_POST[self.path], json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}"))
        if self.path not in self.POST:
            return self._send(404, {"error": "not found"})
        # The buttons here write mock content, which must never land in a real run.
        if self.server.watching:
            return self._send(403, {"error": "This panel only watches a run in another process."})
        self._call(self.POST[self.path], json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}"))


def make_server(db=LIFE_DB, port=8765, watching=False):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.db = db
    server.watching = watching
    server.runners = Runners(db)
    return server


def ensure_run(db, writes=0):
    """Give the panel a life to show: one run if the database has none, with this many writes made in advance."""
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    store = Store(db)
    try:
        if store.runs():
            return
        run_id = store.create_run(seed_from(LIFE_DEFAULT_SEED))
        if writes:
            Engine(store, run_id, budget=Budget(generator_calls=writes, seconds=300)).run()
    finally:
        store.close()


def reset_demo():
    """Start the demo from nothing, so it plays the same life every time."""
    for suffix in ("", "-wal", "-shm"):
        Path(f"{LIFE_DEMO_DB}{suffix}").unlink(missing_ok=True)


def restart_when_code_changes():
    """Run the panel again after an edit to its Python. Static files need no restart; an open page reloads itself."""
    def files():
        return {path: path.stat().st_mtime for path in [*ROOT.glob("life/*.py"), ROOT / "homeostatic" / "watch.py", ROOT / "settings.py"]}
    seen = files()
    while files() == seen:
        time.sleep(0.5)
    print("Code changed, restarting", flush=True)
    os.environ["LIFE_PANEL_RESTARTED"] = "1"
    os.execv(sys.executable, [sys.executable, "-m", "life.panel", *sys.argv[1:], "--no-open"])


def bind(db, first_port, tries=20, watching=False):
    """The first free port from this one up, so a second copy of the panel still starts."""
    for port in range(first_port, first_port + tries):
        try:
            return make_server(db, port, watching)
        except OSError:
            continue
    raise SystemExit(f"Ports {first_port} to {first_port + tries - 1} are all in use.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=None)
    parser.add_argument("--demo", action="store_true", help="use a separate database with a life already generated, and replay it on open")
    parser.add_argument("--no-open", action="store_true", help="don't open a browser")
    parser.add_argument("--watch", action="store_true", help="only show a run another process is writing to this database")
    args = parser.parse_args()
    db = args.db or (LIFE_DEMO_DB if args.demo else LIFE_DB)
    if args.demo and not args.db and "LIFE_PANEL_RESTARTED" not in os.environ:
        reset_demo()
    if not args.watch:
        ensure_run(db, LIFE_DEMO_WRITES if args.demo else 0)
    server = bind(db, args.port, watching=args.watch)
    url = f"http://127.0.0.1:{server.server_port}/{'?demo=1' if args.demo else ''}"
    print(f"Dev panel at {url}", flush=True)
    threading.Thread(target=restart_when_code_changes, daemon=True).start()
    if not args.no_open:
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
