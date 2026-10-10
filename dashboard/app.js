// AutoOps dashboard - plain JS, no build step. Polls the agent's REST API.
// Each incident card is only redrawn when that incident changes, so open
// panels and half-typed questions survive the polling refresh.

const POLL_MS = 3000;
const cards = new Map();        // incident id -> { version, el }
const openPanels = new Set();   // "<incident id>:<panel>" currently expanded
let pendingTrigger = null;      // scenario currently being investigated

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function fetchJSON(path, opts) {
  const res = await fetch(`${API_URL}${path}`, opts);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function postJSON(path, body) {
  return fetchJSON(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function seconds(fromIso, toIso) {
  const s = (new Date(toIso) - new Date(fromIso)) / 1000;
  if (!isFinite(s) || s < 0) return "";
  return s < 90 ? `${s.toFixed(1)}s` : `${(s / 60).toFixed(1)} min`;
}

async function loadHeader() {
  try {
    const health = await fetchJSON("/health");
    const engine = document.getElementById("engine");
    const offline = health.ai_engine.startsWith("offline");
    engine.textContent = `AI: ${health.ai_engine}`;
    engine.className = `engine ${offline ? "offline" : "live"}`;
    const scenarios = await fetchJSON("/scenarios");
    const bar = document.getElementById("triggers");
    Object.keys(scenarios).forEach((key) => {
      const btn = document.createElement("button");
      btn.textContent = key.replace(/_/g, " ");
      btn.title = scenarios[key];
      btn.dataset.scenario = key;
      if (key === "cert_expiry") btn.classList.add("unseen");
      btn.onclick = () => triggerScenario(key);
      bar.appendChild(btn);
    });
    setConnected(true);
  } catch (e) {
    setConnected(false);
  }
}

function setConnected(ok) {
  const el = document.getElementById("conn-status");
  el.textContent = ok ? "● connected" : "● disconnected";
  el.className = `sub ${ok ? "ok" : "bad"}`;
}

async function triggerScenario(scenario) {
  if (pendingTrigger) return;
  pendingTrigger = scenario;
  renderPending();
  document.querySelectorAll("#triggers button").forEach((b) => (b.disabled = true));
  try {
    await postJSON("/alerts", { scenario });
  } catch (e) {
    alert(`Could not trigger ${scenario}: ${e.message}`);
  } finally {
    pendingTrigger = null;
    renderPending();
    document.querySelectorAll("#triggers button").forEach((b) => (b.disabled = false));
    refresh();
  }
}

function renderPending() {
  const el = document.getElementById("pending");
  el.innerHTML = pendingTrigger
    ? `<div class="incident pending"><span class="spinner"></span>
         Alert fired for <b>${esc(pendingTrigger.replace(/_/g, " "))}</b> — AutoOps is investigating…</div>`
    : "";
}

async function approve(id, approved, btn) {
  btn.disabled = true;
  btn.textContent = approved ? "Applying fix…" : "Rejecting…";
  try {
    await postJSON(`/incidents/${id}/approve`, { approved });
  } catch (e) {
    alert(e.message);
  }
  refresh();
}

async function ask(id, form) {
  const input = form.querySelector("input");
  const question = input.value.trim();
  if (!question) return;
  const button = form.querySelector("button");
  button.disabled = true;
  button.textContent = "Thinking…";
  openPanels.add(`${id}:qa`);
  try {
    await postJSON(`/incidents/${id}/ask`, { question });
    input.value = "";
  } catch (e) {
    alert(e.message);
  }
  button.disabled = false;
  button.textContent = "Ask";
  refresh();
}

function panel(inc, name, summary, body) {
  const key = `${inc.id}:${name}`;
  return `<details data-panel="${esc(key)}" ${openPanels.has(key) ? "open" : ""}>
            <summary>${summary}</summary>${body}</details>`;
}

function timeline(inc) {
  return (inc.trace || []).map((t) => `
    <div class="step act-${esc(t.action)}">
      <span class="who agent-${esc(t.agent)}">${esc(t.agent)}</span>
      <span class="what">${esc(t.action.replace(/_/g, " "))}</span>
      <span class="detail">${esc(t.detail)}</span>
    </div>`).join("");
}

function timing(inc) {
  const marker = (inc.trace || []).find((t) => ["fix_proposed", "escalated"].includes(t.action));
  const bits = [];
  if (marker) bits.push(`diagnosed in <b>${seconds(inc.created_at, marker.timestamp)}</b>`);
  if (inc.status === "resolved" && inc.resolution) {
    bits.push(`resolved in <b>${seconds(inc.created_at, inc.resolution.verified_at || inc.updated_at)}</b>`);
  }
  return bits.length ? `<div class="timing">⏱ ${bits.join(" · ")}</div>` : "";
}

function renderIncident(inc) {
  const d = inc.diagnosis;
  const f = inc.proposed_fix;
  const offline = (inc.ai_engine || "").startsWith("offline");
  const tools = (inc.trace || []).filter((t) => t.action === "tool_call").length;

  const diagnosis = d ? `
    <div class="block">
      <div class="label">Root cause · ${(d.confidence * 100).toFixed(0)}% confidence · ${esc(d.root_cause_type)}</div>
      <div>${esc(d.root_cause)}</div>
      ${d.evidence.length ? `<ul class="evidence">${d.evidence.slice(0, 4).map((e) => `<li>${esc(e)}</li>`).join("")}</ul>` : ""}
    </div>` : "";

  const fix = f ? `
    <div class="block ${f.fix_id === "escalate" ? "escalate" : ""}">
      <div class="label">${f.fix_id === "escalate" ? "Escalated to on-call" : `Proposed fix · risk: ${esc(f.risk)}`}</div>
      <div>${esc(f.description)}</div>
      ${f.fix_id !== "escalate" ? `<code>${esc(f.diff)}</code>` : ""}
      ${f.justification ? `<div class="why"><b>Why:</b> ${esc(f.justification)}</div>` : ""}
      ${f.alternatives_rejected.length ? `<div class="why"><b>Ruled out:</b> ${f.alternatives_rejected.map(esc).join(" · ")}</div>` : ""}
    </div>` : "";

  const actions = inc.status === "awaiting_approval" ? `
    <div class="actions">
      <button class="approve" data-act="approve">✅ Approve fix</button>
      <button class="reject" data-act="reject">❌ Reject</button>
    </div>` : "";

  const resolution = inc.resolution ? `
    <div class="block ${inc.resolution.success ? "ok" : "bad"}">
      <div class="label">Resolution · verified after ${inc.resolution.verification_attempts} check(s)</div>
      ${esc(inc.resolution.detail)}<div class="sub">${esc(inc.resolution.health_after)}</div>
    </div>` : "";

  const qa = (inc.qa || []).map((q) => `
    <div class="qa"><div class="q">Q: ${esc(q.question)}</div><div class="a">${esc(q.answer)}</div>
    <div class="sub">${esc(q.engine)}</div></div>`).join("");

  return `
    <div class="incident-head">
      <div>
        <h3>${esc(inc.scenario.replace(/_/g, " "))} <span class="sub">${esc(inc.id)}</span></h3>
        <div class="alert">${esc(inc.alert_summary)}</div>
      </div>
      <div class="right">
        <span class="badge ${esc(inc.status)}">${esc(inc.status.replace(/_/g, " "))}</span>
        <span class="engine-tag ${offline ? "offline" : "live"}">${esc(inc.ai_engine || "")}</span>
      </div>
    </div>
    ${timing(inc)}
    ${diagnosis}${fix}${actions}${resolution}
    ${panel(inc, "trace", `Agent reasoning trace · ${(inc.trace || []).length} steps${tools ? ` · ${tools} tool calls` : ""}`,
            `<div class="timeline">${timeline(inc)}</div>`)}
    ${inc.postmortem ? panel(inc, "pm", "Postmortem", `<pre class="pm">${esc(inc.postmortem)}</pre>`) : ""}
    ${panel(inc, "qa", `Ask AutoOps${inc.qa && inc.qa.length ? ` · ${inc.qa.length}` : ""}`, `
      ${qa}
      <form class="ask"><input maxlength="1000" placeholder="e.g. Why not just restart the api?" />
      <button type="submit">Ask</button></form>`)}
  `;
}

function bindCard(inc, el) {
  el.querySelectorAll("details").forEach((d) => d.addEventListener("toggle", () => {
    d.open ? openPanels.add(d.dataset.panel) : openPanels.delete(d.dataset.panel);
  }));
  el.querySelectorAll("button[data-act]").forEach((b) =>
    b.addEventListener("click", () => approve(inc.id, b.dataset.act === "approve", b)));
  const form = el.querySelector("form.ask");
  form.addEventListener("submit", (e) => { e.preventDefault(); ask(inc.id, form); });
}

function renderStats(incidents) {
  const count = (s) => incidents.filter((i) => i.status === s).length;
  document.getElementById("stats").innerHTML = `
    <div class="stat"><div class="num">${incidents.length}</div><div class="lbl">Incidents</div></div>
    <div class="stat"><div class="num">${count("awaiting_approval")}</div><div class="lbl">Awaiting approval</div></div>
    <div class="stat"><div class="num">${count("resolved")}</div><div class="lbl">Resolved</div></div>
    <div class="stat"><div class="num">${count("escalated")}</div><div class="lbl">Escalated</div></div>`;
}

async function refresh() {
  let incidents;
  try {
    incidents = await fetchJSON("/incidents");
    setConnected(true);
  } catch (e) {
    setConnected(false);
    return;
  }
  renderStats(incidents);
  const container = document.getElementById("incidents");
  const empty = document.getElementById("empty");
  empty.style.display = incidents.length || pendingTrigger ? "none" : "block";

  const seen = new Set();
  incidents.forEach((inc, index) => {
    seen.add(inc.id);
    const version = `${inc.updated_at}|${(inc.qa || []).length}`;
    let entry = cards.get(inc.id);
    if (!entry || entry.version !== version) {
      const el = document.createElement("div");
      el.className = "incident";
      const typing = entry && entry.el.querySelector("form.ask input");
      const draft = typing && document.activeElement === typing ? typing.value : null;
      el.innerHTML = renderIncident(inc);
      bindCard(inc, el);
      if (draft !== null) {
        const input = el.querySelector("form.ask input");
        input.value = draft;
        setTimeout(() => input.focus(), 0);
      }
      if (entry) entry.el.replaceWith(el);
      entry = { version, el };
      cards.set(inc.id, entry);
    }
    if (container.children[index] !== entry.el) container.insertBefore(entry.el, container.children[index] || null);
  });
  for (const [id, entry] of cards) {
    if (!seen.has(id)) { entry.el.remove(); cards.delete(id); }
  }
}

loadHeader();
refresh();
setInterval(refresh, POLL_MS);
