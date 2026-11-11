// Watch the agent: a local Qwen living in the city. Its eyes, what it's doing, where it is on the plan, and every decision.
// A live run is polled; a finished one is replayed decision by decision. It only reads what kokopelli/agents/live.py writes.
import {LAYERS, drawCity, el} from "/static/city-draw.js";

const $ = id => document.getElementById(id);
const LIVE_MS = 3000;
const RUNS_MS = 10000;
const FOLLOW_M = 160;
const ui = {runs: [], run: null, data: null, world: null, places: {}, index: 0, follow: true, view: null, size: [600, 600],
            uiVersion: null, logKey: "", fetchedAt: 0, timer: null, frameSrc: ""};

const escapeHtml = text => String(text ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const words = text => String(text ?? "").replaceAll("_", " ");
const frameUrl = (run, name, bust = "") => `/api/city-live/frame?run=${encodeURIComponent(run)}&name=${encodeURIComponent(name)}${bust ? `&v=${encodeURIComponent(bust)}` : ""}`;
const placeName = id => ui.places[id]?.name || words(id);
const personName = id => ui.data?.state?.npcs?.find(npc => npc.id === id)?.name || words(id).replace(/^\w/, c => c.toUpperCase());

function describe(action) {
  if (!action) return "";
  switch (action.type) {
    case "go_to": return `Walk to ${placeName(action.place)}`;
    case "approach": return `Walk up to ${personName(action.person)}`;
    case "say": return `Say “${action.text}”`;
    case "look_at": return `Look at ${ui.places[action.target] ? placeName(action.target) : personName(action.target)}`;
    case "pick_up": return `Pick up ${words(action.object)}`;
    case "put_down": return "Put down what it's carrying";
    case "wait": return "Wait";
    case "continue": return "Keep walking";
    case "unreadable": return action.text;
    default: return JSON.stringify(action);
  }
}

function routeLength(agent, route) {
  let total = 0, at = [agent.x_m, agent.y_m];
  for (const point of route) { total += Math.hypot(point[0] - at[0], point[1] - at[1]); at = point; }
  return Math.round(total);
}

function ago(seconds) {
  if (seconds === null || seconds === undefined) return "";
  return seconds < 90 ? `${Math.round(seconds)} s ago` : `${Math.round(seconds / 60)} min ago`;
}

// --- the moment shown: the live state, or one decision of a finished run ----------------------------------

function moment() {
  const {state, decisions, trail} = ui.data;
  if (ui.data.live || !decisions.length) {
    return {live: ui.data.live, clock: state.clock, step: state.step, thought: state.last_thought, action: state.last_action,
            result: state.last_result, heard: state.heard || [], agent: state.agent, npcs: state.npcs || [], objects: state.objects || [],
            route: state.route || [], goal: state.goal, walked: trail,
            frame: state.has_live_frame ? frameUrl(ui.run, "live.png", state.updated || ui.fetchedAt) : null};
  }
  const decision = decisions[ui.index];
  // Step n's outcome is where the agent stood after step n, so at decision n it stood where step n-1 left it.
  const at = trail[Math.max(0, decision.step - 1)];
  const next = trail[decision.step], before = trail[decision.step - 2];
  const toward = next && at && (next[0] !== at[0] || next[1] !== at[1]) ? [at, next] : before && at ? [before, at] : null;
  const yaw = toward && (toward[0][0] !== toward[1][0] || toward[0][1] !== toward[1][1])
    ? Math.atan2(toward[1][1] - toward[0][1], toward[1][0] - toward[0][0]) * 180 / Math.PI : null;
  const index = ui.index;
  return {live: false, clock: decision.clock, step: decision.step, thought: decision.thought, action: decision.action,
          result: decision.notes.join(" "), heard: decision.replies.map(reply => `${reply.name}: ${reply.text}`),
          agent: at && {x_m: at[0], y_m: at[1], yaw}, npcs: [], objects: [], route: [], goal: decision.action?.type === "go_to" ? decision.action.place : null,
          walked: trail.slice(0, Math.max(0, decision.step)), ahead: trail.slice(Math.max(0, decision.step - 1)),
          frame: decision.has_frame ? frameUrl(ui.run, decision.frame) : null, index};
}

function drawEyes(now) {
  const img = $("eyes");
  img.hidden = !now.frame;
  $("eyes-none").hidden = Boolean(now.frame);
  // Only a new frame changes the picture, so the image doesn't flicker on every poll.
  if (now.frame && now.frame !== ui.frameSrc) {
    ui.frameSrc = now.frame;
    img.src = now.frame;
  }
  $("eyes-label").textContent = now.live ? "Its eyes, now" : "What it saw";
  $("eyes-when").textContent = [now.clock, now.step !== null && now.step !== undefined ? `step ${now.step}` : ""].filter(Boolean).join(" · ");
}

function drawNow(now) {
  const state = ui.data.state;
  const rows = [];
  let doing = describe(now.action);
  if (now.live && now.route.length && now.goal && now.agent) doing = `Walking to ${placeName(now.goal)}, ${routeLength(now.agent, now.route)} m to go`;
  rows.push(["Doing", doing || "Nothing yet"]);
  if (now.live) {
    rows.push(["Carrying", words(now.agent?.carrying) || "nothing"]);
    rows.push(["At", now.agent?.place ? placeName(now.agent.place) : "out in the streets"]);
  } else if (!state.derived && state.agent) {
    // A run with live.json knows how it ended; an older one only knows where it walked.
    rows.push(["Carrying at the end", words(state.agent.carrying) || "nothing"]);
  }
  rows.push(["Vision", state.vision || "unknown"]);
  $("now-facts").innerHTML = rows.map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join("");
  $("now-label").textContent = now.live ? "Now" : "At this decision";
  $("now-clock").textContent = now.clock || "";
  $("thought").textContent = now.thought || "—";
  $("result").textContent = now.result || "—";
  $("heard").innerHTML = now.heard.length ? now.heard.map(line => `<li>${escapeHtml(line)}</li>`).join("") : `<li class="meta">Nothing</li>`;
}

// --- the map: the shared city drawing, with the agent and the people over it -----------------------------

function setView() {
  const svg = $("plan-svg"), [width, height] = ui.size;
  const aspect = 642 / 612;
  const agent = moment().agent;
  if (ui.follow && agent) ui.view = [agent.x_m - FOLLOW_M / 2, agent.y_m - FOLLOW_M * aspect / 2, FOLLOW_M, FOLLOW_M * aspect];
  else ui.view = [-6, -6, width + 12, height + 36];
  svg.setAttribute("viewBox", ui.view.join(" "));
}

function drawOverlay(now) {
  const svg = $("plan-svg");
  svg.querySelector(".layer-agent")?.remove();
  setView();
  const g = el("g", {class: "layer layer-agent"}, svg);
  // Marks stay one size on screen at every zoom: k is metres per screen pixel.
  const k = ui.view[2] / Math.max(1, svg.clientWidth || 600);
  const line = (points, cls) => points.length > 1 && el("polyline", {points: points.map(p => p.join(",")).join(" "), class: cls}, g);
  line(now.ahead || [], "trail-ahead");
  line(now.walked || [], "trail");
  if (now.goal && ui.places[now.goal]) {
    const [cx, cy] = ui.places[now.goal].pos_m;
    el("circle", {cx, cy, r: 8 * k, class: "goal"}, g);
  }
  if (now.agent && now.route.length) line([[now.agent.x_m, now.agent.y_m], ...now.route], "route");
  for (const thing of now.objects) {
    if (thing.held_by) continue;
    const s = 3.5 * k;
    el("rect", {x: thing.x_m - s, y: thing.y_m - s, width: 2 * s, height: 2 * s, class: "object"}, g);
    el("text", {x: thing.x_m + 6 * k, y: thing.y_m, class: "mark-label", "font-size": 11 * k}, g).textContent = words(thing.id);
  }
  for (const npc of now.npcs) {
    el("circle", {cx: npc.x_m, cy: npc.y_m, r: 4 * k, class: "npc"}, g);
    el("text", {x: npc.x_m + 7 * k, y: npc.y_m, class: "mark-label", "font-size": 11 * k}, g).textContent = npc.name;
  }
  if (now.agent) {
    const {x_m: x, y_m: y, yaw} = now.agent;
    // yaw 0 faces +x (east), 90 faces +y (south): the same as the plan's own axes, so it needs no flip.
    if (yaw !== null && yaw !== undefined) {
      const a = yaw * Math.PI / 180;
      el("line", {x1: x, y1: y, x2: x + Math.cos(a) * 22 * k, y2: y + Math.sin(a) * 22 * k, class: "agent-heading"}, g);
    }
    el("circle", {cx: x, cy: y, r: 7 * k, class: "agent-dot"}, g);
  }
  const notes = [];
  if (!now.agent) notes.push("No position recorded");
  else if (!now.live && !now.npcs.length) notes.push("Other people weren't recorded");
  $("map-note").textContent = notes.join(" · ");
}

function hideQuietLayers() {
  for (const [name, , on] of LAYERS) $("plan-svg").querySelector(`.layer-${name}`)?.toggleAttribute("hidden", !on);
}

// --- the decision log -------------------------------------------------------------------------------------

function drawLog() {
  const {decisions} = ui.data;
  const key = `${ui.run}:${decisions.length}`;
  const list = $("decisions");
  $("log-count").textContent = decisions.length ? `${decisions.length}` : "";
  if (key !== ui.logKey) {
    ui.logKey = key;
    const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 80;
    list.innerHTML = decisions.length ? decisions.map((d, i) => `<li><button type="button" class="decision" data-index="${i}">
      ${d.has_frame ? `<img src="${frameUrl(ui.run, d.frame)}" alt="" loading="lazy" width="96" height="54">` : `<span class="no-thumb"></span>`}
      <span class="decision-text">
        <span class="eyebrow">${escapeHtml(d.clock)} · step ${d.step}</span>
        <span class="decision-thought">${escapeHtml(d.thought)}</span>
        <span class="mono">${escapeHtml(describe(d.action))}</span>
        ${d.notes.map(note => `<span class="meta">${escapeHtml(note)}</span>`).join("")}
        ${d.replies.map(reply => `<span class="reply"><b>${escapeHtml(reply.name)}</b> ${escapeHtml(reply.text)}</span>`).join("")}
      </span></button></li>`).join("") : `<li class="none">No decisions recorded in this run.</li>`;
    // While live, the newest decision stays in view unless you've scrolled up to read.
    if (ui.data.live && nearBottom || ui.firstLog) list.scrollTop = ui.data.live ? list.scrollHeight : 0;
    ui.firstLog = false;
  }
  list.querySelectorAll(".decision").forEach(button => { button.setAttribute("aria-current", String(!ui.data.live && Number(button.dataset.index) === ui.index)); });
}

function drawReplay() {
  const {decisions, live} = ui.data;
  const replay = !live && decisions.length > 0;
  $("replay").hidden = !replay;
  if (!replay) return;
  $("scrub").max = decisions.length - 1;
  $("scrub").value = ui.index;
  $("scrub-text").textContent = `${ui.index + 1} of ${decisions.length}`;
  $("prev").disabled = ui.index === 0;
  $("next").disabled = ui.index === decisions.length - 1;
}

function drawStatus() {
  const line = $("status-line"), data = ui.data;
  line.classList.toggle("live", Boolean(data?.live));
  if (!data) return;
  if (data.live) {
    const age = data.age_s + (Date.now() - ui.fetchedAt) / 1000;
    $("status-text").textContent = `Live · updated ${ago(age)}`;
  } else {
    $("status-text").textContent = data.decisions.length ? `Finished · replaying ${data.decisions.length} decisions` : "Finished · nothing to replay";
  }
  const state = data.state;
  $("who").textContent = [state.who, state.situation].filter(Boolean).join(" ");
}

function render() {
  if (!ui.data) return;
  const now = moment();
  drawStatus();
  drawEyes(now);
  drawNow(now);
  if (ui.world) drawOverlay(now);
  drawReplay();
  drawLog();
}

// --- fetching ---------------------------------------------------------------------------------------------

async function getJson(url) {
  const response = await fetch(url);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}

function fail(error) {
  $("status-line").classList.remove("live");
  $("status-text").textContent = `Can't read the run: ${error.message}`;
}

async function loadRuns() {
  try {
    const body = await getJson("/api/city-live/runs");
    if (ui.uiVersion !== null && body.ui_version !== ui.uiVersion) location.reload();
    ui.uiVersion = body.ui_version;
    ui.runs = body.runs;
    const select = $("run");
    const options = body.runs.map(run => `<option value="${escapeHtml(run.run)}">${escapeHtml(run.run)}${run.live ? " · live" : ""} · ${run.decisions} decisions</option>`).join("");
    if (select.innerHTML !== options) { select.innerHTML = options || `<option value="">No runs yet</option>`; }
    if (!ui.run && body.runs.length) {
      const wanted = new URLSearchParams(location.search).get("run");
      const pick = body.runs.find(run => run.run === wanted) || body.runs.find(run => run.live) || body.runs[0];
      choose(pick.run);
    }
    select.value = ui.run || "";
    // A run that has started being live again since it was opened goes back to polling.
    if (body.runs.find(run => run.run === ui.run)?.live && ui.data && !ui.data.live) loadRun();
  } catch (error) { fail(error); }
}

async function loadRun() {
  const run = ui.run;
  if (!run) return;
  try {
    const body = await getJson(`/api/city-live/run?run=${encodeURIComponent(run)}`);
    if (run !== ui.run) return;
    const first = !ui.data || ui.data.run !== run;
    const ended = ui.data?.live && !body.live;
    ui.data = body;
    ui.fetchedAt = Date.now();
    if (first || ended) ui.index = body.live ? 0 : Math.max(0, body.decisions.length - 1);
    render();
  } catch (error) { fail(error); }
  clearTimeout(ui.timer);
  // Only a live run is polled. A finished one doesn't change.
  if (ui.data?.live) ui.timer = setTimeout(loadRun, LIVE_MS);
}

function choose(run) {
  ui.run = run;
  ui.data = null;
  ui.logKey = "";
  ui.firstLog = true;
  ui.frameSrc = "";
  const url = new URL(location.href);
  url.searchParams.set("run", run);
  history.replaceState(null, "", url);
  loadRun();
}

async function loadWorld() {
  try {
    const body = await getJson("/api/city");
    ui.world = body.world;
    ui.places = Object.fromEntries(body.world.places.map(place => [place.id, place]));
    ui.size = drawCity($("plan-svg"), body.world);
    hideQuietLayers();
    render();
  } catch (error) { $("map-note").textContent = `Can't read the plan: ${error.message}`; }
}

function step(by) {
  if (!ui.data || ui.data.live) return;
  ui.index = Math.min(ui.data.decisions.length - 1, Math.max(0, ui.index + by));
  render();
}

function wire() {
  $("run").addEventListener("change", event => choose(event.target.value));
  $("scrub").addEventListener("input", event => { ui.index = Number(event.target.value); render(); });
  $("prev").addEventListener("click", () => step(-1));
  $("next").addEventListener("click", () => step(1));
  $("decisions").addEventListener("click", event => {
    const button = event.target.closest(".decision");
    if (!button || ui.data?.live) return;
    ui.index = Number(button.dataset.index);
    render();
  });
  document.addEventListener("keydown", event => {
    if (event.target.closest("input, select, textarea")) return;
    if (event.key === "ArrowLeft") step(-1);
    if (event.key === "ArrowRight") step(1);
  });
  const setFollow = on => {
    ui.follow = on;
    $("follow").setAttribute("aria-pressed", String(on));
    $("fit").setAttribute("aria-pressed", String(!on));
    try { localStorage.setItem("city-live-follow", on ? "1" : "0"); } catch {}
    render();
  };
  $("follow").addEventListener("click", () => setFollow(true));
  $("fit").addEventListener("click", () => setFollow(false));
  try { ui.follow = localStorage.getItem("city-live-follow") !== "0"; } catch {}
  $("follow").setAttribute("aria-pressed", String(ui.follow));
  $("fit").setAttribute("aria-pressed", String(!ui.follow));
  window.addEventListener("resize", () => render());
  // The "updated N s ago" line keeps counting between polls.
  setInterval(() => { if (ui.data?.live) drawStatus(); }, 1000);
}

wire();
loadWorld();
loadRuns();
setInterval(loadRuns, RUNS_MS);
