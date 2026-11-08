// The Experiment 1 view. It polls what a run has written to disk and redraws; nothing here can change a run.
const $ = id => document.getElementById(id);
const POLL_MS = 3000;
const ui = {name: new URLSearchParams(location.hash.slice(1)).get("run"), picked: location.hash.length > 1, uiVersion: null,
            run: null, pick: null, follow: true, armsAt: 0, arms: null};

const GLOSSARY = {
  "observation": "The text the agent reads before a decision: recent mornings in words, the scene, how it feels, its options. It never contains numbers, odds or counts.",
  "felt text": "The needs turned into words (\"a little tense\"). It's the only way the agent knows its needs.",
  "pi": "π, the policy: the probability the model gives to each offered option, from how likely it is to start its answer with {\"choice\": \"that option\"}.",
  "needs": "Three numbers between 0 and 1: comfort, calm and connection. Each morning they start near 0.45; the setpoint is 0.7.",
  "setpoint": "0.7. Needs below it count as deficit; anything above it is wasted.",
  "drive": "Total deficit: how far each need sits below 0.7, summed. Lower is better.",
  "reward": "Drive before the outcome minus drive after it. Positive when the outcome helped. Only the outcome step is rewarded; the depletion between decisions never is.",
  "depletion": "Every need drops by 0.15 between decisions in a morning, whatever was chosen. It's never rewarded or punished.",
  "baseline": "A running mean of reward for this decision (D1, D2 or D3), moved a fifth of the way to each new reward.",
  "advantage": "Reward minus the baseline: whether this went better or worse than usual for this decision. Its sign decides which way the update pushes.",
  "sleep update": "At the end of each free day: 1 to 4 gradient steps on today's choices and the last five days', each weighted by its advantage, plus a KL term.",
  "KL": "How far the trained policy has moved from the untrained model on these states. β times it is added to the loss, which pulls the policy back.",
  "importance weight": "π now ÷ π when the choice was made, clipped to 0.8 to 1.2. It corrects for replaying choices an older policy made.",
  "rare outcome": "An outcome with probability below one half for that option. The odds are shown here for you; the agent never sees them.",
  "rare-bad": "An option that's usually fine but sometimes goes badly (run_main, front_gap, leave_early). Experience tends to keep these: the bad outcome is rarely met.",
  "rare-good": "An option that's usually dull but sometimes great (check_desk, wait_for_break, stay_and_chat). Experience tends to drop these: the good outcome is rarely met.",
  "front-gap gate": "The front gap is offered at D2 only if D1 got the agent to the lawn by 9:08. So D1's outcome decides D2's options.",
  "exploration": "Mornings before day 1 where each option is assigned at least twice. Their outcomes go into memory and the baseline, but never into a gradient.",
  "probe": "A fixed first-morning observation at the average entry state, scored every night, so changes in π come from training alone.",
  "tabular band": "What the tabular REINFORCE learner (one number per option, lr 8) does in this arm: the 10th to 90th percentile of its shares across lives.",
  "random": "A policy that picks uniformly among what's offered. Training has to beat it to have learned anything.",
  "always safe": "Takes each decision's safe option. The scenario has no do-nothing option, so this is the nearest to doing nothing.",
  "arm": "lived: outcomes from the option's own odds. flipped: rare-bad and rare-good swap odds, so the prediction reverses. shuffled: outcomes come from a random offered option, so choices carry no information.",
};
const term = (key, text = key) => `<span class="term" tabindex="0" data-term="${key}">${text}</span>`;

const escapeHtml = text => String(text ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const fixed = (value, places = 2) => value == null ? "n/a" : Number(value).toFixed(places);
const signed = (value, places = 3) => value == null ? "n/a" : `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(places)}`;
const percent = value => value == null ? "n/a" : `${Math.round(value * 100)}%`;
const code = where => `<span class="code">${escapeHtml(where)}</span>`;

function duration(seconds) {
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

// ----- charts -----
// series: [{points: [{x, y}], cls, label}]. references: [{y, label, quiet}]. marks: [{x, y, cls, text, title}].
function drawLines(element, series, {yMin = null, yMax = null, references = [], marks = [], cursor = null, xLabel = "", format = fixed} = {}) {
  const all = series.flatMap(s => s.points);
  if (!all.length) { element.innerHTML = `<div class="empty">Nothing logged yet</div>`; return; }
  const {width, height} = element.getBoundingClientRect();
  const margin = {left: 40, right: references.length ? 76 : 8, top: 8, bottom: 18};
  const ys = [...all.map(p => p.y), ...references.map(r => r.y)].filter(v => v != null);
  let low = yMin ?? Math.min(...ys), high = yMax ?? Math.max(...ys);
  if (low === high) { low -= 1; high += 1; }
  const xLow = Math.min(...all.map(p => p.x)), xHigh = Math.max(...all.map(p => p.x), xLow + 1);
  const x = v => margin.left + (v - xLow) / (xHigh - xLow) * (width - margin.left - margin.right);
  const y = v => margin.top + (high - v) / (high - low) * (height - margin.top - margin.bottom);
  const grid = [high, (low + high) / 2, low].map(v => `<path class="chart-grid" d="M${margin.left} ${y(v)}H${width - margin.right}"/><text x="${margin.left - 4}" y="${y(v) + 4}" text-anchor="end">${format(v)}</text>`).join("");
  const refs = references.filter(r => r.y != null).map(r => `<path class="${r.quiet ? "quiet-line" : "chart-reference"}" d="M${margin.left} ${y(r.y)}H${width - margin.right}"/><text x="${width - margin.right + 4}" y="${y(r.y) + 4}">${escapeHtml(r.label)}</text>`).join("");
  const lines = series.map(s => {
    const d = s.points.map((p, i) => `${i ? "L" : "M"}${x(p.x).toFixed(1)} ${y(p.y).toFixed(1)}`).join("");
    const dots = s.dots ? s.points.map(p => `<circle class="point" cx="${x(p.x)}" cy="${y(p.y)}" r="3"/>`).join("") : "";
    return `<path class="${s.cls}" d="${d}"><title>${escapeHtml(s.label ?? "")}</title></path>${dots}`;
  }).join("");
  const markup = marks.map(m => `<text class="mark ${m.cls}" x="${x(m.x)}" y="${y(m.y) + 4}" text-anchor="middle">${escapeHtml(m.text)}<title>${escapeHtml(m.title)}</title></text>`).join("");
  const cursorLine = cursor == null ? "" : `<path class="cursor" d="M${x(cursor)} ${margin.top}V${height - margin.bottom}"/>`;
  element.innerHTML = `<svg role="img" aria-label="${escapeHtml(series.map(s => s.label).join(", "))}">${grid}${refs}${cursorLine}${lines}${markup}<text x="${margin.left}" y="${height - 4}">${xLow}</text><text x="${width - margin.right}" y="${height - 4}" text-anchor="end">${escapeHtml(xLabel)} ${Math.floor(xHigh)}</text></svg>`;
}

const keyMarkup = items => items.map(({cls, label, dashed}) => `<span><svg><path class="${cls}" d="M0 4H16" ${dashed ? 'stroke-dasharray="2 4"' : ""}/></svg>${label}</span>`).join("");

// ----- the selected decision -----
function nightFor(run, row) {
  return run.nights.find(n => n.index === row.index) ?? null;
}

function gateLine(run, row) {
  if (row.decision === "D1") {
    const opened = row.arrival_after && row.arrival_after <= "09:08";
    return `Arrived at ${escapeHtml(row.arrival_after ?? "an unknown time")}, so the ${term("front-gap gate")} was ${opened ? "open" : "closed"} for D2.`;
  }
  if (row.decision === "D2") return `D1 got here at ${escapeHtml(row.arrival ?? "?")}, so the ${term("front-gap gate")} was ${row.gate_open ? "open: front_gap was offered" : "closed: front_gap wasn't offered"}.`;
  return "";
}

function piText(pi, choice) {
  return Object.entries(pi).sort((a, b) => b[1] - a[1]).map(([o, p]) => o === choice ? `<b>${escapeHtml(o)} ${percent(p)}</b>` : `${escapeHtml(o)} ${percent(p)}`).join(" · ");
}

function needsText(run, row) {
  return run.needs.map((need, i) => `${need} ${fixed(row.h_pre[i])}→${fixed(row.h_post[i])}`).join("<br>");
}

function stripMarkup(run, row) {
  const c = run.code, night = nightFor(run, row);
  const trained = night && night.steps > 0;
  const after = row.pi_after_night?.[row.choice];
  const odds = `${row.rare ? "rare" : "common"}, ${percent(row.outcome_p)}`;
  const source = run.config.arm === "shuffled" && row.outcome_source !== row.choice ? ` It came from ${escapeHtml(row.outcome_source)}, a random offered option (shuffled arm).` : "";
  const steps = [
    ["Observation", `“${escapeHtml(row.felt_text)}”`, `What the agent reads: past mornings in words, the scene, its ${term("felt text")}, its options. No numbers.`, c.observation,
     `<details><summary>Full text</summary><pre>${escapeHtml(row.observation)}</pre></details>`],
    ["Policy", piText(row.pi, row.choice), `${term("pi")}: how likely the model is to answer with each offered option.`, c.policy],
    ["Choice", `${escapeHtml(row.choice)}${row.forced ? " (assigned)" : ""}`, row.forced ? `${term("exploration")} morning: assigned, not chosen, and never trained on.` : "Sampled from π at temperature 1. The reason is written afterwards, for logs only.", c.choice,
     row.reason ? `<div class="meta">“${escapeHtml(row.reason)}”</div>` : ""],
    ["Outcome", `“${escapeHtml(row.memory)}”<br>${odds}`, `Entry ${row.schedule_index} of this option's pre-drawn schedule.${source} The odds are for you; the agent never sees them.`, c.outcome],
    ["Needs", needsText(run, row), `Each ${term("needs", "need")} moves by the outcome's change. Next decision they first ${term("depletion", "deplete")} by ${run.deplete}.`, c.needs],
    ["Reward", `drive ${fixed(row.drive_pre, 3)}→${fixed(row.drive_post, 3)}<br>reward ${signed(row.reward)}`, `${term("drive")} is total deficit below the ${term("setpoint")}; ${term("reward")} is how much the outcome cut it.`, c.reward],
    ["Advantage", `${signed(row.reward)} − ${signed(row.baseline)} = ${signed(row.advantage)}`, `${term("advantage")}: better or worse than this decision's ${term("baseline")}.`, c.advantage],
    ["Sleep update", trained ? `${night.steps} steps, ${night.samples} samples<br>KL ${fixed(night.kl, 4)}` : row.forced ? "not trained on" : night ? "not trained" : "tonight, not yet",
     trained ? `That night's ${term("sleep update")} pushed ${escapeHtml(row.choice)} ${row.advantage >= 0 ? "up" : "down"} here, and the ${term("KL")} term pulled toward the untrained model.` : "Exploration choices only move the baseline.", c.sleep],
    ["Policy shift", after == null ? "n/a" : `π(${escapeHtml(row.choice)}) ${percent(row.pi[row.choice])}→${percent(after)}`, "The same observation scored again after that night.", c.shift],
  ];
  return steps.map(([name, value, says, where, extra = ""], i) => `<li class="step card${(row.forced && i >= 6) ? " quiet" : ""}"><div class="eyebrow">${i + 1} ${name}</div><div class="value">${value}</div><div class="says">${says}</div>${extra}${code(where)}</li>`).join("");
}

function traceMarkup(run, row) {
  const when = row.phase === "free" ? `Free day ${row.day}` : "An exploration morning";
  const date = new Date(`${row.date}T12:00:00`).toLocaleDateString(undefined, {weekday: "long"});
  const top = Object.entries(row.pi).sort((a, b) => b[1] - a[1])[0];
  const picked = row.forced ? `${escapeHtml(row.choice)} was assigned` : `it picked ${escapeHtml(row.choice)}, which it gave ${percent(row.pi[row.choice])}${top[0] !== row.choice ? ` (its favourite was ${escapeHtml(top[0])} at ${percent(top[1])})` : ""}`;
  const outcome = `${row.rare ? `a ${term("rare outcome")}` : "the common outcome"}, “${escapeHtml(row.memory)}” (${percent(row.outcome_p)} odds)`;
  const reward = `${term("drive")} went from ${fixed(row.drive_pre, 3)} to ${fixed(row.drive_post, 3)}, a ${term("reward")} of ${signed(row.reward)}`;
  const advantage = `The ${row.decision} ${term("baseline")} was ${signed(row.baseline)}, so the ${term("advantage")} was ${signed(row.advantage)}`;
  const after = row.pi_after_night?.[row.choice];
  const update = row.forced ? "It wasn't trained on." : after == null ? "Tonight's update hasn't run yet." :
    percent(after) === percent(row.pi[row.choice])
      ? `That night π(${escapeHtml(row.choice)}) here stayed at ${percent(after)}${row.pi[row.choice] > 0.95 || row.pi[row.choice] < 0.05 ? ": near 0 or 1 the gradient of log π is close to zero, so one choice barely moves it" : ""}.`
      : `That night π(${escapeHtml(row.choice)}) here went ${percent(row.pi[row.choice])} → ${percent(after)}${Math.sign(after - row.pi[row.choice]) === Math.sign(row.advantage) ? "" : ", the opposite way to its own advantage: the other choices replayed that night and the KL pull outweighed it"}.`;
  const gate = gateLine(run, row);
  return `<p>${when}, ${escapeHtml(date)}, ${row.decision}. ${term("felt text", "It felt")}: “${escapeHtml(row.felt_text.replace(/^You feel /, "").replace(/\.$/, ""))}”. ${picked[0].toUpperCase()}${picked.slice(1)}. It got ${outcome}. ${reward}. ${advantage}. ${update}</p>`
    + (gate ? `<p class="gate">${gate}</p>` : "") + (row.reason ? `<p class="reason">Its reason, written after choosing: “${escapeHtml(row.reason)}”</p>` : "");
}

function overnightMarkup(run, row) {
  const night = nightFor(run, row);
  if (!night) return `<div class="meta">This morning's night hasn't run yet.</div>`;
  if (!night.steps) return `<div class="meta">${escapeHtml(night.skipped ?? "No update that night.")}</div>`;
  const shifts = night.today.map(t => {
    const lines = Object.keys(t.pi_before).map(o => `<span class="${o === t.choice ? "chosen" : ""}">${escapeHtml(o)}</span><span>${percent(t.pi_before[o])}</span><span>→</span><span>${percent(t.pi_after[o])}</span>`).join("");
    return `<div class="overnight-block"><div class="meta">${t.decision}: chose ${escapeHtml(t.choice)}, ${term("advantage")} ${signed(t.advantage)}</div><div class="shift">${lines}</div></div>`;
  }).join("");
  const stats = `<div class="meta">Day ${night.day}: ${night.steps} steps on ${night.samples} choices (today and ${night.replay_days} days back). PG loss ${fixed(night.loss_pg, 4)}, ${term("KL")} ${fixed(night.kl, 4)} (β·KL ${fixed(night.loss_kl, 5)}), grad norm ${fixed(night.grad_norm, 3)}, mean ${term("importance weight")} ${fixed(night.per_step?.at(-1)?.weight_mean, 3)}. LoRA step ${night.lora_step}.</div>`;
  const probes = Object.keys(night.probes_after).map(name => {
    const before = night.probes_before[name], after = night.probes_after[name];
    const moved = Object.keys(after).map(o => ({o, d: after[o] - before[o]})).sort((a, b) => Math.abs(b.d) - Math.abs(a.d))[0];
    return `${escapeHtml(name)}: ${escapeHtml(moved.o)} ${signed(moved.d * 100, 1)} points`;
  }).join("<br>");
  return stats + shifts + `<div class="meta">Biggest move on each ${term("probe")}:<br>${probes}</div>`;
}

// ----- whole-run views -----
function drawNeeds(run, row) {
  // Eight mornings ending at the selected one: the whole life is too dense to read a sawtooth in.
  const last = row ? row.index : 0, shown = run.rows.filter(r => r.index > last - 8 && r.index <= last + (row ? 0 : 8));
  const series = run.needs.map((need, i) => ({cls: `s${i}`, label: need, points: shown.flatMap(r => [{x: r.n, y: r.h_pre[i]}, {x: r.n + 0.6, y: r.h_post[i]}])}));
  const rare = shown.filter(r => r.rare).map(r => ({x: r.n + 0.6, y: 0.04, cls: "", text: "×", title: `${r.decision} ${r.choice}: rare outcome, reward ${signed(r.reward)}`}));
  drawLines($("needs"), series, {yMin: 0, yMax: 1, references: [{y: run.setpoint, label: "setpoint", quiet: true}], marks: rare, cursor: row ? row.n + 0.3 : null, xLabel: "decision"});
  $("needs-key").innerHTML = keyMarkup(run.needs.map((need, i) => ({cls: `s${i}`, label: need}))) + `<span>The last eight mornings up to the selected decision. Each decision is a step at the outcome, then the ${term("depletion")} before the next one. Mornings reset. × is a ${term("rare outcome")}.</span>`;
}

function drawProbes(run) {
  const trained = run.nights.filter(n => n.steps > 0);
  const element = $("probs");
  if (!trained.length) { element.innerHTML = `<div class="note">No night has trained yet. Probes start on free day 1.</div>`; return; }
  const names = Object.keys(trained[0].probes_after);
  element.innerHTML = names.map((name, k) => `<div><div class="eyebrow">${escapeHtml(name)}</div><div id="probe-${k}" class="chart"></div><div id="probe-key-${k}" class="chart-key-row"></div></div>`).join("");
  names.forEach((name, k) => {
    const options = Object.keys(trained[0].probes_after[name]);
    const series = options.map((o, i) => ({cls: `s${i}`, label: o, points: [{x: 0, y: trained[0].probes_before[name][o]}, ...trained.map(n => ({x: n.day, y: n.probes_after[name][o]}))]}));
    const decision = name.slice(0, 2), gate = name.includes("open") ? true : name.includes("closed") ? false : null;
    const marks = run.rows.filter(r => r.rare && r.phase === "free" && r.decision === decision && (gate === null || r.gate_open === gate) && options.includes(r.choice))
      .map(r => ({x: r.day, y: 0.02, cls: `s${options.indexOf(r.choice)}`, text: "×", title: `day ${r.day}: ${r.choice} got rare ${r.outcome_label} (reward ${signed(r.reward)})`}));
    drawLines($(`probe-${k}`), series, {yMin: 0, yMax: 1, marks, references: [{y: 1 / options.length, label: "chance", quiet: true}], xLabel: "day", format: percent});
    $(`probe-key-${k}`).innerHTML = keyMarkup(options.map((o, i) => ({cls: `s${i}`, label: o})));
  });
}

function drawShares(run) {
  const groups = run.summary?.shares, tab = run.reference.tabular.shares, random = run.reference.random.across_lives.shares;
  $("shares-note").innerHTML = `The dot is this run. The hollow ring is the untrained model's average π on the same states: if the dot sits on it, training changed nothing. The line is the ${term("tabular band")} for the ${escapeHtml(run.config.arm)} ${term("arm")}; the dotted tick is what a ${term("random")} policy picks on average. n is how many picks the dot is from.`;
  if (!groups) { $("shares").innerHTML = `<div class="note">No free days yet.</div>`; return; }
  const x = v => `${(2 + v * 96).toFixed(2)}%`;
  $("shares").innerHTML = Object.entries(groups).map(([name, group]) => {
    const rows = Object.entries(group.options).map(([o, share]) => {
      const band = tab[name]?.[o], chance = random[name]?.[o]?.mean;
      const svg = `<svg role="img" aria-label="${escapeHtml(o)}: ${percent(share)}, tabular ${percent(band?.p10)} to ${percent(band?.p90)}"><line class="axis" x1="2%" x2="98%" y1="10" y2="10"/>`
        + (band ? `<line class="band" x1="${x(band.p10)}" x2="${x(band.p90)}" y1="10" y2="10"/><line class="band" x1="${x(band.p10)}" x2="${x(band.p10)}" y1="6" y2="14"/><line class="band" x1="${x(band.p90)}" x2="${x(band.p90)}" y1="6" y2="14"/>` : "")
        + (chance != null ? `<line class="chance" x1="${x(chance)}" x2="${x(chance)}" y1="3" y2="17"/>` : "")
        + (group.base_pi?.[o] != null ? `<circle class="base" cx="${x(group.base_pi[o])}" cy="10" r="4"/>` : "")
        + (share != null ? `<circle class="dot" cx="${x(share)}" cy="10" r="3"/>` : "") + `</svg>`;
      const role = Object.entries(run.pairs).find(([g, pair]) => g === name && pair.includes(o));
      const tag = role ? (role[1][0] === o ? ` ${term("rare-bad", "rb")}` : ` ${term("rare-good", "rg")}`) : "";
      return `<div class="share-row"><span>${escapeHtml(o)}${tag}</span>${svg}<b>${percent(share)}</b></div>`;
    }).join("");
    return `<div><div class="eyebrow">${escapeHtml(name)}, n ${group.n}</div>${rows}</div>`;
  }).join("");
}

function drawTraining(run) {
  const trained = run.nights.filter(n => n.steps > 0);
  const byDay = new Map();
  run.rows.filter(r => r.phase === "free").forEach(r => byDay.set(r.day, [...(byDay.get(r.day) ?? []), r.reward]));
  const rewards = [...byDay].map(([day, values]) => ({x: day, y: values.reduce((a, b) => a + b, 0) / values.length}));
  const ref = run.reference;
  const randomMean = ref.random.this_seed.mean_reward.all, safeMean = ref.always_safe.this_seed.mean_reward.all;
  drawLines($("reward"), [{cls: "chart-key", label: "this run", points: rewards, dots: true}], {references: [{y: randomMean, label: "random"}, {y: safeMean, label: "always safe", quiet: true}], xLabel: "day", format: v => fixed(v, 3)});
  $("reward-key").innerHTML = `<span>The ${term("random")} line is a uniformly random policy on this same seed; ${term("always safe")} is the nearest thing to doing nothing (this scenario has none).</span>`;
  const series = key => [{cls: "chart-line", label: key, points: trained.map(n => ({x: n.day, y: n[key]}))}];
  drawLines($("loss"), series("loss_pg"), {xLabel: "day", format: v => fixed(v, 4)});
  drawLines($("kl"), series("kl"), {xLabel: "day", format: v => fixed(v, 4)});
  drawLines($("grad"), series("grad_norm"), {xLabel: "day", format: v => fixed(v, 3)});
  const g = run.guardrails?.results;
  $("guardrails").innerHTML = g ? `<div class="table-scroll"><table><thead><tr><th>guardrail</th><th>questions</th><th>untrained</th><th>trained</th><th>difference</th><th>± se</th><th></th></tr></thead><tbody>${g.map(r => `<tr><td>${escapeHtml(r.check)}</td><td>${r.questions}</td><td>${fixed(r.base_points, 1)}</td><td>${fixed(r.trained_points, 1)}</td><td>${signed(r.difference, 1)}</td><td>${fixed(r.difference_se, 1)}</td><td class="${r.flagged ? "fail" : "pass"}">${r.flagged ? "more than 1 point down" : "ok"}</td></tr>`).join("")}</tbody></table></div>`
    : `<p class="note">Guardrails (MMLU and IFEval subsets, untrained vs trained) run after a life when asked for with --guardrails. None for this run.</p>`;
}

function drawArms(data) {
  const arms = Object.entries(data.arms);
  if (!arms.length) { $("arms").innerHTML = `<p class="note">No runs yet.</p>`; return; }
  const rows = arms.flatMap(([arm, info]) => info.runs.map(run => {
    const cells = Object.keys(data.pairs).map(group => {
      const d = run.direction[group];
      if (d.pass == null) return `<td class="na">no picks</td>`;
      const [bad, good] = data.pairs[group];
      const base = run.base_pi?.[group];
      const prior = base ? `, untrained ${percent(base[bad])}/${percent(base[good])}` : "";
      return `<td class="${d.pass ? "pass" : "fail"}">${d.pass ? "yes" : "no"} ${percent(d.observed[bad])}/${percent(d.observed[good])} n${d.n}${prior}</td>`;
    }).join("");
    return `<tr><td>${escapeHtml(arm)}</td><td>${escapeHtml(run.name)}</td><td>${escapeHtml(run.policy)} lr ${run.lr}</td><td>${escapeHtml(run.state)}</td>${cells}<td>${fixed(run.mean_reward, 3)}</td><td>${fixed(info.random_reward, 3)}</td><td>${fixed(info.always_safe_reward, 3)}</td></tr>`;
  })).join("");
  const predicted = `<p class="note">Predicted: ${term("arm", "lived")} keeps ${term("rare-bad")} over ${term("rare-good")}; flipped reverses it; shuffled shows neither. Each cell is rare-bad / rare-good share in the second half. One life gives about a dozen picks per decision, so a single run is a reading, not a test.</p>`;
  const head = `<tr><th>arm</th><th>run</th><th>policy</th><th>state</th>${Object.keys(data.pairs).map(g => `<th>${escapeHtml(g)}</th>`).join("")}<th>reward</th><th>random</th><th>always safe</th></tr>`;
  $("arms").innerHTML = predicted + `<div class="table-scroll"><table><thead>${head}</thead><tbody>${rows}</tbody></table></div>`;
}

function statusText(run) {
  const s = run.status;
  if (!s) return "Starting";
  const where = s.phase === "sleeping" && s.night_after != null
    ? (s.night_after === "exploration" ? `after exploration morning ${s.explore_days}` : `after free day ${s.night_after} of ${s.days}`)
    : s.free_day ? `free day ${Math.min(s.free_day, s.days)} of ${s.days}` : `exploration morning ${s.explore_days}`;
  const age = duration((Date.now() - new Date(s.updated).getTime()) / 1000);
  if (run.state === "finished") return `Finished: ${s.decisions} decisions, ${s.lora_step} LoRA steps`;
  if (run.state === "stopped") return `Stopped at ${where}, last write ${age} ago`;
  return `${s.phase[0].toUpperCase()}${s.phase.slice(1)}, ${where}, decision ${s.decisions}, LoRA step ${s.lora_step}, ${age} ago`;
}

function drawSelected() {
  const run = ui.run;
  const rows = run.rows;
  if (!rows.length) { $("strip").innerHTML = ""; $("trace").innerHTML = `<div class="meta">No decisions yet.</div>`; $("overnight").innerHTML = ""; return; }
  const row = rows[ui.pick];
  $("pick-text").textContent = `decision ${row.n + 1} of ${rows.length}, ${row.phase === "free" ? `day ${row.day}` : "exploration"} ${row.decision}`;
  $("strip").innerHTML = stripMarkup(run, row);
  $("trace").innerHTML = traceMarkup(run, row);
  $("overnight").innerHTML = overnightMarkup(run, row);
  drawNeeds(run, row);
}

function draw(run, force = false) {
  const signature = `${run.name} ${run.rows.length} ${run.nights.length} ${run.status?.updated}`;
  $("status-line").classList.toggle("live", ["living", "sleeping", "guardrails", "baselines"].includes(run.state));
  $("status-text").textContent = statusText(run);
  if (!force && signature === ui.signature) return;
  ui.signature = signature;
  ui.run = run;
  const max = Math.max(run.rows.length - 1, 0);
  $("pick").max = max;
  if (ui.follow || ui.pick == null || ui.pick > max) ui.pick = max;
  $("pick").value = ui.pick;
  const notice = run.config.policy === "table" ? "This run used the table policy, not Qwen: a check of the loop, not a model result." : "";
  $("notice").hidden = !notice;
  $("notice").textContent = notice;
  drawSelected();
  drawProbes(run);
  drawShares(run);
  drawTraining(run);
}

async function get(path) {
  const response = await fetch(path);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error);
  return body;
}

async function poll() {
  try {
    const {runs, ui_version: version} = await get("/api/exp1/runs");
    if (ui.uiVersion !== null && version !== ui.uiVersion) location.reload();
    ui.uiVersion = version;
    const live = runs.find(run => run.state === "living" || run.state === "sleeping");
    if (!runs.some(run => run.name === ui.name) || (!ui.picked && live)) ui.name = (live ?? runs[0])?.name ?? null;
    $("runs").innerHTML = runs.map(run => `<option value="${escapeHtml(run.name)}"${run.name === ui.name ? " selected" : ""}>${escapeHtml(run.name)} (${escapeHtml(run.state)})</option>`).join("");
    if (!ui.name) { $("status-text").textContent = "No Experiment 1 runs yet. Start one with python -m exp1.run."; return; }
    if (ui.picked) history.replaceState(null, "", `#run=${encodeURIComponent(ui.name)}`);
    draw(await get(`/api/exp1/run?name=${encodeURIComponent(ui.name)}`));
    if (Date.now() - ui.armsAt > 30000) { ui.armsAt = Date.now(); drawArms(await get("/api/exp1/arms")); }
  } catch (error) {
    $("status-text").textContent = `Can't read the run: ${error.message}`;
  }
}

function choose(index) {
  if (!ui.run) return;
  ui.pick = Math.max(0, Math.min(index, ui.run.rows.length - 1));
  ui.follow = ui.pick === ui.run.rows.length - 1;
  $("pick").value = ui.pick;
  drawSelected();
}

// One tooltip for every glossary term, on hover or keyboard focus.
function showTip(target) {
  const tip = $("tip"), text = GLOSSARY[target.dataset.term];
  if (!text) return;
  tip.textContent = text;
  tip.hidden = false;
  const box = target.getBoundingClientRect();
  tip.style.left = `${Math.max(8, Math.min(box.left, innerWidth - tip.offsetWidth - 8))}px`;
  tip.style.top = `${box.bottom + 6 + tip.offsetHeight > innerHeight ? box.top - tip.offsetHeight - 6 : box.bottom + 6}px`;
}
for (const kind of ["mouseover", "focusin"]) document.addEventListener(kind, e => { const t = e.target.closest?.(".term"); if (t) showTip(t); });
for (const kind of ["mouseout", "focusout"]) document.addEventListener(kind, e => { if (e.target.closest?.(".term")) $("tip").hidden = true; });

$("runs").addEventListener("change", event => { ui.name = event.target.value; ui.picked = true; ui.follow = true; ui.armsAt = 0; poll(); });
$("pick").addEventListener("input", event => choose(Number(event.target.value)));
$("prev").addEventListener("click", () => choose(ui.pick - 1));
$("next").addEventListener("click", () => choose(ui.pick + 1));
addEventListener("keydown", event => {
  if (event.target.matches("input, select, textarea")) return;
  if (event.key === "ArrowLeft") choose(ui.pick - 1);
  if (event.key === "ArrowRight") choose(ui.pick + 1);
});
addEventListener("resize", () => ui.run && draw(ui.run, true));
poll();
setInterval(poll, POLL_MS);
