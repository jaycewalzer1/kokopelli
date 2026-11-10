// The only module that touches the tree's drawing surface.
const SVG = "http://www.w3.org/2000/svg";
const escapeText = text => String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;");
// A little wider and taller than the type really is, so kept labels have air between them.
const LABEL_WIDTH = 0.65, LABEL_HEIGHT = 1.35;

// Labels stay one size on screen, so the further out the view is, the fewer fit. Keep the most important that don't touch.
function declutter(labels, elements, k) {
  const kept = [];
  labels.map((label, i) => ({label, element: elements[i]})).sort((a, b) => a.label.rank - b.label.rank).forEach(({label, element}) => {
    const w = label.text.length * label.size * LABEL_WIDTH * k, h = label.size * LABEL_HEIGHT * k;
    const x0 = label.anchor === "start" ? label.x : label.anchor === "end" ? label.x - w : label.x - w / 2;
    const box = {x0, x1: x0 + w, y0: label.y - h / 2, y1: label.y + h / 2};
    const clear = !kept.some(other => box.x0 < other.x1 && other.x0 < box.x1 && box.y0 < other.y1 && other.y0 < box.y1);
    element.style.display = clear ? "" : "none";
    if (clear) kept.push(box);
  });
}

function nodeMarkup(node) {
  const dash = node.dash ? `;stroke-dasharray:${node.dash}` : "";
  const halo = node.halo ? `<circle cx="${node.x}" cy="${node.y}" r="${node.halo}" style="fill:none;stroke:var(--ink);stroke-width:1.4"/>` : "";
  const hit = `<circle data-id="${node.id}" cx="${node.x}" cy="${node.y}" r="${Math.max(node.r + 3, 6)}" style="fill:transparent;cursor:pointer"/>`;
  return `${halo}<circle cx="${node.x}" cy="${node.y}" r="${node.r}" style="fill:${node.fill};stroke:${node.stroke};stroke-width:${node.sw}${dash}" pointer-events="none"/>${hit}`;
}

// The paths the eye follows keep the same width on screen at every zoom.
function pathLine(d, stroke, width) {
  return `<path d="${d}" style="fill:none;stroke:${stroke};stroke-width:${width}" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>`;
}

function sceneMarkup(scene) {
  const labels = scene.labels.map(label => `<text class="graph-label${label.onNode ? " on-node" : ""}" x="${label.x}" y="${label.y}" text-anchor="${label.anchor}" style="--size:${label.size};fill:${label.color}" font-weight="${label.weight || 400}">${escapeText(label.text)}</text>`).join("");
  return `<g>` +
    pathLine(scene.ghostSpokes, "var(--hairline)", 1) +
    scene.branches.map(branch => pathLine(branch.spokes + branch.ticks, branch.color, 1)).join("") +
    pathLine(scene.hoverLine, "var(--ink-muted)", 2) +
    pathLine(scene.liveLine, "var(--ink)", 3) +
    pathLine(scene.highlight, "var(--gold)", 3) +
    scene.nodes.map(nodeMarkup).join("") +
    `</g><g style="pointer-events:none">${labels}</g>`;
}

export function createRenderer(svg) {
  const stage = document.createElementNS(SVG, "g");
  const live = document.createElementNS(SVG, "g");
  live.style.pointerEvents = "none";
  svg.append(stage, live);
  let drawn = "", liveDrawn = "", labels = [], scale = 1;
  const placeLabels = () => declutter(labels, stage.querySelectorAll(".graph-label"), scale);

  return {
    draw(scene, running) {
      const markup = sceneMarkup(scene);
      if (markup !== drawn) { stage.innerHTML = markup; drawn = markup; labels = scene.labels; placeLabels(); }
      const cursor = scene.positions.get(scene.cursor);
      const liveMarkup = running && scene.liveLine ?
        `<path class="tree-pulse" d="${scene.liveLine}" style="fill:none;stroke:var(--surface-100);stroke-width:2" stroke-linecap="round" vector-effect="non-scaling-stroke"/>` +
        (cursor ? `<circle class="tree-ring" cx="${cursor.x}" cy="${cursor.y}" r="4" style="fill:none;stroke:var(--ink);stroke-width:1.4"/>` : "") : "";
      if (liveMarkup !== liveDrawn) { live.innerHTML = liveMarkup; liveDrawn = liveMarkup; }
    },
    setView(view) {
      svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.w} ${view.h}`);
      scale = Math.max(view.w / (svg.clientWidth || 1), view.h / (svg.clientHeight || 1));
      svg.style.setProperty("--k", scale);
      placeLabels();
    },
    picture() { return drawn; },
    toScreen(x, y) {
      const matrix = svg.getScreenCTM();
      return {x: matrix.a * x + matrix.e, y: matrix.d * y + matrix.f};
    },
    toWorld(clientX, clientY) {
      const matrix = svg.getScreenCTM();
      return {x: (clientX - matrix.e) / matrix.a, y: (clientY - matrix.f) / matrix.d};
    },
  };
}
