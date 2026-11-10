// The model runs view: every video a model or the sim made, from every tool. It opens on one list of everything, newest
// first; it can also be grouped by where a run came from or by type.
// It polls, so a run that's still writing shows its newest chunks. A video only loads once its card scrolls into view.
const $ = id => document.getElementById(id);
const POLL_MS = 15000;
const SHOWN = 8;
const KIND_TAG = {sd15: "SD1.5", sim: "Sim", mock: "Mock", mixed: "Mixed", input: "Input"};
const SORTS = {
  newest: (a, b) => (b.at || 0) - (a.at || 0),
  oldest: (a, b) => (a.at || 0) - (b.at || 0),
  longest: (a, b) => (b.seconds ?? -1) - (a.seconds ?? -1),
  largest: (a, b) => (b.mb ?? -1) - (a.mb ?? -1),
  name: (a, b) => a.name.localeCompare(b.name, "en-US", {numeric: true}),
};
// Each viewer's own choices. Storage can be missing (a private window), so every use is guarded.
const remembered = (key, fallback) => { try { return localStorage.getItem(`runs.${key}`) || fallback; } catch { return fallback; } };
const remember = (key, value) => { try { localStorage.setItem(`runs.${key}`, value); } catch { /* not kept, that's all */ } };
// New keys, so a choice saved under the old grouped default doesn't override the new one.
const ui = {uiVersion: null, body: null, drawn: "", kind: remembered("tab", "all"), groupBy: remembered("group", "none"),
            sort: remembered("sort", "newest"), open: new Set()};

const escapeHtml = text => String(text ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const plural = (n, thing) => `${n.toLocaleString("en-US")} ${thing}${n === 1 ? "" : "s"}`;
// Mixed runs (a real piece alongside a mock one) are listed with the mocks.
const typeOf = run => run.kind === "mixed" ? "mock" : run.kind;
const matches = run => ui.kind === "all" || typeOf(run) === ui.kind;

function length(seconds) {
  if (seconds == null) return "length unknown";
  return seconds < 60 ? `${seconds.toFixed(1)} s` : `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

function when(at) {
  if (!at) return "";
  return new Date(at * 1000).toLocaleString("en-US", {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
}

function status(text, live = false) {
  $("status-text").textContent = text;
  $("status-line").classList.toggle("live", live);
}

function card(run) {
  // The file's time is in the address, so a run that wrote a new chunk loads it fresh.
  const src = `/api/worlds/video?id=${encodeURIComponent(run.id)}&at=${run.at}`;
  const player = run.video
    ? `<video data-src="${escapeHtml(src)}" controls muted loop playsinline preload="none" aria-label="${escapeHtml(run.name)}"></video>`
    : `<div class="empty">No video yet</div>`;
  const tags = [run.state === "running" ? `<span class="tag live"><i></i>Running</span>` : "",
                KIND_TAG[run.kind] ? `<span class="tag">${KIND_TAG[run.kind]}</span>` : ""].join("");
  const numbers = [run.video ? length(run.seconds) : "", run.mb != null ? `${run.mb} MB` : "", when(run.at)].filter(Boolean).join(" · ");
  return `<figure class="run card">
    ${player}
    <div class="name">${escapeHtml(run.name)}${tags}</div>
    <div class="numbers">${numbers}</div>
    ${run.about ? `<p class="about">${escapeHtml(run.about)}</p>` : ""}
    ${run.prompt ? `<p class="prompt">${escapeHtml(run.prompt)}</p>` : ""}
    ${run.lines.map(line => `<p class="meta">${escapeHtml(line)}</p>`).join("")}
  </figure>`;
}

function group(info, runs) {
  const open = ui.open.has(info.id);
  const shown = open || info.id === "everything" ? runs : runs.slice(0, SHOWN);
  const more = runs.length > SHOWN && info.id !== "everything" ? `<button type="button" class="more" data-group="${info.id}">${open ? "Show fewer" : `Show all ${runs.length}`}</button>` : "";
  return `<section class="group" aria-label="${escapeHtml(info.name)}">
    <div class="eyebrow ruled"><span>${escapeHtml(info.name)}</span><span>${runs.length}</span></div>
    ${info.about ? `<p class="meta">${escapeHtml(info.about)}</p>` : ""}
    ${runs.length ? `<div class="cards">${shown.map(card).join("")}</div>${more}` : `<div class="none">None of these.</div>`}
  </section>`;
}

function summary() {
  const runs = ui.body.runs;
  const made = runs.filter(run => run.kind === "cosmos" && run.video);
  const running = runs.filter(run => run.state === "running");
  const longest = ui.body.longest;
  $("headline").textContent = longest ? `Longest Cosmos video: ${length(longest.seconds)}` : "No Cosmos videos yet";
  $("subline").textContent = [longest ? `${longest.name}.` : "", `${plural(made.length, "Cosmos video")} and ${plural(runs.length - made.length, "other run")} on this machine.`,
                              running.length ? `${running.map(run => run.name).join(", ")} still running.` : ""].filter(Boolean).join(" ");
  status(running.length ? `${plural(running.length, "run")} writing` : "Nothing running", running.length > 0);
}

function tabs() {
  // A type with no runs gets no tab. If the chosen one has none left, show everything.
  const runs = ui.body.runs;
  const types = [{id: "all", name: "All", count: runs.length},
                 ...ui.body.types.map(type => ({...type, count: runs.filter(run => typeOf(run) === type.id).length})).filter(type => type.count)];
  if (!types.some(type => type.id === ui.kind)) ui.kind = "all";
  const html = types.map(type => `<button class="tab" role="tab" data-kind="${type.id}" aria-selected="${type.id === ui.kind}">${escapeHtml(type.name)}<span class="count">${type.count}</span></button>`).join("");
  if ($("types").innerHTML !== html) $("types").innerHTML = html;
}

function sections() {
  const runs = ui.body.runs.filter(matches).sort(SORTS[ui.sort] || SORTS.newest);
  if (ui.groupBy === "none") return [[{id: "everything", name: "Every run"}, runs]];
  if (ui.groupBy === "type") return ui.body.types.map(type => [{id: `type-${type.id}`, name: type.name}, runs.filter(run => typeOf(run) === type.id)]).filter(([, inside]) => inside.length);
  return ui.body.groups.map(info => [info, runs.filter(run => run.group === info.id)]).filter(([, inside]) => inside.length || ui.kind === "all");
}

function draw() {
  tabs();
  $("group-by").value = ui.groupBy;
  $("sort").value = ui.sort;
  const html = sections().map(([info, inside]) => group(info, inside)).join("") || `<div class="none">No runs of this kind.</div>`;
  if (html === ui.drawn) return;
  ui.drawn = html;
  $("groups").innerHTML = html;
  for (const video of $("groups").querySelectorAll("video")) seen.observe(video);
}

// Loading every video at once would fetch over a hundred files, so each one starts loading near the screen.
const seen = new IntersectionObserver(entries => {
  for (const {target, isIntersecting} of entries) {
    if (!isIntersecting) continue;
    target.src = target.dataset.src;
    target.preload = "metadata";
    seen.unobserve(target);
  }
}, {rootMargin: "400px"});

const playing = () => [...document.querySelectorAll("video")].some(video => !video.paused);

async function poll() {
  try {
    const response = await fetch("/api/worlds");
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    if (ui.uiVersion !== null && body.ui_version !== ui.uiVersion) location.reload();
    ui.uiVersion = body.ui_version;
    ui.body = body;
    summary();
    // Redrawing swaps the players, which would stop one someone is watching.
    if (!playing()) draw();
  } catch (error) {
    status(`Can't reach the panel: ${error.message}`);
  }
}

$("types").addEventListener("click", event => {
  const tab = event.target.closest(".tab");
  if (!tab || !ui.body) return;
  ui.kind = tab.dataset.kind;
  remember("tab", ui.kind);
  draw();
});

for (const [id, key, saved] of [["group-by", "groupBy", "group"], ["sort", "sort", "sort"]]) {
  $(id).addEventListener("change", event => {
    ui[key] = event.target.value;
    remember(saved, ui[key]);
    if (ui.body) draw();
  });
}

$("groups").addEventListener("click", event => {
  const id = event.target.dataset.group;
  if (!id) return;
  ui.open.has(id) ? ui.open.delete(id) : ui.open.add(id);
  draw();
});

poll();
setInterval(poll, POLL_MS);
