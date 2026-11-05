// The side panel: what the chosen node is, its plan against what happened, and the recent events.
import {esc} from "./rulers.js";

const STATUS = {closed: "Written", open: "In progress", ghost: "Not written yet", skipped: "Skipped at its depth limit"};
const LEVEL_NAMES = {life: "Life", year: "Year", season: "Season", month: "Month", week: "Week", day: "Day",
                     hour: "Hour", min15: "15 minutes", min5: "5 minutes", min1: "1 minute", sec30: "30 seconds"};

const when = iso => iso.replace("T00:00:00", "").replace("T", " ");

function pressures(list, outcomes, diverged = new Set()) {
  if (!list.length) return `<div class="meta">No pressures.</div>`;
  const words = {met: "met", avoided: "avoided", didnt_arise: "didn't arise"};
  return list.map(pressure => {
    const outcome = outcomes?.get(pressure.id);
    return `<div>${esc(pressure.text)} <span class="${diverged.has(pressure.id) ? "diverged" : "meta"}">${Math.round(pressure.odds * 100)}% odds${outcome ? `, ${words[outcome]}` : ""}</span></div>`;
  }).join("");
}

function planAndActual(detail, written) {
  const {opening} = detail;
  const closing = written ? detail.closing : null;
  const outcomes = closing && new Map(closing.pressures.map(pressure => [pressure.id, pressure.outcome]));
  const plan = opening ? `<div>${esc(opening.setting)}</div>${opening.exogenous.map(text => `<div>Event: ${esc(text)}</div>`).join("")}${pressures(opening.pressures)}` : `<div class="meta">Not written.</div>`;
  const actual = closing ? `<div>${esc(closing.what_happened)}</div>${opening ? pressures(opening.pressures, outcomes, new Set(detail.divergences.map(item => item.id))) : ""}${closing.choices.map(choice => `<div>Chose ${esc(choice.verb)} (${esc(choice.stance)})</div>`).join("")}` : `<div class="meta">Not closed yet.</div>`;
  return `<div class="plan-actual"><div><div class="eyebrow">Plan</div>${plan}</div><div><div class="eyebrow">Actual</div>${actual}</div></div>
    <details class="raw"><summary>Raw data</summary><pre>${esc(JSON.stringify(detail, null, 2))}</pre></details>`;
}

// Empty if there's no node to describe yet.
export function inspectorMarkup(model, calendar, id, detail, pinned) {
  const slot = calendar.slots.get(id);
  const node = model.nodes.get(id);
  const source = slot ?? node;
  if (!source) return "";
  const status = node?.status ?? "ghost";
  const path = calendar.pathTo(id, model);
  const crumbs = path.slice(0, -1).map(step => `<button type="button" class="crumb" data-id="${esc(step)}">${esc((calendar.slots.get(step) ?? model.nodes.get(step)).label)}</button>`).join("");
  const age = source.age !== undefined ? `Age ${source.age}. ` : "";
  const button = (action, text) => `<button type="button" data-action="${action}">${text}</button>`;
  const actions = status === "closed" ? button("fork", "Fork from here") : status === "ghost" && pinned ? button("until", "Run until here") : "";
  const summary = node?.summary ?? "Nothing is written here until the agent arrives.";
  return `${crumbs ? `<nav id="crumbs" aria-label="Path">${crumbs}</nav>` : ""}
    <article class="subject">
      <div class="eyebrow ruled">${LEVEL_NAMES[source.level]}</div>
      <h2>${esc(source.label)}</h2>
      <div class="meta">${age}${when(source.start)}. ${STATUS[status]}.</div>
      <p>${esc(summary)}</p>
      ${actions ? `<div class="actions">${actions}</div>` : ""}
    </article>
    ${detail ? planAndActual(detail, status === "closed") : ""}`;
}

// What the tree's tooltip says about a node.
export function describeHover(model, position) {
  const {slot, status} = position;
  if (slot.level === "stage") {
    const written = slot.group.filter(year => model.nodes.get(year.id)?.status === "closed").length;
    return {label: slot.label, meta: "Stage", summary: `${written} of ${slot.group.length} years written.`};
  }
  const summary = model.nodes.get(slot.id)?.summary ?? "Nothing is written here yet.";
  return {label: slot.label, meta: `${LEVEL_NAMES[slot.level]}, age ${slot.age}. ${STATUS[status]}.`, summary};
}

function eventLine(event) {
  const data = event.data;
  if (event.type === "node_opened") return `Opened ${event.label}`;
  if (event.type === "node_closed") return `Closed ${LEVEL_NAMES[event.id.split(":")[0]].toLowerCase()}, ${when(event.id.slice(event.id.indexOf(":") + 1))}`;
  if (event.type === "choice_point") return `Choice of ${event.options.join(", ")}`;
  if (event.type === "agent_action") return `Chose ${event.verb} (${event.stance})`;
  if (event.type === "node_escalated") return `Went finer, to ${LEVEL_NAMES[event.to].toLowerCase()}`;
  if (event.kind === "moved") return `Moved to ${data.place}`;
  if (event.kind === "person_met") return `Met ${data.name}`;
  if (event.kind === "relationship_changed") return `${data.name}: ${data.delta > 0 ? "closer" : "more distant"}`;
  if (event.kind === "money_changed") return `Money ${data.delta > 0 ? "+" : ""}${data.delta}`;
  if (event.kind === "skill_changed") return `Skill ${data.skill} +${data.delta}`;
  return event.kind ?? event.type;
}

export function logMarkup(model) {
  return [...model.recent].reverse().map(event => `<button type="button" class="log-line" data-id="${esc(event.id)}">#${event.seq} ${esc(eventLine(event))}</button>`).join("");
}

