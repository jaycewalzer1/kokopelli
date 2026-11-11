// The city plan view: data/city/world.json drawn from above, one SVG unit to a meter, with the file's own checks beside it.
// It only reads. Changing the city means changing the file.
import {LAYERS, drawCity} from "/static/city-draw.js";

const $ = id => document.getElementById(id);
const POLL_MS = 5000;
const ui = {data: null, drawn: "", items: new Map(), pinned: null, view: null, layers: {}, flagged: new Set()};

const escapeHtml = text => String(text ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const words = text => String(text).replaceAll("_", " ");

// Everything you can point at is registered once, so the detail panel and the checks can find it by kind and id.
function hold(node, kind, item) {
  const key = `${kind}:${item.id}`;
  node.dataset.key = key;
  ui.items.set(key, {kind, item, node});
  return node;
}

function draw(data) {
  const svg = $("plan-svg");
  ui.items.clear();
  ui.size = drawCity(svg, data, hold);
  ui.view = ui.view || [-6, -6, ui.size[0] + 12, ui.size[1] + 36];
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
  if (!checks.length) {
    $("plan-checks").innerHTML = `<div class="none">The file agrees with itself.</div>`;
    return;
  }
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
    document.querySelectorAll(".check").forEach(other => { other.setAttribute("aria-pressed", String(!same && other === button)); });
    flag(new Set(same ? [] : button.dataset.ids.split(" ")));
  });
}

function showView() {
  const view = location.hash === "#pictures" ? "pictures" : "plan";
  $("view-plan").hidden = view !== "plan";
  $("view-pictures").hidden = view !== "pictures";
  document.querySelectorAll(".views .tab").forEach(tab => { tab.setAttribute("aria-current", tab.dataset.view === view ? "page" : "false"); });
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
