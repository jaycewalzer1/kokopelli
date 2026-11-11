// The city moodboard view. Claude puts pictures up for review; here each one is kept or removed, with a note on why.
// It polls the board, so pictures added while the page is open show up too.
const $ = id => document.getElementById(id);
const POLL_MS = 5000;
const UNSORTED = {id: "unsorted", name: "No section yet", ask: "Kept, but not placed in a section."};
const ACTIONS = {
  proposed: [["kept", "Keep"], ["removed", "Remove"]],
  kept: [["removed", "Remove"], ["proposed", "Back to review"]],
  removed: [["kept", "Keep instead"], ["proposed", "Back to review"]],
};
const ui = {uiVersion: null, board: null, drawn: "", status: "proposed"};

const escapeHtml = text => String(text ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const imageUrl = image => `/api/moodboard/image?id=${encodeURIComponent(image.id)}`;
const withStatus = status => ui.board.images.filter(image => image.status === status);

function status(text, live = false) {
  $("status-text").textContent = text;
  $("status-line").classList.toggle("live", live);
}

function options(chosen) {
  return [...ui.board.sections, UNSORTED].map(section =>
    `<option value="${escapeHtml(section.id)}"${section.id === chosen ? " selected" : ""}>${escapeHtml(section.name)}</option>`).join("");
}

function provenance(image) {
  const channel = image.origin?.channel;
  const where = channel ? `<a href="${escapeHtml(image.origin.channel_url)}" target="_blank" rel="noopener">${escapeHtml(channel)}</a>` : "";
  const title = image.title ? escapeHtml(image.title) : "";
  const credit = image.origin?.license ? escapeHtml([image.origin.license, image.origin.author].filter(Boolean).join(", ")) : "";
  return title || where ? `<p class="meta">${[title, where, credit].filter(Boolean).join(" · ")}</p>` : "";
}

function pin(image) {
  const id = escapeHtml(image.id);
  const buttons = ACTIONS[image.status].map(([to, label]) => `<button type="button" data-to="${to}">${label}</button>`).join("");
  return `<figure class="pin card" data-id="${id}">
    <a href="${escapeHtml(image.source || imageUrl(image))}" target="_blank" rel="noopener"><img src="${imageUrl(image)}" alt="${escapeHtml(image.title || "A moodboard picture")}" loading="lazy"></a>
    ${provenance(image)}
    <label>Why<textarea data-field="note" rows="2" placeholder="What works or doesn't">${escapeHtml(image.note)}</textarea></label>
    <label>Section<select data-field="section">${options(image.section)}</select></label>
    <div class="actions">${buttons}</div>
  </figure>`;
}

function zone(name, ask, images) {
  return `<section class="zone" aria-label="${escapeHtml(name)}">
    <div class="eyebrow ruled"><span>${escapeHtml(name)}</span><span>${images.length}</span></div>
    ${ask ? `<p class="meta">${escapeHtml(ask)}</p>` : ""}
    ${images.length ? `<div class="grid">${images.map(pin).join("")}</div>` : `<div class="none">Nothing here yet.</div>`}</section>`;
}

function draw() {
  const images = withStatus(ui.status);
  let html;
  if (ui.status === "kept") {
    // Kept pictures are grouped by section, the way the architects will read them.
    html = [...ui.board.sections, UNSORTED].map(section => [section, images.filter(image => image.section === section.id)])
      .filter(([section, inside]) => inside.length || section !== UNSORTED)
      .map(([section, inside]) => zone(section.name, section.ask, inside)).join("");
  } else {
    html = zone(ui.status === "proposed" ? "Waiting for review" : "Removed, with reasons", "", images);
  }
  for (const tab of document.querySelectorAll(".tabs[role=\"tablist\"] .tab")) {
    tab.setAttribute("aria-selected", String(tab.dataset.status === ui.status));
    tab.innerHTML = `${tab.textContent.replace(/\s*\d[\d,]*$/, "")}<span class="count">${withStatus(tab.dataset.status).length}</span>`;
  }
  if (html === ui.drawn) return;
  ui.drawn = html;
  $("sections").innerHTML = html;
}

function resting() {
  const [waiting, kept, removed] = ["proposed", "kept", "removed"].map(state => withStatus(state).length);
  status(ui.board.images.length ? `${waiting} to review, ${kept} kept, ${removed} removed` : "No pictures yet");
}

async function poll() {
  try {
    const response = await fetch("/api/moodboard");
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    if (ui.uiVersion !== null && body.ui_version !== ui.uiVersion) location.reload();
    ui.uiVersion = body.ui_version;
    ui.board = body;
    // Redrawing while someone types would throw their words away, so wait until they leave the field.
    if (!document.activeElement?.closest(".pin")) draw();
    resting();
  } catch (error) {
    status(`Can't reach the panel: ${error.message}`);
  }
}

async function save(id, fields) {
  const response = await fetch("/api/moodboard/update", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({id, ...fields})});
  const answer = await response.json();
  if (!response.ok) throw new Error(answer.error);
  // Use the saved picture right away, so it leaves this tab without waiting for the next poll.
  ui.board.images = ui.board.images.map(image => image.id === id ? answer : image);
  return answer;
}

document.querySelector(".tabs[role=\"tablist\"]").addEventListener("click", event => {
  const tab = event.target.closest(".tab");
  if (!tab || !ui.board) return;
  ui.status = tab.dataset.status;
  draw();
});

// A note or section saves when its field is left, and only if it changed.
$("sections").addEventListener("change", async event => {
  const field = event.target.dataset.field;
  const id = event.target.closest(".pin")?.dataset.id;
  if (!field || !id) return;
  try {
    await save(id, {[field]: event.target.value});
    status("Saved");
  } catch (error) {
    status(`Couldn't save: ${error.message}`);
  }
  if (field === "section" && ui.status === "kept") { event.target.blur(); draw(); }
});

// Keeping or removing also sends the note as it stands, in case the field hasn't been left yet.
$("sections").addEventListener("click", async event => {
  const to = event.target.dataset.to;
  const card = event.target.closest(".pin");
  if (!to || !card) return;
  try {
    await save(card.dataset.id, {status: to, note: card.querySelector("textarea").value});
  } catch (error) {
    return status(`Couldn't save: ${error.message}`);
  }
  event.target.blur();
  draw();
  resting();
});

poll();
setInterval(poll, POLL_MS);
