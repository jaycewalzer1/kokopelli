// The training view. It polls what a run has written to disk and redraws; nothing here can change a run.
const $ = id => document.getElementById(id);
const POLL_MS = 2000, VARIABLES = ["security", "belonging", "ambition", "energy"];
const WARNING = "Every group has given the same action for five updates. Identical replies tie, and a tie has no gradient, so this run has stopped learning.";
// Until a run is picked, the view follows whichever one is training.
const ui = {name: new URLSearchParams(location.hash.slice(1)).get("run"), picked: location.hash.length > 1, uiVersion: null, charts: {}};

const escapeHtml = text => String(text).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const fixed = (value, places = 1) => value == null ? "n/a" : value.toFixed(places);

function duration(seconds) {
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

// One series on one axis. references are horizontal lines to read it against: the gold one is what it has to beat.
function drawChart(element, points, {key = false, references = [], format = fixed, xMax = null} = {}) {
  if (!points.length) { element.innerHTML = `<div class="empty">Nothing logged yet</div>`; return; }
  const {width, height} = element.getBoundingClientRect();
  const margin = {left: 36, right: references.length ? 64 : 8, top: 8, bottom: 18};
  const ys = [...points.map(p => p.y), ...references.map(r => r.y)];
  let low = Math.min(...ys), high = Math.max(...ys);
  if (low === high) { low -= 1; high += 1; }
  const xLow = 0, xHigh = Math.max(xMax ?? 0, ...points.map(p => p.x), 1);
  const x = v => margin.left + (v - xLow) / (xHigh - xLow) * (width - margin.left - margin.right);
  const y = v => margin.top + (high - v) / (high - low) * (height - margin.top - margin.bottom);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(p.x).toFixed(1)} ${y(p.y).toFixed(1)}`).join("");
  const grid = [high, (low + high) / 2, low].map(v => `<path class="chart-grid" d="M${margin.left} ${y(v)}H${width - margin.right}"/><text x="${margin.left - 4}" y="${y(v) + 4}" text-anchor="end">${format(v)}</text>`).join("");
  const lines = references.map(r => `<path class="${r.quiet ? "reference-quiet" : "chart-reference"}" d="M${margin.left} ${y(r.y)}H${width - margin.right}"/><text x="${width - margin.right + 4}" y="${y(r.y) + 4}">${escapeHtml(r.label)}</text>`).join("");
  const dots = key ? points.map(p => `<circle class="point" cx="${x(p.x)}" cy="${y(p.y)}" r="4"/>`).join("") : "";
  element.innerHTML = `<svg role="img" aria-label="${points.length} points, latest ${format(points.at(-1).y)}">${grid}${lines}<path class="${key ? "chart-key" : "chart-line"}" d="${line}"/>${dots}<text x="${margin.left}" y="${height - 4}">${xLow}</text><text x="${width - margin.right}" y="${height - 4}" text-anchor="end">update ${xHigh}</text><path class="crosshair" d="" hidden/></svg><div class="readout" hidden></div>`;
  ui.charts[element.id] = {points, x, format, margin, width};
}

// A crosshair and the exact number, which the axis alone can't give.
function addHover(element) {
  element.addEventListener("pointermove", event => {
    const chart = ui.charts[element.id];
    if (!chart) return;
    const box = element.getBoundingClientRect(), at = event.clientX - box.left;
    const point = chart.points.reduce((a, b) => Math.abs(chart.x(b.x) - at) < Math.abs(chart.x(a.x) - at) ? b : a);
    const cross = element.querySelector(".crosshair"), readout = element.querySelector(".readout");
    if (!cross || !readout) return;
    cross.hidden = false;
    cross.setAttribute("d", `M${chart.x(point.x)} 0V${box.height - 18}`);
    readout.hidden = false;
    readout.textContent = `update ${point.x}: ${chart.format(point.y)}`;
    const left = chart.x(point.x) + 8;
    readout.style.left = `${Math.min(left, box.width - readout.offsetWidth)}px`;
  });
  element.addEventListener("pointerleave", () => {
    element.querySelector(".crosshair")?.setAttribute("d", "");
    element.querySelector(".readout")?.setAttribute("hidden", "");
  });
}

const actionName = action => action === "None" ? "invalid" : action;

function actionMarkup(run) {
  const latest = run.validation.at(-1), base = run.baselines.base;
  const rows = latest ?? base;
  if (!rows) return `<div class="none">No validation has finished yet</div>`;
  const total = Object.values(rows.actions).reduce((a, b) => a + b, 0);
  const heading = latest ? `Update ${latest.iteration}` : "Untrained model";
  const lines = Object.entries(rows.actions).map(([action, count]) => {
    const share = count / total * 100;
    return `<div class="action-row"><span>${escapeHtml(actionName(action))}</span><b>${share.toFixed(0)}%</b><i style="width:${share}%"></i></div>`;
  }).join("");
  const compare = latest && base ? `<div class="none">Untrained: ${Object.entries(base.actions).map(([a, n]) => `${escapeHtml(actionName(a))} ${(n / Object.values(base.actions).reduce((x, y) => x + y, 0) * 100).toFixed(0)}%`).join(", ")}</div>` : "";
  return `<div class="none">${heading}</div>${lines}${compare}`;
}

function groupMarkup(group) {
  const variables = VARIABLES.map((name, i) => {
    const value = group.values[i], low = group.low[i], high = group.high[i];
    const off = value < low ? value - low : value > high ? value - high : 0;
    return `<div class="variable${off ? " off" : ""}"><span>${name}</span><span>${value.toFixed(0)} in ${low.toFixed(0)}-${high.toFixed(0)}</span><span>${off ? (off > 0 ? "+" : "") + off.toFixed(1) : "ok"}</span></div>`;
  }).join("");
  const tally = new Map();
  group.replies.forEach((reply, i) => {
    const key = reply.trim() || "(nothing)";
    tally.set(key, {count: (tally.get(key)?.count ?? 0) + 1, score: group.scores[i]});
  });
  const sorted = [...tally].sort((a, b) => b[1].score - a[1].score);
  const replies = sorted.map(([reply, {count, score}], i) => `<div class="reply${i === 0 && sorted.length > 1 ? " best" : ""}"><span>${escapeHtml(reply.slice(0, 24))}</span><span>×${count}</span><span>${score > 0 ? "+" : ""}${score.toFixed(1)}</span></div>`).join("");
  const age = duration(Date.now() / 1000 - group.time);
  return `<div class="group"><div class="group-meta">Turn ${group.turn + 1}, last action ${escapeHtml(group.last ?? "none")}, ${age} ago</div>${variables}<div>${replies}</div></div>`;
}

function resultsMarkup(results) {
  const columns = [["mean_drive", "mean drive"], ["in_range", "in range"], ["above", "above"], ["deaths", "died"], ["invalid", "invalid"]];
  const rows = Object.entries(results).map(([name, summary]) => `<tr><td>${escapeHtml(name)}</td>${columns.map(([key]) => `<td>${fixed(summary[key], 2)}</td>`).join("")}</tr>`).join("");
  return `<div class="table-scroll"><table><thead><tr><th>policy</th>${columns.map(([, label]) => `<th>${label}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

function statusText(run) {
  const progress = run.total ? `update ${run.done} of ${run.total}` : `update ${run.done}`;
  if (run.state === "finished") return `Finished at update ${run.done}`;
  if (run.state === "stopped") return `Stopped at update ${run.done}, ${duration(run.seconds_since_update)} ago`;
  if (run.validating) return `Validating, life ${run.validating.done} of ${run.validating.total}, ${progress}`;
  return `Training, ${progress}, last write ${duration(run.seconds_since_update)} ago`;
}

function draw(run) {
  const statusLine = $("status-line");
  statusLine.classList.toggle("live", run.state === "training");
  $("status-text").textContent = statusText(run);
  $("warning").hidden = !run.collapsed;
  $("warning").textContent = run.collapsed ? WARNING : "";

  const {base, planner, greedy} = run.baselines;
  const references = [
    base && {y: base.mean_drive, label: "untrained"},
    greedy && {y: greedy.mean_drive, label: "greedy", quiet: true},
    planner && {y: planner.mean_drive, label: "planner", quiet: true},
  ].filter(Boolean);
  const series = (rows, key) => rows.filter(row => row[key] != null).map(row => ({x: row.iteration, y: row[key]}));
  const xMax = run.total;
  drawChart($("validation"), series(run.validation, "mean_drive"), {key: true, references, xMax});
  $("validation-key").textContent = references.length ? "The gold line is the untrained model. Dotted lines know the true effects, so they're what's possible." : "";
  drawChart($("reward"), series(run.train, "train_reward_mean"), {xMax});
  drawChart($("distinct"), series(run.train, "train_distinct_actions"), {format: v => fixed(v, 2), xMax});
  drawChart($("invalid"), series(run.train, "train_invalid_rate"), {format: v => fixed(v, 2), xMax});
  $("actions").innerHTML = actionMarkup(run);
  $("groups").innerHTML = run.groups.length ? run.groups.map(groupMarkup).join("") : `<div class="none">This run started before groups were logged, or hasn't scored one yet.</div>`;
  const hasResults = Object.keys(run.results).length > 0;
  $("results-section").hidden = !hasResults;
  if (hasResults) $("results").innerHTML = resultsMarkup(run.results);
}

async function get(path) {
  const response = await fetch(path);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error);
  return body;
}

async function poll() {
  try {
    const {runs, ui_version: version} = await get("/api/training/runs");
    if (ui.uiVersion !== null && version !== ui.uiVersion) location.reload();
    ui.uiVersion = version;
    const live = runs.find(run => run.state === "training");
    if (!runs.some(run => run.name === ui.name) || (!ui.picked && live)) ui.name = (live ?? runs[0])?.name ?? null;
    $("runs").innerHTML = runs.map(run => `<option value="${escapeHtml(run.name)}"${run.name === ui.name ? " selected" : ""}>${escapeHtml(run.name)} (${run.state})</option>`).join("");
    if (!ui.name) { $("status-text").textContent = "No training runs yet. Start one with make homeostatic."; return; }
    if (ui.picked) history.replaceState(null, "", `#run=${encodeURIComponent(ui.name)}`);
    draw(await get(`/api/training/run?name=${encodeURIComponent(ui.name)}`));
  } catch (error) {
    $("status-text").textContent = `Can't read the run: ${error.message}`;
  }
}

$("runs").addEventListener("change", event => { ui.name = event.target.value; ui.picked = true; poll(); });
for (const id of ["validation", "reward", "distinct", "invalid"]) addHover($(id));
addEventListener("resize", poll);
poll();
setInterval(poll, POLL_MS);
