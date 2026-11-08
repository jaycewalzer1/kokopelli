// The GPU queue as one screen: what has the GPU (with a running clock), the GPU and memory as moving lines, twelve hours as a
// timeline, the line of waiting jobs, and recent results. Details and every control live in a drawer that opens on a job, so
// the board itself stays readable at a glance. The data is polled; between polls the clocks, bars and charts keep moving.
const $ = id => document.getElementById(id);
const POLL_MS = 3000;
const CONFIRM_MS = 5000;
const CHART_S = 15 * 60;
const GROUPS = ["demo", "training", "evals", "mind", "other"];
const ui = {data: null, offset: 0, samples: [], open: null, confirming: null, busy: false, logs: {}, uiVersion: null, drawerHtml: ""};

const escapeHtml = text => String(text ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const plural = (n, thing) => `${n.toLocaleString("en-US")} ${thing}${n === 1 ? "" : "s"}`;
const now = () => Date.now() / 1000 + ui.offset;  // the server's clock, so ages don't depend on this machine's
const dot = group => `<span class="dot g-${escapeHtml(group || "other")}" aria-hidden="true"></span>`;
const tag = (text, kind = "") => `<span class="tag ${kind}">${escapeHtml(text)}</span>`;
const fileUrl = (id, item) => `/api/queue/output?id=${encodeURIComponent(id)}&n=${item.n}&v=${Math.round(item.at || 0)}`;

function span(seconds) {
  if (seconds == null) return "?";
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return seconds < 172800 ? `${(seconds / 3600).toFixed(1)} h` : `${Math.round(seconds / 86400)} days`;
}
function clock(seconds) {
  const s = Math.max(0, Math.floor(seconds)), h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
const QUIET_WARNING = 1800;  // seconds without log output before the board says so
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ---- the job on the GPU ------------------------------------------------------------------------------------------------

function nowMarkup(data) {
  const holders = [...data.running.map(job => ({...job, place: "on this Mac"})), ...data.on_pace.map(job => ({...job, place: "on PACE"}))];
  if (!holders.length && data.outside.length) {
    const job = data.outside[0];
    return `<div class="panel-head"><span class="eyebrow">On the GPU now</span></div><div class="holder-name">${escapeHtml(job.name)}</div>
      <p class="meta">Started without the queue${job.queue_waits ? "; the queue waits for it" : ", and the queue can't see it"}. pid ${job.pid}.</p>`;
  }
  if (!holders.length) {
    const next = data.waiting[0];
    return `<div class="panel-head"><span class="eyebrow">On the GPU now</span></div><div class="holder-name idle">Free</div>
      <p class="meta">${next ? (next.waiting_for && !next.waiting_for.includes("has the GPU") ? `${escapeHtml(next.name)} is held: ${escapeHtml(next.waiting_for)}.` : `${escapeHtml(next.name)} goes at the queue's next check.`) : "Nothing is waiting."}</p>`;
  }
  const job = holders[0];
  const picture = (job.files || []).find(item => item.kind === "image" || item.kind === "video");
  const media = picture ? (picture.kind === "video"
    ? `<video src="${fileUrl(job.id, picture)}" muted loop autoplay playsinline aria-label="${escapeHtml(picture.name)}"></video>`
    : `<img src="${fileUrl(job.id, picture)}" alt="${escapeHtml(picture.name)}">`) : "";
  const limit = job.limit_seconds ? `<div class="limit" role="img" aria-label="Share of its time limit used"><i data-limit="${job.limit_seconds}" data-from="${job.started_at}"></i></div>
    <div class="meta"><span data-used="${job.started_at}"></span> of ${span(job.limit_seconds)} allowed</div>` : `<div class="meta">No time limit</div>`;
  const more = holders.length > 1 ? `<p class="warning">${holders.length} jobs hold the GPU at once.</p>` : "";
  return `<div class="panel-head"><span class="eyebrow">On the GPU now · ${escapeHtml(job.place)}</span><button type="button" class="link" data-open="${escapeHtml(job.id)}">Details</button></div>
    <div class="holder"><div class="holder-text">
      <div class="holder-name">${dot(job.group)}<span>${escapeHtml(job.name)}</span></div>
      <div class="elapsed" data-since="${job.started_at}">${clock(now() - job.started_at)}</div>
      ${limit}${job.quiet_seconds >= QUIET_WARNING ? `<p class="warning">No log output for ${span(job.quiet_seconds)}.</p>` : ""}<p class="about clamp">${escapeHtml(job.about || "Not described.")}</p>${more}
    </div>${media ? `<div class="holder-media">${media}</div>` : ""}</div>`;
}

// ---- moving charts -----------------------------------------------------------------------------------------------------

function sample(data) {
  // The server keeps a reading about a minute apart; each poll adds one, so the line moves every few seconds.
  const seen = new Set(ui.samples.map(point => Math.round(point.at)));
  for (const row of data.history) if (!seen.has(Math.round(row.at))) ui.samples.push({at: row.at, busy: row.busy, memory: row.memory});
  ui.samples.push({at: data.now, busy: data.device.busy_percent, memory: data.device.memory_gb});
  ui.samples.sort((a, b) => a.at - b.at);
  ui.samples = ui.samples.filter(point => point.at > data.now - CHART_S - 60);
}

function chart(canvas, key, top, guides) {
  const box = canvas.getBoundingClientRect();
  if (!box.width || !box.height) return;
  const ratio = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(box.width * ratio) || canvas.height !== Math.round(box.height * ratio)) {
    canvas.width = Math.round(box.width * ratio);
    canvas.height = Math.round(box.height * ratio);
  }
  const g = canvas.getContext("2d");
  g.setTransform(ratio, 0, 0, ratio, 0, 0);
  g.clearRect(0, 0, box.width, box.height);
  const end = now(), start = end - CHART_S, w = box.width, h = box.height - 14;
  const x = at => (at - start) / CHART_S * w, y = value => h - Math.min(value, top) / top * (h - 4);
  g.font = `11px ${css("--font-mono")}`;
  g.lineWidth = 1;
  g.strokeStyle = css("--hairline");
  g.fillStyle = css("--ink-muted");
  for (const value of guides) {
    g.beginPath(); g.moveTo(0, Math.round(y(value)) + 0.5); g.lineTo(w, Math.round(y(value)) + 0.5); g.stroke();
    g.fillText(String(value), 2, y(value) + 12);  // under its line, so the top one stays clear of the reading
  }
  for (const minutes of [10, 5]) g.fillText(`−${minutes} min`, x(end - minutes * 60) - 16, box.height - 2);
  g.strokeStyle = css("--ink");
  g.lineWidth = 1.5;
  g.beginPath();
  let pen = false, last = null;
  for (const point of ui.samples) {
    if (point[key] == null || point.at < start - 120) { pen = false; continue; }
    const px = x(point.at), py = y(point[key]);
    if (pen) g.lineTo(px, py); else g.moveTo(px, py);
    pen = true;
    last = {px, py};
  }
  if (last) g.lineTo(w, last.py);  // the latest reading holds until the next one
  g.stroke();
  if (last) { g.fillStyle = css("--ink"); g.fillRect(w - 4, last.py - 2, 4, 4); }
}

function drawCharts() {
  const total = ui.data?.device.total_gb || 36;
  chart($("busy-chart"), "busy", 100, [50, 100]);
  chart($("memory-chart"), "memory", total, [Math.round(total / 2), total]);
}

// ---- the timeline ------------------------------------------------------------------------------------------------------

function pack(items, from, to) {
  const rows = [];
  for (const item of items) {
    let row = rows.findIndex(end => end <= from(item));
    if (row < 0) { row = rows.length; rows.push(0); }
    rows[row] = to(item) + 60;
    item.row = row;
  }
  return Math.max(1, rows.length);
}

function timelineMarkup(data) {
  const box = $("timeline");
  const width = Math.max(320, box.clientWidth), height = Math.max(120, box.clientHeight);
  const end = now(), since = end - 12 * 3600, left = 44, right = 56, plot = width - left - right;
  const x = at => left + Math.max(0, Math.min(1, (at - since) / (end - since))) * plot;
  const jobs = data.timeline.jobs.map(job => ({...job}));
  const runs = jobs.filter(job => job.started && job.where !== "pace");
  const cloud = jobs.filter(job => job.started && job.where === "pace");
  const waits = jobs.filter(job => (job.started || job.ended || end) - job.queued > 60);
  const runRows = pack(runs, job => job.started, job => job.ended || end);
  const waitRows = pack(waits, job => job.queued, job => job.started || job.ended || end);
  const top = 8, axis = height - 16, laneH = Math.min(22, (axis - top) / (runRows + (cloud.length ? 1 : 0) + Math.min(waitRows, 6) * 0.6 + 1));
  const runY = row => top + row * laneH + laneH / 2;
  const cloudY = top + runRows * laneH + laneH / 2;
  const waitTop = top + (runRows + (cloud.length ? 1 : 0)) * laneH + 8;
  const waitGap = Math.max(5, Math.min(9, (axis - waitTop - 6) / Math.max(1, waitRows)));
  const bar = (job, y) => {
    const x1 = x(job.started), x2 = x(job.ended || end), w = Math.max(3, x2 - x1), live = !job.ended;
    const label = w > 60 ? `<text class="label" x="${x1 + 5}" y="${y + 4}">${escapeHtml(job.name.slice(0, Math.floor((w - 8) / 7)))}</text>` : "";
    return `<g class="g-${escapeHtml(job.group)} hit" data-open="${escapeHtml(job.id)}"><title>${escapeHtml(job.name)}: ${live ? `running ${span(end - job.started)}` : `ran ${span(job.ended - job.started)}`}${job.failed ? ", failed" : ""}</title>
      <rect class="turn${live ? " live" : ""}${job.failed ? " failed" : ""}" x="${x1}" y="${y - laneH / 2 + 3}" width="${w}" height="${laneH - 6}"/>${label}
      ${job.failed ? `<text class="x" x="${x2}" y="${y + 4}" text-anchor="middle">×</text>` : ""}</g>`;
  };
  const wait = job => {
    const y = waitTop + job.row * waitGap;
    if (y > axis - 4) return "";
    const stop = job.started || job.ended || end;
    return `<g class="g-${escapeHtml(job.group)} hit" data-open="${escapeHtml(job.id)}"><title>${escapeHtml(job.name)} ${job.started || job.ended ? "waited" : "has waited"} ${span(stop - job.queued)}</title>
      <line class="wait${job.started || job.ended ? "" : " live"}" x1="${x(job.queued)}" y1="${y}" x2="${x(stop)}" y2="${y}"/><circle cx="${x(job.queued)}" cy="${y}" r="2"/></g>`;
  };
  const ticks = [];
  for (let at = Math.ceil(since / 7200) * 7200; at < end; at += 7200) {
    ticks.push(`<line class="grid" x1="${x(at)}" y1="${top}" x2="${x(at)}" y2="${axis}"/><text x="${x(at)}" y="${height - 3}" text-anchor="middle">${new Date(at * 1000).toLocaleTimeString([], {hour: "numeric"})}</text>`);
  }
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="Turns on the GPU as bars and waits as dotted lines over the last 12 hours">
    ${ticks.join("")}<text x="0" y="${runY(0) + 4}">Mac</text>${cloud.length ? `<text x="0" y="${cloudY + 4}">PACE</text>` : ""}<text x="0" y="${waitTop + 4}">Line</text>
    ${waits.map(wait).join("")}${runs.map(job => bar(job, runY(job.row))).join("")}${cloud.map(job => bar(job, cloudY)).join("")}
    <line class="nowline" x1="${x(end)}" y1="2" x2="${x(end)}" y2="${axis}"/><text class="now" x="${x(end) + 4}" y="12">now</text>
    <text class="now" x="${x(end) + 4}" y="26">${new Date(end * 1000).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"})}</text></svg>`;
}

// ---- the line ----------------------------------------------------------------------------------------------------------

function lineMarkup(data) {
  const longest = Math.max(600, ...data.waiting.map(ticket => now() - ticket.queued_at));
  const holders = [...data.running, ...data.outside];
  const cards = data.waiting.map((ticket, position) => `<button type="button" class="car g-${escapeHtml(ticket.group)}${ui.open === ticket.id ? " open" : ""}" data-open="${escapeHtml(ticket.id)}">
      <span class="car-top"><span class="position">${position + 1}</span><span class="prio">p${escapeHtml(ticket.priority ?? "?")}</span>${ticket.where === "pace" ? tag("PACE") : ""}</span>
      <span class="car-name">${dot(ticket.group)}${escapeHtml(ticket.name)}</span>
      <span class="car-wait"><span data-waited="${ticket.queued_at}">${span(now() - ticket.queued_at)}</span> waiting</span>
      <span class="grow" aria-hidden="true"><i data-grow="${ticket.queued_at}" data-longest="${longest}"></i></span>
      ${position === 0 && (ticket.waiting_for || holders.length) ? `<span class="meta">${ticket.waiting_for ? escapeHtml(ticket.waiting_for) : `after ${escapeHtml(holders.map(job => job.name).join(", "))}`}</span>` : ""}</button>`).join("");
  const staged = (data.staged || []).map(job => `<div class="car staged"><span class="car-top"><span class="prio">p${escapeHtml(job.priority)}</span>${tag("ready to start")}</span>
      <span class="car-name">${escapeHtml(job.name)}</span><span class="meta">${job.estimate ? `about ${job.estimate.hours} h` : ""}</span>
      <button type="button" class="btn-primary" data-act="start" data-name="${escapeHtml(job.name)}"${ui.busy ? " disabled" : ""}>Start</button></div>`).join("");
  return cards + staged || `<div class="none">Nothing is waiting.</div>`;
}

// ---- recent ------------------------------------------------------------------------------------------------------------

function outcome(job) {
  if (job.stopped) return {word: "stopped", bad: false};
  if (job.timed_out) return {word: "timed out", bad: true};
  if (job.state === "finished") return {word: job.exit_code === 0 ? "done" : job.exit_code === 75 ? "paused" : `exit ${job.exit_code}`, bad: job.failed};
  return {word: job.state === "gave_up" ? "gave up" : job.state, bad: job.failed};
}
const scale = rating => `<span class="scale" role="img" aria-label="${rating} of 5">${[1, 2, 3, 4, 5].map(step => `<i class="${step <= rating ? "on" : ""}"></i>`).join("")}</span>`;

function recentMarkup(data) {
  const squares = data.past.slice(0, 40).map(job => {
    const {word, bad} = outcome(job);
    return `<button type="button" class="square ${bad ? "bad" : job.state === "finished" ? "ok" : ""}" data-open="${escapeHtml(job.id)}" title="${escapeHtml(job.name)}: ${escapeHtml(word)}, ${span(now() - job.at)} ago" aria-label="${escapeHtml(job.name)}: ${escapeHtml(word)}"></button>`;
  }).join("");
  const rows = data.past.slice(0, 6).map(job => {
    const {word, bad} = outcome(job);
    const rating = job.result?.rating;
    return `<button type="button" class="past-row${bad ? " failed" : ""}" data-open="${escapeHtml(job.id)}">${dot(job.group)}<span class="past-name">${escapeHtml(job.name)}</span>
      ${tag(word, bad ? "fail" : "")}${rating != null ? scale(rating) : ""}<span class="right">${span(now() - job.at)} ago</span></button>`;
  }).join("");
  return `<div class="squares" aria-label="Newest first">${squares}</div>${rows || `<div class="none">No job has had a turn yet.</div>`}`;
}

// ---- the drawer: everything about one job, and its controls ------------------------------------------------------------

function findJob(id) {
  const data = ui.data;
  const lists = [["running", data.running], ["running", data.on_pace], ["waiting", data.waiting], ["past", data.past]];
  for (const [kind, jobs] of lists) {
    const job = jobs.find(item => item.id === id);
    if (job) return {kind, job};
  }
  const job = data.timeline.jobs.find(item => item.id === id);
  return job ? {kind: "past", job} : null;
}

function filesMarkup(job) {
  const files = job.files || [];
  const media = files.filter(item => item.kind === "image" || item.kind === "video").slice(0, 4).map(item => item.kind === "video"
    ? `<video src="${fileUrl(job.id, item)}" controls muted loop playsinline preload="metadata" aria-label="${escapeHtml(item.name)}"></video>`
    : `<img src="${fileUrl(job.id, item)}" alt="${escapeHtml(item.name)}" loading="lazy">`).join("");
  const others = files.filter(item => !["image", "video"].includes(item.kind));
  const list = others.length ? `<ul class="files">${others.map(item => `<li class="${item.kind}">${escapeHtml(item.name)}${item.kind === "folder" ? ` <span>${plural(item.size || 0, "file")}</span>` : item.kind === "missing" ? " <span>not written</span>" : ""}</li>`).join("")}</ul>` : "";
  return media || list ? `<div class="eyebrow">Outputs</div>${media ? `<div class="media">${media}</div>` : ""}${list}` : "";
}

function controlsMarkup(job) {
  const pace = ui.data.pace;
  const noPace = !job.can_pace ? "No PACE version: its command uses MLX" : pace.ready ? "" : "PACE isn't ready yet";
  const where = value => `<button type="button" data-act="where" data-where="${value}" aria-pressed="${job.where === value}"${(value === "pace" && noPace) || ui.busy ? ` disabled${noPace ? ` title="${escapeHtml(noPace)}"` : ""}` : ""}>${value === "pace" ? "PACE" : "Mac"}</button>`;
  const confirming = ui.confirming === job.id;
  return `<div class="eyebrow">Change it</div><div class="controls" data-id="${escapeHtml(job.id)}">
    <div class="switch" role="group" aria-label="Where it runs">${where("local")}${where("pace")}</div>
    <label>Priority <input type="number" inputmode="numeric" min="0" max="999" step="1" value="${escapeHtml(job.priority ?? "")}"></label>
    <button type="button" data-act="move"${ui.busy ? " disabled" : ""}>Move</button>
    <button type="button" data-act="cancel" class="${confirming ? "confirm" : ""}"${ui.busy ? " disabled" : ""}>${confirming ? "Click again to cancel" : "Cancel job"}</button></div>`;
}

function stopMarkup(job) {
  if (!job.keeper) return job.where === "pace" ? "" : `<p class="meta">Started before jobs had keepers, so it can't be stopped from here.</p>`;
  const confirming = ui.confirming === job.id;
  return `<div class="eyebrow">Change it</div><div class="controls" data-id="${escapeHtml(job.id)}">
    <button type="button" data-act="stop" class="${confirming ? "confirm" : ""}"${ui.busy ? " disabled" : ""}>${confirming ? "Click again to stop it" : "Stop job"}</button></div>`;
}

function drawerMarkup() {
  const found = ui.open && findJob(ui.open);
  if (!found) return "";
  const {kind, job} = found;
  const result = job.result;
  const {word, bad} = kind === "past" ? outcome(job) : {word: kind === "running" ? "running" : "waiting", bad: false};
  const facts = [job.priority != null ? `priority ${job.priority}` : "", job.seconds != null ? `ran ${span(job.seconds)}` : "",
                 job.waited != null ? `waited ${span(job.waited)}` : "", job.peak_job_gb != null ? `${job.peak_job_gb} GB peak` : job.peak_rss_gb != null ? `${job.peak_rss_gb} GB peak` : "",
                 job.swap_grew_gb != null ? `swap +${job.swap_grew_gb} GB` : "", job.gpu_busy_mean != null ? `GPU ${Math.round(job.gpu_busy_mean * 100)}% busy` : "", job.watts_mean != null ? `${Math.round(job.watts_mean)} W` : "",
                 job.gpu_temp_max != null ? `${Math.round(job.gpu_temp_max)} °C peak` : "",
                 job.at ? `${span(now() - job.at)} ago` : ""].filter(Boolean).join(" · ");
  const judged = result ? `<div class="judged">${result.rating != null ? `<span class="score">${escapeHtml(result.rating)}<small>/ 5</small></span>${scale(result.rating)}` : tag("not rated", "unsaid")}
      <span class="label">${escapeHtml(result.rating_label || "")}</span></div>${result.summary ? `<p>${escapeHtml(result.summary)}</p>` : ""}
      ${result.key_numbers?.length ? `<ul class="numbers">${result.key_numbers.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}` : "";
  const log = job.log || kind === "running" ? `<details class="fold" data-log="${escapeHtml(job.id)}"${ui.logs[job.id] != null ? " open" : ""}><summary>Log</summary><pre>${escapeHtml(job.tail ?? ui.logs[job.id] ?? "Opening the log")}</pre></details>` : "";
  const command = job.command?.length ? `<details class="fold"><summary>Command</summary><pre>${escapeHtml(`${job.cwd ? `In ${job.cwd}\n` : ""}${job.command.join(" ")}`)}</pre></details>` : "";
  return `<div class="drawer-head"><div class="holder-name">${dot(job.group)}<span>${escapeHtml(job.name)}</span></div>
      <button type="button" class="link" data-close aria-label="Close details">Close</button></div>
    <div>${tag(word, bad ? "fail" : "")} <span class="meta">${escapeHtml(facts)}</span></div>
    <p class="about">${escapeHtml(job.about || "Queued before jobs had to say what they do.")}</p>
    ${judged}${kind === "waiting" ? controlsMarkup(job) : kind === "running" ? stopMarkup(job) : ""}${filesMarkup(job)}${log}${command}`;
}

function drawDrawer() {
  const drawer = $("drawer");
  const html = drawerMarkup();
  drawer.hidden = !html;
  // A priority being typed isn't redrawn out from under the cursor.
  if (html === ui.drawerHtml || drawer.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
  drawer.innerHTML = html;
  ui.drawerHtml = html;
}

// Where new jobs that have a PACE version go. PACE can't be picked until it's set up and connected.
function defaultWhere(data) {
  const blocked = data.pace.ready ? "" : data.pace.configured ? "PACE set up, SSH not open" : "PACE not set up yet";
  const button = (value, text) => `<button type="button" data-act="default" data-where="${value}" aria-pressed="${data.default_where === value}"${(value === "pace" && blocked) || ui.busy ? ` disabled${blocked ? ` title="${escapeHtml(blocked)}"` : ""}` : ""}>${text}</button>`;
  return `<span class="default"><span class="eyebrow">New jobs</span><span class="switch" role="group" aria-label="Where new jobs run">${button("local", "Mac")}${button("pace", "PACE")}</span></span>`;
}

// ---- drawing -----------------------------------------------------------------------------------------------------------

function headline(data) {
  const holders = [...data.running, ...data.outside];
  const lead = holders.length ? `${holders[0].name} has the GPU` : data.on_pace.length ? `${data.on_pace[0].name} is on PACE` : "The GPU is free";
  return `${escapeHtml(lead)}<span class="sub">${data.waiting.length ? ` · ${plural(data.waiting.length, "job")} waiting, ${escapeHtml(data.waiting[0].name)} next` : " · nothing waiting"}</span>`;
}

const drawn = {};
function put(id, html) {
  if (drawn[id] === html) return;
  $(id).innerHTML = html;
  drawn[id] = html;
}

function draw() {
  const data = ui.data;
  put("headline", headline(data));
  put("now", nowMarkup(data));
  put("line", lineMarkup(data));
  put("recent", recentMarkup(data));
  put("default-where", defaultWhere(data));
  put("legend", GROUPS.map(group => `<span>${dot(group)}${group}</span>`).join(""));
  $("line-title").textContent = `Waiting: ${data.waiting.length}`;
  $("recent-title").textContent = "Recent";
  $("recent-counts").textContent = `${data.finished} finished · ${data.failed} failed`;
  $("busy-value").textContent = data.device.busy_percent ?? "–";
  $("memory-value").textContent = data.device.memory_gb ?? "–";
  $("memory-total").textContent = `of ${data.device.total_gb} GB${data.machine ? ` · swap ${data.machine.swap_gb}` : ""}`;
  $("busy-note").textContent = data.machine ? `${data.machine.gpu_temp} °C · ${data.machine.watts} W` : "last 15 min";
  const busy = data.running.length + data.outside.length > 0;
  $("status-line").classList.toggle("live", busy);
  $("status-text").textContent = data.error ? `Can't read the queue: ${data.error}` : `Updated ${new Date().toLocaleTimeString([], {hour: "numeric", minute: "2-digit", second: "2-digit"})}`;
  drawDrawer();
  tick();
}

// Every second: clocks, wait times, growing bars and the timeline's "now" move without waiting for a poll.
function tick() {
  if (!ui.data) return;
  const t = now();
  for (const item of document.querySelectorAll("[data-since]")) item.textContent = clock(t - Number(item.dataset.since));
  for (const item of document.querySelectorAll("[data-waited]")) item.textContent = span(t - Number(item.dataset.waited));
  for (const item of document.querySelectorAll("[data-used]")) item.textContent = span(t - Number(item.dataset.used));
  for (const item of document.querySelectorAll("[data-limit]")) {
    const used = Math.min(1, (t - Number(item.dataset.from)) / Number(item.dataset.limit));
    item.style.width = `${(used * 100).toFixed(2)}%`;
    item.classList.toggle("near", used > 0.85);
  }
  for (const item of document.querySelectorAll("[data-grow]")) {
    item.style.width = `${Math.min(100, (t - Number(item.dataset.grow)) / Number(item.dataset.longest) * 100).toFixed(2)}%`;
  }
  put("timeline", timelineMarkup(ui.data));
}

function frame() {
  if (ui.data) drawCharts();
  requestAnimationFrame(frame);
}

async function poll() {
  try {
    const response = await fetch("/api/queue");
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    if (ui.uiVersion !== null && body.ui_version !== ui.uiVersion) location.reload();
    ui.uiVersion = body.ui_version;
    ui.offset = body.now - Date.now() / 1000;
    ui.data = body;
    sample(body);
    draw();
  } catch (error) {
    $("status-line").classList.remove("live");
    $("status-text").textContent = `Can't read the queue: ${error.message}`;
  }
}

// ---- actions -----------------------------------------------------------------------------------------------------------

function notify(text, bad = false) {
  const notice = $("notice");
  notice.textContent = text;
  notice.classList.toggle("bad", bad);
  notice.hidden = false;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => { notice.hidden = true; }, 6000);
}

async function change(path, body, done) {
  ui.busy = true;
  ui.confirming = null;
  document.activeElement?.blur();
  ui.drawerHtml = "";
  draw();
  try {
    const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const answer = await response.json();
    if (!response.ok) throw new Error(answer.error);
    notify(done(answer));
  } catch (error) {
    notify(error.message, true);
  }
  ui.busy = false;
  await poll();
}

function act(button) {
  if (button.dataset.act === "start") {
    return change("/api/queue/start", {name: button.dataset.name}, answer => `Started ${answer.started}. It's in the line at its own priority.`);
  }
  if (button.dataset.act === "default") {
    const where = button.dataset.where;
    return change("/api/queue/default", {where}, () => `New jobs with a PACE version now run on ${where === "pace" ? "PACE" : "this Mac"}.`);
  }
  const id = button.closest(".controls").dataset.id;
  if (button.dataset.act === "where") {
    const where = button.dataset.where;
    return change("/api/queue/where", {id, where}, answer => `${answer.sent} will run on ${where === "pace" ? "PACE" : "this Mac"}.`);
  }
  if (button.dataset.act === "move") {
    const value = button.closest(".controls").querySelector("input").value.trim();
    const priority = /^\d+$/.test(value) ? Number(value) : NaN;
    if (!(priority >= 0 && priority <= 999)) return notify("A priority is a whole number from 0 to 999.", true);
    return change("/api/queue/move", {id, priority}, answer => `Moved ${answer.moved} to priority ${answer.priority}.`);
  }
  // Cancelling and stopping take a second click on the same button, so one stray click can't drop a job.
  if (ui.confirming !== id) {
    ui.confirming = id;
    setTimeout(() => { if (ui.confirming === id) { ui.confirming = null; ui.drawerHtml = ""; drawDrawer(); } }, CONFIRM_MS);
    ui.drawerHtml = "";
    return drawDrawer();
  }
  if (button.dataset.act === "stop") return change("/api/queue/stop", {id}, answer => `Stopped ${answer.stopped}.`);
  change("/api/queue/cancel", {id}, answer => `Cancelled ${answer.cancelled}. A script waiting on it sees it fail.`);
}

async function openLog(id) {
  try {
    const response = await fetch(`/api/queue/log?id=${encodeURIComponent(id)}`);
    const body = await response.json();
    ui.logs[id] = body.tail || "The log is empty.";
  } catch (error) {
    ui.logs[id] = `Couldn't open the log: ${error.message}`;
  }
  ui.drawerHtml = "";
  drawDrawer();
  const pre = $("drawer").querySelector("details[data-log] pre");
  if (pre) pre.scrollTop = pre.scrollHeight;
}

document.addEventListener("click", event => {
  const button = event.target.closest("button[data-act]");
  if (button) { if (!ui.busy) act(button); return; }
  if (event.target.closest("[data-close]")) { ui.open = null; ui.drawerHtml = ""; drawDrawer(); put("line", lineMarkup(ui.data)); return; }
  const opener = event.target.closest("[data-open]");
  if (opener) {
    ui.open = opener.dataset.open;
    ui.confirming = null;
    ui.drawerHtml = "";
    drawDrawer();
    put("line", lineMarkup(ui.data));
  }
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && ui.open) { ui.open = null; ui.drawerHtml = ""; drawDrawer(); }
  if (event.key === "Enter" && event.target.matches(".controls input")) act(event.target.closest(".controls").querySelector('[data-act="move"]'));
});
document.addEventListener("toggle", event => {
  const id = event.target.dataset?.log;
  if (id && event.target.open && ui.logs[id] == null && !findJob(id)?.job.tail) openLog(id);
}, true);

window.addEventListener("resize", () => { drawn.timeline = ""; if (ui.data) tick(); });
poll();
setInterval(poll, POLL_MS);
setInterval(tick, 1000);
requestAnimationFrame(frame);
