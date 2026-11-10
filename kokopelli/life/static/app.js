// Ties it together: the log folds into the model, and each animation frame draws whatever changed.
import {Feed} from "./feed.js";
import {describeHover, inspectorMarkup, logMarkup} from "./inspector.js";
import {buildScene} from "./layout.js";
import {applyEvent, cursorOf, emptyModel} from "./model.js";
import {createRenderer} from "./render-svg.js";
import {buildRulers, Calendar, ROW_COUNT} from "./rulers.js";

const $ = id => document.getElementById(id);
const REPLAY_SECONDS = 30, SIDE_PANEL_EVERY_MS = 200, DETAIL_DELAY_MS = 150;
const HOME_RADIUS = 300, MIN_VIEW_WIDTH = 380, MAX_VIEW_WIDTH = 4000, MIN_ZOOM_WIDTH = 30, ANCHOR_MAX_ZOOM_OUT = 1.1, FRAME_MARGIN = 26, DRAG_THRESHOLD = 4;
const CAMERA_EASE_MS = 170, FOLLOW_EASE_MS = 420, AUTO_RESUME_MS = 4000;
// The follow camera holds one zoom and tracks the agent's week, not its exact node, so it doesn't bounce as the agent
// goes deeper and comes back up. It looks a little outward from the week, where the finer levels are.
const FOLLOW_WIDTH = 640, FOLLOW_LEAD = 95, FOLLOW_SLACK = 0.2, FOLLOW_LEVELS = ["year", "season", "month", "week"];
const STOP_WORDS = {budget: "Stopped at the write limit. Press Run to continue.", done: "Life finished", reached: "Reached that point", stepped: "Stepped"};

const renderer = createRenderer($("graph"));

// pinned is the node the person chose. While it's null the view stays with the agent, unless they've moved it by hand (freeView).
const ui = {run: null, feed: null, calendar: null, model: emptyModel(), applied: 0, replayRate: null, held: false, demo: new URLSearchParams(location.search).has("demo"),
            pinned: null, detail: null, detailKey: null, detailTimer: null, confirming: null, requested: new Set(),
            dirty: true, lastSide: 0, drawn: {}, uiVersion: null, dragging: false, drawnLive: false,
            view: {x: -345, y: -280, w: 690, h: 560}, camera: null, anchor: null, fitPending: false, freeView: false, freeSince: 0, findAgent: false,
            hover: null, scene: null, viewPath: [], lastFrame: 0};

async function request(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error);
  return body;
}
const get = path => request(path);
const post = (path, body) => request(path, {method: "POST", body: JSON.stringify(body)});
function notify(text) { $("notice").textContent = text; }
async function act(action) {
  try { notify(""); await action(); } catch (error) { notify(error.message); }
}
function swap(key, element, markup) {
  if (ui.drawn[key] !== markup) { element.innerHTML = markup; ui.drawn[key] = markup; }
}

const isRunning = () => ui.feed?.status?.running ?? false;
const isReplaying = () => ui.replayRate !== null;
const logLength = () => ui.feed?.log.length ?? 0;
const subject = () => ui.pinned ?? cursorOf(ui.model) ?? ui.calendar.life.id;

// ---- Moving through the log

function applyUpTo(end) {
  const log = ui.feed.log;
  for (let i = ui.applied; i < end; i++) applyEvent(ui.model, log[i]);
  ui.applied = end;
  ui.dirty = true;
}

// Going backward rebuilds from the start. The log is the only truth, so any point in a run can be rebuilt exactly.
function seek(position) {
  if (position < ui.applied) { ui.model = emptyModel(); ui.applied = 0; }
  applyUpTo(position);
}

function startReplay(from = 0) {
  seek(from);
  ui.held = false;
  ui.pinned = null;
  ui.freeView = false;
  ui.replayRate = reducedMotion() ? Infinity : Math.max(1, Math.ceil((logLength() - from) / (REPLAY_SECONDS * 60)));
  writeHash();
}
const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

function advance() {
  if (!ui.feed || ui.held) return;
  const length = logLength();
  if (ui.demo) {
    if (ui.feed.status && ui.feed.log.at(-1)?.seq === ui.feed.status.last_seq) { ui.demo = false; startReplay(); }
    return;
  }
  if (ui.applied < length) applyUpTo(isReplaying() ? Math.min(length, ui.applied + ui.replayRate) : length);
  if (isReplaying() && ui.applied >= length) { ui.replayRate = null; ui.dirty = true; if (isFollowing()) ui.camera = homeView(); }
}

// ---- Drawing

const isLive = () => isRunning() || isReplaying();
const isFollowing = () => !ui.pinned && !ui.freeView;

// The rulers and the tree are two views of one selection, so they're always drawn together.
function drawViews() {
  const box = $("rulers").getBoundingClientRect();
  const {rows, funnels, path, agentPath, missing} = buildRulers(ui.model, ui.calendar, ui.pinned, box.width - 64);
  ui.viewPath = path;
  ui.scene = buildScene(ui.model, ui.calendar, {selected: ui.pinned, hover: ui.hover, viewPath: path, agentPath});
  ui.scene.missing.forEach(id => missing.add(id));
  if (isFollowing() && (isLive() || ui.findAgent)) { ui.findAgent = false; followCamera(); }
  // The chosen branch may need calendar slots from the server, so wait for those before framing it. The agent's don't count.
  if (ui.fitPending && !path.slice(path.indexOf(ui.pinned)).some(id => missing.has(id))) { ui.fitPending = false; frameBranch(); }
  renderer.draw(ui.scene, isLive());
  drawTooltip();
  for (let i = 0; i < ROW_COUNT; i++) {
    swap(`row${i}`, $(`row${i}`), rows[i] ?? "");
    swap(`funnel${i}`, $(`funnel${i}`), funnels[i] ?? "");
  }
  if (missing.size) loadMissing(missing).catch(error => notify(error.message));
}

async function loadMissing(missing) {
  const needed = [...missing].filter(id => !ui.requested.has(id));
  if (!needed.length) return;
  needed.forEach(id => ui.requested.add(id));
  const run = ui.run;
  const table = await get(`/api/calendar?run=${run}&nodes=${encodeURIComponent(needed.join(","))}`);
  if (run !== ui.run) return;
  ui.calendar.add(table);
  ui.dirty = true;
}

// ---- The tree's camera. It's automatic: it frames what's chosen, follows the agent while nothing is, and shows the
// whole life when a run ends. Moving it by hand only holds it for a moment during a run. Hovering never moves it.

function holdView() {
  ui.freeView = true;
  ui.freeSince = performance.now();
}
function resumeCamera(now) {
  if (!ui.freeView || ui.pinned || !isLive() || now - ui.freeSince < AUTO_RESUME_MS) return;
  ui.freeView = false;
  ui.dirty = true;
}

function aspect() {
  const box = $("graph-wrap").getBoundingClientRect();
  return box.width / Math.max(box.height, 1);
}

// The whole life, including any branch that's open, so nothing runs off the edge.
function homeView() {
  const points = ui.scene ? [...ui.scene.positions.values()] : [];
  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  const [x0, x1] = [Math.min(-HOME_RADIUS, ...xs) - FRAME_MARGIN, Math.max(HOME_RADIUS, ...xs) + FRAME_MARGIN];
  const [y0, y1] = [Math.min(-HOME_RADIUS, ...ys) - FRAME_MARGIN, Math.max(HOME_RADIUS, ...ys) + FRAME_MARGIN];
  const w = Math.max(x1 - x0, (y1 - y0) * aspect()), h = w / aspect();
  return {x: (x0 + x1 - w) / 2, y: (y0 + y1 - h) / 2, w, h};
}

// Frame the chosen node and the branch below it. When the pointer chose it, keep it under the pointer if that still fits.
function frameBranch() {
  if (!ui.pinned) return;
  const points = [];
  for (const id of ui.viewPath.slice(ui.viewPath.indexOf(ui.pinned))) {
    for (const item of [{id}, ...(ui.calendar.children.get(id) ?? [])]) {
      const position = ui.scene.positions.get(item.id);
      if (position) points.push(position);
    }
  }
  if (points.length < 2) return;
  const ratio = aspect();
  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  const [x0, x1, y0, y1] = [Math.min(...xs) - FRAME_MARGIN, Math.max(...xs) + FRAME_MARGIN, Math.min(...ys) - FRAME_MARGIN, Math.max(...ys) + FRAME_MARGIN];
  const anchor = ui.anchor && ui.scene.positions.get(ui.anchor.id);
  if (anchor) {
    const {fx, fy} = ui.anchor;
    const w = Math.max(MIN_VIEW_WIDTH, (anchor.x - x0) / fx, (x1 - anchor.x) / (1 - fx), ratio * (anchor.y - y0) / fy, ratio * (y1 - anchor.y) / (1 - fy));
    // Near the edge of the view a branch can point off screen. Then framing it matters more than holding the node still.
    if (w <= homeView().w * ANCHOR_MAX_ZOOM_OUT) {
      ui.camera = {x: anchor.x - fx * w, y: anchor.y - fy * w / ratio, w, h: w / ratio};
      return;
    }
  }
  const w = Math.max(MIN_VIEW_WIDTH, x1 - x0, (y1 - y0) * ratio);
  ui.camera = {x: (x0 + x1 - w) / 2, y: (y0 + y1 - w / ratio) / 2, w, h: w / ratio};
}

// A lazy camera. Between years the agent passes through Life for a moment, which shouldn't pull it away.
function followCamera() {
  const id = ui.scene.cursor && ui.calendar.pathTo(ui.scene.cursor, ui.model).findLast(step => FOLLOW_LEVELS.includes(step.split(":")[0]));
  const position = ui.scene.positions.get(id);
  if (!position) return;
  const outward = (Math.hypot(position.x, position.y) + FOLLOW_LEAD) / Math.hypot(position.x, position.y);
  const [x, y] = [position.x * outward, position.y * outward];
  const w = FOLLOW_WIDTH, h = w / aspect();
  const aim = ui.camera ?? ui.view;
  const inFrame = Math.abs(x - (aim.x + aim.w / 2)) < aim.w * FOLLOW_SLACK && Math.abs(y - (aim.y + aim.h / 2)) < aim.h * FOLLOW_SLACK;
  if (inFrame && Math.abs(aim.w - w) < w * 0.05) return;
  ui.camera = {x: x - w / 2, y: y - h / 2, w, h};
}

function moveCamera(now) {
  if (!ui.camera) return;
  const blend = reducedMotion() ? 1 : 1 - Math.exp(-(now - ui.lastFrame) / (isFollowing() ? FOLLOW_EASE_MS : CAMERA_EASE_MS));
  const next = {};
  let settled = true;
  for (const key of ["x", "y", "w", "h"]) {
    next[key] = ui.view[key] + (ui.camera[key] - ui.view[key]) * blend;
    if (Math.abs(ui.camera[key] - next[key]) > 0.25) settled = false;
  }
  ui.view = settled ? ui.camera : next;
  if (settled) ui.camera = null;
  renderer.setView(ui.view);
  drawTooltip();
}

function drawTooltip() {
  const tip = $("tip");
  const position = ui.hover && ui.scene?.positions.get(ui.hover);
  if (!position) { tip.hidden = true; return; }
  const info = describeHover(ui.model, position);
  const box = $("graph-wrap").getBoundingClientRect();
  const screen = renderer.toScreen(position.x, position.y);
  tip.hidden = false;
  $("tip-label").textContent = info.label;
  $("tip-meta").textContent = info.meta;
  $("tip-summary").textContent = info.summary;
  // Near the right edge the tip sits to the left of the node, so it stays on screen.
  const left = screen.x - box.left;
  tip.style.left = `${left + tip.offsetWidth + 12 > box.width ? Math.max(0, left - tip.offsetWidth - 24) : left}px`;
  tip.style.top = `${screen.y - box.top}px`;
}

function zoomAround(factor, worldX, worldY) {
  holdView();
  ui.camera = null;
  const view = ui.view;
  const w = Math.min(MAX_VIEW_WIDTH, Math.max(MIN_ZOOM_WIDTH, view.w * factor));
  const actual = w / view.w;
  ui.view = {x: worldX - (worldX - view.x) * actual, y: worldY - (worldY - view.y) * actual, w, h: view.h * actual};
  renderer.setView(ui.view);
  drawTooltip();
}
const zoomCenter = factor => zoomAround(factor, ui.view.x + ui.view.w / 2, ui.view.y + ui.view.h / 2);

function drawSide(now) {
  if (now - ui.lastSide < SIDE_PANEL_EVERY_MS) return;
  ui.lastSide = now;
  const inspector = $("inspector");
  // Replacing a panel the person has opened would close it, so an open one waits.
  if (!inspector.querySelector("details[open]") || ui.drawn.subject !== subject()) {
    swap("inspector", inspector, inspectorMarkup(ui.model, ui.calendar, subject(), ui.detail, ui.pinned));
    ui.drawn.subject = subject();
  }
  swap("log", $("log"), logMarkup(ui.model));
}

function statusWords(status) {
  if (isReplaying()) return "Replaying";
  if (ui.held) return "Looking back through the run";
  if (status.watching) return status.finished ? "Life finished" : "Watching a run in another process";
  if (status.running) return "Agent running";
  if (status.finished) return "Life finished";
  if (status.reason?.startsWith("error")) return status.reason;
  if (!status.last_seq) return "Ready. Press Run to start this life.";
  return STOP_WORDS[status.reason] ?? "Stopped. Press Run to continue.";
}

function drawStatus() {
  const status = ui.feed?.status;
  if (!status) return;
  if (ui.uiVersion !== null && status.ui_version !== ui.uiVersion) location.reload();
  ui.uiVersion = status.ui_version;
  const running = status.running, replaying = isReplaying();
  if (isLive() !== ui.drawnLive) {
    ui.drawnLive = isLive();
    ui.dirty = true;
    // A run that ended shows the whole life. One the person paused stays where it is, since they stopped to look.
    if (!ui.drawnLive && isFollowing() && !ui.held && status.reason !== "stopped") ui.camera = homeView();
  }
  $("status-line").className = running || replaying ? "live" : "";
  $("status-text").textContent = statusWords(status);
  const facts = `${ui.model.nodes.size.toLocaleString()} nodes, ${ui.applied.toLocaleString()} events, ${status.real_llm_calls} LLM calls`;
  $("facts").textContent = facts;
  const primary = $("primary");
  primary.textContent = running || replaying ? "Pause" : ui.held ? "Resume" : status.finished ? "Finished" : "Run";
  primary.disabled = !running && !replaying && !ui.held && status.finished;
  $("step").disabled = running || replaying || status.finished;
  $("replay").disabled = running || !logLength();
  primary.hidden = $("step").hidden = $("new-run").hidden = status.watching;
  $("back").hidden = isFollowing();
  const scrub = $("scrub");
  scrub.max = logLength();
  if (!ui.dragging) scrub.value = ui.applied;
  $("scrub-text").textContent = `Event ${ui.applied.toLocaleString()} of ${logLength().toLocaleString()}`;
}

function loadDetail() {
  const id = subject();
  const status = ui.model.nodes.get(id)?.status;
  // While the view rides along with a run the node changes too fast to read, so only a chosen node or a still one loads.
  const key = status && (ui.pinned || (!isRunning() && !isReplaying())) ? `${ui.run}/${id}` : null;
  if (key === ui.detailKey) return;
  ui.detailKey = key;
  clearTimeout(ui.detailTimer);
  if (ui.detail) { ui.detail = null; ui.dirty = true; }
  if (!key) return;
  ui.detailTimer = setTimeout(async () => {
    try {
      const detail = await get(`/api/node?run=${ui.run}&node=${encodeURIComponent(id)}`);
      if (ui.detailKey === key) { ui.detail = detail; ui.dirty = true; ui.lastSide = 0; }
    } catch (error) { notify(error.message); }
  }, DETAIL_DELAY_MS);
}

function frame(now) {
  // One bad frame shouldn't silently freeze the page, so it says what went wrong and the next frame still runs.
  try {
    if (ui.calendar && ui.feed) {
      advance();
      resumeCamera(now);
      if (ui.dirty) { ui.dirty = false; ui.sideDirty = true; drawViews(); }
      moveCamera(now);
      loadDetail();
      if (ui.sideDirty) { drawSide(now); if (ui.lastSide === now) ui.sideDirty = false; }
      drawStatus();
    }
  } catch (error) {
    console.error(error);
    notify(`Drawing failed: ${error.message}`);
  }
  ui.lastFrame = now;
  requestAnimationFrame(frame);
}

// ---- Choosing what to look at

function writeHash() {
  const node = ui.pinned ? `&node=${encodeURIComponent(ui.pinned)}` : "";
  history.replaceState(null, "", `${location.pathname}#run=${ui.run}${node}`);
}

function pin(id, anchor = null) {
  ui.pinned = id;
  ui.anchor = anchor;
  ui.fitPending = id !== null;
  if (id === null) { ui.freeView = false; ui.findAgent = true; }
  ui.confirming = null;
  ui.dirty = true;
  ui.lastSide = 0;
  notify("");
  writeHash();
}

// Arrow keys walk the calendar: left and right to siblings, up to the parent, down to the first child.
function walk(key) {
  const id = subject();
  const slot = ui.calendar.slots.get(id);
  if (!slot) return;
  if (key === "ArrowUp") { if (slot.parent && slot.parent !== ui.calendar.life.id) pin(slot.parent); return; }
  if (key === "ArrowDown") {
    const kids = ui.calendar.children.get(id);
    if (kids) pin(kids[0].id); else loadMissing([id]).catch(error => notify(error.message));
    return;
  }
  const siblings = ui.calendar.children.get(slot.parent);
  const next = siblings?.[siblings.findIndex(item => item.id === id) + (key === "ArrowRight" ? 1 : -1)];
  if (next) pin(next.id);
}

// ---- Controls

function pressPrimary() {
  if (isRunning()) return act(() => post("/api/stop", {run: ui.run}));
  if (isReplaying()) { ui.replayRate = null; ui.held = true; ui.dirty = true; return; }
  if (ui.held) return startReplay(ui.applied);
  pin(null);
  return act(() => post("/api/run", runBody()));
}
const runBody = () => ({run: ui.run, step_delay: +$("speed").value});

$("primary").onclick = pressPrimary;
$("step").onclick = () => { ui.held = false; ui.replayRate = null; act(() => post("/api/step", {run: ui.run})); };
$("replay").onclick = () => startReplay();
$("back").onclick = () => pin(null);
$("scrub").addEventListener("input", event => {
  ui.dragging = true;
  ui.replayRate = null;
  ui.held = +event.target.value < logLength();
  seek(+event.target.value);
});
$("scrub").addEventListener("change", () => { ui.dragging = false; });

// ---- The tree's pointer

function showWholeLife() {
  ui.pinned = null;
  holdView();
  ui.camera = homeView();
  ui.dirty = true;
  writeHash();
}

// A stage isn't a calendar slot, so choosing one looks at its first year, as its ruler does.
const pickNode = id => id.startsWith("hub:") ? ui.calendar.children.get(ui.calendar.life.id).find(year => year.hub === +id.slice(4)).id : id;
function pointerAnchor(id, event) {
  const box = $("graph-wrap").getBoundingClientRect();
  return {id, fx: Math.min(0.92, Math.max(0.08, (event.clientX - box.left) / box.width)),
          fy: Math.min(0.92, Math.max(0.08, (event.clientY - box.top) / box.height))};
}
function setHover(id) {
  if (id === ui.hover) return;
  ui.hover = id;
  ui.dirty = true;
}

const graph = $("graph");
const nodeAt = event => event.target.closest?.("[data-id]")?.dataset.id ?? null;
let drag = null;
graph.addEventListener("pointerdown", event => {
  drag = {x: event.clientX, y: event.clientY, view: {...ui.view}, moved: false, target: nodeAt(event),
          scale: renderer.toWorld(1, 0).x - renderer.toWorld(0, 0).x};
});
graph.addEventListener("pointermove", event => {
  if (!drag) return setHover(nodeAt(event));
  const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
  if (!drag.moved && Math.abs(dx) + Math.abs(dy) < DRAG_THRESHOLD) return;
  if (!drag.moved) {
    drag.moved = true;
    graph.setPointerCapture(event.pointerId);
    graph.style.cursor = "grabbing";
    setHover(null);
    ui.camera = null;
    holdView();
  }
  if (drag.moved) holdView();
  ui.view = {...drag.view, x: drag.view.x - dx * drag.scale, y: drag.view.y - dy * drag.scale};
  renderer.setView(ui.view);
});
graph.addEventListener("pointerup", event => {
  // A press that moved is a pan, never a click. A press on empty space goes back to the whole life.
  if (drag && !drag.moved) {
    if (drag.target) pin(pickNode(drag.target), pointerAnchor(pickNode(drag.target), event));
    else showWholeLife();
  }
  drag = null;
  graph.style.cursor = "grab";
});
graph.addEventListener("pointercancel", () => { drag = null; graph.style.cursor = "grab"; });
graph.addEventListener("pointerleave", () => { if (!drag) setHover(null); });
graph.addEventListener("wheel", event => {
  event.preventDefault();
  const point = renderer.toWorld(event.clientX, event.clientY);
  zoomAround(event.deltaY > 0 ? 1.12 : 1 / 1.12, point.x, point.y);
}, {passive: false});
$("zoom-in").onclick = () => zoomCenter(0.8);
$("zoom-out").onclick = () => zoomCenter(1.25);
$("whole").onclick = showWholeLife;
new ResizeObserver(() => {
  if (!ui.scene) return;
  if (ui.pinned) frameBranch(); else if (isFollowing() && isLive()) followCamera(); else ui.camera = homeView();
}).observe($("graph-wrap"));

// Cells are redrawn while a run plays, so a press has to count at once: by the time of the click the button may be gone.
const idAt = event => event.target.closest?.("[data-id]")?.dataset.id;
$("rulers").addEventListener("pointerdown", event => { const id = idAt(event); if (id) pin(id); });
$("rulers").addEventListener("click", event => { if (event.detail === 0 && idAt(event)) pin(idAt(event)); });
$("log").addEventListener("pointerdown", event => { const id = idAt(event); if (id && id !== "undefined") pin(id); });
$("inspector").addEventListener("pointerdown", event => { const id = idAt(event); if (id) pin(id); });
$("inspector").addEventListener("click", event => {
  const action = event.target.closest("[data-action]")?.dataset.action;
  if (action === "fork") return act(forkHere);
  if (action === "until") return act(runUntilHere);
});

async function forkHere() {
  const {run_id} = await post("/api/fork", {run: ui.run, node: subject()});
  await loadRuns(run_id);
}
async function runUntilHere() {
  // A second click on the same warned node is the confirmation.
  const target = subject();
  const answer = await post("/api/run", {...runBody(), until: target, confirmed: ui.confirming === target});
  ui.confirming = answer.warn ? target : null;
  if (answer.warn) notify(`${answer.warn} Click Run until here again to confirm.`);
}

document.addEventListener("keydown", event => {
  if (event.target.closest("input, select, textarea, summary") && event.target.id !== "scrub") return;
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if (event.key.startsWith("Arrow") && event.target.id !== "scrub") { event.preventDefault(); walk(event.key); }
  else if (event.key === "Escape") pin(null);
  else if (event.key === " " && event.target.tagName !== "BUTTON") { event.preventDefault(); pressPrimary(); }
  else if (event.key === "r" && !$("replay").disabled) startReplay();
});
document.addEventListener("pointerdown", event => {
  document.querySelectorAll("header details[open]").forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
});

// ---- Runs

function lines(text) { return text.split("\n").map(line => line.trim()).filter(Boolean); }
$("seed-form").onsubmit = event => {
  event.preventDefault();
  const form = Object.fromEntries(new FormData(event.target));
  const body = {...form, rng_seed: +form.rng_seed,
    family: lines(form.family).map(line => line.split(":").map(part => part.trim())),
    anchors: lines(form.anchors).map(line => [line.slice(0, line.indexOf(" ")), line.slice(line.indexOf(" ") + 1)])};
  act(async () => {
    const {run_id} = await post("/api/runs", body);
    $("new-run").open = false;
    await loadRuns(run_id);
  });
};
$("runs").onchange = event => switchRun(+event.target.value);

async function switchRun(run, pinned = null) {
  ui.feed?.close();
  Object.assign(ui, {run, calendar: null, model: emptyModel(), applied: 0, replayRate: null, held: false, pinned, detail: null, detailKey: null, requested: new Set(),
                     hover: null, scene: null, camera: null, freeView: false, fitPending: !!pinned, anchor: null, view: homeView()});
  renderer.setView(ui.view);
  ui.calendar = new Calendar(await get(`/api/calendar?run=${run}`));
  ui.feed = new Feed(run, notify);
  ui.dirty = true;
  writeHash();
}

async function loadRuns(pick, pinned) {
  const runs = await get("/api/runs");
  $("runs").replaceChildren(...runs.map(run => Object.assign(document.createElement("option"), {value: run.run_id,
    textContent: `#${run.run_id}${run.fork_of ? ` fork of #${run.fork_of}` : ""}: ${run.prompt.slice(0, 32)}`})));
  const chosen = runs.some(run => run.run_id === pick) ? pick : runs.at(-1).run_id;
  $("runs").value = chosen;
  await switchRun(chosen, pinned);
}

async function fillForm() {
  const seed = await get("/api/defaults");
  const form = $("seed-form").elements;
  for (const name of ["prompt", "birth_date", "place", "era", "temperament", "rng_seed"]) form[name].value = seed[name];
  form.family.value = seed.family.map(pair => pair.join(": ")).join("\n");
  form.anchors.value = seed.anchors.map(pair => pair.join(" ")).join("\n");
}

$("rulers").innerHTML = Array.from({length: ROW_COUNT}, (_, i) => `<div class="row" id="row${i}"></div><div class="funnel" id="funnel${i}"></div>`).join("");
new ResizeObserver(() => { ui.dirty = true; }).observe($("rulers"));

// For checking from the console or a browser test.
window.lifePanel = {ui, seek, pin, picture: () => renderer.picture()};

const hash = new URLSearchParams(location.hash.slice(1));
Promise.all([fillForm(), loadRuns(+hash.get("run"), hash.get("node"))]).catch(error => notify(error.message));
requestAnimationFrame(frame);
