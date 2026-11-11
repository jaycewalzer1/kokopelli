// The sensations view: the hunger videos (full, half, starving side by side) and the text sweeps behind them.
// Two toggles change what the videos show, and each viewer's choice is remembered in this browser:
//   Viewer overlay  the true body numbers and what reached the agent, beside the painted film (off: the bare film)
//   Inner voice     the agent's thoughts read aloud, when the run has a voice track; it plays on each level's film
// Neither toggle touches a run: the agent never sees the overlay or hears the voice. It polls, so new runs appear.
const $ = id => document.getElementById(id);
const POLL_MS = 15000;
const LEVELS = ["full", "half", "starving"];
const escapeHtml = text => String(text ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
// Storage can be missing (a private window), so every use is guarded.
const remembered = (key, fallback) => { try { return localStorage.getItem(`sensations.${key}`) ?? fallback; } catch { return fallback; } };
const remember = (key, value) => { try { localStorage.setItem(`sensations.${key}`, value); } catch { /* not kept, that's all */ } };
const ui = {body: null, drawn: "", run: remembered("run", ""), overlay: remembered("overlay", "on") === "on",
            voice: remembered("voice", "off") === "on", uiVersion: null};

function status(text, live = false) {
  $("status-text").textContent = text;
  $("status-line").classList.toggle("live", live);
}

const pct = stat => stat && stat.mean != null ? `${Math.round(stat.mean * 100)}%` : "n/a";
const ci = stat => stat && stat.mean != null ? `[${Math.round(stat.low * 100)}, ${Math.round(stat.high * 100)}]` : "";
const pts = stat => stat && stat.mean != null
  ? `${stat.mean >= 0 ? "+" : ""}${Math.round(stat.mean * 100)} pts [${Math.round(stat.low * 100)}, ${Math.round(stat.high * 100)}]` : "n/a";

function videoUrl(run, kind, level) {
  const params = new URLSearchParams({run: run.id, kind, at: String(run.at)});
  if (level) params.set("level", level);
  return `/api/sensations/video?${params}`;
}

function describe(action) {
  if (!action) return "No answer recorded.";
  if (action.type === "say") return `Said: "${action.text ?? ""}"`;
  if (action.type === "give") return "Gave Teo an egg.";
  return {cook: "Cooked an egg.", eat: "Ate.", wait: "Waited."}[action.type] ?? action.type;
}

function levelCard(run, level) {
  const info = run.levels[level];
  if (!info) return `<figure class="level"><div class="empty box">No ${level} run</div><div class="name">${level}</div></figure>`;
  const kind = !ui.overlay ? "plain" : ui.voice && info.has.voice ? "voice" : "overlay";
  const player = info.has[kind]
    ? `<video src="${escapeHtml(videoUrl(run, kind, level))}" controls ${kind === "voice" ? "" : "muted"} playsinline preload="metadata"
         aria-label="${escapeHtml(`${level}, ${kind === "plain" ? "painted film" : "film with the viewer overlay"}`)}"></video>`
    : `<div class="empty box">No ${kind === "plain" ? "film" : "overlay"} yet</div>`;
  const outcome = info.outcome ? `<span class="tag ${info.outcome === "gave" ? "strong" : ""}">${escapeHtml(info.outcome)}</span>` : "";
  return `<figure class="level">
    ${player}
    <div class="name">${escapeHtml(level)}${outcome}</div>
    <p class="first">${escapeHtml(describe(info.first))}</p>
    ${info.thought ? `<p class="thought">${escapeHtml(info.thought)}</p>` : ""}
  </figure>`;
}

function drawVideos() {
  const runs = ui.body.videos;
  const select = $("video-run");
  select.innerHTML = runs.map(run => `<option value="${escapeHtml(run.id)}">${escapeHtml(run.id)}${run.arm ? ` · ${escapeHtml(run.arm)}` : ""}</option>`).join("")
    || `<option value="">No runs yet</option>`;
  const run = runs.find(r => r.id === ui.run) || runs[0];
  if (run) select.value = run.id;
  $("toggle-overlay").setAttribute("aria-pressed", String(ui.overlay));
  $("toggle-voice").setAttribute("aria-pressed", String(ui.voice));
  $("toggle-voice").disabled = !ui.overlay;
  const anyVoice = run && LEVELS.some(level => run.levels[level]?.has.voice);
  $("toggle-note").textContent = !run ? "" : !ui.overlay ? "The bare painted film: what the agent saw."
    : ui.voice && !anyVoice ? "This run has no voice track." : ui.voice ? "The voice plays on each level's film, not the side-by-side."
    : "";
  if (!run) {
    $("triptych").innerHTML = "";
    $("levels").innerHTML = `<p class="none">No hunger videos yet. Queue kokopelli/agents/run_egg_videos.sh (see its header).</p>`;
    return;
  }
  $("triptych").innerHTML = ui.overlay && run.triptych
    ? `<video src="${escapeHtml(videoUrl(run, "triptych"))}" controls muted playsinline preload="metadata" aria-label="Full, half and starving side by side"></video>`
    : "";
  $("levels").innerHTML = LEVELS.map(level => levelCard(run, level)).join("");
}

function sweepBlock(sweep) {
  // Each scene brings its own words for its score; a report written before the scenes registry has none and is the hunger scene's.
  const words = sweep.words ?? {rate: "Giving rate", primary: "a give action to Teo"};
  const first = sweep.levels[0] ?? "";
  const span = `${first.charAt(0).toUpperCase()}${first.slice(1)} to ${sweep.levels[sweep.levels.length - 1] ?? ""}`;
  const noAnchor = sweep.anchor.verified === false;
  const head = `<tr><th>Arm</th>${sweep.levels.map(level => `<th>${escapeHtml(level)}</th>`).join("")}<th>${escapeHtml(span)}</th><th>Reads as</th></tr>`;
  const rows = sweep.arms.map(arm => {
    const cells = sweep.levels.map(level => {
      const cell = sweep.cells[`${arm}|${level}`];
      return `<td>${pct(cell?.gave)} <span class="ci">${ci(cell?.gave)}</span></td>`;
    }).join("");
    const verdict = sweep.verdicts[arm];
    return `<tr><td>${escapeHtml(arm)}</td>${cells}<td>${pts(verdict?.change)}</td><td class="verdict">${escapeHtml(verdict?.verdict ?? "")}</td></tr>`;
  }).join("");
  const when = new Date(sweep.at * 1000).toLocaleString("en-US", {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
  return `<article class="sweep">
    <div class="title">${escapeHtml(sweep.id)}${sweep.real ? "" : `<span class="tag">Not a real model</span>`}</div>
    <div class="numbers">${escapeHtml(sweep.model ?? "")} · ${escapeHtml(sweep.backend)} · ${sweep.samples} samples × ${sweep.paraphrases ?? 3} wordings per cell · ${when}</div>
    <div class="table-wrap"><table><thead>${head}</thead><tbody>${rows}</tbody></table></div>
    <p class="meta">${escapeHtml(words.rate)}: ${escapeHtml(words.primary.replaceAll("`", ""))}, with its 95% interval. "none" gets the same prompt at every level, so it must
      read flat; if it doesn't, the level is leaking.</p>
    <div class="anchor">
      <p><span class="eyebrow">${noAnchor ? "No verified anchor" : "What people do"}</span><br>${escapeHtml(sweep.anchor.real)}</p>
      <p><span class="eyebrow">What people predict</span><br>${escapeHtml(sweep.anchor.lay)}</p>
    </div>
  </article>`;
}

function drawSweeps() {
  const sweeps = ui.body.sweeps;
  $("sweeps").innerHTML = sweeps.length ? sweeps.map(sweepBlock).join("")
    : `<p class="none">No sweeps yet. Run python -m experiments.sensation.sweep through the GPU queue (see sweep.py).</p>`;
}

function draw(force = false) {
  const key = JSON.stringify([ui.body, ui.run, ui.overlay, ui.voice]);
  if (!force && key === ui.drawn) return;   // redrawing would restart playing videos
  ui.drawn = key;
  drawVideos();
  drawSweeps();
}

async function poll() {
  try {
    const response = await fetch("/api/sensations");
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || response.status);
    if (ui.uiVersion && body.ui_version !== ui.uiVersion) return location.reload();
    ui.uiVersion = body.ui_version;
    delete body.ui_version;
    ui.body = body;
    const n = body.videos.length + body.sweeps.length;
    status(n ? `${body.videos.length} video run${body.videos.length === 1 ? "" : "s"}, ${body.sweeps.length} sweep${body.sweeps.length === 1 ? "" : "s"}` : "Nothing yet");
    draw();
  } catch (error) {
    status(`Couldn't load: ${error.message}`);
  }
}

$("video-run").addEventListener("change", event => { ui.run = event.target.value; remember("run", ui.run); draw(); });
$("toggle-overlay").addEventListener("click", () => { ui.overlay = !ui.overlay; remember("overlay", ui.overlay ? "on" : "off"); draw(); });
$("toggle-voice").addEventListener("click", () => { ui.voice = !ui.voice; remember("voice", ui.voice ? "on" : "off"); draw(); });

poll();
setInterval(poll, POLL_MS);
