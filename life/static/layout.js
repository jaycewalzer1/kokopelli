// Turns the model and calendar into a scene of plain data. A node's position depends only on its calendar path.
import {depth, statusOf} from "./model.js";

// The years sweep three quarters of a circle, clockwise from the top. The last year lands exactly on the end.
const ARC = 1.5 * Math.PI, HUB_RING = 95, YEAR_RING = 175, STAGE_LABEL_RING = 305, SEASON_SHARE = 0.9, CHILD_GAP = 13;
const NODE_SIZE = {season: 4, month: 3.6, week: 3.2, day: 2.8, hour: 2.5, min15: 2.3, min5: 2.1, min1: 2, sec30: 1.8};
// When labels would overlap, the lowest rank stays: the Life node, the chosen path, stage names, the branch in view, then the years.
const RANK = {life: 0, chosen: 1, stage: 2, branch: 3, year: 4};
const PAGE = "var(--surface-100)", INK = "var(--ink)", MUTED = "var(--ink-muted)", HAIRLINE = "var(--hairline)";
// One color per stage, in DESIGN.md's fixed order. Clay is the action color and gold is the highlighted path, so neither is a stage.
export const STAGE_COLORS = ["var(--sage)", "var(--slate)", "var(--dust-rose)", "var(--walnut)"];

// Rings get closer together further out, so eleven levels fit on one screen.
const ringRadius = level => YEAR_RING + 250 * Math.log(1 + (depth(level) - depth("year")) * 0.43);
const at = (r, angle) => [+(r * Math.cos(angle)).toFixed(2), +(r * Math.sin(angle)).toFixed(2)];
const yearAngle = (i, n) => -Math.PI / 2 + ARC * i / (n - 1);

function childAngle(slot, count, parentAngle, sector) {
  if (slot.level === "season") return parentAngle + (slot.index - (count - 1) / 2) * sector * SEASON_SHARE / count;
  return parentAngle + (slot.index - (count - 1) / 2) * CHILD_GAP / ringRadius(slot.level);
}

// A closed node that holds more below it gets one outward tick, longer the more it holds.
const tickLength = descendants => 6 + 3 * Math.log2(descendants + 1);

// A closed node is a solid dot in its stage's color, an open one an ink ring, and an unwritten one a faint ring.
function style(status, id, cursor, selected, onSelected, hovered, r, color) {
  let fill = PAGE, stroke = MUTED, sw = 0.7, dash = "";
  if (status === "closed") { fill = color; stroke = color; sw = 0.5; }
  else if (status === "open") { stroke = INK; sw = 1.8; }
  else if (status === "skipped") { stroke = HAIRLINE; dash = "0.8 1.8"; }
  if (id === cursor) { fill = INK; stroke = PAGE; sw = 1; }
  if (onSelected && !selected && status !== "open") { stroke = INK; sw = 1.6; }
  return {fill, stroke, sw, dash, halo: selected ? r + 6 : hovered ? r + 4 : 0};
}

const shortLabel = label => label.replace("Kindergarten", "K").replace("College ", "C").replace("Postgrad ", "PG ").replace("Grade ", "Gr ");

function polyline(path, positions) {
  const points = path.map(id => positions.get(id)).filter(Boolean).map(p => `${p.x} ${p.y}`);
  return points.length > 1 ? `M${points.join("L")}` : "";
}

// The display path to a node runs through its stage, which the calendar itself doesn't have.
function throughHub(path, calendar) {
  const year = calendar.slots.get(path[1]);
  return year ? [path[0], `hub:${year.hub}`, ...path.slice(1)] : path;
}

// viewPath is the branch the rulers are showing and agentPath is the agent's; both stay open in the tree.
export function buildScene(model, calendar, {selected, hover, viewPath, agentPath}) {
  const missing = new Set();
  const cursor = agentPath.at(-1) ?? null;
  const selPath = selected ? calendar.pathTo(selected, model) : [];
  const expanded = new Set([...viewPath, ...agentPath]);
  const onSel = new Set(selPath), labelled = new Set(viewPath);
  const nodes = [], labels = [], positions = new Map();
  const branches = calendar.hubs.map((hub, i) => ({color: STAGE_COLORS[i], spokes: "", ticks: ""}));
  const scene = {ghostSpokes: "", branches, nodes, labels, positions, missing, cursor};

  const life = calendar.life;
  const lifeNode = model.nodes.get(life.id);
  const lifeStatus = statusOf(model, life, null, null);
  const years = calendar.children.get(life.id);
  const anchorFor = angle => Math.cos(angle) >= 0 ? "start" : "end";
  const addNode = (id, status, x, y, r, slot, color) => {
    positions.set(id, {x, y, status, r, slot});
    nodes.push({id, x, y, r, ...style(status, id, cursor, id === selected, onSel.has(id), id === hover, r, color)});
  };
  const spoke = (x0, y0, x1, y1, status, hubIndex) => {
    const line = `M${x0} ${y0}L${x1} ${y1}`;
    if (status === "open" || status === "closed") branches[hubIndex].spokes += line; else scene.ghostSpokes += line;
  };

  const visit = (slot, status, angle, parentXY, sector, hubIndex) => {
    const r = ringRadius(slot.level);
    const [x, y] = at(r, angle);
    spoke(parentXY[0], parentXY[1], x, y, status, hubIndex);
    const size = slot.level === "year" ? (status === "open" ? 6.5 : 4.5) : NODE_SIZE[slot.level];
    addNode(slot.id, status, x, y, slot.id === cursor ? size + 1.2 : size, slot, STAGE_COLORS[hubIndex]);
    if (slot.level === "year" || (labelled.has(slot.id) && slot.level !== "sec30")) {
      const [lx, ly] = at(r + (slot.level === "year" ? 9 : 7), angle);
      const rank = onSel.has(slot.id) ? RANK.chosen : labelled.has(slot.id) ? RANK.branch : RANK.year;
      // Within a rank, coarser levels win, since they say more about where the branch is.
      labels.push({x: lx, y: ly, text: shortLabel(slot.label), anchor: anchorFor(angle), size: 13, rank: rank + depth(slot.level) / 100,
                   color: onSel.has(slot.id) ? INK : MUTED, weight: onSel.has(slot.id) ? 500 : 400});
    }
    // Only the agent itself ever shows a 30 second tick.
    const pastMinute = slot.level === "min1" && !agentPath.includes(slot.id);
    if (slot.level === "year" || (expanded.has(slot.id) && !pastMinute)) {
      const kids = calendar.children.get(slot.id);
      if (!kids) { missing.add(slot.id); return; }
      const parentNode = model.nodes.get(slot.id);
      for (const kid of kids) {
        visit(kid, statusOf(model, kid, status, parentNode), childAngle(kid, kids.length, angle, sector), [x, y], sector, hubIndex);
      }
    } else if (status === "closed" && model.descendants.get(slot.id) > 1) {
      const [ex, ey] = at(r + tickLength(model.descendants.get(slot.id)), angle);
      branches[hubIndex].ticks += `M${x} ${y}L${ex} ${ey}`;
    }
  };

  calendar.hubs.forEach((hub, i) => {
    const group = years.filter(year => year.hub === i);
    if (!group.length) return;
    const angle = yearAngle((group[0].index + group.at(-1).index) / 2, years.length);
    const [hx, hy] = at(HUB_RING, angle);
    const statuses = group.map(year => statusOf(model, year, lifeStatus, lifeNode));
    const status = statuses.every(item => item === "closed") ? "closed" : statuses.some(item => item === "open" || item === "closed") ? "open" : "ghost";
    spoke(0, 0, hx, hy, status, i);
    addNode(`hub:${i}`, status, hx, hy, status === "open" ? 8 : 7, {label: hub.name, level: "stage", group}, STAGE_COLORS[i]);
    // Outside the ring, where there's room, so each name labels its whole sector.
    const [lx, ly] = at(STAGE_LABEL_RING, angle);
    labels.push({x: lx, y: ly, text: hub.name, anchor: anchorFor(angle), size: 14, weight: 500, color: INK, rank: RANK.stage});
    group.forEach((year, k) => visit(year, statuses[k], yearAngle(year.index, years.length), [hx, hy], ARC / (years.length - 1), i));
  });

  addNode(life.id, lifeStatus, 0, 0, 13, life, INK);
  labels.push({x: 0, y: 0, text: "Life", anchor: "middle", size: 13, weight: 500, color: life.id === cursor ? PAGE : INK, onNode: true, rank: RANK.life});

  scene.highlight = polyline(throughHub(viewPath, calendar), positions);
  scene.liveLine = polyline(throughHub(agentPath, calendar), positions);
  scene.hoverLine = hover && hover !== selected && !hover.startsWith("hub:") ? polyline(throughHub(calendar.pathTo(hover, model), calendar), positions) : "";
  return scene;
}
