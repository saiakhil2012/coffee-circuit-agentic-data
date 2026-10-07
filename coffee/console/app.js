// Coffee Circuit Quality console: renders the agent's event stream (see coffee/session.py) as one incident.
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmt = (n) => Number(n ?? 0).toLocaleString("en-IN");
function el(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; }

const TOOLS = {
  find_similar_complaints: ["Checking whether other outlets are seeing this", "Hybrid search: keywords and meaning in one query, last 14 days, plus the quality procedure that applies"],
  who_else_is_affected: ["Following the beans through the supply chain", "Supply-chain trace: roast lot → green-bean batch → every roast lot made from it"],
  run_sql_plus_plus_query: ["Trying to change the data", "A query written by the agent, sent through the read-only database connection"],
  place_quality_hold: ["Committing the hold", "One ACID transaction: hold deliveries, credit customers, quarantine lots; then notify"],
};
// The first suggestion moves the incident forward; the others are follow-ups the agent answers live.
const NEXT = {
  similar: ["Who else got these beans?", "Which outlets have the most complaints?", "What does our quality procedure say?"],
  chain: ["Hold those deliveries", "Which outlets are those deliveries going to?", "Where do these beans come from?"],
};

const state = { config: null, started: false, busy: false, phase: "idle", similar: null, thinking: null, ctrl: null, running: null, chips: [], showChips: false };
try { state.showChips = localStorage.getItem("showChips") === "1"; } catch { /* storage blocked: stay hidden */ }

// ---------------------------------------------------------------- plumbing
async function stream(url, body) {
  setBusy(true);
  const ctrl = new AbortController();
  state.ctrl = ctrl;
  let finished;
  state.running = new Promise((r) => (finished = r));
  try {
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined, signal: ctrl.signal });
    if (!res.ok) {
      const detail = await res.json().then((j) => j.detail).catch(() => res.statusText);
      problem(detail || "Something went wrong. Try again.");
      return;
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (line) handle(JSON.parse(line));
      }
    }
  } catch (err) {
    if (!ctrl.signal.aborted) problem(`Lost the connection to the console server (${err.message}). Check that “coffee web” is still running.`);
  } finally {
    if (state.ctrl === ctrl) { state.ctrl = null; clearThinking(); setBusy(false); }
    finished();
  }
}

// Stop the running turn (the server releases its lock when the stream closes).
async function cancelRunning() {
  if (!state.ctrl) return;
  const running = state.running;
  state.ctrl.abort();
  state.ctrl = null;
  clearThinking();
  await running;
}

function add(node) { $("feedInner").appendChild(node); node.scrollIntoView({ behavior: "smooth", block: "end" }); return node; }
function setStatus(cls, text) { const s = $("status"); s.hidden = false; s.className = "status " + cls; s.textContent = text; }
function setBusy(b) {
  state.busy = b;
  $("askInput").disabled = b || !state.started;
  $("askBtn").disabled = b || !state.started;
  document.querySelectorAll(".chip").forEach((c) => (c.disabled = b));
  $("resetBtn").disabled = b;
  // the proposal can appear before the agent has finished its reply: approve only once the turn is over
  const approveBtn = $("approve");
  if (approveBtn && approveBtn.textContent === "Approve the hold") approveBtn.disabled = b;
}
// Suggested next questions stay hidden unless the presenter turns them on ("Suggestions" at the top).
function chips(list) {
  state.chips = list;
  const c = $("chips");
  c.hidden = !state.showChips;
  if (!state.showChips) return c.replaceChildren();
  c.replaceChildren(...list.map((q, i) => { const b = el(`<button class="chip${i === 0 ? " primary-chip" : ""}" type="button"></button>`); b.textContent = q; b.onclick = () => ask(q); b.disabled = state.busy; return b; }));
}
function thinking(label) {
  if (!state.thinking) {
    state.thinking = add(el('<div class="section thinking" aria-live="polite"><span class="who"></span><div class="bar"></div><div class="bar w2"></div><div class="bar w3"></div></div>'));
  }
  state.thinking.querySelector(".who").textContent = label;
}
function clearThinking() { if (state.thinking) { state.thinking.remove(); state.thinking = null; } }
function problem(msg) { clearThinking(); const p = add(el('<div class="section problem"></div>')); p.textContent = msg; }

function step(e) {
  $("stepsEmpty").hidden = true;
  const write = e.name === "run_sql_plus_plus_query" || e.name === "place_quality_hold";
  const li = el(`<li><span class="tool${write ? " write" : ""}"></span><span class="why"></span>${e.query ? "<details><summary>View query</summary><pre></pre></details>" : ""}</li>`);
  li.querySelector(".tool").textContent = e.name;
  li.querySelector(".why").textContent = (TOOLS[e.name] || [null, "Tool call"])[1];
  if (e.query) li.querySelector("pre").textContent = e.query;
  $("steps").appendChild(li);
  $("stepCount").textContent = $("steps").children.length;
}

// ---------------------------------------------------------------- event renderers
function handle(e) {
  switch (e.type) {
    case "complaint": return complaint(e);
    case "thinking": return thinking("Working on it");
    case "tool_call": step(e); return thinking((TOOLS[e.name] || ["Working on it"])[0]);
    case "similar": clearThinking(); return similar(e);
    case "chain": clearThinking(); return chain(e);
    case "refused": clearThinking(); return refused(e);
    case "proposal": return proposal(e);
    case "approved": return approved(e);
    case "resolved": clearThinking(); return resolved(e);
    case "answer": return reply(e.text);
    case "rows": return rows(e.rows);
    case "tool_error": return reply(`A tool reported a problem: ${e.message}`);
    case "error": return problem(e.message);
    case "done": clearThinking(); chips(NEXT[state.phase] || []); return;
  }
}

function complaint(e) {
  state.started = true;
  clearThinking();
  $("feedInner").replaceChildren();
  $("title").textContent = `${/burnt/i.test(e.text) ? "Burnt taste" : "Quality complaint"} · ${e.outlet}`;
  $("incId").hidden = false; $("incId").textContent = `INC-${String(e.bill_id || "").replace(/\D/g, "").slice(-4) || "0001"}`;
  setStatus("investigating", "Investigating");
  add(el(`<section class="section"><div class="label">Complaint</div><p class="quote"></p>
    <div class="meta"><span>${esc(e.customer)} · ${esc(e.outlet)}</span><span>Bill <b>${esc(e.bill_id)}</b></span><span>Received ${esc(e.received_on)}</span></div></section>`))
    .querySelector(".quote").textContent = `“${e.text}”`;
  renderInbox();
}

function similar(e) {
  state.similar = e; state.phase = "similar";
  add(el(`<section class="section"><div class="label">Similar complaints ${e.sop ? `<span class="src">Source: ${esc(e.sop)}</span>` : ""}</div>
    <div class="stats"><div class="stat hot"><span class="n">${fmt(e.similar_complaints)}</span><span class="k">similar complaints</span></div>
    <div class="stat"><span class="n">${fmt(e.outlets)}</span><span class="k">outlets</span></div>
    <div class="stat"><span class="n mono">${esc(e.top_lot)}</span><span class="k">${esc(e.blend || "")} · the roast lot behind them</span></div></div>
    <p class="say"></p></section>`)).querySelector(".say").textContent = state.opened === "incoming"
    ? "Not a one-off: the same complaint in different words, “kadwa” and “ruchi sariyilla” included, traced to one roast lot."
    : `Not a one-off: ${fmt(e.similar_complaints)} similar complaints across ${fmt(e.outlets)} outlets, traced to one roast lot.`;
}

function chain(e) {
  state.phase = "chain";
  const [estate, place] = String(e.supplier || "").split(" (");
  const lots = (e.lots || []).slice(0, 3);
  // circles are things, lines are relationships: estate → green-bean batch → every roast lot made from it → deliveries
  const H = Math.max(300, lots.length * 130 + 40);
  const mid = H / 2;
  const lotY = (i) => mid + (i - (lots.length - 1) / 2) * 130;
  const dots = (n, cx, cy, delay) => {
    const k = Math.min(9, Math.max(1, Math.round(n / 40)));
    return Array.from({ length: k }, (_, j) => {
      const a = (j / k) * Math.PI * 2;
      return `<circle class="dot" style="animation-delay:${delay + j * 0.04}s" cx="${cx + Math.cos(a) * 26}" cy="${cy + Math.sin(a) * 26}" r="6"/>`;
    }).join("");
  };
  const nodes = lots.map((l, i) => {
    // the lot found in beat 1 shows the same count as the "Similar complaints" card above it
    if (state.similar && l.roast_lot_id === state.similar.top_lot) l = { ...l, taste_complaints: state.similar.similar_complaints };
    const quiet = !l.taste_complaints;
    const y = lotY(i);
    const d = 0.9 + i * 0.35;
    return `<path class="edge" style="animation-delay:${d - 0.3}s" d="M346 ${mid} C 420 ${mid}, 420 ${y}, 488 ${y}"/>
      ${i === 0 ? `<text class="el" x="452" y="${y - 16}" text-anchor="middle" style="animation-delay:${d}s">roasted into</text>` : ""}
      <g class="pop" style="animation-delay:${d}s"><circle class="lot${quiet ? " quiet" : ""}" cx="528" cy="${y}" r="40"/>
      <text class="in" x="528" y="${y + 5}" text-anchor="middle">${esc(l.roast_lot_id)}</text>
      <text class="t" x="584" y="${y - 8}">Roast lot · ${esc(l.blend)}</text>
      <text class="${quiet ? "r" : "s"}" x="584" y="${y + 16}">${quiet ? "0 complaints yet · same beans" : `${fmt(l.taste_complaints)} complaints`}</text></g>
      <path class="edge thin" style="animation-delay:${d + 0.5}s" d="M784 ${y} L 852 ${y}"/>
      ${dots(l.pending_deliveries, 892, y, d + 0.7)}
      <text class="s" x="892" y="${y + 52}" text-anchor="middle" style="animation-delay:${d + 0.7}s">${fmt(l.pending_deliveries)} deliveries</text>`;
  }).join("");
  add(el(`<section class="section"><div class="label">Supply chain · traced through the documents</div>
    <div class="chain-wrap"><svg class="chain" viewBox="0 0 960 ${H}" role="img" aria-label="${esc(estate)} supplied green-bean batch ${esc(e.green_bean_lot)}, roasted into ${esc((e.roast_lot_ids || []).join(", "))}">
      <path class="edge" d="M100 ${mid} L 230 ${mid}"/>
      <text class="el" x="165" y="${mid - 12}" text-anchor="middle">supplied</text>
      ${nodes}
      <g class="pop"><circle class="estate" cx="62" cy="${mid}" r="34"/>
      <text class="s" x="62" y="${mid + 60}" text-anchor="middle">${esc(estate)}</text>
      <text class="s" x="62" y="${mid + 80}" text-anchor="middle">${esc((place || "").replace(")", ""))}</text></g>
      <g class="pop" style="animation-delay:.45s"><circle class="beans" cx="290" cy="${mid}" r="56"/>
      <text class="in big" x="290" y="${mid + 6}" text-anchor="middle">${esc(e.green_bean_lot)}</text>
      <text class="t" x="290" y="${mid + 88}" text-anchor="middle">Green-bean batch</text></g>
    </svg></div>
    <p class="legend">A <b>roast lot</b> (RL) is one roasting run. A <b>green-bean batch</b> (GB) is the raw beans it was roasted from. One batch, several lots: a complaint about one lot puts every lot from the same beans at risk. Each roast lot records the batch it came from, and the agent follows those links with a join.</p>
    <div class="road"><b>${fmt(e.pending_deliveries)}</b> deliveries on the road from the same beans</div></section>`));
}

function refused(e) {
  const s = add(el(`<section class="section blocked"><span class="shield" aria-hidden="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12h6"/></svg></span>
    <div><h3>Change blocked by the data layer</h3><p>The agent tried to change the data directly. Its database connection is <code>read-only</code>, so the write was refused before it reached the data. Changes need your approval.</p><p class="note"></p></div></section>`));
  s.querySelector(".note").textContent = e.message;
}

function proposal(e) {
  state.phase = "proposed";
  const p = add(el(`<section class="section proposal" id="proposal"><div class="label">Proposed action · needs your approval</div>
    <ul class="changes">
      <li><span class="n">${fmt(e.deliveries)}</span><span class="d"><b>deliveries put on hold</b> · ${e.lots.map((l) => `${esc(l.roast_lot_id)}: ${fmt(l.pending_deliveries)}`).join(" · ")}</span></li>
      <li><span class="n">${fmt(e.customers)}</span><span class="d"><b>customers offered a coffee credit</b> · everyone with open feedback on these lots</span></li>
      <li><span class="n">${e.roast_lot_ids.length}</span><span class="d"><b>roast lots quarantined</b> · ${esc(e.roast_lot_ids.join(", "))} (batch ${esc(e.green_bean_lot)})</span></li>
    </ul>
    <div class="actions"><button class="primary" id="approve" type="button">Approve the hold</button><button class="secondary" id="dismiss" type="button">Dismiss</button>
    <span class="fine">All three changes commit together, or none do. Safe to run twice.</span></div></section>`));
  setStatus("proposed", "Action proposed");
  p.querySelector("#approve").onclick = approve;
  p.querySelector("#approve").disabled = state.busy;
  p.querySelector("#dismiss").onclick = () => {
    p.querySelector(".actions").replaceChildren(el('<span class="fine" style="margin:0">Dismissed. Nothing was changed.</span>'));
    setStatus("investigating", "Investigating");
  };
  p.querySelector("#approve").focus({ preventScroll: true });
}

function approved(e) {
  const a = document.querySelector("#proposal .actions");
  const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (a) a.replaceChildren(el(`<span class="fine" style="margin:0">Approved by ${esc(e.by)} · ${time}</span>`));
}

function resolved(e) {
  state.phase = "resolved";
  if (e.already_done) {
    add(el(`<section class="section resolved"><div class="label">Already on hold · ${esc(e.hold_id)}</div><p class="say">This hold was committed earlier, so nothing changed. Running it twice is safe.</p></section>`));
  } else {
    const mailed = e.notification === "sent via n8n";
    add(el(`<section class="section resolved"><div class="label">Resolved · hold ${esc(e.hold_id)} committed</div>
      <div class="stats"><div class="stat"><span class="n">${fmt(e.deliveries_on_hold)}</span><span class="k">deliveries held</span></div>
      <div class="stat"><span class="n">${fmt(e.customers_credited)}</span><span class="k">customers credited</span></div>
      <div class="stat"><span class="n">${fmt(e.lots_quarantined)}</span><span class="k">roast lots quarantined</span></div></div>
      <div class="mail">${mailed ? 'Area managers emailed · <a href="http://localhost:8025" target="_blank" rel="noopener">open the inbox</a>' : `Email not sent: ${esc(e.notification)}`}</div></section>`));
  }
  setStatus("resolved", "Resolved");
}

function rows(data) {
  if (!data.length) return reply("The query returned no rows.");
  const cols = Object.keys(data[0]).slice(0, 5);
  const t = el(`<section class="section"><div class="label">Query result · ${data.length} row${data.length === 1 ? "" : "s"}</div>
    <div class="table-wrap"><table class="rows"><thead><tr></tr></thead><tbody></tbody></table></div></section>`);
  cols.forEach((c) => { const th = document.createElement("th"); th.textContent = c.replace(/_/g, " "); t.querySelector("thead tr").appendChild(th); });
  data.slice(0, 8).forEach((r) => {
    const tr = document.createElement("tr");
    cols.forEach((c) => { const td = document.createElement("td"); const v = r[c]; td.textContent = typeof v === "object" ? JSON.stringify(v) : String(v ?? ""); tr.appendChild(td); });
    t.querySelector("tbody").appendChild(tr);
  });
  add(t);
}

function reply(text) {
  const r = add(el('<p class="reply"><b>Quality agent:</b> <span></span></p>'));
  r.querySelector("span").textContent = text;
}

// ---------------------------------------------------------------- actions
// Opening a feedback only shows it; the agent starts when the presenter presses "Start analysis".
async function open(feedbackId) {
  const target = feedbackId || "incoming";
  if (state.opened === target) return;  // already open (previewed or running): never lose a run by accident
  state.opened = target; renderInbox();
  if (state.busy) {
    $("inbox").classList.add("switching");
    await cancelRunning();
    $("inbox").classList.remove("switching");
  }
  if (state.opened !== target) return;  // another click arrived while the old run was stopping
  state.phase = "idle"; state.similar = null; state.started = false;
  $("steps").replaceChildren(); $("stepCount").textContent = "0"; $("stepsEmpty").hidden = false; chips([]);
  preview(target);
  setBusy(false);
}

function preview(target) {
  const inc = state.config?.incoming || {};
  const r = target === "incoming"
    ? { customer: inc.customer, outlet: inc.outlet, text: inc.text, when: "New · just arrived" }
    : (({ customer, outlet, text, received_on, status }) => ({ customer, outlet, text, when: `Received ${received_on} · ${status}` }))(inboxRows.find((x) => x.id === target) || {});
  $("title").textContent = `${/burnt/i.test(r.text || "") ? "Burnt taste" : "Quality complaint"} · ${r.outlet || ""}`;
  $("incId").hidden = true;
  setStatus("idle", "Not started");
  const card = el(`<section class="section"><div class="label">Complaint</div><p class="quote"></p>
    <div class="meta"><span></span><span></span></div>
    <div class="actions"><button class="primary" id="startBtn" type="button">Start analysis</button>
    <span class="fine">The agent will check other outlets, the quality procedure and the supply chain.</span></div></section>`);
  card.querySelector(".quote").textContent = `“${r.text || ""}”`;
  const [who, when] = card.querySelectorAll(".meta span");
  who.textContent = `${r.customer || ""} · ${r.outlet || ""}`;
  when.textContent = r.when || "";
  card.querySelector("#startBtn").onclick = () => startAnalysis(target);
  $("feedInner").replaceChildren(card);
  card.querySelector("#startBtn").focus({ preventScroll: true });
}

function startAnalysis(target) {
  if (state.busy || state.opened !== target) return;
  const b = $("startBtn");
  if (b) b.closest(".actions").remove();
  setStatus("investigating", "Investigating");
  thinking("Filing the feedback and opening the incident");
  stream("/api/start", target === "incoming" ? null : { feedback_id: target });
}

function ask(text) {
  if (state.busy || !state.started) return;
  const a = add(el('<div class="asked"><small>You asked</small></div>'));
  a.append(text);
  if (state.phase === "similar" || state.phase === "chain") chips([]);
  stream("/api/ask", { text });
}

function approve() {
  if (state.busy) return;
  const b = $("approve");
  if (b) { b.disabled = true; b.textContent = "Committing…"; }
  const d = $("dismiss");
  if (d) d.hidden = true;
  stream("/api/approve");
}

async function resetData() {
  if (state.busy) return;
  setBusy(true);
  $("feedInner").replaceChildren(el('<div class="section thinking"><span class="who">Reloading the data and clearing the inbox, about half a minute</span><div class="bar"></div><div class="bar w2"></div></div>'));
  try {
    const res = await fetch("/api/reset", { method: "POST" });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    location.reload();
  } catch (err) {
    setBusy(false);
    problem(`Reset failed: ${err.message}`);
  }
}

// ---------------------------------------------------------------- inbox and first paint
let inboxRows = [];
function bindOpen(li, id) {
  li.onclick = () => open(id);
  li.onkeydown = (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(id); } };
}
function renderInbox() {
  const inc = state.config?.incoming;
  const items = [];
  if (inc) {
    const active = state.opened === "incoming";
    const li = el(`<li class="clickable ${active ? "active" : "incoming new"}" tabindex="0" role="button"><span class="dot" aria-hidden="true"></span>
      <span class="who"><span></span><em>now</em></span><span class="txt"></span>${active ? "" : '<span class="open">Open feedback</span>'}</li>`);
    li.querySelector(".who span").textContent = `${inc.customer} · ${inc.outlet}`;
    li.querySelector(".txt").textContent = inc.text;
    bindOpen(li, null);
    items.push(li);
  }
  for (const r of inboxRows) {
    const li = el(`<li class="clickable${state.opened === r.id ? " active" : ""}" tabindex="0" role="button"><span class="dot" aria-hidden="true"></span><span class="who"><span></span><em></em></span><span class="txt"></span></li>`);
    bindOpen(li, r.id);
    li.querySelector(".who span").textContent = `${r.customer} · ${r.outlet}`;
    li.querySelector(".who em").textContent = r.status === "open" ? "open" : r.status;
    li.querySelector(".txt").textContent = r.text;
    items.push(li);
  }
  $("inbox").replaceChildren(...items);
  $("inboxCount").textContent = `${items.length} recent`;
}

async function boot() {
  try {
    state.config = await fetch("/api/config").then((r) => r.json());
    const [name, role] = String(state.config.approver).split(" (");
    $("who").textContent = name; $("role").textContent = role ? role.replace(")", "").replace(/^./, (c) => c.toUpperCase()) : "Approver";
    $("avatar").textContent = name.slice(0, 2).toUpperCase();
    inboxRows = await fetch("/api/inbox").then((r) => (r.ok ? r.json() : []));
  } catch {
    inboxRows = [];
  }
  renderInbox();
  $("feedInner").replaceChildren(el(`<div class="empty-state"><h2>New feedback is waiting</h2>
    <p>Open a feedback from the inbox to review it, then start the analysis when you're ready. The quality agent checks other outlets, follows the beans through the supply chain, and proposes an action for you to approve.</p></div>`));
  setBusy(false);
}

$("askForm").addEventListener("submit", (ev) => { ev.preventDefault(); const v = $("askInput").value.trim(); if (!v) return; $("askInput").value = ""; ask(v); });
$("resetBtn").onclick = resetData;
function setShowChips(on) {
  state.showChips = on;
  $("chipsBtn").setAttribute("aria-pressed", String(on));
  try { localStorage.setItem("showChips", on ? "1" : "0"); } catch { /* not remembered: fine */ }
  chips(state.chips);
}
$("chipsBtn").onclick = () => setShowChips(!state.showChips);
setShowChips(state.showChips);
$("drawerBtn").onclick = () => { const open = $("drawer").hidden; $("drawer").hidden = !open; $("app").classList.toggle("drawer-open", open); $("drawerBtn").setAttribute("aria-pressed", String(open)); };
boot();
