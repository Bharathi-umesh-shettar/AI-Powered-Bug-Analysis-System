/* Intelligent Bug Diagnosis Platform with Fix Recommendation Assistance — UI */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function notify(text, kind = "success") {
  const box = $("#message");
  box.textContent = text;
  box.className = `message ${kind}`;
}

async function api(url, options = {}) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

/* ------------------------------------------------------------------ tabs */
$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach((t) => t.classList.remove("active"));
    $$(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    $(`#panel-${tab.dataset.tab}`).classList.add("active");
    if (tab.dataset.tab === "analytics") loadAnalytics();
    if (tab.dataset.tab === "watch") loadWatch();
    if (tab.dataset.tab === "knowledge") loadKnowledge();
    if (tab.dataset.tab === "bugs") loadBugs();
  });
});

/* -------------------------------------------------------------- findings */
function list(items) {
  if (!items || !items.length) return "<p class='muted small'>None.</p>";
  return `<ul>${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`;
}

function renderFindings(bug, f) {
  if (!f) {
    $("#findings").innerHTML = "<p class='muted'>No analysis stored for this bug yet.</p>";
    return;
  }
  const dup = f.duplicate || {};
  const rem = f.remediation || {};
  const an = f.analysis || {};
  $("#findings").innerHTML = `
    <div class="finding-block">
      <h4>Bug summary</h4>
      <p>${esc(f.bug_summary)}</p>
      <p class="small muted">Bug #${esc(bug.id)} &middot; ${esc(f.severity)} &middot;
        component ${esc(f.component)} &middot; error types: ${esc((f.error_types || []).join(", "))}</p>
    </div>
    <div class="finding-block">
      <h4>Possible root cause (confidence ${esc(((f.root_cause_confidence || 0) * 100).toFixed(0))}%)</h4>
      <p>${esc(f.possible_root_cause)}</p>
      <p class="small muted">Basis: ${esc(f.root_cause_basis)}</p>
      ${an.explanation ? `<p class="small">${esc(an.explanation)}</p>` : ""}
    </div>
    <div class="finding-block">
      <h4>Duplicate detection — ${esc(dup.status)} (${esc(((dup.confidence || 0) * 100).toFixed(0))}%)</h4>
      <p>${esc(dup.explanation)}</p>
      ${dup.shared_terms && dup.shared_terms.length
        ? `<p class="small muted">Shared terms: ${esc(dup.shared_terms.join(", "))}</p>` : ""}
    </div>
    <div class="finding-block">
      <h4>Recommended fix</h4>
      <p>${esc(f.recommended_fix)}</p>
      <h4>Fix steps</h4>${list(rem.fix_steps)}
      <h4>Verification</h4>${list(rem.verification_steps)}
      <h4>Preventive actions</h4>${list(rem.preventive_actions)}
    </div>
    <div class="finding-block">
      <h4>Supporting evidence (RAG)</h4>
      ${list((f.supporting_evidence || []).map((e) => (typeof e === "string" ? e : JSON.stringify(e))))}
    </div>
    <div class="finding-block">
      <h4>Similar historical bugs</h4>
      <div class="table-wrapper"><table><thead>
        <tr><th>KB ID</th><th>Title</th><th>Severity</th><th>Root cause</th><th>Suggested fix</th><th>Score</th></tr>
      </thead><tbody>
      ${(f.similar_bugs || []).map((s) => `<tr>
        <td>${esc(s.bug_id)}</td><td>${esc(s.title)}</td>
        <td><span class="badge ${esc(s.severity)}">${esc(s.severity)}</span></td>
        <td>${esc(s.root_cause)}</td><td>${esc(s.suggested_fix)}</td>
        <td>${esc(s.similarity)}</td></tr>`).join("") ||
        "<tr><td colspan='6' class='muted'>No similar bugs found.</td></tr>"}
      </tbody></table></div>
      <p class="small muted">Next action: ${esc(f.next_action)}</p>
    </div>`;

  $("#findings-actions").classList.remove("hidden");
  $("#pdf-link").href = `/api/bugs/${bug.id}/report.pdf`;
  $("#csv-link").href = `/api/bugs/${bug.id}/report.csv`;
}

/* ---------------------------------------------------------------- submit */
$("#bug-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  notify("Running multi-agent diagnosis...");
  try {
    const payload = {
      title: $("#title").value,
      description: $("#description").value,
      severity: $("#severity").value,
      component: $("#component").value,
      environment: $("#environment").value,
      error_message: $("#error_message").value,
      stack_trace: $("#stack_trace").value,
      additional_info: $("#additional_info").value,
    };
    const data = await api("/submit-bug", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    notify(`${data.message} (bug #${data.bug.id})`);
    renderFindings(data.bug, data.findings);
    $("#bug-form").reset();
    loadBugs();
  } catch (err) {
    notify(err.message, "error");
  }
});

$("#upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = $("#file").files[0];
  if (!file) return notify("Choose a .txt or .log file first.", "error");
  const fd = new FormData();
  fd.append("file", file);
  notify("Parsing and diagnosing the uploaded report...");
  try {
    const data = await api("/upload-bug", { method: "POST", body: fd });
    notify(`${data.message} (bug #${data.bug.id})`);
    renderFindings(data.bug, data.findings);
    loadBugs();
  } catch (err) {
    notify(err.message, "error");
  }
});

/* ------------------------------------------------------------------ bugs */
async function loadBugs() {
  const params = new URLSearchParams();
  if ($("#filter-q").value.trim()) params.set("q", $("#filter-q").value.trim());
  if ($("#filter-status").value) params.set("status", $("#filter-status").value);
  if ($("#filter-severity").value) params.set("severity", $("#filter-severity").value);
  try {
    const { bugs } = await api(`/api/bugs?${params.toString()}`);
    $("#bugs-table tbody").innerHTML = bugs.map((b) => `<tr>
      <td>${esc(b.id)}</td>
      <td>${esc(b.title)}</td>
      <td><span class="badge ${esc(b.severity)}">${esc(b.severity)}</span></td>
      <td>${esc(b.component || "-")}</td>
      <td>${esc(b.status || "Open")}${b.in_knowledge_base ? " &middot; KB" : ""}</td>
      <td>${esc(b.duplicate_status || "-")}${b.duplicate_of ? ` #${esc(b.duplicate_of)}` : ""}</td>
      <td>${esc(b.source || "manual")}</td>
      <td class="small">${esc((b.created_at || "").replace("T", " "))}</td>
      <td><button class="link-btn" data-bug="${esc(b.id)}">Open</button></td>
    </tr>`).join("") || "<tr><td colspan='9' class='muted'>No bugs recorded yet.</td></tr>";

    $$("#bugs-table button[data-bug]").forEach((btn) => {
      btn.addEventListener("click", () => openBug(btn.dataset.bug));
    });
  } catch (err) {
    notify(err.message, "error");
  }
}

async function openBug(id) {
  try {
    const data = await api(`/api/bugs/${id}`);
    const b = data.bug;
    $("#bug-detail").classList.remove("hidden");
    $("#bug-detail-body").innerHTML = `
      <h3>#${esc(b.id)} — ${esc(b.title)}</h3>
      <p class="small muted">${esc(b.severity)} &middot; ${esc(b.status)} &middot;
        ${esc(b.component || "unclassified")} &middot; ${esc(b.source || "manual")}
        &middot; KB eligible: ${data.kb_eligible ? "yes" : "no"} (${esc(data.kb_reason)})</p>
      <p>${esc(b.description)}</p>
      ${b.error_message ? `<p class="mono small">${esc(b.error_message)}</p>` : ""}
      ${b.stack_trace ? `<pre>${esc(b.stack_trace)}</pre>` : ""}
      ${b.root_cause ? `<p><strong>Root cause:</strong> ${esc(b.root_cause)}</p>` : ""}
      ${b.recommendation ? `<p><strong>Recommended fix:</strong> ${esc(b.recommendation)}</p>` : ""}
      <div class="row">
        <button class="secondary" id="reanalyze">Re-run diagnosis</button>
        <a class="button secondary" href="/api/bugs/${b.id}/report.pdf">PDF</a>
        <a class="button secondary" href="/api/bugs/${b.id}/report.csv">CSV</a>
      </div>`;
    $("#resolve-id").value = b.id;
    $("#resolve-cause").value = b.root_cause || "";
    $("#resolve-fix").value = b.recommendation || "";
    $("#resolve-details").value = b.resolution_details || "";
    $("#reanalyze").addEventListener("click", async () => {
      try {
        const res = await api(`/api/bugs/${b.id}/analyze`, { method: "POST" });
        notify(`Re-analysed bug #${b.id}.`);
        renderFindings(res.bug, res.findings);
        loadBugs();
      } catch (err) { notify(err.message, "error"); }
    });
    $("#bug-detail").scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    notify(err.message, "error");
  }
}

$("#resolve-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = $("#resolve-id").value;
  try {
    const data = await api(`/api/bugs/${id}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        root_cause: $("#resolve-cause").value,
        confirmed_fix: $("#resolve-fix").value,
        resolution_details: $("#resolve-details").value,
        verified: $("#resolve-verified").checked,
      }),
    });
    const p = data.promotion;
    notify(p
      ? `${data.message}: KB entry #${p.knowledge_id}, index now ${p.index_size} vectors.`
      : data.message);
    loadBugs();
    loadKnowledge();
  } catch (err) {
    notify(err.message, "error");
  }
});

$("#refresh-btn").addEventListener("click", loadBugs);
["#filter-q", "#filter-status", "#filter-severity"].forEach((sel) => {
  $(sel).addEventListener("change", loadBugs);
});

/* ----------------------------------------------------------------- watch */
async function loadWatch() {
  try {
    const s = await api("/api/watch/status");
    $("#watch-summary").textContent =
      `${s.running ? "RUNNING" : "STOPPED"} · folder ${s.directory} · every ${s.interval_seconds}s · ` +
      `extensions ${s.extensions.join(", ")} · last scan ${s.last_scan || "never"}`;
    $("#watch-table tbody").innerHTML = (s.events || []).map((e) => `<tr>
      <td>${esc(e.file_name)}</td><td>${esc(e.status)}</td><td>${esc(e.detail || "-")}</td>
      <td>${e.bug_id ? `#${esc(e.bug_id)}` : "-"}</td>
      <td class="small">${esc((e.detected_at || "").replace("T", " "))}</td></tr>`).join("") ||
      "<tr><td colspan='5' class='muted'>No files detected yet.</td></tr>";
  } catch (err) { notify(err.message, "error"); }
}

$("#watch-scan").addEventListener("click", async () => {
  try {
    const r = await api("/api/watch/scan", { method: "POST" });
    notify(`Scan complete: ${r.processed.length} processed, ${r.skipped.length} skipped, ${r.failed.length} failed.`);
    loadWatch(); loadBugs();
  } catch (err) { notify(err.message, "error"); }
});
$("#watch-start").addEventListener("click", async () => {
  await api("/api/watch/start", { method: "POST" }); notify("Auto-Watch started."); loadWatch();
});
$("#watch-stop").addEventListener("click", async () => {
  await api("/api/watch/stop", { method: "POST" }); notify("Auto-Watch stopped."); loadWatch();
});

/* ------------------------------------------------------------- analytics */
function bars(target, rows, labelKey, valueKey) {
  const el = $(target);
  if (!rows || !rows.length) { el.innerHTML = "<p class='muted small'>No data yet.</p>"; return; }
  const max = Math.max(...rows.map((r) => r[valueKey] || 0)) || 1;
  el.innerHTML = rows.map((r) => `<div class="bar-row">
      <span class="bar-label" title="${esc(r[labelKey])}">${esc(r[labelKey] || "Unspecified")}</span>
      <span class="bar"><span style="width:${((r[valueKey] / max) * 100).toFixed(1)}%"></span></span>
      <strong>${esc(r[valueKey])}</strong></div>`).join("");
}

async function loadAnalytics() {
  try {
    const g = $("#granularity").value;
    const r = await api(`/api/analytics${g ? `?granularity=${g}` : ""}`);
    const k = r.kpis;
    const cards = [
      ["Total defects", k.total_defects], ["Open", k.open_defects],
      ["Resolved", k.resolved_defects], ["Verified", k.verified_defects],
      ["Critical", k.critical_defects], ["Duplicates", k.duplicate_defects],
      ["KB entries", k.knowledge_base_entries], ["Promoted to KB", k.bugs_promoted_to_kb],
    ];
    $("#kpis").innerHTML = cards.map(([label, value]) =>
      `<div class="kpi"><div class="value">${esc(value ?? 0)}</div><div class="label">${esc(label)}</div></div>`
    ).join("") + `<div class="kpi"><div class="value small">${esc(k.most_affected_component || "-")}</div>
        <div class="label">Top component</div></div>
      <div class="kpi"><div class="value small">${esc(k.recent_trend || "-")}</div>
        <div class="label">Recent trend</div></div>`;

    bars("#chart-severity", r.severity, "severity", "count");
    bars("#chart-components", r.components, "component", "count");
    bars("#chart-errors", r.error_types, "error_type", "count");
    bars("#chart-causes", r.root_causes, "root_cause", "count");
    bars("#chart-themes", r.themes, "theme", "count");
    bars("#chart-trend", r.trend.points, "period", "count");
  } catch (err) { notify(err.message, "error"); }
}
$("#analytics-refresh").addEventListener("click", loadAnalytics);
$("#granularity").addEventListener("change", loadAnalytics);

/* ------------------------------------------------------------- knowledge */
async function loadKnowledge() {
  try {
    const q = $("#kb-search").value.trim();
    const r = await api(`/api/knowledge${q ? `?q=${encodeURIComponent(q)}` : ""}`);
    $("#kb-summary").textContent =
      `${r.count} entries shown · index ${r.rag.index_size} vectors · ` +
      `embedding backend ${r.rag.backend} · store ${r.rag.vector_store}`;
    $("#kb-table tbody").innerHTML = r.entries.map((e) => `<tr>
      <td>${esc(e.bug_id)}</td><td>${esc(e.title)}</td><td>${esc(e.category || "-")}</td>
      <td><span class="badge ${esc(e.severity)}">${esc(e.severity)}</span></td>
      <td>${esc(e.root_cause || "-")}</td><td>${esc(e.suggested_fix || "-")}</td>
      <td>${esc(e.origin || "dataset")}</td></tr>`).join("") ||
      "<tr><td colspan='7' class='muted'>No knowledge entries.</td></tr>";
  } catch (err) { notify(err.message, "error"); }
}
$("#kb-refresh").addEventListener("click", loadKnowledge);
$("#kb-search").addEventListener("change", loadKnowledge);

/* ------------------------------------------------------------------ init */
(async function init() {
  try {
    const m = await api("/api/meta");
    $("#meta-line").textContent =
      `${m.group} · embeddings ${m.rag.backend} · vector store ${m.rag.vector_store} · ` +
      `${m.rag.entries} knowledge entries · top-k ${m.top_k} · ` +
      `Auto-Watch ${m.auto_watch.running ? "running" : "stopped"}`;
  } catch (_) { /* meta is informational only */ }
  loadBugs();
})();
