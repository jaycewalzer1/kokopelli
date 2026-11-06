// The city plan's drawing, shared by the plan view (city-plan.js) and the live agent view (city-live.js).
// city/world.json from above, one SVG unit to a meter. Styles are in moodboard.css under #plan-svg.
export const SVG = "http://www.w3.org/2000/svg";
export const LAYERS = [
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

export function el(name, attrs = {}, parent) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  parent?.appendChild(node);
  return node;
}

export function rect([x0, y0, x1, y1], attrs, parent) {
  return el("rect", {x: x0, y: y0, width: x1 - x0, height: y1 - y0, ...attrs}, parent);
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

// Draws the whole plan into svg, replacing what was there. hold(node, kind, item) registers each part you can point at.
// Returns the site's size in metres.
export function drawCity(svg, data, hold = node => node) {
  svg.replaceChildren();
  const [width, height] = data.meta.size_m;
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
  return [width, height];
}
