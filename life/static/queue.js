// The GPU queue view. It polls what the queue leaves on disk and redraws. Its only changes are to waiting jobs (a priority, Mac or
// PACE, or cancelling) and where new jobs go. Order, as the owner asked: the job on the GPU, then the line, then every past job.
const $ = id => document.getElementById(id);
const POLL_MS = 3000;
const CONFIRM_MS = 5000;
const PAGE = 30;
const ui = {uiVersion: null, open: new Set(), drawn: {}, confirming: null, notice: null, busy: false, latest: null,
            more: [], total: null, loading: false, logs: {}};

const escapeHtml = text => String(text ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const plural = (n, thing) => `${n.toLocaleString("en-US")} ${thing}${n === 1 ? "" : "s"}`;

function span(seconds) {
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return seconds < 172800 ? `${(seconds / 3600).toFixed(1)} h` : `${Math.round(seconds / 86400)} days`;
}
const ago = (now, at) => at == null ? "unknown age" : `${span(Math.max(0, now - at))} ago`;

const heading = title => `<div class="eyebrow ruled"><span>${escapeHtml(title)}</span></div>`;
const none = text => `<div class="none">${escapeHtml(text)}</div>`;
const tag = (text, kind = "") => `<span class="tag ${kind}">${escapeHtml(text)}</span>`;
const mark = `<span class="mark" aria-hidden="true"></span>`;
const names = jobs => jobs.map(job => job.name).join(", ");
const GROUPS = ["demo", "training", "evals", "mind", "other"];
const dot = group => `<span class="dot g-${escapeHtml(group || "other")}" aria-hidden="true"></span>`;
const legend = () => `<div class="legend">${GROUPS.map(group => `<span class="g-${group}">${dot(group)}${group}</span>`).join("")}</div>`;
const fileUrl = (id, item) => `/api/queue/output?id=${encodeURIComponent(id)}&n=${item.n}&v=${Math.round(item.at || 0)}`;

// A folded block that stays open across redraws.
function fold(key, title, body, raw = false) {
  return `<details class="tail" data-key="${escapeHtml(key)}"${ui.open.has(key) ? " open" : ""}><summary>${escapeHtml(title)}</summary>${raw ? body : `<pre>${escapeHtml(body)}</pre>`}</details>`;
}

function commandFold(ticket) {
  const place = ticket.cwd ? `In ${ticket.cwd}\n` : "";
  return ticket.command?.length ? fold(`command-${ticket.id}`, "Command", `${place}${ticket.command.join(" ")}`) : "";
}

// The log is fetched when its fold is opened, so a long list of past jobs doesn't carry every log on every poll.
function logFold(job) {
  const text = job.tail ?? ui.logs[job.id];
  const body = text != null ? `<pre>${escapeHtml(text || "The log is empty.")}</pre>` : `<pre data-log="${escapeHtml(job.id)}">Opening the log</pre>`;
  return fold(`log-${job.id}`, "Log", body, true);
}

function about(job) {
  return job.about ? `<p class="about">${escapeHtml(job.about)}</p>` : `<p class="about unsaid" title="Queued before jobs had to say what they do">${tag("not described", "unsaid")}</p>`;
}

// Media inline, everything else as a list. A job with no declared outputs shows its --out guess, marked as such.
function media(job, item, big = false) {
  const label = escapeHtml(item.name);
  if (item.kind === "video") return `<video class="${big ? "frame" : "thumb"}" src="${fileUrl(job.id, item)}"${big ? " controls" : ""} muted loop playsinline preload="metadata" aria-label="${label}"></video>`;
  return `<img class="${big ? "frame" : "thumb"}" src="${fileUrl(job.id, item)}" alt="${label}" loading="lazy">`;
}

function outputs(job, {big = false, limit = 4} = {}) {
  const files = job.files || [];
  const shown = files.filter(item => item.kind === "image" || item.kind === "video");
  const lead = big && shown.length ? media(job, shown[0], true) : "";
  const thumbs = shown.slice(big ? 1 : 0, (big ? 1 : 0) + limit).map(item => media(job, item)).join("");
  const others = files.filter(item => !["image", "video"].includes(item.kind));
  const note = {folder: item => ` <span>${plural(item.size || 0, "file")}</span>`, missing: () => " <span>not written</span>", outside: () => " <span>outside the project, not shown</span>"};
  const list = others.length ? `<ul class="files">${others.map(item => `<li class="${item.kind}">${escapeHtml(item.name)}${note[item.kind]?.(item) ?? ""}</li>`).join("")}</ul>` : "";
  const guess = job.described === false && shown.length ? `<div class="meta">Guessed from its --out folder</div>` : "";
  return `${lead}${thumbs ? `<div class="thumbs">${thumbs}</div>` : ""}${guess}${list}`;
}

function headline({running, on_pace: onPace, outside, waiting}) {
  const holders = [...running, ...outside];
  const cloud = onPace.length ? `, ${plural(onPace.length, "job")} on PACE` : "";
  if (holders.length > 1) return `${holders.length} jobs are on the GPU at once${cloud}`;
  if (running.length) return `${running[0].name} has the GPU${cloud}`;
  if (outside.length) return `${outside[0].name} has the GPU, outside the queue${cloud}`;
  return (waiting.length ? `The GPU is free. ${waiting[0].name} goes next` : "The GPU is free") + cloud;
}

// A reading and its last minutes as a line. A gap in the readings is a gap in the line, not a drop to zero.
function gauge(label, value, unit, points, top) {
  const shown = value == null ? "?" : value;
  if (points.length < 2) return `<div class="gauge"><div class="eyebrow">${label}</div><div class="big">${shown}<small>${unit}</small></div></div>`;
  const first = points[0].at, last = points[points.length - 1].at, width = Math.max(1, last - first);
  let path = "", pen = false;
  for (const point of points) {
    if (point.value == null) { pen = false; continue; }
    const x = ((point.at - first) / width * 100).toFixed(2), y = (46 - Math.min(point.value, top) / top * 44).toFixed(2);
    path += `${pen ? "L" : "M"}${x} ${y} `;
    pen = true;
  }
  return `<div class="gauge"><div class="eyebrow">${label}, last ${span(width)}</div><div class="big">${shown}<small>${unit}</small></div>
    <svg viewBox="0 0 100 48" preserveAspectRatio="none" aria-hidden="true"><line class="axis" x1="0" y1="47" x2="100" y2="47"/><path class="spark" d="${path}"/></svg></div>`;
}

function whereSwitch(current, act, disabledPace, label) {
  const button = (value, text) => `<button type="button" data-act="${act}" data-where="${value}" aria-pressed="${current === value}"${value === "pace" && disabledPace ? ` disabled title="${escapeHtml(disabledPace)}"` : ""}${ui.busy ? " disabled" : ""}>${text}</button>`;
  return `<div class="switch" role="group" aria-label="${escapeHtml(label)}">${button("local", "Mac")}${button("pace", "PACE")}</div>`;
}

function paceNote(pace) {
  if (pace.ready) return `<div class="pace-state ready">${dot()}<span>PACE connected${pace.host ? ` as ${escapeHtml(pace.host)}` : ""}</span></div>`;
  const why = pace.error ? `Can't check PACE: ${pace.error}` : pace.configured ? "PACE set up, SSH not open" : "PACE not set up yet";
  return `<div class="pace-state">${dot()}<span>${escapeHtml(why)}</span></div>`;
}

// The job on the GPU: its newest output large, what it is, and how far through its time limit it is.
function holderCard(job, now, where, lead) {
  const pace = job.pace || {};
  const ran = job.started_at != null ? now - job.started_at : null;
  const used = job.limit_seconds && ran != null ? Math.min(1, ran / job.limit_seconds) : null;
  const limit = used != null ? `<div class="limit${used > 0.85 ? " near" : ""}" role="img" aria-label="${Math.round(used * 100)}% of its time limit used"><i style="width:${(used * 100).toFixed(1)}%"></i></div>
    <div class="meta">${span(ran)} of ${span(job.limit_seconds)} allowed${used > 0.85 ? ". Close to being stopped." : ""}</div>` : `<div class="meta">No time limit</div>`;
  const state = where === "pace" ? tag(`PACE ${(pace.state || "submitting").toLowerCase()}`) : tag("on this Mac");
  const shown = outputs(job, {big: true, limit: 3});
  return `<article class="holder${lead ? " lead" : ""} g-${escapeHtml(job.group || "other")}">${shown ? `<div class="holder-media">${shown}</div>` : ""}
    <div class="holder-text"><div class="name">${mark}${dot(job.group)}<span>${escapeHtml(job.name)}</span>${state}</div>${about(job)}
    <div class="elapsed">${ran != null ? span(ran) : "starting"}</div>${limit}${logFold(job)}${commandFold(job)}</div></article>`;
}

// The newest finished job, judged: a 1 to 5 rating against what it said it would do, then what happened.
// A job queued without a description has nothing to be judged against, so it reads "not rated", never as a low score.
function ratingScale(rating) {
  return `<div class="scale" role="img" aria-label="${rating} of 5">${[1, 2, 3, 4, 5].map(step => `<i class="${step <= rating ? "on" : ""}"></i>`).join("")}</div>`;
}

function lastResultMarkup(result, now) {
  if (!result) return "";
  const rated = result.rating != null;
  const score = rated ? `<div class="score"><span class="big">${escapeHtml(result.rating)}</span><span class="of">/ 5</span></div>${ratingScale(result.rating)}`
    : `<div class="score"><span class="big muted">–</span></div>${tag("not rated", "unsaid")}`;
  const failed = result.exit_code != null && result.exit_code !== 0;
  const summary = result.summary ? `<p class="summary">${escapeHtml(result.summary)}</p>`
    : `<p class="summary bad">${escapeHtml(result.error ? `Couldn't summarize: ${result.error}` : "No summary.")}</p>`;
  const numbers = result.key_numbers?.length ? `<ul class="numbers">${result.key_numbers.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : "";
  const caveats = result.caveats?.length ? `<ul class="caveats">${result.caveats.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : "";
  const first = (result.files || []).find(item => item.kind === "image" || item.kind === "video");
  return `<article class="result${failed ? " failed" : ""} g-${escapeHtml(result.group || "other")}">${first ? `<div class="result-media">${media(result, first, true)}</div>` : ""}
    <div class="result-text"><div class="eyebrow">Last result</div><div class="name">${dot(result.group)}<span>${escapeHtml(result.name)}</span>${tag(failed ? `exit ${result.exit_code}` : "exit 0", failed ? "fail" : "")}<span class="right">${ago(now, result.at)}</span></div>
    <div class="judged">${score}<div class="why"><div class="label">${escapeHtml(result.rating_label || "")}</div><div class="meta">${escapeHtml(result.rating_reason || "")}</div></div></div>
    ${summary}${numbers}${caveats ? fold(`caveats-${result.id}`, `Caveats: ${result.caveats.length}`, caveats, true) : ""}</div></article>`;
}

function outsideRow(job) {
  const note = job.queue_waits ? "Started without the queue. The queue waits for it." : "Started without the queue, and the queue can't see this kind of job, so it won't wait.";
  return `<div class="row"><div class="row-head">${mark}${tag("outside the queue", job.queue_waits ? "" : "fail")}<span>${escapeHtml(job.name)}</span><span class="right">pid ${job.pid}</span></div><div class="meta">${note}</div></div>`;
}

function nowMarkup(data) {
  const {running, on_pace: onPace, outside, stale, available, error, device, history, pace} = data;
  const holders = running.length + outside.length;
  const unreadable = error ? `<div class="none bad">Can't read the queue: ${escapeHtml(error)}</div>` : available === false ? none("out/ops isn't there to read.") : "";
  const warning = holders > 1 ? `<p class="warning">Two model jobs at once can run this Mac out of memory.</p>` : "";
  const leftover = stale.length ? none(`${plural(stale.length, "stale ticket")} left by a dead process, not counted: ${names(stale)}`) : "";
  const busy = history.map(row => ({at: row.at, value: row.busy})), memory = history.map(row => ({at: row.at, value: row.memory}));
  const blocked = pace.ready ? "" : "PACE isn't ready yet";
  const cards = [...running.map((job, index) => holderCard(job, data.now, "local", index === 0)), ...onPace.map(job => holderCard(job, data.now, "pace", !running.length))].join("");
  return `${heading("On the GPU now")}<div class="goal-line">${escapeHtml(headline(data))}</div>${warning}${unreadable}${cards}${outside.map(outsideRow).join("")}${leftover}
    ${lastResultMarkup(data.last_result, data.now)}
    <div class="top"><div class="gauges">${gauge("GPU busy", device.busy_percent, "%", busy, 100)}${gauge("Memory in use", device.memory_gb, `of ${device.total_gb} GB`, memory, device.total_gb || 36)}</div>
    <div class="where"><div class="eyebrow">New jobs with a PACE version run on</div>${whereSwitch(data.default_where, "default", blocked, "Where new jobs run")}${paceNote(pace)}</div></div>`;
}

function waitingNote(position, {running, outside}) {
  if (position > 0) return "";
  const holders = [...running, ...outside];
  return holders.length ? `Goes when ${names(holders)} ${holders.length === 1 ? "finishes" : "finish"}.` : "Goes at the queue's next check.";
}

// Cancelling takes a second click on the same button, so one stray click can't drop a job.
function controls(ticket) {
  const confirming = ui.confirming === ticket.id;
  const disabled = ui.busy ? " disabled" : "";
  return `<label>Priority <input type="number" inputmode="numeric" min="0" max="999" step="1" value="${escapeHtml(ticket.priority ?? "")}" aria-label="New priority for ${escapeHtml(ticket.name)}"></label>
    <button type="button" data-act="move"${disabled}>Move</button>
    <button type="button" data-act="cancel" class="${confirming ? "confirm" : ""}"${disabled}>${confirming ? "Click again to cancel" : "Cancel job"}</button>`;
}

function noticeMarkup() {
  if (!ui.notice) return "";
  return `<div class="notice${ui.notice.bad ? " bad" : ""}" role="status">${escapeHtml(ui.notice.text)}</div>`;
}

function lineMarkup(data) {
  const longest = Math.max(60, ...data.waiting.map(ticket => data.now - ticket.queued_at));
  const blocked = data.pace.ready ? "" : "PACE isn't ready yet";
  const row = (ticket, position) => {
    const waited = data.now - ticket.queued_at;
    const noPace = ticket.can_pace ? blocked : "No PACE version: its command uses MLX";
    const planned = ticket.planned?.length ? `<div class="meta">Will write ${escapeHtml(ticket.planned.join(", "))}</div>` : "";
    return `<div class="row g-${escapeHtml(ticket.group)}"><div class="row-head"><span class="position">${position + 1}</span>${dot(ticket.group)}<span>${escapeHtml(ticket.name)}</span>
      <span class="right">p${escapeHtml(ticket.priority ?? "?")} · waiting ${span(waited)}</span></div>
      <div class="waited" role="img" aria-label="Waited ${span(waited)}"><i style="width:${(waited / longest * 100).toFixed(1)}%"></i></div>
      ${about(ticket)}${planned}${position === 0 ? `<div class="meta">${escapeHtml(waitingNote(position, data))}</div>` : ""}
      <div class="controls" data-id="${escapeHtml(ticket.id)}">${whereSwitch(ticket.where, "where", noPace, `Where ${ticket.name} runs`)}${controls(ticket)}</div>
      ${commandFold(ticket)}</div>`;
  };
  const note = data.waiting.length > 1 ? none("Lowest priority number goes first. A running job is never stopped for a new one.") : "";
  return `${heading(`Waiting: ${data.waiting.length}`)}${noticeMarkup()}${data.waiting.map(row).join("") || none("Nothing is waiting.")}${note}`;
}

// Jobs written out ahead of time. They aren't in the queue until Start puts them there, at their own priority.
function stagedMarkup(data) {
  const jobs = data.staged || [];
  if (!jobs.length) return "";
  const row = job => {
    const guess = job.estimate ? `About ${job.estimate.hours} h: ${plural(job.estimate.qwen_calls, "Qwen call")}${job.estimate.clips ? `, ${plural(job.estimate.clips, "Cosmos clip")}` : ""}` : "";
    return `<div class="row"><div class="row-head">${dot("other")}<span>${escapeHtml(job.name)}</span><span class="right">p${escapeHtml(job.priority)} · stops after ${escapeHtml(job.max_hours)} h</span></div>
      ${about(job)}${guess ? `<div class="meta">${escapeHtml(guess)}. Staged ${ago(data.now, job.created_at)}.</div>` : ""}
      <div class="controls"><button type="button" class="btn-primary" data-act="start" data-name="${escapeHtml(job.name)}"${ui.busy ? " disabled" : ""}>Start</button></div>
      ${commandFold({id: `staged-${job.name}`, cwd: job.cwd, command: job.command})}</div>`;
  };
  return `${heading(`Ready to start: ${jobs.length}`)}${jobs.map(row).join("")}`;
}

// Twelve hours as lanes: the Mac's turns on one line, PACE's below, and waits stacked so none hides another.
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
  const {since, now, jobs} = data.timeline;
  const width = Math.max(320, $("timeline").clientWidth || 900), left = 48, right = 8, plot = width - left - right;
  const x = at => left + Math.max(0, Math.min(1, (at - since) / (now - since))) * plot;
  const mac = jobs.filter(job => job.where !== "pace" && job.started);
  const cloud = jobs.filter(job => job.where === "pace" && job.started);
  const waits = jobs.filter(job => (job.started || job.ended || now) - job.queued > 60);
  const cloudRows = pack(cloud, job => job.started, job => job.ended || now);
  const waitRows = Math.min(8, pack(waits, job => job.queued, job => job.started || job.ended || now));
  const rowGap = 10, macY = 28, cloudY = macY + 40, waitY = cloudY + cloudRows * 20 + 24, height = waitY + waitRows * rowGap + 28;
  const bar = (job, y) => {
    const x1 = x(job.started), x2 = x(job.ended || now), w = Math.max(2, x2 - x1);
    const tip = `<title>${escapeHtml(job.name)}: ${job.ended ? `ran ${span(job.ended - job.started)}` : `running ${span(now - job.started)}`}${job.failed ? ", failed" : ""}</title>`;
    const label = w > 70 ? `<text class="label" x="${x1 + 4}" y="${y + 4}">${escapeHtml(job.name.slice(0, Math.floor(w / 7)))}</text>` : "";
    const failed = job.failed ? `<line class="failed" x1="${x2}" y1="${y - 9}" x2="${x2}" y2="${y + 9}"/><text class="failed-mark" x="${x2}" y="${y - 12}" text-anchor="middle">×</text>` : "";
    return `<g class="g-${job.group}">${tip}<rect class="turn${job.ended ? "" : " live"}${job.failed ? " was-failed" : ""}" x="${x1}" y="${y - 7}" width="${w}" height="14"/>${label}${failed}</g>`;
  };
  const wait = job => {
    if (job.row >= waitRows) return "";
    const y = waitY + job.row * rowGap, end = job.started || job.ended || now;
    return `<g class="g-${job.group}"><title>${escapeHtml(job.name)} waited ${span(end - job.queued)}</title><line class="wait" x1="${x(job.queued)}" y1="${y}" x2="${x(end)}" y2="${y}"/><circle cx="${x(job.queued)}" cy="${y}" r="2" fill="var(--g)"/></g>`;
  };
  const ticks = [];
  for (let at = Math.ceil(since / 7200) * 7200; at < now; at += 7200) {
    ticks.push(`<line class="lane" x1="${x(at)}" y1="8" x2="${x(at)}" y2="${height - 18}"/><text x="${x(at)}" y="${height - 4}" text-anchor="middle">${new Date(at * 1000).toLocaleTimeString([], {hour: "numeric"})}</text>`);
  }
  const lanes = `<text x="0" y="${macY + 4}">Mac</text><text x="0" y="${cloudY + 4}">PACE</text><text x="0" y="${waitY + 4}">Line</text>
    <line class="lane" x1="${left}" y1="${macY}" x2="${width - right}" y2="${macY}"/><line class="lane" x1="${left}" y1="${cloudY}" x2="${width - right}" y2="${cloudY}"/>`;
  const svg = `<svg class="chart" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="Jobs over the last 12 hours: run times as bars, waits as dotted lines, failures marked">
    ${ticks.join("")}${lanes}${waits.map(wait).join("")}${mac.map(job => bar(job, macY)).join("")}${cloud.map(job => bar(job, cloudY + job.row * 20)).join("")}
    <line class="nowline" x1="${x(now)}" y1="4" x2="${x(now)}" y2="${height - 18}"/><text x="${x(now) - 4}" y="10" text-anchor="end">now</text></svg>`;
  const hidden = waits.filter(job => job.row >= waitRows).length;
  return `${heading("Last 12 hours")}${legend()}${svg}${hidden ? none(`${plural(hidden, "more wait")} not drawn.`) : ""}`;
}

function outcome(job) {
  if (job.timed_out) return {word: "timed out", bad: true};
  if (job.state === "finished") return {word: job.exit_code === 0 ? "exit 0" : `exit ${job.exit_code}${job.meaning ? ` (${job.meaning})` : ""}`, bad: job.failed};
  return {word: job.state === "gave_up" ? "gave up" : job.state, bad: job.failed};
}

function judged(job) {
  if (job.summarizing) return {badge: tag("summarizing…", "unsaid"), text: ""};
  const result = job.result;
  if (!result) return {badge: "", text: ""};
  const badge = result.rating != null ? `<span class="rating" title="${escapeHtml(result.rating_label || "")}">${ratingScale(result.rating)}<span>${escapeHtml(result.rating)}/5</span></span>` : tag("not rated", "unsaid");
  const text = result.summary ? `<p class="summary">${escapeHtml(result.summary)}</p>` : result.error ? `<p class="summary bad">Couldn't summarize: ${escapeHtml(result.error)}</p>` : "";
  return {badge, text};
}

function pastRow(job, now) {
  const {word, bad} = outcome(job);
  const {badge, text} = judged(job);
  const facts = [job.seconds != null ? `ran ${span(job.seconds)}` : "", job.waited != null ? `waited ${span(job.waited)}` : "", job.peak_rss_gb != null ? `${job.peak_rss_gb} GB peak RAM` : ""].filter(Boolean).join(" · ");
  return `<article class="past${bad ? " failed" : ""} g-${escapeHtml(job.group || "other")}"><div class="row-head">${dot(job.group)}<span>${escapeHtml(job.name)}</span>${tag(word, bad ? "fail" : "")}${badge}<span class="right">${ago(now, job.at)}</span></div>
    ${about(job)}${text}${facts ? `<div class="meta">${escapeHtml(facts)}</div>` : ""}${outputs(job, {limit: 4})}${logFold(job)}</article>`;
}

function ledgerMarkup(data) {
  const seen = new Set(data.past.map(job => job.id));
  const jobs = [...data.past, ...ui.more.filter(job => !seen.has(job.id))];
  const total = Math.max(ui.total ?? 0, data.past_total);
  const squares = jobs.map(job => {
    const {word, bad} = outcome(job);
    return `<span class="${bad ? "bad" : job.state === "finished" ? "ok" : ""}" title="${escapeHtml(job.name)}: ${escapeHtml(word)}, ${ago(data.now, job.at)}"></span>`;
  }).join("");
  const end = jobs.length >= total ? none(`That's all ${plural(total, "past job")}.`) : `<div class="more" id="more">${ui.loading ? "Loading older jobs" : "Scroll for older jobs"}</div>`;
  return `${heading(`Every past job: ${data.finished} finished, ${data.failed} failed`)}<div class="outcomes" role="img" aria-label="Newest first: filled finished, red failed">${squares}</div>
    ${jobs.map(job => pastRow(job, data.now)).join("") || none("No job has had a turn yet.")}${end}`;
}

const SECTIONS = {now: nowMarkup, staged: stagedMarkup, line: lineMarkup, timeline: timelineMarkup, ledger: ledgerMarkup};

// Only what changed is replaced, so a section being read doesn't lose its scroll position, its selection or a playing video.
function draw(data) {
  ui.latest = data;
  for (const [id, markup] of Object.entries(SECTIONS)) {
    const html = markup(data);
    // A priority being typed isn't redrawn out from under the cursor.
    if (ui.drawn[id] === html || $(id).contains(document.activeElement) && document.activeElement.tagName === "INPUT") continue;
    $(id).innerHTML = html;
    ui.drawn[id] = html;
    for (const pre of $(id).querySelectorAll('details[data-key^="log-"] pre')) pre.scrollTop = pre.scrollHeight;
  }
  const busy = data.running.length + data.outside.length > 0;
  $("status-line").classList.toggle("live", busy);
  $("status-text").textContent = `GPU ${busy ? "in use" : "free"}, ${data.waiting.length} waiting${data.on_pace.length ? `, ${data.on_pace.length} on PACE` : ""}.`;
  watchMore();
}

async function poll() {
  try {
    const response = await fetch("/api/queue");
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    if (ui.uiVersion !== null && body.ui_version !== ui.uiVersion) location.reload();
    ui.uiVersion = body.ui_version;
    draw(body);
  } catch (error) {
    // With no fresh reading, nothing on the page can claim to be moving.
    for (const item of document.querySelectorAll(".mark")) item.remove();
    ui.drawn = {};
    $("status-line").classList.remove("live");
    $("status-text").textContent = `Can't read the queue: ${error.message}`;
  }
}

function redraw() {
  ui.drawn = {};
  if (ui.latest) draw(ui.latest);
}

// Older jobs load a page at a time when the end of the list scrolls into view.
async function loadMore() {
  if (ui.loading || !ui.latest) return;
  const have = ui.latest.past.length + ui.more.length;
  if (have >= Math.max(ui.total ?? 0, ui.latest.past_total)) return;
  ui.loading = true;
  try {
    const response = await fetch(`/api/queue/past?offset=${have}&limit=${PAGE}`);
    const page = await response.json();
    if (!response.ok) throw new Error(page.error);
    ui.more.push(...page.jobs);
    ui.total = page.total;
  } catch (error) {
    ui.notice = {text: `Couldn't load older jobs: ${error.message}`, bad: true};
  }
  ui.loading = false;
  redraw();
}

const observer = "IntersectionObserver" in window ? new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting)) loadMore(); }, {rootMargin: "400px"}) : null;
function watchMore() {
  observer?.disconnect();
  const more = $("more");
  if (more && observer) observer.observe(more);
}

async function openLog(pre) {
  const id = pre.dataset.log;
  try {
    const response = await fetch(`/api/queue/log?id=${encodeURIComponent(id)}`);
    const body = await response.json();
    ui.logs[id] = body.tail ?? "No log was kept for this job.";
  } catch (error) {
    ui.logs[id] = `Couldn't open the log: ${error.message}`;
  }
  redraw();
}

async function change(path, body, done) {
  ui.busy = true;
  ui.confirming = null;
  // A focused input holds its section still, and the answer has to show there.
  document.activeElement?.blur();
  redraw();
  try {
    const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const answer = await response.json();
    if (!response.ok) throw new Error(answer.error);
    ui.notice = {text: done(answer)};
  } catch (error) {
    ui.notice = {text: error.message, bad: true};
  }
  ui.busy = false;
  await poll();
  redraw();
}

function act(button) {
  if (button.dataset.act === "start") {
    const name = button.dataset.name;
    return change("/api/queue/start", {name}, answer => `Started ${answer.started}. It's in the line now, at its own priority.`);
  }
  if (button.dataset.act === "default") {
    const where = button.dataset.where;
    return change("/api/queue/default", {where}, () => `New jobs with a PACE version now run on ${where === "pace" ? "PACE" : "this Mac"}.`);
  }
  const box = button.closest(".controls");
  const id = box.dataset.id;
  if (button.dataset.act === "where") {
    const where = button.dataset.where;
    return change("/api/queue/where", {id, where}, answer => `${answer.sent} will run on ${where === "pace" ? "PACE" : "this Mac"}.`);
  }
  if (button.dataset.act === "move") {
    const value = box.querySelector("input").value.trim();
    const priority = /^\d+$/.test(value) ? Number(value) : NaN;
    if (!(priority >= 0 && priority <= 999)) { ui.notice = {text: "A priority is a whole number from 0 to 999.", bad: true}; return redraw(); }
    return change("/api/queue/move", {id, priority}, answer => `Moved ${answer.moved} to priority ${answer.priority}.`);
  }
  if (ui.confirming !== id) {
    ui.confirming = id;
    setTimeout(() => { if (ui.confirming === id) { ui.confirming = null; redraw(); } }, CONFIRM_MS);
    return redraw();
  }
  change("/api/queue/cancel", {id}, answer => `Cancelled ${answer.cancelled}. A script waiting on it sees it fail.`);
}

document.addEventListener("click", event => {
  const button = event.target.closest("button[data-act]");
  if (button && !ui.busy) act(button);
});
document.addEventListener("keydown", event => {
  if (event.key === "Enter" && event.target.matches(".controls input")) act(event.target.closest(".controls").querySelector('[data-act="move"]'));
});

// A toggle event doesn't bubble, so it's caught on the way down.
document.addEventListener("toggle", event => {
  const key = event.target.dataset?.key;
  if (!key) return;
  if (event.target.open) ui.open.add(key); else ui.open.delete(key);
  const pending = event.target.open && event.target.querySelector("pre[data-log]");
  if (pending) openLog(pending);
  ui.drawn = {};
}, true);

// The timeline is drawn to the page's width, so a new width needs a new drawing.
let resizing = null;
window.addEventListener("resize", () => { clearTimeout(resizing); resizing = setTimeout(redraw, 150); });
poll();
setInterval(poll, POLL_MS);
