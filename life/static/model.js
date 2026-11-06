// What the log says so far. Everything drawn comes from folding events into this, so replay matches live.
export const LEVELS = ["life", "year", "season", "month", "week", "day", "hour", "min15", "min5", "min1", "sec30"];
export const depth = level => LEVELS.indexOf(level);
const RECENT = 40;

export function emptyModel() {
  return {nodes: new Map(), open: [], descendants: new Map(), deepest: new Map(), recent: [], writes: 0};
}

function ancestors(model, id) {
  const chain = [];
  for (let node = model.nodes.get(id); node; node = model.nodes.get(node.parent)) chain.push(node);
  return chain;
}

export function applyEvent(model, event) {
  model.writes = event.seq;
  model.recent.push(event);
  if (model.recent.length > RECENT) model.recent.shift();
  if (event.type === "node_opened") {
    model.nodes.set(event.id, {...event, status: "open"});
    model.open.push(event.id);
    const level = depth(event.level);
    for (const node of ancestors(model, event.id)) {
      model.descendants.set(node.id, (model.descendants.get(node.id) || 0) + 1);
      model.deepest.set(node.id, Math.max(model.deepest.get(node.id) || 0, level));
    }
  } else if (event.type === "node_closed") {
    const node = model.nodes.get(event.id);
    node.status = "closed";
    node.summary = event.summary;
    node.diverged = event.diverged;
    model.open.pop();
  } else if (event.type === "node_escalated") {
    model.nodes.get(event.id).limit = event.to;
  }
}

export const cursorOf = model => model.open.at(-1) ?? null;

// A calendar slot with no node is a ghost if the agent can still reach it, and skipped if that window closed without it.
export function statusOf(model, slot, parentStatus, parentNode) {
  const node = model.nodes.get(slot.id);
  if (node) return node.status;
  if (slot.parent === null) return "ghost";
  if (parentStatus === "closed" || parentStatus === "skipped") return "skipped";
  if (parentStatus === "open") return depth(parentNode.limit) > depth(parentNode.level) ? "ghost" : "skipped";
  return depth(slot.level) <= depth("day") ? "ghost" : "skipped";
}
