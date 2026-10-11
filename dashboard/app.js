// AutoOps incident console. Plain JS, no build step.
// Polls the agent API. The detail panel only re-renders when the selected
// incident changes, so a half-typed question or scroll position survives refreshes.

const POLL_MS = 3000;

const SCENARIOS = {
  bad_deploy:    { title: "Worker jobs failing", service: "worker" },
  oom_leak:      { title: "Worker pods restarting", service: "worker" },
  db_exhaustion: { title: "API error rate spike", service: "api" },
  bad_config:    { title: "API can't reach the database", service: "api" },
  cert_expiry:   { title: "Checkout returning 502s", service: "api" },
  vendor_outage: { title: "Checkout returning 503s", service: "api" },
  stuck_worker:  { title: "Worker queue backing up", service: "worker" },
  poisoned_logs: { title: "Payment worker crashing", service: "worker" },
};
const GUARDRAIL_DEMO = new Set(["poisoned_logs"]);
const OUTSIDE_RULES = new Set(["cert_expiry", "vendor_outage", "stuck_worker"]);
const STATUS_LABEL = {
  detected: "Detected", diagnosing: "Investigating", awaiting_approval: "Needs approval",
  remediating: "Applying fix", verifying: "Verifying", resolved: "Resolved",
  escalated: "Escalated", rejected: "Fix rejected", failed: "Failed",
};
const AGENT_LABEL = {
  guardrails: "Guardrails", watcher: "Watcher", investigator: "Investigator", diagnoser: "Diagnoser",
  remediation_planner: "Planner", remediator: "Remediator", orchestrator: "Orchestrator",
  executor: "Executor", scribe: "Scribe", ask_autoops: "Ask AutoOps",
};
const AI_AGENTS = new Set(["investigator", "diagnoser", "remediation_planner", "scribe", "ask_autoops"]);
const SUGGESTED = [
  "Why this fix and not a restart?",
  "What evidence points to the root cause?",
  "How do we stop this happening again?",
];

const state = {
  view: "incidents",
  incidents: [],
  selectedId: null,
  tab: "investigation",
  pending: null,
  detailKey: "",
  health: null,
};

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function fetchJSON(path, opts) {
  const res = await fetch(`${API_URL}${path}`, opts);
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch (_) { /* not JSON */ }
    throw new Error(detail || `${path} returned ${res.status}`);
  }
  return res.json();
}

const postJSON = (path, body) => fetchJSON(path, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

function duration(fromIso, toIso) {
  const s = (new Date(toIso) - new Date(fromIso)) / 1000;
  if (!isFinite(s) || s < 0) return "";
  if (s < 60) return `${s.toFixed(1)} s`;
  if (s < 3600) return `${(s / 60).toFixed(1)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

function ago(iso) {
  const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

const clock = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const titleOf = (inc) => (SCENARIOS[inc.scenario] || {}).title || inc.scenario.replace(/_/g, " ");
const serviceOf = (inc) => (SCENARIOS[inc.scenario] || {}).service || (inc.alert_summary.split(" service")[0] || "");
const isOffline = (engine) => !engine || engine.startsWith("offline");
const stepTime = (inc, ...actions) => (inc.trace || []).find((t) => actions.includes(t.action))?.timestamp;
const sentence = (s) => s ? s.charAt(0).toUpperCase() + s.slice(1) : s;

/* ---------- Engine + scenarios ---------- */

async function loadHealth() {
  const box = $("engine");
  try {
    state.health = await fetchJSON("/health");
    const engine = state.health.ai_engine;
    if (isOffline(engine)) {
      box.className = "engine offline";
      $("engine-name").textContent = "Offline engine";
      $("engine-sub").textContent = "Gemini is turned off";
    } else {
      box.className = "engine live";
      $("engine-name").textContent = engine.replace(/ via ADK$/, "");
      $("engine-sub").textContent = "Gemini via Agent Development Kit";
    }
  } catch (e) {
    box.className = "engine down";
    $("engine-name").textContent = "Agent unreachable";
    $("engine-sub").textContent = "Is the API running?";
  }
}

async function loadScenarios() {
  let alerts = {};
  try { alerts = await fetchJSON("/scenarios"); } catch (_) { return; }
  const keys = Object.keys(alerts);
  const known = keys.filter((k) => !OUTSIDE_RULES.has(k));
  const novel = keys.filter((k) => OUTSIDE_RULES.has(k));
  const item = (k) => `
    <button class="menu-item" role="menuitem" data-scenario="${esc(k)}">
      <span class="menu-title">${esc((SCENARIOS[k] || {}).title || k)}
        ${OUTSIDE_RULES.has(k) ? '<span class="tag">Needs Gemini</span>' : ""}
        ${GUARDRAIL_DEMO.has(k) ? '<span class="tag tag-guard">Secrets + injection</span>' : ""}</span>
      <span class="menu-desc">${esc(alerts[k])}</span>
    </button>`;
  $("simulate-menu").innerHTML =
    known.map(item).join("") +
    (novel.length ? `<div class="menu-sep"></div>
      <div class="menu-note">No built-in rule covers these. Without Gemini they escalate to a human.</div>
      ${novel.map(item).join("")}` : "");
}

function toggleMenu(open) {
  const menu = $("simulate-menu");
  const show = open ?? menu.hidden;
  menu.hidden = !show;
  $("simulate-btn").setAttribute("aria-expanded", String(show));
  if (show) menu.querySelector(".menu-item")?.focus();
}

async function simulate(scenario) {
  toggleMenu(false);
  if (state.pending) return;
  state.pending = scenario;
  $("simulate-btn").disabled = true;
  renderList();
  try {
    const incident = await postJSON("/alerts", { scenario });
    state.selectedId = incident.id;
    state.tab = "investigation";
  } catch (e) {
    alert(`Could not simulate this incident: ${e.message}`);
  } finally {
    state.pending = null;
    $("simulate-btn").disabled = false;
    await refresh();
  }
}

/* ---------- Data refresh ---------- */

async function refresh() {
  try {
    state.incidents = await fetchJSON("/incidents");
  } catch (e) {
    $("engine").className = "engine down";
    $("engine-name").textContent = "Agent unreachable";
    return;
  }
  if (!state.selectedId && state.incidents.length && window.innerWidth > 960) {
    state.selectedId = state.incidents[0].id;
  }
  renderStats();
  renderList();
  renderDetail();
  if (state.view === "runbooks") loadRunbooks();
}

function renderStats() {
  const n = (s) => state.incidents.filter((i) => i.status === s).length;
  const open = n("awaiting_approval");
  const diag = state.incidents
    .map((i) => {
      const t = stepTime(i, "fix_proposed", "escalated");
      return t ? (new Date(t) - new Date(i.created_at)) / 1000 : null;
    })
    .filter((x) => x !== null)
    .sort((a, b) => a - b);
  const median = diag.length ? diag[Math.floor(diag.length / 2)] : null;
  $("stats").innerHTML = state.incidents.length ? `
    <span class="stat ${open ? "attn" : ""}"><b>${open}</b> need approval</span>
    <span class="stat"><b>${n("resolved")}</b> resolved</span>
    <span class="stat"><b>${n("escalated")}</b> escalated</span>
    ${median !== null ? `<span class="stat">Median time to diagnose <b>${median.toFixed(1)} s</b></span>` : ""}`
    : `<span class="stat">Nothing has broken yet</span>`;
  const badge = $("nav-open");
  badge.hidden = !open;
  badge.textContent = open;
}

/* ---------- Incident list ---------- */

function renderList() {
  const list = $("incident-list");
  const pending = state.pending ? `
    <div class="row pending">
      <span class="spinner"></span>
      <span class="row-title">${esc((SCENARIOS[state.pending] || {}).title || state.pending)}</span>
      <span class="row-time">now</span>
      <span class="row-meta">AutoOps is investigating…</span>
    </div>` : "";
  if (!state.incidents.length && !pending) {
    list.innerHTML = `<div class="list-empty"><b>No incidents yet</b>
      Use <em>Simulate incident</em> to break something on purpose and watch AutoOps respond.</div>`;
    return;
  }
  list.innerHTML = pending + state.incidents.map((inc) => `
    <button class="row status-${esc(inc.status)} ${inc.id === state.selectedId ? "selected" : ""}" data-id="${esc(inc.id)}">
      <span class="row-dot"></span>
      <span class="row-title">${esc(titleOf(inc))}</span>
      <span class="row-time">${esc(ago(inc.created_at))}</span>
      <span class="row-meta">
        <span class="pill pill-${esc(inc.status)}">${esc(STATUS_LABEL[inc.status] || inc.status)}</span>
        ${esc(serviceOf(inc))}
        ${(inc.guardrails && inc.guardrails.injection_flags.length) ? '<span class="flag">Injection flagged</span>' : ""}
      </span>
    </button>`).join("");
}

/* ---------- Detail ---------- */

function renderRail(inc) {
  const steps = [];
  const start = inc.created_at;
  const rel = (t) => (t ? `+${duration(start, t)}` : "");
  steps.push({ label: "Alert received", time: clock(start), cls: "done" });

  const diagnosed = stepTime(inc, "diagnosis");
  steps.push({ label: "Diagnosed", time: rel(diagnosed), cls: diagnosed ? "done" : "current" });

  if (inc.status === "escalated") {
    steps.push({ label: "Escalated to on-call", time: rel(stepTime(inc, "escalated")), cls: "final-esc" });
  } else {
    const proposed = stepTime(inc, "fix_proposed");
    steps.push({ label: "Fix proposed", time: rel(proposed), cls: proposed ? "done" : "" });

    const approved = stepTime(inc, "approved", "auto_approved");
    const rejected = stepTime(inc, "rejected");
    if (rejected) steps.push({ label: "Fix rejected", time: rel(rejected), cls: "final-bad" });
    else steps.push({
      label: stepTime(inc, "auto_approved") ? "Auto-approved" : approved ? "Approved" : "Awaiting approval",
      time: approved ? rel(approved) : "waiting for an engineer",
      cls: approved ? "done" : inc.status === "awaiting_approval" ? "current" : "",
    });

    if (!rejected) {
      const verified = inc.resolution && inc.resolution.verified_at;
      if (inc.status === "resolved") steps.push({ label: "Recovery verified", time: rel(verified || inc.updated_at), cls: "final-ok" });
      else if (inc.status === "failed") steps.push({ label: "Not recovered", time: rel(inc.updated_at), cls: "final-bad" });
      else steps.push({ label: "Recovery verified", time: "", cls: "" });
    }
  }

  const proposedAt = stepTime(inc, "fix_proposed", "escalated");
  let total = "";
  if (inc.status === "resolved") {
    total = `Alert to verified recovery in <b>${duration(start, (inc.resolution && inc.resolution.verified_at) || inc.updated_at)}</b>` +
      (proposedAt ? `, of which AutoOps needed <b>${duration(start, proposedAt)}</b> to diagnose and propose the fix.` : ".");
  } else if (inc.status === "awaiting_approval" && proposedAt) {
    total = `AutoOps diagnosed this and proposed a fix in <b>${duration(start, proposedAt)}</b>.`;
  } else if (inc.status === "escalated" && proposedAt) {
    total = `Diagnosed in <b>${duration(start, proposedAt)}</b>. No safe automated fix exists, so a human takes it from here.`;
  }

  return `<div class="rail" style="--steps:${steps.length}">
    ${steps.map((s, i) => `
      <div class="rail-step ${s.cls} ${i === steps.length - 1 ? "last" : ""}">
        <span class="rail-node"></span>
        <div class="rail-label">${esc(s.label)}</div>
        <div class="rail-time">${esc(s.time)}</div>
      </div>`).join("")}
    ${total ? `<div class="rail-total">${total}</div>` : ""}
  </div>`;
}

const MASK_LABEL = {
  password: "password", secret: "secret", token: "token", jwt: "JWT", google_api_key: "Google API key",
  aws_access_key: "AWS key", github_token: "GitHub token", slack_token: "Slack token", api_secret: "API secret",
  private_key: "private key", email: "email", card_number: "card number", aadhaar: "Aadhaar",
  pan: "PAN", phone: "phone", ip_address: "public IP",
};

function renderGuardrails(inc) {
  const g = inc.guardrails || { masked: {}, injection_flags: [] };
  const total = Object.values(g.masked).reduce((a, b) => a + b, 0);
  const kinds = Object.entries(g.masked).sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `<span class="mask-chip">${esc(MASK_LABEL[k] || k)}${n > 1 ? ` ×${n}` : ""}</span>`).join("");
  const banner = g.injection_flags.length ? `
    <div class="injection" role="alert">
      <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.5l7.5 13H2.5z"/><path d="M10 8v3.5M10 13.6v.1"/></svg>
      <div>
        <b>Possible prompt injection in the evidence</b>
        <p>Something in the logs tried to give the AI instructions. AutoOps treated it as data and did not follow it.
        Auto-approval is off for this incident, so review the evidence before approving.</p>
        <code>${esc(g.injection_flags[0])}</code>
      </div>
    </div>` : "";
  return `${banner}
    <div class="guard">
      <svg class="guard-icon" viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.5l6 2.2v4.6c0 3.9-2.6 6.9-6 8.2-3.4-1.3-6-4.3-6-8.2V4.7z"/><path d="M7.5 10l1.8 1.8 3.4-3.6"/></svg>
      <span>${total
        ? `<b>${total} sensitive value${total === 1 ? "" : "s"} masked</b> before the evidence reached Gemini, the database or this screen`
        : "No secrets or personal data found in the evidence"}</span>
      ${kinds ? `<span class="mask-chips">${kinds}</span>` : ""}
    </div>`;
}

function renderCause(inc) {
  const d = inc.diagnosis;
  if (!d) return "";
  const pct = Math.round(d.confidence * 100);
  return `<section class="section">
    <h3>Root cause</h3>
    <p class="cause">${esc(d.root_cause)}</p>
    <div class="cause-meta">
      <span class="meter" title="${pct}% confidence"><i style="width:${pct}%"></i></span>
      <span>${pct}% confidence</span>
      <span>Category <code>${esc(d.root_cause_type)}</code></span>
    </div>
    ${d.evidence.length ? `<ul class="evidence">${d.evidence.slice(0, 5).map((e) => `<li>${esc(e)}</li>`).join("")}</ul>` : ""}
  </section>`;
}

function renderFix(inc) {
  const f = inc.proposed_fix;
  if (!f) return "";
  if (f.fix_id === "escalate") {
    return `<section class="section"><div class="escalation">
      <h3>Escalated to on-call</h3>
      <p class="fix-desc">${esc(f.justification || f.description)}</p>
      <p class="placeholder">No change was made to the system.</p>
      ${f.alternatives_rejected.length ? `<dl class="reasoning"><dt>Ruled out</dt><dd><ul>
        ${f.alternatives_rejected.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></dd></dl>` : ""}
    </div></section>`;
  }
  const actions = inc.status === "awaiting_approval" ? `
    <div class="actions">
      <button class="btn btn-approve" data-act="approve">
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4.5 10.5l3.5 3.5 7.5-8"/></svg>Approve fix</button>
      <button class="btn" data-act="reject">Reject</button>
    </div>` : "";
  return `<section class="section">
    <div class="fix-head">
      <h3>Proposed fix</h3>
      <span class="risk risk-${esc(f.risk)}">Risk <b>${esc(f.risk)}</b></span>
    </div>
    <p class="fix-desc">${esc(f.description)}</p>
    <code class="command">${esc(f.diff)}</code>
    <dl class="reasoning">
      ${f.justification ? `<dt>Why</dt><dd>${esc(f.justification)}</dd>` : ""}
      ${f.alternatives_rejected.length ? `<dt>Ruled out</dt><dd><ul>
        ${f.alternatives_rejected.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></dd>` : ""}
      <dt>If it fails</dt><dd>${esc(f.rollback_plan)}</dd>
    </dl>
    ${actions}
  </section>`;
}

function renderResolution(inc) {
  const r = inc.resolution;
  if (!r) return "";
  const icon = r.success
    ? '<svg class="resolution-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.8 2.8L16.5 9"/></svg>'
    : '<svg class="resolution-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.4v.1"/></svg>';
  return `<section class="section"><div class="resolution ${r.success ? "ok" : "bad"}">${icon}
    <div><p>${esc(r.success ? "Fix applied and recovery verified" : "Fix applied but recovery was not verified")}</p>
    <p class="sub">${esc(r.detail)}</p><p class="sub">${esc(r.health_after)} (${r.verification_attempts} check${r.verification_attempts === 1 ? "" : "s"})</p></div>
  </div></section>`;
}

function renderTimeline(inc) {
  return `<ol class="timeline">${(inc.trace || []).map((t) => {
    const cls = [
      AI_AGENTS.has(t.agent) ? "agent-step" : "",
      t.action.startsWith("tool_") ? "tool" : "",
      ["gemini_unavailable", "escalated", "verification_failed", "pipeline_failed", "injection_detected", "auto_approval_blocked"].includes(t.action) ? "warn" : "",
      t.agent === "guardrails" ? "guard-step" : "",
    ].join(" ");
    return `<li class="tl ${cls}">
      <span class="tl-t">+${esc(duration(inc.created_at, t.timestamp) || "0.0 s")}</span>
      <span class="tl-who">${esc(AGENT_LABEL[t.agent] || t.agent)}<small>${esc(sentence(t.action.replace(/_/g, " ")))}</small></span>
      <span class="tl-what">${esc(t.detail)}</span>
    </li>`;
  }).join("")}</ol>`;
}

function markdown(md) {
  const lines = esc(md).split(/\r?\n/);
  const out = [];
  let list = false;
  const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>").replace(/(^|\s)_(.+?)_(?=\s|$)/g, "$1<i>$2</i>");
  for (const raw of lines) {
    const line = raw.trim();
    const bullet = line.match(/^[-*]\s+(.*)/) || line.match(/^\d+\.\s+(.*)/);
    if (bullet) {
      if (!list) { out.push("<ul>"); list = true; }
      out.push(`<li>${inline(bullet[1])}</li>`);
      continue;
    }
    if (list) { out.push("</ul>"); list = false; }
    const heading = line.match(/^#{1,4}\s+(.*)/);
    if (heading) out.push(`<h3>${inline(heading[1])}</h3>`);
    else if (line) out.push(`<p>${inline(line)}</p>`);
  }
  if (list) out.push("</ul>");
  return out.join("");
}

function renderTabPanel(inc) {
  if (state.tab === "postmortem") {
    return inc.postmortem
      ? `<div class="prose">${markdown(inc.postmortem)}</div>`
      : `<p class="placeholder">The postmortem is written automatically once a fix is approved and recovery is verified.</p>`;
  }
  if (state.tab === "ask") {
    const chat = (inc.qa || []).map((q) => `
      <div class="msg-q">${esc(q.question)}</div>
      <div class="msg-a">${esc(q.answer)}<small>${esc(q.engine)}</small></div>`).join("");
    return `<div class="chat">${chat || '<p class="placeholder">Ask anything about this incident. Answers come from its evidence, diagnosis and fix decision.</p>'}</div>
      <form class="ask" data-form="ask">
        <input name="q" maxlength="1000" autocomplete="off" placeholder="Ask about this incident" aria-label="Question about this incident">
        <button class="btn btn-primary" type="submit">Ask</button>
      </form>
      ${(inc.qa || []).length ? "" : `<div class="suggestions">${SUGGESTED.map((s) => `<button class="chip" data-suggest="${esc(s)}">${esc(s)}</button>`).join("")}</div>`}`;
  }
  return renderTimeline(inc);
}

function renderDetail(force = false) {
  const box = $("detail");
  const inc = state.incidents.find((i) => i.id === state.selectedId);
  if (!inc) {
    state.detailKey = "";
    box.innerHTML = `<div class="detail-empty">${state.incidents.length
      ? "Select an incident to see what AutoOps found."
      : "When an alert fires, AutoOps investigates it and shows its findings here."}</div>`;
    return;
  }
  const key = `${inc.id}|${inc.updated_at}|${(inc.qa || []).length}|${state.tab}`;
  if (!force && key === state.detailKey) return;
  state.detailKey = key;

  const input = box.querySelector('input[name="q"]');
  const draft = input ? input.value : "";
  const hadFocus = input && document.activeElement === input;
  const sameIncident = box.dataset.incident === inc.id;
  const scroll = sameIncident ? box.scrollTop : 0;

  const tools = (inc.trace || []).filter((t) => t.action === "tool_call").length;
  const tab = (id, label, count) =>
    `<button class="tab" role="tab" data-tab="${id}" aria-selected="${state.tab === id}">${label}${count ? `<span class="count">${count}</span>` : ""}</button>`;

  box.innerHTML = `
    <header class="detail-head">
      <div class="detail-title-row">
        <div>
          <h2>${esc(titleOf(inc))}</h2>
          <p class="detail-alert">${esc(inc.alert_summary)}</p>
        </div>
        <span class="pill pill-${esc(inc.status)}">${esc(STATUS_LABEL[inc.status] || inc.status)}</span>
      </div>
      <div class="detail-ids">
        <span>Incident <b class="mono">${esc(inc.id)}</b></span>
        <span>Service <b>${esc(serviceOf(inc))}</b></span>
        <span class="engine-chip ${isOffline(inc.ai_engine) ? "offline" : ""}">${esc(isOffline(inc.ai_engine) ? "Offline engine" : inc.ai_engine)}</span>
      </div>
    </header>
    ${renderGuardrails(inc)}
    ${renderRail(inc)}
    ${renderCause(inc)}
    ${renderFix(inc)}
    ${renderResolution(inc)}
    <div class="tabs" role="tablist">
      ${tab("investigation", "Investigation", tools ? `${tools} tool calls` : "")}
      ${tab("postmortem", "Postmortem")}
      ${tab("ask", "Ask AutoOps", (inc.qa || []).length || "")}
    </div>
    <div class="tab-panel" role="tabpanel">${renderTabPanel(inc)}</div>`;

  const newInput = box.querySelector('input[name="q"]');
  if (newInput && draft) newInput.value = draft;
  if (newInput && hadFocus) newInput.focus();
  box.dataset.incident = inc.id;
  box.scrollTop = scroll;
}

/* ---------- Actions ---------- */

async function decide(approved, button) {
  const id = state.selectedId;
  button.disabled = true;
  button.textContent = approved ? "Applying fix…" : "Rejecting…";
  try {
    await postJSON(`/incidents/${encodeURIComponent(id)}/approve`, { approved });
  } catch (e) {
    alert(e.message);
  }
  await refresh();
}

async function ask(question, form) {
  if (!question.trim()) return;
  const button = form ? form.querySelector("button") : null;
  if (button) { button.disabled = true; button.innerHTML = '<span class="spinner"></span> Thinking'; }
  try {
    await postJSON(`/incidents/${encodeURIComponent(state.selectedId)}/ask`, { question });
    const input = $("detail").querySelector('input[name="q"]');
    if (input) input.value = "";
  } catch (e) {
    alert(e.message);
  }
  await refresh();
}

async function loadRunbooks() {
  let runbooks = [];
  try { runbooks = await fetchJSON("/runbooks"); } catch (_) { return; }
  const count = $("nav-runbooks");
  count.hidden = !runbooks.length;
  count.textContent = runbooks.length;
  const open = new Set([...document.querySelectorAll(".rb[open]")].map((d) => d.dataset.id));
  $("runbooks").innerHTML = runbooks.length ? runbooks.map((rb) => `
    <details class="rb" data-id="${esc(rb.id)}" ${open.has(rb.id) ? "open" : ""}>
      <summary>
        <span class="rb-title">${esc((SCENARIOS[rb.scenario] || {}).title || rb.scenario)}</span>
        <span class="rb-when">${esc(ago(rb.created_at))}</span>
        <span class="rb-fix">${esc(rb.fix_applied)}</span>
      </summary>
      <div class="prose">${markdown(rb.summary)}</div>
    </details>`).join("")
    : `<div class="list-empty"><b>No runbooks yet</b>Approve a fix on any incident. Once recovery is verified, AutoOps writes the postmortem and saves it here.</div>`;
}

function setView(view) {
  state.view = view;
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $("view-incidents").hidden = view !== "incidents";
  $("view-runbooks").hidden = view !== "runbooks";
  if (view === "runbooks") loadRunbooks();
}

/* ---------- Events ---------- */

document.querySelector(".nav").addEventListener("click", (e) => {
  const item = e.target.closest(".nav-item");
  if (item) setView(item.dataset.view);
});

$("simulate-btn").addEventListener("click", (e) => { e.stopPropagation(); toggleMenu(); });
$("simulate-menu").addEventListener("click", (e) => {
  const item = e.target.closest("[data-scenario]");
  if (item) simulate(item.dataset.scenario);
});
document.addEventListener("click", (e) => {
  if (!e.target.closest(".simulate")) toggleMenu(false);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("simulate-menu").hidden) { toggleMenu(false); $("simulate-btn").focus(); }
});

$("incident-list").addEventListener("click", (e) => {
  const row = e.target.closest(".row[data-id]");
  if (!row) return;
  if (row.dataset.id !== state.selectedId) state.tab = "investigation";
  state.selectedId = row.dataset.id;
  renderList();
  renderDetail(true);
  if (window.innerWidth <= 960) $("detail").scrollIntoView({ behavior: "smooth", block: "start" });
});

$("detail").addEventListener("click", (e) => {
  const act = e.target.closest("[data-act]");
  if (act) return decide(act.dataset.act === "approve", act);
  const tab = e.target.closest("[data-tab]");
  if (tab) { state.tab = tab.dataset.tab; return renderDetail(true); }
  const chip = e.target.closest("[data-suggest]");
  if (chip) return ask(chip.dataset.suggest, $("detail").querySelector('form[data-form="ask"]'));
});

$("detail").addEventListener("submit", (e) => {
  const form = e.target.closest('form[data-form="ask"]');
  if (!form) return;
  e.preventDefault();
  ask(form.q.value, form);
});

loadHealth();
loadScenarios();
refresh();
setInterval(refresh, POLL_MS);
setInterval(loadHealth, 30000);
