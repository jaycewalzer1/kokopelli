// The city plan view: city/world.json drawn from above, one SVG unit to a meter, with the file's own checks beside it.
// It only reads. Changing the city means changing the file.
const $ = id => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";
const POLL_MS = 5000;
const LAYERS = [
  ["ground", "Parks, farms and courtyards", true],
  ["water", "Water", true],
  ["lanes", "Lanes and paths", true],
  ["buildings", "Buildings, shaded by height", true],
  ["canopy", "Canopy walk and sky bridges", true],
  ["places", "Places", true],
  ["labels", "Names", true],
  ["entrances", "Entrances", false],
  ["trees", "Street trees", false],
  ["furniture", "Street furniture", false],
];
const ui = {data: null, drawn: "", items: new Map(), pinned: null, view: null, layers: {}, flagged: new Set()};

const escapeHtml = text => String(text ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const words = text => String(text).replaceAll("_", " ");

function el(name, attrs = {}, parent) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  parent?.appendChild(node);
  return node;
}

function rect([x0, y0, x1, y1], attrs, parent) {
  return el("rect", {x: x0, y: y0, width: x1 - x0, height: y1 - y0, ...attrs}, parent);
}

// Everything you can point at is registered once, so the detail panel and the checks can find it by kind and id.
function hold(node, kind, item) {
  const key = `${kind}:${item.id}`;
  node.dataset.key = key;
  ui.items.set(key, {kind, item, node});
  return node;
}

function patterns(svg) {
  const defs = el("defs", {}, svg);
  const hatch = (id, cls, angle, gap) => {
    const pattern = el("pattern", {id, width: gap, height: gap, patternUnits: "userSpaceOnUse", patternTransform: `rotate(${angle})`}, defs);
    el("line", {x1: 0, y1: 0, x2: 0, y2: gap, class: cls}, pattern);
  };
  hatch("hatch-ground", "hatch-sage", 45, 4);
  hatch("hatch-farm", "hatch-sage", 0, 3);
  hatch("hatch-water", "hatch-slate", -45, 3);
  const dots = el("pattern", {id: "dots-forest", width: 5, height: 5, patternUnits: "userSpaceOnUse"}, defs);
  el("circle", {cx: 2.5, cy: 2.5, r: 1.1, class: "dot-sage"}, dots);
}

function draw(data) {
  const svg = $("plan-svg");
  svg.replaceChildren();
  ui.items.clear();
  const [width, height] = data.meta.size_m;
  ui.size = [width, height];
  patterns(svg);
  const layer = name => el("g", {class: `layer layer-${name}`, "data-layer": name}, svg);
  const g = Object.fromEntries(["ground", "lanes", "water", "buildings", "trees", "furniture", "entrances", "canopy", "places", "labels", "flags"].map(name => [name, layer(name)]));
  rect([0, 0, width, height], {class: "site"}, g.ground);

  const fills = {food_forest: "url(#dots-forest)", farm: "url(#hatch-farm)", linear_park: "url(#hatch-ground)", riparian_park: "url(#hatch-ground)"};
  for (const edge of data.edges) {
    hold(rect(edge.bounds_m, {class: "area", fill: fills[edge.type] || "none"}, g.ground), "edge", edge);
  }
  for (const lane of data.lanes.segments) hold(rect(lane.rect_m, {class: "lane"}, g.lanes), "lane", lane);
  for (const path of data.paths.filter(path => path.polyline_m)) {
    hold(el("polyline", {points: path.polyline_m.map(p => p.join(",")).join(" "), class: `path path-${path.type}`}, g.lanes), "path", path);
  }
  for (const cell of data.cells) hold(rect(cell.bounds_m, {class: "cell"}, g.lanes), "cell", cell);

  for (const item of data.landscape) {
    if (item.type === "creek") {
      hold(el("polyline", {points: item.centerline_m.map(p => p.join(",")).join(" "), class: "creek", "stroke-width": item.width_m}, g.water), "landscape", item);
    } else if (item.type === "pond") {
      const {center: [cx, cy], rx, ry} = item.ellipse_m;
      hold(el("ellipse", {cx, cy, rx, ry, class: "pond"}, g.water), "landscape", item);
    } else if (item.type === "water_channel") {
      for (const id of item.follows) {
        const lane = data.lanes.segments.find(lane => lane.id === id);
        if (!lane) continue;
        const [x0, y0, x1, y1] = lane.rect_m, mid = (y0 + y1) / 2;
        hold(el("line", {x1: x0, y1: mid, x2: x1, y2: mid, class: "runnel"}, g.water), "landscape", item);
      }
    } else if (item.type === "tree_rows") {
      for (const lane of data.lanes.segments) {
        const [x0, y0, x1, y1] = lane.rect_m, along = x1 - x0 > y1 - y0;
        if (Math.min(x1 - x0, y1 - y0) < 10) continue;
        for (let t = (along ? x0 : y0) + item.spacing_m / 2; t < (along ? x1 : y1); t += item.spacing_m) {
          for (const side of along ? [y0 + 2, y1 - 2] : [x0 + 2, x1 - 2]) {
            hold(el("circle", {cx: along ? t : side, cy: along ? side : t, r: 1.6, class: "tree"}, g.trees), "landscape", item);
          }
        }
      }
    }
  }

  for (const building of data.buildings) {
    const open = building.type === "courtyard" || !building.height_m;
    const style = open ? {} : {style: `--floors:${building.floors || 1}`};
    const landing = building.type === "canopy_landing";
    const parent = open ? g.ground : landing ? g.canopy : g.buildings;
    hold(rect(building.footprint_m, {class: open ? "open" : landing ? "building landing" : "building", ...style}, parent), "building", building);
    for (const entrance of building.entrances || []) {
      const [x, y] = entrance.pos_m;
      hold(rect([x - 1, y - 1, x + 1, y + 1], {class: "entrance"}, g.entrances), "entrance", {...entrance, id: `${building.id} · ${entrance.type}`, of: building.id});
    }
  }

  for (const bridge of data.sky_bridges.segments) {
    const [[x1, y1], [x2, y2]] = bridge.span_m;
    hold(el("line", {x1, y1, x2, y2, class: "bridge", "stroke-width": data.sky_bridges.width_m}, g.canopy), "bridge",
      {...bridge, elevation_m: data.sky_bridges.elevation_m, width_m: data.sky_bridges.width_m});
  }

  data.street_furniture.forEach((thing, index) => {
    if (!thing.pos_m) return;
    const [cx, cy] = thing.pos_m;
    hold(el("circle", {cx, cy, r: 0.9, class: `furniture furniture-${thing.type}`}, g.furniture), "furniture", {...thing, id: `${thing.type} ${index + 1}`});
  });

  for (const place of data.places) {
    const [cx, cy] = place.pos_m;
    hold(el("circle", {cx, cy, r: 3.2, class: "place"}, g.places), "place", place);
  }

  for (const cell of [...data.cells, ...data.edges]) {
    const [x0, y0, x1, y1] = cell.bounds_m;
    const label = el("text", {x: (x0 + x1) / 2, y: (y0 + y1) / 2, class: "cell-label"}, g.labels);
    label.textContent = (cell.name || cell.id).toUpperCase();
    if (y1 - y0 > 3 * (x1 - x0)) label.setAttribute("transform", `rotate(-90 ${(x0 + x1) / 2} ${(y0 + y1) / 2})`);
  }

  // A scale bar and north arrow, drawn in meters like everything else.
  const scale = el("g", {class: "scale"}, svg);
  el("line", {x1: 0, y1: height + 12, x2: 100, y2: height + 12}, scale);
  for (const x of [0, 50, 100]) {
    el("line", {x1: x, y1: height + 9, x2: x, y2: height + 15}, scale);
    el("text", {x, y: height + 25}, scale).textContent = `${x} m`;
  }
  el("text", {x: width - 4, y: height + 25, class: "north"}, scale).textContent = "N ↑";

  ui.view = ui.view || [-6, -6, width + 12, height + 36];
  setView(ui.view);
  applyLayers();
  flag(ui.flagged);
}

function setView(view) {
  ui.view = view;
  $("plan-svg").setAttribute("viewBox", view.join(" "));
}

function applyLayers() {
  for (const [name] of LAYERS) document.querySelector(`.layer-${name}`)?.toggleAttribute("hidden", !ui.layers[name]);
}

function facts(kind, item) {
  const rows = [];
  const add = (label, value) => { if (value !== undefined && value !== null && value !== "") rows.push([label, value]); };
  const box = item.footprint_m || item.bounds_m || item.rect_m;
  add("Kind", words(item.type || item.category || kind));
  if (box) add("Size", `${box[2] - box[0]} × ${box[3] - box[1]} m, ${((box[2] - box[0]) * (box[3] - box[1])).toLocaleString("en-US")} m²`);
  add("Floors", Array.isArray(item.floors) ? item.floors.join("–") : item.floors);
  add("Height", item.height_m ? `${item.height_m} m` : undefined);
  add("Elevation", item.elevation_m ? `${item.elevation_m} m` : undefined);
  add("Width", item.width_m ? `${item.width_m} m` : undefined);
  add("In", item.cell);
  add("Ground floor", item.ground_floor);
  add("Upper floors", item.upper_floors);
  add("Roof", item.roof || item.rooftop?.map(words).join(", "));
  add("Materials", item.materials);
  add("Palette", item.palette?.join(", "));
  add("Capacity", item.capacity);
  add("Activities", item.activities?.map(words).join(", "));
  add("Features", item.features?.join(", ") || item.species?.join(", "));
  add("Position", item.pos_m && `${item.pos_m.join(", ")} m`);
  add("Notes", item.vibe || item.description || item.notes);
  return rows;
}

function detail(key) {
  const found = key && ui.items.get(key);
  if (!found) {
    const meta = ui.data?.meta;
    $("plan-detail").innerHTML = meta ? `<div class="eyebrow ruled"><span>Site</span></div>
      <p class="h2">${escapeHtml(meta.name)}</p>
      <dl class="facts"><dt>Size</dt><dd>${meta.size_m.join(" × ")} m</dd><dt>Light</dt><dd>${escapeHtml(Object.values(meta.default_lighting).join(", "))}</dd>
      <dt>Version</dt><dd>${escapeHtml(meta.version)}</dd></dl><p class="meta">Point at a part of the plan to read it. Click to keep it here.</p>` : "";
    return;
  }
  const {kind, item} = found;
  const problems = (ui.data.checks || []).filter(check => check.ids.includes(item.id) || check.ids.includes(item.of));
  $("plan-detail").innerHTML = `<div class="eyebrow ruled"><span>${escapeHtml(words(kind))}</span>${ui.pinned === key ? "<span>Pinned</span>" : ""}</div>
    <p class="h2">${escapeHtml(item.name || words(item.id))}</p>
    <dl class="facts">${facts(kind, item).map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl>
    ${problems.map(check => `<p class="meta bad">${escapeHtml(check.text)}</p>`).join("")}`;
}

function flag(ids) {
  ui.flagged = ids;
  for (const {item, node} of ui.items.values()) node.classList.toggle("flagged", ids.has(item.id));
}

function drawChecks(checks) {
  $("plan-check-count").textContent = checks.length;
  if (!checks.length) return void ($("plan-checks").innerHTML = `<div class="none">The file agrees with itself.</div>`);
  const kinds = [...new Set(checks.map(check => check.kind))];
  $("plan-checks").innerHTML = kinds.map(kind => {
    const these = checks.filter(check => check.kind === kind);
    return `<details class="notes check-group" open><summary>${escapeHtml(words(kind))} · ${these.length}</summary>
      ${these.map(check => `<button type="button" class="check" data-ids="${escapeHtml(check.ids.join(" "))}">${escapeHtml(check.text)}</button>`).join("")}</details>`;
  }).join("");
}

function point(event) {
  const svg = $("plan-svg"), box = svg.getBoundingClientRect(), [x, y, w, h] = ui.view;
  const scale = Math.max(w / box.width, h / box.height);
  return [x + (event.clientX - box.left - (box.width - w / scale) / 2) * scale, y + (event.clientY - box.top - (box.height - h / scale) / 2) * scale, scale];
}

function wire() {
  const svg = $("plan-svg");
  svg.addEventListener("pointerover", event => { if (!ui.pinned) detail(event.target.dataset?.key); });
  svg.addEventListener("pointerleave", () => { if (!ui.pinned) detail(null); });
  svg.addEventListener("click", event => {
    if (ui.dragged) return;
    const key = event.target.dataset?.key;
    ui.pinned = key && key !== ui.pinned ? key : null;
    detail(ui.pinned || key);
  });
  svg.addEventListener("wheel", event => {
    event.preventDefault();
    const [mx, my] = point(event), factor = event.deltaY > 0 ? 1.15 : 1 / 1.15;
    const [x, y, w, h] = ui.view, full = ui.size[0] + 12;
    const nw = Math.min(full * 1.5, Math.max(40, w * factor)), nh = nw * h / w;
    setView([mx - (mx - x) * nw / w, my - (my - y) * nh / h, nw, nh]);
  }, {passive: false});
  svg.addEventListener("pointerdown", event => {
    const [, , scale] = point(event), start = [...ui.view];
    ui.dragged = false;
    const move = moved => {
      const dx = (moved.clientX - event.clientX) * scale, dy = (moved.clientY - event.clientY) * scale;
      if (Math.abs(dx) + Math.abs(dy) > 2 * scale) ui.dragged = true;
      if (ui.dragged) setView([start[0] - dx, start[1] - dy, start[2], start[3]]);
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  });
  $("plan-reset").addEventListener("click", () => setView([-6, -6, ui.size[0] + 12, ui.size[1] + 36]));

  $("plan-layers").innerHTML = LAYERS.map(([name, label]) =>
    `<label><input type="checkbox" id="layer-${name}" data-layer="${name}"${ui.layers[name] ? " checked" : ""}> ${escapeHtml(label)}</label>`).join("");
  $("plan-layers").addEventListener("change", event => {
    ui.layers[event.target.dataset.layer] = event.target.checked;
    try { localStorage.setItem("plan-layers", JSON.stringify(ui.layers)); } catch {}
    applyLayers();
  });

  // Pointing at a check marks the parts it names. Clicking keeps the marks.
  const checks = $("plan-checks");
  checks.addEventListener("pointerover", event => { const ids = event.target.closest(".check")?.dataset.ids; if (ids && !ui.held) flag(new Set(ids.split(" "))); });
  checks.addEventListener("pointerleave", () => { if (!ui.held) flag(new Set()); });
  checks.addEventListener("click", event => {
    const button = event.target.closest(".check");
    if (!button) return;
    const same = ui.held === button.dataset.ids;
    ui.held = same ? null : button.dataset.ids;
    document.querySelectorAll(".check").forEach(other => other.setAttribute("aria-pressed", String(!same && other === button)));
    flag(new Set(same ? [] : button.dataset.ids.split(" ")));
  });
}

function showView() {
  const view = location.hash === "#pictures" ? "pictures" : "plan";
  $("view-plan").hidden = view !== "plan";
  $("view-pictures").hidden = view !== "pictures";
  document.querySelectorAll(".views .tab").forEach(tab => tab.setAttribute("aria-current", tab.dataset.view === view ? "page" : "false"));
}

async function poll() {
  try {
    const response = await fetch("/api/city");
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    const text = JSON.stringify([body.world, body.checks]);
    if (text === ui.drawn) return;
    ui.drawn = text;
    ui.data = {...body.world, checks: body.checks};
    $("plan-title").textContent = body.world.meta.name;
    draw(body.world);
    drawChecks(body.checks);
    detail(ui.pinned);
  } catch (error) {
    $("plan-detail").innerHTML = `<p class="meta bad">Can't read the plan: ${escapeHtml(error.message)}</p>`;
  }
}

try { ui.layers = JSON.parse(localStorage.getItem("plan-layers")) || {}; } catch { ui.layers = {}; }
for (const [name, , on] of LAYERS) if (!(name in ui.layers)) ui.layers[name] = on;
window.addEventListener("hashchange", showView);
showView();
wire();
poll();
setInterval(poll, POLL_MS);
