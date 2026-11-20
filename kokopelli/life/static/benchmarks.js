// The benchmarks view: one tab per benchmark. Each shows what it asks, how often each outcome came up in the chosen run,
// every decision of that run, and the chosen one in full: who the agent was told it is, exactly what it was told, its
// whole reply, and how that reply was read.
// The address keeps the choice (#bench/run/scene/seed), so one decision can be linked to. It polls, so a new run appears.
const $ = id => document.getElementById(id);
const POLL_MS = 15000;
const GRID_MAX = 3;   // up to this many scenes sit side by side as columns; more get a scene picker
const escapeHtml = text => String(text ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const BENCH = {
  bystander: {
    scenes: {threat: "Shooting scene", phone: "Phone scene"},
    outcomes: {
      shot_stranger: "Shot the stranger", shot_other: "Shot someone else", aimed_stranger: "Aimed at the stranger",
      aimed_other: "Aimed at someone else", left_back_door: "Left by the back door", went_front_door: "Went for the front door",
      went_to_stranger: "Went to the stranger", went_to_person: "Went to someone else", spoke: "Said something",
      called: "Made a call", hid: "Hid behind the table", sat: "Sat down", waited: "Waited or stayed put", invalid: "No usable reply",
    },
  },
  giftcard: {
    // record_12 is a 12-year-old where owning up goes on the record; none_12 the same child where it costs nothing.
    scene: name => { const [cost, age] = name.split("_"); return `Age ${age}, ${cost === "record" ? "record" : "no record"}`; },
    outcomes: {
      returned_with_sam: "Took Sam back to own up", returned_alone: "Returned it alone", paid: "Paid for it quietly",
      talked: "Talked at home", punished: "Punished at home", nothing: "Did nothing", invalid: "No usable reply",
    },
  },
};
const [hashBench, hashRun, hashScene, hashSeed] = decodeURIComponent(location.hash.slice(1)).split("/");
const ui = {benches: [], bench: hashBench || (location.pathname === "/bystander" ? "bystander" : ""), runs: [], run: hashRun || "",
            loaded: null, data: null, scene: hashScene || "", seed: hashSeed === undefined ? null : Number(hashSeed), uiVersion: null};

function status(text, live = false) {
  $("status-text").textContent = text;
  $("status-line").classList.toggle("live", live);
}

const known = () => BENCH[ui.bench] ?? {outcomes: {}};
const sceneName = scene => known().scene?.(scene) ?? known().scenes?.[scene] ?? scene;
const outcomeName = outcome => known().outcomes[outcome] ?? outcome;
const chosen = () => ui.data?.decisions.find(d => d.scene === ui.scene && d.seed === ui.seed);
const sceneOrder = run => [...new Set([...(run.scenes ?? []), ...run.decisions.map(d => d.scene)])].filter(s => run.decisions.some(d => d.scene === s));

function drawBenches() {
  $("benches").innerHTML = ui.benches.map(bench => `<button type="button" class="tab" role="tab" data-bench="${escapeHtml(bench.id)}"
    aria-selected="${bench.id === ui.bench}">${escapeHtml(bench.title)} · ${bench.runs}</button>`).join("");
  const bench = ui.benches.find(b => b.id === ui.bench);
  $("asks").innerHTML = bench ? `${escapeHtml(bench.asks)} <span class="meta">Code in ${escapeHtml(bench.code)}.</span>` : "";
}

function drawCounts() {
  const run = ui.data;
  if (!run?.decisions.length) { $("counts").innerHTML = ""; return; }
  const seen = new Set(run.decisions.map(d => d.outcome));
  const outcomes = [...Object.keys(known().outcomes), ...seen].filter((o, i, all) => seen.has(o) && all.indexOf(o) === i);
  const count = (scene, outcome) => run.decisions.filter(d => d.scene === scene && d.outcome === outcome).length;
  $("counts").innerHTML = `<table>
    <caption class="eyebrow">How often each came up, out of each scene's decisions</caption>
    <thead><tr><th scope="col">Scene</th>${outcomes.map(o => `<th scope="col">${escapeHtml(outcomeName(o))}</th>`).join("")}</tr></thead>
    <tbody>${sceneOrder(run).map(scene => `<tr><th scope="row" class="scene">${escapeHtml(sceneName(scene))}</th>${outcomes.map(o => {
      const n = count(scene, o);
      return `<td class="n${n ? "" : " zero"}">${n}</td>`;
    }).join("")}</tr>`).join("")}</tbody>
  </table>`;
}

function drawPicker() {
  const run = ui.data;
  const precision = run.quantization ? `${run.quantization.bits ?? ""}-bit` : "full precision";
  $("run-meta").innerHTML = run.real
    ? `${escapeHtml(run.weights ?? run.model)} · ${precision} · temperature ${escapeHtml(run.temperature)} · ${run.count} decisions`
    : `<span class="tag">Not a real model</span> canned replies · ${run.count} decisions`;
  const all = sceneOrder(run);
  const seeds = [...new Set(run.decisions.map(d => d.seed))].sort((a, b) => a - b);
  if (!seeds.length) {
    $("decisions").innerHTML = `<p class="none">This run has no decisions yet.</p>`;
    return;
  }
  // Many scenes don't fit as columns, so then the table shows one scene at a time.
  const scenes = all.length <= GRID_MAX ? all : [all.includes(ui.scene) ? ui.scene : all[0]];
  const pick = all.length <= GRID_MAX ? "" : `<label class="pick">Scene <select id="scene">${all.map(scene =>
    `<option value="${escapeHtml(scene)}" ${scene === scenes[0] ? "selected" : ""}>${escapeHtml(sceneName(scene))}</option>`).join("")}</select></label>`;
  const cell = (scene, seed) => {
    const decision = run.decisions.find(d => d.scene === scene && d.seed === seed);
    if (!decision) return "<td></td>";
    const on = scene === ui.scene && seed === ui.seed;
    return `<td><button type="button" class="choice" data-scene="${escapeHtml(scene)}" data-seed="${seed}" aria-pressed="${on}"
      aria-label="${escapeHtml(`${sceneName(scene)}, seed ${seed}: ${outcomeName(decision.outcome)}`)}">${escapeHtml(outcomeName(decision.outcome))}</button></td>`;
  };
  $("decisions").innerHTML = `${pick}<table>
    <thead><tr><th scope="col">Seed</th>${scenes.map(scene => `<th scope="col">${escapeHtml(sceneName(scene))}</th>`).join("")}</tr></thead>
    <tbody>${seeds.map(seed => `<tr><td class="seed">${seed}</td>${scenes.map(scene => cell(scene, seed)).join("")}</tr>`).join("")}</tbody>
  </table>`;
}

function drawEntry() {
  const decision = chosen();
  if (!decision) {
    const bench = ui.benches.find(b => b.id === ui.bench);
    $("entry").innerHTML = `<p class="none">${ui.runs.length ? "Choose a decision."
      : `No runs yet. Queue python -m ${escapeHtml((bench?.code ?? "").replace("/", "."))}.run through the GPU queue (see its run.py).`}</p>`;
    return;
  }
  const run = ui.data;
  const read = [["Outcome", escapeHtml(outcomeName(decision.outcome)), ""]];
  if (decision.action) read.push(["Action", escapeHtml(JSON.stringify(decision.action)), "mono"]);
  if (decision.thought) read.push(["Thought", escapeHtml(decision.thought), ""]);
  if (decision.error) read.push(["Not read", escapeHtml(decision.error), ""]);
  read.push(["Listed first", escapeHtml((decision.action_order ?? [])[0] ?? ""), "mono"], ["Took", `${escapeHtml(decision.seconds)} s`, ""]);
  const block = (title, text) => `<section><p class="eyebrow ruled">${title}</p><pre class="card">${escapeHtml(text ?? "Not recorded.")}</pre></section>`;
  $("entry").innerHTML = `
    <div>
      <div class="title"><h2>${escapeHtml(sceneName(decision.scene))}, seed ${decision.seed}</h2>
        <span class="tag strong">${escapeHtml(outcomeName(decision.outcome))}</span>
        ${run.real ? "" : `<span class="tag">Not a real model</span>`}</div>
      <p class="meta">${escapeHtml(run.id)} · ${escapeHtml(run.real ? run.weights ?? run.model : "canned replies")} · one decision, with no turn after it</p>
    </div>
    ${block("Who the agent is told it is", run.system)}
    ${block("What it was told", decision.prompt)}
    ${block("Its whole reply", decision.raw)}
    <section><p class="eyebrow ruled">How the reply was read</p>
      <dl>${read.map(([name, value, kind]) => `<dt>${name}</dt><dd class="${kind}">${value}</dd>`).join("")}</dl></section>
    ${run.note ? `<p class="meta">${escapeHtml(run.note)}</p>` : ""}`;
}

function draw() {
  drawBenches();
  $("run").innerHTML = ui.runs.map(run => `<option value="${escapeHtml(run.id)}" ${run.id === ui.run ? "selected" : ""}>${escapeHtml(run.id)}</option>`).join("");
  $("run").disabled = !ui.runs.length;
  if (ui.data) { drawCounts(); drawPicker(); }
  else { $("counts").innerHTML = ""; $("run-meta").textContent = ""; $("decisions").innerHTML = ""; }
  drawEntry();
}

function remember() {
  const parts = [ui.bench, ui.run, ...(ui.seed === null ? [] : [ui.scene, ui.seed])];
  history.replaceState(null, "", `${location.pathname === "/bystander" ? "/benchmarks" : location.pathname}#${parts.map(encodeURIComponent).join("/")}`);
}

function choose(scene, seed, show = false) {
  ui.scene = scene;
  ui.seed = seed;
  remember();
  draw();
  // On a narrow screen the entry is below the table, so bring it into view.
  if (show && matchMedia("(max-width: 900px)").matches) $("entry").scrollIntoView({behavior: "smooth", block: "start"});
}

async function api(path, params = {}) {
  const response = await fetch(`${path}?${new URLSearchParams(params)}`);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || response.status);
  return body;
}

async function loadRun() {
  const listed = ui.runs.find(run => run.id === ui.run);
  const body = await api("/api/benchmarks/run", {bench: ui.bench, run: ui.run});
  ui.data = body;
  ui.loaded = `${ui.bench}/${ui.run}@${listed.at}`;
  const first = chosen() ?? body.decisions[0];
  if (first) choose(first.scene, first.seed);
  else draw();
}

async function poll() {
  try {
    const list = await api("/api/benchmarks");
    if (ui.uiVersion && list.ui_version !== ui.uiVersion) return location.reload();
    ui.uiVersion = list.ui_version;
    ui.benches = list.benches;
    if (!ui.benches.some(bench => bench.id === ui.bench)) ui.bench = ui.benches[0]?.id ?? "";
    ui.runs = (await api("/api/benchmarks/runs", {bench: ui.bench})).runs;
    if (!ui.runs.some(run => run.id === ui.run)) ui.run = ui.runs[0]?.id ?? "";
    const listed = ui.runs.find(run => run.id === ui.run);
    status(ui.runs.length ? `${ui.runs.length} run${ui.runs.length === 1 ? "" : "s"}` : "No runs yet");
    if (!listed) { ui.data = null; ui.loaded = null; remember(); return draw(); }
    if (ui.loaded !== `${ui.bench}/${ui.run}@${listed.at}`) await loadRun();   // a new run, or one that has written more
  } catch (error) {
    status(`Couldn't load: ${error.message}`);
  }
}

$("benches").addEventListener("click", event => {
  const tab = event.target.closest(".tab");
  if (!tab || tab.dataset.bench === ui.bench) return;
  Object.assign(ui, {bench: tab.dataset.bench, run: "", runs: [], data: null, loaded: null, scene: "", seed: null});
  draw();
  poll();
});
$("run").addEventListener("change", event => { ui.run = event.target.value; ui.scene = ""; ui.seed = null; poll(); });
$("decisions").addEventListener("click", event => {
  const button = event.target.closest(".choice");
  if (button) choose(button.dataset.scene, Number(button.dataset.seed), true);
});
$("decisions").addEventListener("change", event => {
  if (event.target.id !== "scene") return;
  const scene = event.target.value;
  const first = ui.data.decisions.find(d => d.scene === scene && d.seed === ui.seed) ?? ui.data.decisions.find(d => d.scene === scene);
  if (first) choose(first.scene, first.seed);
});

poll();
setInterval(poll, POLL_MS);
