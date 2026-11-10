// The stack of time rulers. Each row shows the children of one node on the path, and fits them to the full width.
import {STAGE_COLORS} from "./layout.js";
import {cursorOf, depth, statusOf} from "./model.js";

const ROW_NAMES = {year: "Year", season: "Season", month: "Month", week: "Week", day: "Day", hour: "Hour",
                   min15: "15 min", min5: "5 min", min1: "1 min", sec30: "30 sec"};
const CHAR_WIDTH = 7.4, CELL_MARGIN = 6;
export const ROW_COUNT = 1 + Object.keys(ROW_NAMES).length;

export const esc = text => String(text ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
const span = slot => new Date(slot.end) - new Date(slot.start);

export class Calendar {
  constructor(boot) {
    this.life = boot.life;
    this.hubs = boot.hubs;
    this.children = new Map();
    this.slots = new Map([[boot.life.id, boot.life]]);
    this.add(boot.children);
  }

  add(table) {
    for (const [id, kids] of Object.entries(table)) {
      this.children.set(id, kids);
      kids.forEach(kid => this.slots.set(kid.id, kid));
    }
  }

  // The log knows a written node's parents even before its calendar slots have loaded.
  pathTo(id, model) {
    const path = [];
    for (let at = id; at;) {
      const slot = this.slots.get(at);
      const node = model.nodes.get(at);
      if (!slot && !node) break;
      path.unshift(at);
      at = slot ? slot.parent : node.parent;
    }
    return path;
  }
}

// Below a chosen node the path keeps going, so the rows are never empty: into the agent's child, else the deepest written.
function continuePath(model, calendar, path, agentPath, missing) {
  const onAgent = new Set(agentPath);
  const rank = kid => (onAgent.has(kid.id) ? 100 : 0) + (model.deepest.get(kid.id) ?? -1) + (model.nodes.has(kid.id) ? 1 : 0);
  let slot = calendar.slots.get(path.at(-1));
  while (slot && depth(slot.level) < depth("min1")) {
    const kids = calendar.children.get(slot.id);
    if (!kids) { missing.add(slot.id); break; }
    if (!kids.length) break;
    slot = kids.reduce((best, kid) => rank(kid) > rank(best) ? kid : best);
    path.push(slot.id);
  }
}

// The longest form of a label that fits in the cell, or nothing.
function fitLabel(slot, width) {
  const label = slot.label;
  const forms = slot.level === "year"
    ? [label.replace(/^(Age|Grade) /, "").replace("Kindergarten", "K").replace("College ", "C").replace("Postgrad ", "P")]
    : slot.level === "hour" ? [label, label.slice(0, 2)]
    : slot.level === "stage" ? [label, label.split(" ")[0], `${label.slice(0, 5)}.`]
    : [label, label.replace(/ \d{4}$/, ""), label.replace(/ \d{4}$/, "").replace("Week of ", "").replace(/^\w{3} /, "")];
  return forms.find(form => form.length * CHAR_WIDTH + CELL_MARGIN <= width) ?? "";
}

function rowMarkup(name, cells) {
  return `<div class="row-name eyebrow">${name}</div><div class="cells">${cells.join("")}</div>`;
}

function cellMarkup(id, text, title, classes, weight, stage) {
  return `<button type="button" data-id="${esc(id)}" class="cell ${classes}" style="flex-grow:${weight};--stage:${STAGE_COLORS[stage]}" title="${esc(title)}">${esc(text)}</button>`;
}

function funnelMarkup(from, to) {
  return `<svg viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true"><path d="M${from} 0L0 10M${to} 0L100 10"/></svg>`;
}

// Returns the rows and the funnels between them as HTML, the full path being shown, and any calendar slots still to load.
export function buildRulers(model, calendar, pinned, width) {
  const missing = new Set();
  const cursor = cursorOf(model);
  const agentPath = cursor ? calendar.pathTo(cursor, model) : [];
  const path = pinned ? calendar.pathTo(pinned, model) : agentPath.length ? [...agentPath] : [calendar.life.id];
  if (pinned) continuePath(model, calendar, path, agentPath, missing);
  const onAgent = new Set(agentPath), onPath = new Set(path), focus = pinned ?? cursor;
  const classes = (id, status) => [status, onPath.has(id) ? "on-path" : "", onAgent.has(id) ? "agent" : "", id === focus ? "focus" : ""].join(" ");

  const rows = [], funnels = [];
  const lifeNode = model.nodes.get(calendar.life.id);
  const lifeStatus = lifeNode?.status ?? "ghost";
  const years = calendar.children.get(calendar.life.id);
  const yearStatus = year => statusOf(model, year, lifeStatus, lifeNode);
  const total = years.reduce((sum, year) => sum + span(year), 0);

  // The stages bracket the years on the same scale. Choosing one looks at its first year.
  rows.push(rowMarkup("Stage", calendar.hubs.map((hub, i) => {
    const group = years.filter(year => year.hub === i);
    const statuses = group.map(yearStatus);
    const status = statuses.every(item => item === "closed") ? "closed" : statuses.some(item => item !== "ghost") ? "open" : "ghost";
    const weight = group.reduce((sum, year) => sum + span(year), 0);
    const text = fitLabel({level: "stage", label: hub.name}, width * weight / total);
    const active = group.some(year => onPath.has(year.id));
    return cellMarkup(group[0].id, text, hub.name, `ticked ${status === "open" ? "ghost" : status} ${active ? "on-path" : ""}`, weight, i);
  })));
  funnels.push("");

  let parentStatus = lifeStatus;
  for (const [i, id] of path.entries()) {
    const kids = calendar.children.get(id);
    if (!kids) { missing.add(id); break; }
    // The finest level has no children, so the stack ends there.
    if (!kids.length) break;
    const parentNode = model.nodes.get(id);
    const statuses = kids.map(kid => statusOf(model, kid, parentStatus, parentNode));
    const sum = kids.reduce((all, kid) => all + span(kid), 0);
    rows.push(rowMarkup(ROW_NAMES[kids[0].level], kids.map((kid, k) =>
      cellMarkup(kid.id, fitLabel(kid, width * span(kid) / sum), `${kid.label}, ${statuses[k]}`, classes(kid.id, statuses[k]), span(kid), kid.hub ?? calendar.slots.get(path[1])?.hub))));
    // The lines between this row and the next start at the edges of the cell the next row zooms into.
    const next = kids.findIndex(kid => kid.id === path[i + 1]);
    if (next < 0) { funnels.push(""); break; }
    const before = kids.slice(0, next).reduce((all, kid) => all + span(kid), 0);
    funnels.push(funnelMarkup(+(100 * before / sum).toFixed(3), +(100 * (before + span(kids[next])) / sum).toFixed(3)));
    parentStatus = statuses[next];
  }
  return {rows, funnels, path, agentPath, missing};
}
