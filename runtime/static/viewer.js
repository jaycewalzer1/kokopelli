// Draws one run from /api/run. Every value comes from the run's log, so text is only ever set as text.
const byId = (id) => document.getElementById(id);
const file = (path) => `/files/${path}`;
const theme = new URLSearchParams(location.search).get("theme");
if (theme) document.documentElement.dataset.theme = theme;

const page = { ticks: [], index: 0, playing: null, truth: "rgb", detail: "World model prompt" };
const TRUTH = { rgb: "Color", depth: "Depth", seg: "Segments" };

function actionText(action) {
  const detail = action.target || (action.text ? `"${action.text}"` : "");
  return `${action.type.replace("_", " ")} ${detail}`.trim();
}

function details(tick) {
  return {
    "World model prompt": `${tick.wm_prompt.text}\n\nConditioning frames:\n${tick.wm_prompt.cond.map((f) => `${f.source}  ${f.path}`).join("\n")}`,
    "Agent prompt": tick.agent_input.prompt,
    "Agent replies": tick.outputs.map((o) => `try ${o.attempt}, ${o.valid ? "valid" : `rejected: ${o.error}`}, ${o.seconds}s\n${o.raw}`).join("\n\n"),
    "Sim state": JSON.stringify(tick.sim.state, null, 2),
    "Timing": Object.entries(tick.timing.seconds).map(([stage, value]) => `${stage.padEnd(12)}${value.toFixed(3)}s`).join("\n")
      + "\n\nPeak RAM on the whole machine\n"
      + Object.entries(tick.timing.memory_gb || {}).map(([stage, value]) => `${stage.padEnd(12)}${value === null ? "n/a" : `${value} GB`}`).join("\n"),
  };
}

function setTabs(holder, labels, active, choose) {
  holder.replaceChildren(...labels.map(([value, label]) => {
    const tab = document.createElement("button");
    tab.className = "tab";
    tab.textContent = label;
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", value === active);
    tab.onclick = () => choose(value);
    return tab;
  }));
}

function drawChart(run) {
  const svg = byId("chart");
  const width = 1000, height = 120, pad = 4;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const checks = page.ticks.flatMap((tick, index) => tick.drift.map((check) => ({ ...check, index })));
  const threshold = run.run_start ? run.run_start.config.drift_threshold : 0;
  const top = Math.max(1, ...checks.map((check) => check.score));
  const x = (i) => pad + (i / Math.max(1, checks.length - 1)) * (width - 2 * pad);
  const y = (value) => height - pad - (value / top) * (height - 2 * pad);
  const shape = (name, attributes) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
    node.setAttribute("vector-effect", "non-scaling-stroke");
    return node;
  };
  const line = (cls, y1) => shape("line", { class: cls, x1: 0, x2: width, y1, y2: y1 });
  const parts = [line("chart-grid", y(0)), line("chart-reference", y(threshold))];
  checks.forEach((check, i) => {
    if (check.reanchor) parts.push(shape("line", { class: "chart-grid", x1: x(i), x2: x(i), y1: 0, y2: height }));
  });
  parts.push(shape("polyline", { class: "chart-line", points: checks.map((check, i) => `${x(i)},${y(check.score)}`).join(" ") }));
  const here = checks.findIndex((check) => check.index === page.index);
  if (here >= 0) parts.push(shape("line", { class: "chart-line", x1: x(here), x2: x(here), y1: height - 12, y2: height }));
  svg.replaceChildren(...parts);
}

function draw(run) {
  const tick = page.ticks[page.index];
  const total = page.ticks.length;
  byId("headline").textContent = `Tick ${tick.tick} of ${total}`;
  byId("moment").textContent = `${tick.sim.state.sim_time}, ${tick.sim.state.time_of_day}, ${tick.sim.state.weather}`;
  byId("slider").value = page.index;

  const clip = tick.chunks[tick.chunks.length - 1];
  const video = byId("clip");
  if (video.dataset.clip !== clip.clip) {
    video.dataset.clip = clip.clip;
    video.src = file(clip.clip);
    if (page.playing) video.play().catch(() => {});
  }
  byId("clip-note").textContent = `Last of ${tick.chunks.length} chunks, ${clip.frames} frames, rendered in ${clip.seconds.toFixed(2)}s.`;

  const capture = tick.sim.captures[tick.sim.captures.length - 1];
  // SimWorld saves raw depth as numbers rather than a picture, so that view only exists on the mock.
  const views = Object.entries(TRUTH).filter(([view]) => !capture[view].endsWith(".npy"));
  if (!views.some(([view]) => view === page.truth)) page.truth = "rgb";
  byId("truth").src = file(capture[page.truth]);
  setTabs(byId("truth-tabs"), views, page.truth, (value) => { page.truth = value; draw(run); });

  byId("action").textContent = actionText(tick.decision.action);
  byId("diary").textContent = tick.decision.diary || "";
  const auto = tick.autonomy;
  const notes = [auto.differs ? `Differs from the tree's default (${auto.default}).` : `Same as the tree's default (${auto.default}).`];
  if (tick.fallback) notes.push("Two invalid replies, so this tick became a wait.");
  notes.push(`Leak check ${tick.agent_input.leak_check}. ${tick.wm_prompt.dropped_future} future items dropped.`);
  byId("decision-note").textContent = notes.join(" ");
  byId("strip").replaceChildren(...tick.agent_input.images.map((path, index) => {
    const image = document.createElement("img");
    image.src = file(path);
    image.alt = `Frame ${index + 1} the agent was shown`;
    return image;
  }));

  const text = details(tick);
  setTabs(byId("detail-tabs"), Object.keys(text).map((key) => [key, key]), page.detail, (value) => { page.detail = value; draw(run); });
  byId("detail").textContent = text[page.detail];

  const anchors = tick.reanchors.map((item) => `${item.reason} at +${item.offset_s}s`).join(", ");
  const scores = tick.drift.map((check) => check.score.toFixed(2)).join(", ");
  byId("chart-note").textContent = `This tick: ${scores || "no check"}${anchors ? `. Re-anchored (${anchors})` : ""}. The gold line is the threshold; vertical rules mark re-anchors.`;
  drawChart(run);
}

function peakMemory(totals) {
  const peaks = Object.values(totals.peak_memory_gb || {});
  return peaks.length ? `${Math.max(...peaks)} GB` : "n/a";
}

function stats(run, name) {
  const totals = run.totals;
  const away = run.counterfactual ? `${run.counterfactual.final_distance} cells` : "not run";
  const rows = [["Ticks", totals.ticks], ["Differs from tree", totals.autonomy === null ? "n/a" : `${Math.round(totals.autonomy * 100)}%`],
    ["From null agent", away], ["Re-anchors", totals.reanchors], ["Invalid replies", totals.invalid_replies],
    ["Compute", `${(totals.seconds.total || 0).toFixed(1)}s`], ["Peak RAM", peakMemory(totals)], ["Cost", `$${totals.cost_usd.toFixed(2)}`], ["Events", totals.events]];
  byId("stats").replaceChildren(...rows.flatMap(([label, value]) => {
    const wrap = document.createElement("div");
    const term = document.createElement("dt");
    const data = document.createElement("dd");
    term.textContent = label;
    data.textContent = value;
    wrap.append(term, data);
    return [wrap];
  }));
  byId("run-name").textContent = name;
  document.title = "Run Replay";
  if (run.alarms.length) {
    const box = byId("alarms");
    box.hidden = false;
    box.textContent = `Leak alarm at tick ${run.alarms[0].tick}: ${run.alarms[0].error}`;
  }
}

function move(run, to) {
  page.index = Math.max(0, Math.min(page.ticks.length - 1, to));
  draw(run);
}

function togglePlay(run) {
  const button = byId("play");
  if (page.playing) {
    clearInterval(page.playing);
    page.playing = null;
    button.textContent = "Play";
    return;
  }
  if (page.index === page.ticks.length - 1) move(run, 0);
  button.textContent = "Pause";
  page.playing = setInterval(() => {
    if (page.index === page.ticks.length - 1) togglePlay(run);
    else move(run, page.index + 1);
  }, 1500);
}

async function start() {
  const data = await (await fetch("/api/run")).json();
  page.ticks = data.ticks;
  stats(data.run, data.name);
  if (!page.ticks.length) {
    byId("headline").textContent = "No finished ticks yet";
    return;
  }
  byId("slider").max = page.ticks.length - 1;
  byId("slider").oninput = (event) => move(data.run, Number(event.target.value));
  byId("prev").onclick = () => move(data.run, page.index - 1);
  byId("next").onclick = () => move(data.run, page.index + 1);
  byId("play").onclick = () => togglePlay(data.run);
  draw(data.run);
}

start().catch((error) => {
  byId("headline").textContent = "This run couldn't be read";
  byId("moment").textContent = String(error);
});
