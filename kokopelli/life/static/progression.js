// The progression view: the judgment plan's goals, its phases in order with each one's gate and tasks, and the open
// decisions. Clicking a task's status advances it (shift-click goes back); notes and answers save when the field loses focus.
// Everything saves into experiments/judgment/plan.json. It polls, so an edit to the file by hand shows up.
const $ = id => document.getElementById(id);
const POLL_MS = 15000;
const ORDER = ["todo", "doing", "done", "skipped", "blocked"];
const escapeHtml = text => String(text ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const ui = {plan: null, phase: decodeURIComponent(location.hash.slice(1)) || "", uiVersion: null, typing: false};

// Skipped tasks leave the count, so skipping one doesn't make a phase look stuck.
const share = tasks => {
  const counted = tasks.filter(t => t.status !== "skipped");
  return counted.length ? counted.filter(t => t.status === "done").length / counted.length : 0;
};
const bar = fraction => `<div class="bar" aria-hidden="true"><i style="width:${Math.round(fraction * 100)}%"></i></div>`;

function status(text) { $("status-text").textContent = text; }

function draw() {
  const plan = ui.plan;
  $("thesis").textContent = plan.thesis;
  $("goals").innerHTML = plan.goals.map(goal => {
    const fraction = share(plan.phases.filter(p => p.feeds.includes(goal.id)).flatMap(p => p.tasks));
    return `<div class="goal"><span class="eyebrow">${escapeHtml(goal.id)} · ${Math.round(fraction * 100)}%</span>
      <b>${escapeHtml(goal.label)}</b><p>${escapeHtml(goal.detail)}</p>${bar(fraction)}</div>`;
  }).join("");

  $("rail").innerHTML = plan.phases.map((phase, i) => `
    <button class="step" data-phase="${escapeHtml(phase.id)}" aria-current="${phase.id === ui.phase}">
      <span class="eyebrow">P${i} · ${escapeHtml(phase.window)}</span>${escapeHtml(phase.name)}${bar(share(phase.tasks))}</button>`).join("");

  const goalLabel = Object.fromEntries(plan.goals.map(g => [g.id, g.label]));
  $("phases").innerHTML = plan.phases.map((phase, i) => `
    <section class="phase" id="${escapeHtml(phase.id)}">
      <div class="phase-head"><h2>P${i} · ${escapeHtml(phase.name)}</h2><span class="eyebrow">${escapeHtml(phase.window)}</span></div>
      <p class="why">${escapeHtml(phase.why)}</p>
      <p class="gate"><span class="eyebrow">Gate</span> ${escapeHtml(phase.gate)}</p>
      <div class="feeds">${phase.feeds.map(f => `<span class="tag">${escapeHtml(goalLabel[f])}</span>`).join("")}</div>
      ${phase.tasks.map(task => `
        <div class="task ${escapeHtml(task.status)}">
          <button class="task-status ${escapeHtml(task.status)}" data-task="${escapeHtml(task.id)}" title="Click to advance, shift-click to go back">${escapeHtml(task.status)}</button>
          <div><div class="text">${escapeHtml(task.text)}</div>
          <textarea class="note" rows="1" data-task="${escapeHtml(task.id)}" placeholder="note" aria-label="Note">${escapeHtml(task.note)}</textarea></div>
        </div>`).join("")}
    </section>`).join("");

  const all = plan.phases.flatMap(p => p.tasks), count = s => all.filter(t => t.status === s).length;
  $("totals").innerHTML = [["done", count("done")], ["doing", count("doing")], ["left", count("todo") + count("blocked")]]
    .map(([name, n]) => `<div><dd>${n}</dd><dt>${name}</dt></div>`).join("");

  $("decisions").innerHTML = plan.decisions.map(d => `
    <label class="decision ${d.answer ? "answered" : ""}">${escapeHtml(d.q)}
      <input data-decision="${escapeHtml(d.id)}" value="${escapeHtml(d.answer)}" placeholder="Your answer"></label>`).join("");
}

async function edit(change) {
  try {
    const response = await fetch("/api/progression/edit", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(change)});
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || response.status);
    ui.plan = body;
    status(`Saved ${new Date().toLocaleTimeString()}`);
    draw();
  } catch (error) {
    status(`Couldn't save: ${error.message}`);
  }
}

async function poll() {
  if (ui.typing) return;   // a redraw would throw away what's being typed
  try {
    const response = await fetch("/api/progression");
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || response.status);
    if (ui.uiVersion && body.ui_version !== ui.uiVersion) return location.reload();
    ui.uiVersion = body.ui_version;
    ui.plan = body;
    if (!ui.plan.phases.some(p => p.id === ui.phase)) ui.phase = ui.plan.phases[0]?.id ?? "";
    if ($("status-text").textContent === "Loading") status(`${ui.plan.phases.length} phases`);
    draw();
  } catch (error) {
    status(`Couldn't load: ${error.message}`);
  }
}

$("rail").addEventListener("click", event => {
  const step = event.target.closest(".step");
  if (!step) return;
  ui.phase = step.dataset.phase;
  history.replaceState(null, "", `#${encodeURIComponent(ui.phase)}`);
  draw();
  $(ui.phase).scrollIntoView({behavior: "smooth", block: "start"});
});
$("phases").addEventListener("click", event => {
  const button = event.target.closest(".task-status");
  if (!button) return;
  const task = ui.plan.phases.flatMap(p => p.tasks).find(t => t.id === button.dataset.task);
  const next = ORDER[(ORDER.indexOf(task.status) + (event.shiftKey ? ORDER.length - 1 : 1)) % ORDER.length];
  edit({kind: "task", id: task.id, status: next});
});
document.addEventListener("focusin", event => { if (event.target.matches(".note, .decision input")) ui.typing = true; });
document.addEventListener("focusout", event => { if (event.target.matches(".note, .decision input")) ui.typing = false; });
document.addEventListener("change", event => {
  if (event.target.matches(".note")) edit({kind: "task", id: event.target.dataset.task, note: event.target.value});
  else if (event.target.matches(".decision input")) edit({kind: "decision", id: event.target.dataset.decision, answer: event.target.value});
});

await poll();
if (location.hash) $(ui.phase)?.scrollIntoView({block: "start"});
setInterval(poll, POLL_MS);
