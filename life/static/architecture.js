// The architecture view. A chart of the system from life/architecture.py, where only what was just measured moves. Nothing here can change a run.
const $ = id => document.getElementById(id);
const POLL_MS = 2000, NS = "http://www.w3.org/2000/svg";
const NODE_H = 74, ROW_GAP = 46, LANE_H = 40, NARROW_BELOW = 720, COLUMNS = 5, COLUMN_GAP = 60, NARROW_GAP = 24, STEP = 6, CUT = 7, TEXT_X = 8;
const TOKEN_SPEED = 130, MOST_TOKENS = 6, HOP_MS = 700;
const calm = matchMedia("(prefers-reduced-motion: reduce)");
const ui = {catalog: null, data: null, counts: null, uiVersion: null, width: 0, selected: new URLSearchParams(location.hash.slice(1)).get("part"), hovered: null, tokens: [], nodes: {}, edges: [], frame: null};

const escapeHtml = text => String(text).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

function shape(parent, name, attributes = {}, text = null) {
  const element = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  if (text !== null) element.textContent = text;
  parent.appendChild(element);
  return element;
}

// Where every part sits. The desktop grid comes from the catalog; a narrow screen stacks each lane in two columns.
function layOut(width) {
  const {lanes, nodes} = ui.catalog;
  const narrow = width < NARROW_BELOW;
  const columns = narrow ? 2 : COLUMNS, gap = narrow ? NARROW_GAP : Math.max(COLUMN_GAP, width * .08);
  const nodeW = (width - gap * (columns - 1)) / columns;
  const cells = {};
  const laneOf = row => lanes.findIndex(lane => row >= lane.rows[0] && row <= lane.rows[1]);
  if (narrow) {
    let row = 0;
    lanes.forEach((lane, index) => {
      const members = nodes.filter(node => laneOf(node.at[1]) === index).sort((a, b) => a.at[1] - b.at[1] || a.at[0] - b.at[0]);
      members.forEach((node, i) => { cells[node.id] = [i % 2, row + Math.floor(i / 2)]; });
      row += Math.ceil(members.length / 2);
    });
  } else {
    for (const node of nodes) cells[node.id] = node.at;
  }
  // A lane's name sits just above its first row, and the gap above that stays free for routes.
  const firstRows = narrow ? lanes.map((lane, index) => Math.min(...nodes.filter(node => laneOf(node.at[1]) === index).map(node => cells[node.id][1]))) : lanes.map(lane => lane.rows[0]);
  const lastRow = Math.max(...Object.values(cells).map(cell => cell[1]));
  const rowTop = [];
  let y = 0;
  for (let row = 0; row <= lastRow; row++) {
    if (firstRows.includes(row)) y += LANE_H;
    rowTop[row] = y;
    y += NODE_H + ROW_GAP;
  }
  return {narrow, nodeW, gap, cells, rowTop, firstRows, height: y - ROW_GAP + 2, left: col => col * (nodeW + gap)};
}

// Where a port is on a part: a side and how far along it.
function port(rect, spec) {
  const side = spec[0], along = parseFloat(spec.slice(1));
  if (side === "l") return [rect.x, rect.y + along * NODE_H];
  if (side === "r") return [rect.x + rect.w, rect.y + along * NODE_H];
  if (side === "t") return [rect.x + along * rect.w, rect.y];
  return [rect.x + along * rect.w, rect.y + NODE_H];
}

function defaultPorts(from, to) {
  if (from.y === to.y) return from.x < to.x ? ["r.5", "l.5"] : ["l.5", "r.5"];
  return from.y < to.y ? ["b.5", "t.5"] : ["t.5", "b.5"];
}

// An orthogonal path through the gaps the catalog names. Each turn is square, like everything else here.
function routePoints(edge, from, to, layout) {
  const [defaultOut, defaultIn] = defaultPorts(from, to);
  const start = port(from, layout.narrow ? defaultOut : edge.out ?? defaultOut);
  const end = port(to, layout.narrow ? defaultIn : edge.in ?? defaultIn);
  const points = [start];
  for (const token of layout.narrow ? [] : edge.route ?? []) {
    const [whole, fraction] = token.slice(1).split(".");
    const share = parseFloat(`0.${fraction}`), last = points.at(-1);
    if (token[0] === "x") points.push([layout.left(+whole) + layout.nodeW + share * layout.gap, last[1]]);
    else points.push([last[0], layout.rowTop[+whole] + NODE_H + share * ROW_GAP]);
  }
  const last = points.at(-1);
  if (last[0] !== end[0] && last[1] !== end[1]) {
    const entersFromSide = "lr".includes((edge.in ?? defaultIn)[0]);
    points.push(entersFromSide && !layout.narrow ? [last[0], end[1]] : [end[0], last[1]]);
  }
  points.push(end);
  return points;
}

const pathOf = points => points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join("");

function fit(element, text, room) {
  element.textContent = text;
  if (element.getComputedTextLength() <= room) return;
  let kept = text;
  while (kept.length > 1 && element.getComputedTextLength() > room) {
    kept = kept.slice(0, -1);
    element.textContent = `${kept.trimEnd()}…`;
  }
}

// Text on as many lines as it needs, up to a limit, breaking after a space or a hyphen. Returns where the next line goes.
function wrap(parent, className, text, x, y, step, room, most) {
  const line = shape(parent, "text", {class: className, x, y});
  const words = text.match(/[^\s-]+-?\s*/g) ?? [text];
  let lines = 0;
  while (words.length) {
    let kept = words.shift();
    while (words.length && lines < most - 1) {
      line.textContent = kept + words[0];
      if (line.getComputedTextLength() > room) break;
      kept += words.shift();
    }
    if (lines === most - 1) { kept += words.join(""); words.length = 0; }
    const row = lines ? shape(parent, "text", {class: className, x, y: y + lines * step}) : line;
    fit(row, kept.trim(), room);
    lines++;
  }
  return y + lines * step;
}

// A part's outline says what kind of thing it is: stepped corners for a model, two cut corners for an input or output, and plain for the rest. Stored data adds a rule across the top, like the lid of a cylinder.
function outline(kind, w, h, inset = .5) {
  const a = inset, r = w - inset, b = h - inset;
  if (kind === "model") return `M${a + STEP} ${a}H${r - STEP}V${a + STEP}H${r}V${b - STEP}H${r - STEP}V${b}H${a + STEP}V${b - STEP}H${a}V${a + STEP}H${a + STEP}Z`;
  if (kind === "io") return `M${a + CUT} ${a}H${r}V${b - CUT}L${r - CUT} ${b}H${a}V${a + CUT}Z`;
  return `M${a} ${a}H${r}V${b}H${a}Z`;
}

function drawKindMarks(parent, kind, w) {
  if (kind === "data") shape(parent, "path", {class: `lid k-${kind}`, d: `M0 5.5H${w}`});
  shape(parent, "rect", {class: `tick k-${kind}`, x: 0, y: 8, width: 4, height: 13});
}

function drawKindKey() {
  $("kind-key").replaceChildren();
  for (const [kind, name] of Object.entries(ui.catalog.kinds)) {
    const entry = document.createElement("span");
    const icon = shape(entry, "svg", {width: 34, height: 22, "aria-hidden": "true"});
    shape(icon, "path", {class: "box s-built", d: outline(kind, 34, 22)});
    drawKindMarks(icon, kind, 34);
    entry.append(name);
    $("kind-key").append(entry);
  }
}

function drawLaneRules(svg, layout, width) {
  ui.catalog.lanes.forEach((lane, index) => {
    if (index) shape(svg, "path", {class: "lane-rule", d: `M0 ${layout.rowTop[layout.firstRows[index]] - LANE_H + .5}H${width}`});
  });
}

// Lane names go over the lines, so a line passing behind one never strikes through it.
function drawLaneNames(svg, layout) {
  return ui.catalog.lanes.map((lane, index) => {
    const y = layout.rowTop[layout.firstRows[index]] - LANE_H + 22;
    const back = shape(svg, "rect", {class: "lane-back", x: 0, y: y - 12, height: 16});
    const name = shape(svg, "text", {class: "lane-name", x: 0, y}, lane.name);
    const width = name.getComputedTextLength() + 6;
    back.setAttribute("width", width);
    return {x0: 0, x1: width, y0: y - 12, y1: y + 4};
  });
}

const touches = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
const stretchBox = ([a, b]) => ({x0: Math.min(a[0], b[0]) - 1, x1: Math.max(a[0], b[0]) + 1, y0: Math.min(a[1], b[1]) - 1, y1: Math.max(a[1], b[1]) + 1});

// Where a label sits clear of parts, other lines and other labels. A flat line has it above; an upright line has it beside, on either side.
function placeLabel(text, routed, placed, layout) {
  const {points, stretches, edge} = routed;
  const width = text.getComputedTextLength();
  const fixed = !layout.narrow && edge.label_at ? [{i: edge.label_at[0], along: edge.label_at[1]}] : [];
  const longest = stretches.reduce((best, stretch, i) => stretch[2] > stretches[best][2] ? i : best, 0);
  const order = [longest, ...stretches.keys()].filter((i, at, all) => all.indexOf(i) === at);
  const tries = [...fixed, ...order.flatMap(i => [.5, .3, .7, .2, .8, .12, .88].map(along => ({i, along})))];
  const foreign = placed.lines.filter(line => line.owner !== routed);
  const inRoom = box => box.x0 >= 0 && box.x1 <= ui.width;
  const free = box => inRoom(box) && !placed.solid.some(other => touches(box, other)) && !foreign.some(line => touches(box, line.box));
  for (const {i, along} of tries) {
    const [a, b, length] = stretches[i];
    const x = a[0] + (b[0] - a[0]) * along, y = a[1] + (b[1] - a[1]) * along;
    if (a[1] === b[1]) {
      if (length < width + 7) continue;
      const box = {x0: x - width / 2 - 1, x1: x + width / 2 + 1, y0: y - 15, y1: y - 2};
      const far = b[0] > a[0] ? box.x1 <= b[0] - 5 && box.x0 >= a[0] : box.x0 >= b[0] + 5 && box.x1 <= a[0];
      if (far && free(box)) return {x, y: y - 5, anchor: "middle", box};
    } else {
      for (const side of [1, -1]) {
        const box = side > 0 ? {x0: x + 3, x1: x + 7 + width, y0: y - 8, y1: y + 7} : {x0: x - 7 - width, x1: x - 3, y0: y - 8, y1: y + 7};
        if (free(box)) return {x: x + side * 5, y: y + 4, anchor: side > 0 ? "start" : "end", box};
      }
    }
  }
  // Nowhere is clear, so it goes on the longest stretch, and its halo breaks whatever line runs behind it.
  const [a, b, length] = stretches[fixed[0]?.i ?? longest];
  const along = fixed[0]?.along ?? .5;
  const x = a[0] + (b[0] - a[0]) * along, y = a[1] + (b[1] - a[1]) * along;
  if (a[1] !== b[1]) {
    const fits = x + 5 + width <= ui.width;
    return {x: fits ? x + 5 : x - 5, y: y + 4, anchor: fits ? "start" : "end", box: fits ? {x0: x + 3, x1: x + 7 + width, y0: y - 8, y1: y + 7} : {x0: x - 7 - width, x1: x - 3, y0: y - 8, y1: y + 7}};
  }
  return length > width + 2 ? {x, y: y - 5, anchor: "middle", box: {x0: x - width / 2, x1: x + width / 2, y0: y - 15, y1: y - 2}} : null;
}

function drawEdgeLabels(svg, routes, placed, layout) {
  for (const routed of routes) {
    const group = shape(svg, "g", {class: `edge s-${routed.edge.status}`});
    const label = shape(group, "text", {class: "edge-label"}, routed.edge.label);
    const spot = placeLabel(label, routed, placed, layout);
    routed.labelGroup = group;
    // A label with no room would sit on a part or a line. It's still listed in the side panel.
    if (!spot) { label.remove(); routed.dropped = true; continue; }
    label.setAttribute("x", spot.x);
    label.setAttribute("y", spot.y);
    label.setAttribute("text-anchor", spot.anchor);
    // Kept apart, so two labels side by side can't read as one.
    placed.solid.push({...spot.box, x0: spot.box.x0 - 8, x1: spot.box.x1 + 8});
  }
}

function drawEdges(svg, layout, rects) {
  ui.edges = [];
  for (const edge of ui.catalog.edges) {
    const from = rects[edge.from], to = rects[edge.to];
    let shown = true;
    if (layout.narrow) {
      const [a, b] = [layout.cells[edge.from], layout.cells[edge.to]];
      shown = Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) === 1;
    }
    if (!shown) { ui.edges.push({edge}); continue; }
    const points = routePoints(edge, from, to, layout);
    const group = shape(svg, "g", {class: `edge s-${edge.status}`});
    const line = shape(group, "path", {class: "edge-line", d: pathOf(points), "marker-end": "url(#arrow)"});
    shape(group, "path", {class: "edge-flow", d: pathOf(points)});
    const stretches = points.slice(1).map((point, i) => [points[i], point, Math.abs(point[0] - points[i][0]) + Math.abs(point[1] - points[i][1])]).filter(stretch => stretch[2] > 0);
    ui.edges.push({edge, group, line, points, stretches});
  }
  return ui.edges.filter(routed => routed.group);
}

function drawNodes(svg, layout, rects) {
  ui.nodes = {};
  const {statuses} = ui.catalog;
  for (const node of ui.catalog.nodes) {
    const rect = rects[node.id], room = rect.w - TEXT_X - 4;
    const group = shape(svg, "g", {class: `node s-${node.status}`, tabindex: 0, role: "button", transform: `translate(${rect.x} ${rect.y})`});
    shape(group, "path", {class: `box s-${node.status}`, d: outline(node.kind, rect.w, NODE_H)});
    if (node.status === "unproven") shape(group, "path", {class: "inner", d: outline(node.kind, rect.w, NODE_H, 3.5)});
    drawKindMarks(group, node.kind, rect.w);
    // Four lines fit, so a name on two lines leaves the status one.
    const statusAt = wrap(group, "node-name", node.name, TEXT_X, 20, 16, room, 2);
    const liveAt = wrap(group, "node-status", statuses[node.status], TEXT_X, statusAt, 14, room, statusAt > 36 ? 1 : 2);
    const live = shape(group, "text", {class: "node-live", x: TEXT_X, y: liveAt + 1});
    shape(group, "rect", {class: "mark", x: rect.w - 14, y: NODE_H - 16, width: 6, height: 6});
    group.addEventListener("click", () => select(node.id));
    group.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(node.id); } });
    group.addEventListener("pointerenter", () => { ui.hovered = node.id; drawDetails(); });
    group.addEventListener("pointerleave", () => { ui.hovered = null; drawDetails(); });
    ui.nodes[node.id] = {group, live, room};
  }
}

function drawChart() {
  const width = Math.floor($("chart").getBoundingClientRect().width);
  if (!width) return;
  ui.width = width;
  ui.tokens.forEach(token => token.element.remove());
  ui.tokens = [];
  const layout = layOut(width), svg = $("diagram");
  svg.replaceChildren();
  svg.setAttribute("width", width);
  svg.setAttribute("height", layout.height);
  svg.setAttribute("viewBox", `0 0 ${width} ${layout.height}`);
  const defs = shape(svg, "defs");
  const marker = shape(defs, "marker", {id: "arrow", viewBox: "0 0 8 8", refX: 7.5, refY: 4, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse", markerUnits: "userSpaceOnUse"});
  shape(marker, "path", {class: "arrow", d: "M0 .5L7.5 4L0 7.5Z"});
  const liveMarker = shape(defs, "marker", {id: "arrow-live", viewBox: "0 0 8 8", refX: 7.5, refY: 4, markerWidth: 8, markerHeight: 8, orient: "auto-start-reverse", markerUnits: "userSpaceOnUse"});
  shape(liveMarker, "path", {class: "arrow live", d: "M0 .5L7.5 4L0 7.5Z"});
  const rects = {};
  for (const [id, [col, row]] of Object.entries(layout.cells)) rects[id] = {x: layout.left(col), y: layout.rowTop[row], w: layout.nodeW};
  drawLaneRules(svg, layout, width);
  const routes = drawEdges(svg, layout, rects);
  const laneNames = drawLaneNames(svg, layout);
  const partBoxes = Object.values(rects).map(rect => ({x0: rect.x - 2, x1: rect.x + rect.w + 2, y0: rect.y - 2, y1: rect.y + NODE_H + 2}));
  const lines = routes.flatMap(routed => routed.stretches.map(stretch => ({owner: routed, box: stretchBox(stretch)})));
  const laneRules = ui.catalog.lanes.map((lane, index) => layout.rowTop[layout.firstRows[index]] - LANE_H).map(y => ({x0: 0, x1: width, y0: y - 1, y1: y + 2}));
  drawEdgeLabels(svg, routes, {solid: [...partBoxes, ...laneNames, ...laneRules], lines}, layout);
  drawNodes(svg, layout, rects);
  $("chart-note").hidden = !layout.narrow;
  if (ui.data) drawLive();
  markSelected();
}

// Applies what was just measured. An edge moves only while one of its flags is true.
function drawLive() {
  const {flags, live, active_nodes: atWork} = ui.data;
  for (const {edge, group, line, labelGroup} of ui.edges) {
    if (!group) continue;
    const active = (edge.active ?? []).some(key => flags[key]);
    group.classList.toggle("active", active);
    labelGroup.classList.toggle("active", active);
    line.setAttribute("marker-end", active ? "url(#arrow-live)" : "url(#arrow)");
  }
  for (const node of ui.catalog.nodes) {
    const {group, live: line, room} = ui.nodes[node.id];
    const short = live[node.id]?.short ?? "";
    fit(line, short, atWork.includes(node.id) ? room - 12 : room);
    group.classList.toggle("at-work", atWork.includes(node.id));
    group.setAttribute("aria-label", `${node.name}. ${ui.catalog.kinds[node.kind]}. ${ui.catalog.statuses[node.status]}. ${short}`);
  }
}

// A count went up since the last poll, so a row really was written: one token per row, up to a limit.
function sendTokens(counts) {
  const previous = ui.counts;
  ui.counts = counts;
  if (!previous) return;
  for (const {edge, line} of ui.edges) {
    const grown = Math.max(0, ...(edge.pulse ?? []).map(key => (counts[key] ?? 0) - (previous[key] ?? 0)));
    if (!grown || !(edge.active ?? []).some(key => ui.data.flags[key])) continue;
    for (let i = 0; i < Math.min(grown, MOST_TOKENS); i++) launch(edge, line, performance.now() + (edge.hop ?? 0) * HOP_MS + i * 220);
  }
}

function launch(edge, line, startAt) {
  // With reduced motion, or on a screen that doesn't draw this link, the part it arrives at marks it instead.
  if (calm.matches || !line) return setTimeout(() => flash(edge.to), Math.max(0, startAt - performance.now()));
  const element = shape($("diagram"), "rect", {class: "token", width: 6, height: 6, x: -9, y: -9});
  const length = line.getTotalLength();
  ui.tokens.push({element, line, length, startAt, duration: Math.max(500, length / TOKEN_SPEED * 1000), to: edge.to});
  if (!ui.frame) ui.frame = requestAnimationFrame(moveTokens);
}

function moveTokens(now) {
  ui.tokens = ui.tokens.filter(token => {
    const progress = (now - token.startAt) / token.duration;
    if (progress < 0) return true;
    if (progress >= 1) { token.element.remove(); flash(token.to); return false; }
    const point = token.line.getPointAtLength(progress * token.length);
    token.element.setAttribute("x", point.x - 3);
    token.element.setAttribute("y", point.y - 3);
    return true;
  });
  ui.frame = ui.tokens.length ? requestAnimationFrame(moveTokens) : null;
}

function flash(id) {
  const group = ui.nodes[id]?.group;
  if (!group) return;
  group.classList.add("hit");
  setTimeout(() => group.classList.remove("hit"), 400);
}

const planText = plan => plan.split(", ").map(section => `${section} ${ui.catalog.sections[section]}`).join(", ");
const nodeById = id => ui.catalog.nodes.find(node => node.id === id);

function linkMarkup(edge, other) {
  const moving = (edge.active ?? []).some(key => ui.data?.flags[key]);
  return `<button type="button" class="part-link" data-part="${other.id}">${escapeHtml(other.name)} <small>${escapeHtml(edge.label)}${moving ? ", in use now" : edge.status === "planned" ? ", planned" : ""}</small></button>`;
}

function detailsMarkup(node) {
  const {statuses, kinds, edges} = ui.catalog;
  const live = ui.data?.live[node.id];
  const incoming = edges.filter(edge => edge.to === node.id), outgoing = edges.filter(edge => edge.from === node.id);
  const links = (title, rows, end) => rows.length ? `<div><div class="eyebrow ruled">${title}</div><div class="links">${rows.map(edge => linkMarkup(edge, nodeById(edge[end]))).join("")}</div></div>` : "";
  return `<div class="subject"><h2>${escapeHtml(node.name)}</h2><div class="status-tag">${escapeHtml(statuses[node.status])}</div><div class="status-tag"><i class="k-${node.kind}"></i>${escapeHtml(kinds[node.kind])}</div></div>
    <div><p class="detail">${escapeHtml(node.does)}</p></div>
    <div><div class="eyebrow ruled">Why this status</div><p class="detail">${escapeHtml(node.why)}</p></div>
    ${live?.lines.length ? `<div><div class="eyebrow ruled">Live</div>${live.lines.map(line => `<p class="detail">${escapeHtml(line)}</p>`).join("")}</div>` : ""}
    ${links("Takes in", incoming, "from")}${links("Sends out", outgoing, "to")}
    ${node.files.length ? `<div><div class="eyebrow ruled">Code</div><ul class="paths">${node.files.map(path => `<li>${escapeHtml(path)}</li>`).join("")}</ul></div>` : ""}
    ${node.branch_files?.length ? `<div><div class="eyebrow ruled">Code on a branch, not merged</div><ul class="paths">${node.branch_files.map(path => `<li>${escapeHtml(path.replace(".claude/worktrees/", ""))}</li>`).join("")}</ul></div>` : ""}
    ${node.plan ? `<div><div class="eyebrow ruled">Plan</div><p class="detail">${escapeHtml(planText(node.plan))}</p></div>` : ""}
    ${ui.selected === node.id ? `<div><button type="button" class="part-link" data-part="">Back to the overview</button></div>` : ""}`;
}

function overviewMarkup() {
  const {nodes, statuses} = ui.catalog;
  const running = ui.data?.running ?? [];
  const tally = Object.entries(statuses).map(([status, name]) => `<span>${nodes.filter(node => node.status === status).length}</span><span>${escapeHtml(name)}</span>`).join("");
  const list = status => nodes.filter(node => node.status === status).map(node => `<button type="button" class="part-link" data-part="${node.id}">${escapeHtml(node.name)}</button>`).join("");
  return `<div><div class="eyebrow ruled">Running now</div>${running.length ? running.map(line => `<p class="detail">${escapeHtml(line)}</p>`).join("") : `<p class="detail muted">Nothing is running, so nothing moves.</p>`}</div>
    <div><div class="eyebrow ruled">${nodes.length} parts</div><div class="tally">${tally}</div></div>
    <div><div class="eyebrow ruled">Runs, but doesn't work yet</div><div class="links">${list("unproven")}</div></div>
    <div><div class="eyebrow ruled">Partly built</div><div class="links">${list("partial")}</div></div>
    <p class="detail muted">Hover or choose a part for what it does, why it has its status, and where its code is.</p>`;
}

function drawDetails() {
  const showing = ui.hovered ?? ui.selected;
  const node = showing && nodeById(showing);
  const key = `${showing}|${JSON.stringify(ui.data?.live[showing] ?? ui.data?.running ?? null)}|${JSON.stringify(ui.data?.flags ?? null)}|${ui.selected}`;
  if (key === ui.drawnDetails) return;
  ui.drawnDetails = key;
  $("inspector").innerHTML = node ? detailsMarkup(node) : overviewMarkup();
}

function markSelected() {
  for (const [id, {group}] of Object.entries(ui.nodes)) group.classList.toggle("selected", id === ui.selected);
}

function select(id, scroll = true) {
  ui.selected = id || null;
  ui.hovered = null;
  history.replaceState(null, "", ui.selected ? `#part=${encodeURIComponent(ui.selected)}` : location.pathname);
  markSelected();
  drawDetails();
  // Stacked on a phone, the details are far below the chart.
  if (scroll && ui.selected && innerWidth <= 900) $("inspector").scrollIntoView({block: "start"});
}

function drawStatus(running) {
  $("status-line").classList.toggle("live", running.length > 0);
  $("status-text").textContent = running.length ? `Running: ${running.join("; ")}` : "Nothing is running";
}

// With no measurement there's nothing to show moving, so a failed read stops everything.
function showUnreadable(message) {
  ui.data = {flags: {}, counts: {}, live: {}, active_nodes: [], running: []};
  ui.counts = null;
  drawLive();
  $("status-line").classList.remove("live");
  $("status-text").textContent = `Can't read the system: ${message}`;
}

async function poll() {
  try {
    const response = await fetch("/api/architecture");
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    if (ui.uiVersion !== null && body.ui_version !== ui.uiVersion) location.reload();
    ui.uiVersion = body.ui_version;
    if (!ui.catalog) { ui.catalog = body.catalog; drawKindKey(); drawChart(); }
    ui.data = body;
    drawLive();
    sendTokens(body.counts);
    drawDetails();
    drawStatus(body.running);
  } catch (error) {
    if (ui.catalog) showUnreadable(error.message);
    else $("status-text").textContent = `Can't read the system: ${error.message}`;
  }
}

$("inspector").addEventListener("click", event => {
  const link = event.target.closest("[data-part]");
  if (link) { ui.hovered = null; select(link.dataset.part, false); }
});
addEventListener("keydown", event => { if (event.key === "Escape") select(null); });
new ResizeObserver(() => {
  if (!ui.catalog) return;
  if (Math.floor($("chart").getBoundingClientRect().width) !== ui.width) drawChart();
}).observe($("chart"));
document.fonts?.ready.then(() => { if (ui.catalog) drawChart(); });
poll();
setInterval(poll, POLL_MS);
