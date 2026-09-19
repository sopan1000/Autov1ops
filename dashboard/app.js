// AutoOps dashboard - plain JS, no build step. Polls the agent's REST API
// every 2s. Swapping to Firestore's real-time onSnapshot listeners is a
// natural upgrade once STORE_BACKEND=firestore in production; polling is
// what keeps this runnable with zero cloud setup for local dev/demo.

const POLL_MS = 2000;
let scenarios = {};

async function fetchJSON(path, opts) {
  const res = await fetch(`${API_URL}${path}`, opts);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

async function loadScenarios() {
  try {
    scenarios = await fetchJSON("/scenarios");
    const bar = document.getElementById("triggers");
    Object.keys(scenarios).forEach((key) => {
      const btn = document.createElement("button");
      btn.textContent = key.replace(/_/g, " ");
      btn.onclick = () => triggerScenario(key);
      bar.appendChild(btn);
    });
    document.getElementById("conn-status").textContent = "● connected";
  } catch (e) {
    document.getElementById("conn-status").textContent = "● disconnected";
  }
}

async function triggerScenario(scenario) {
  await fetchJSON("/alerts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario }),
  });
  refresh();
}

async function approve(id, approved) {
  await fetchJSON(`/incidents/${id}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved }),
  });
  refresh();
}

function statusLabel(status) {
  return status.replace(/_/g, " ");
}

function renderStats(incidents) {
  const resolved = incidents.filter((i) => i.status === "resolved").length;
  const pending = incidents.filter((i) => i.status === "awaiting_approval").length;
  const stats = document.getElementById("stats");
  stats.innerHTML = `
    <div class="stat"><div class="num">${incidents.length}</div><div class="lbl">Total incidents</div></div>
    <div class="stat"><div class="num">${resolved}</div><div class="lbl">Resolved</div></div>
    <div class="stat"><div class="num">${pending}</div><div class="lbl">Awaiting approval</div></div>
  `;
}

function renderIncident(inc) {
  const diag = inc.diagnosis;
  const fix = inc.proposed_fix;
  const showActions = inc.status === "awaiting_approval";

  const traceHtml = (inc.trace || [])
    .map(
      (t) =>
        `<div class="trace-step"><b>${t.agent}</b> · ${t.action} — ${t.detail}</div>`
    )
    .join("");

  return `
    <div class="incident">
      <div class="incident-head">
        <div>
          <h3>${inc.id} <span class="sub">(${inc.scenario})</span></h3>
          <div class="alert">${inc.alert_summary}</div>
        </div>
        <span class="badge ${inc.status}">${statusLabel(inc.status)}</span>
      </div>

      ${
        diag
          ? `<div class="diagnosis">
              <div class="label">Root cause · ${(diag.confidence * 100).toFixed(0)}% confidence</div>
              ${diag.root_cause}
            </div>`
          : ""
      }

      ${
        fix
          ? `<div class="fix">
              <div class="label" style="color:var(--muted);font-size:11px;text-transform:uppercase;margin-bottom:4px;">
                Proposed fix · risk: ${fix.risk}
              </div>
              ${fix.description}<br/><code>${fix.diff}</code>
            </div>`
          : ""
      }

      ${
        showActions
          ? `<div class="actions">
              <button class="approve" onclick="approve('${inc.id}', true)">✅ Approve</button>
              <button class="reject" onclick="approve('${inc.id}', false)">❌ Reject</button>
            </div>`
          : ""
      }

      ${
        inc.resolution
          ? `<div class="fix"><div class="label" style="color:var(--muted);font-size:11px;text-transform:uppercase;margin-bottom:4px;">Resolution</div>${inc.resolution.detail}<br/><span class="sub">${inc.resolution.health_after}</span></div>`
          : ""
      }

      <details class="trace">
        <summary>Agent reasoning trace (${(inc.trace || []).length} steps)</summary>
        ${traceHtml}
      </details>
    </div>
  `;
}

async function refresh() {
  try {
    const incidents = await fetchJSON("/incidents");
    document.getElementById("conn-status").textContent = "● connected";
    renderStats(incidents);
    const container = document.getElementById("incidents");
    container.innerHTML = incidents.length
      ? incidents.map(renderIncident).join("")
      : `<div class="empty">No incidents yet — trigger a scenario above.</div>`;
  } catch (e) {
    document.getElementById("conn-status").textContent = "● disconnected";
  }
}

loadScenarios();
refresh();
setInterval(refresh, POLL_MS);
