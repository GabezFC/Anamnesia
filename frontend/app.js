// Memory Gateway frontend — vanilla JS, talks only to the REST API.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (v) => v === null || v === undefined ? "n/a" : (typeof v === "number" ? (Math.abs(v) < 1 && v !== 0 ? v.toPrecision(3) : Math.round(v * 10) / 10) : esc(v));
const PIPES = ["baseline", "graphify", "graphify_jev"];
let integrations = null;

async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

document.querySelectorAll("nav button").forEach((b) => b.onclick = () => {
  document.querySelectorAll("nav button, .tab").forEach((e) => e.classList.remove("active"));
  b.classList.add("active"); $("tab-" + b.dataset.tab).classList.add("active");
  ({ history: loadHistory, stats: loadStats, system: loadSystem })[b.dataset.tab]?.();
});

// ---------- consumers (only really available ones are selectable, §76) ----------
async function loadIntegrations() {
  integrations = await api("/system/integrations");
  const sel = $("agent");
  for (const a of integrations.agents) {
    const o = new Option(`${a.agent}${a.available ? "" : " (indisponível)"}`, a.agent);
    o.disabled = !a.available; sel.add(o);
  }
  sel.onchange = fillProviders; fillProviders();
}
function fillProviders() {
  const agent = $("agent").value, p = $("provider"), m = $("model");
  p.innerHTML = ""; m.innerHTML = "";
  const models = integrations?.models || {};
  const provs = agent === "hermes" ? [["", "(config do Hermes isolado)"], ["custom", "custom (Ollama)"]]
    : agent === "generic" ? Object.entries(models).filter(([, v]) => v.available).map(([k]) => [k, k]) : [["", ""]];
  provs.forEach(([v, t]) => p.add(new Option(t, v)));
  const fillModels = () => {
    m.innerHTML = "";
    const key = p.value === "custom" ? "ollama" : p.value;
    const list = agent === "hermes" && !p.value ? ["", ...(models.ollama?.models || [])] : (models[key]?.models || [""]);
    list.forEach((x) => m.add(new Option(x || "(padrão)", x)));
  };
  p.onchange = fillModels; fillModels();
}
function consumer() {
  const agent = $("agent").value;
  return agent ? [{ agent, provider: $("provider").value || null, model: $("model").value || null }] : [];
}
function overrides() { return { jev_mode: $("jevmode").value, threshold: parseFloat($("threshold").value) }; }

// ---------- run ----------
async function busy(label, fn) {
  document.querySelectorAll(".buttons button").forEach((b) => b.disabled = true);
  $("status").textContent = label + "…";
  const t0 = performance.now();
  try { await fn(); $("status").textContent = `ok (${Math.round(performance.now() - t0)} ms)`; }
  catch (e) { $("status").innerHTML = `<span class="bad">${esc(e.message)}</span>`; }
  finally { document.querySelectorAll(".buttons button").forEach((b) => b.disabled = false); }
}

$("btn-run").onclick = () => busy("Run", async () => {
  if (consumer().length) return runBench([$("pipeline").value], [$("q").value]);
  const r = await api("/memory/search", { query: $("q").value, pipeline: $("pipeline").value, max_results: +$("maxres").value, ...overrides(), include_candidates: true });
  $("result").innerHTML = renderSingle(r);
});
$("btn-all").onclick = () => busy("Run All", async () => {
  if (consumer().length) return runBench(PIPES, [$("q").value]);
  const rs = [];
  for (const p of PIPES) rs.push(await api("/memory/search", { query: $("q").value, pipeline: p, max_results: +$("maxres").value, ...overrides(), include_candidates: true }));
  $("result").innerHTML = renderComparison(rs.map((r) => ({ pipeline: r.pipeline, metrics: r.metrics, sources: r.sources, run_id: r.run_id })))
    + rs.map(renderSingle).join("");
});
$("btn-compare").onclick = $("btn-all").onclick;
$("btn-bench").onclick = () => busy("Benchmark", async () => {
  const body = { pipelines: PIPES, consumers: consumer(), repetitions: +$("reps").value, ...overrides(), max_results: +$("maxres").value };
  const est = await api("/benchmark/estimate", body);
  $("estimate").textContent = `estimated_runs=${est.estimated_runs} (${est.formula})`;
  if (!confirm(`Executar ${est.estimated_runs} runs?`)) return;
  const job = await api("/benchmark/run-all", { ...body, background: true });
  await pollJob(job.job_id);
});

async function runBench(pipelines, questions) {
  const res = await api("/benchmark/run-all", { questions, pipelines, consumers: consumer(), repetitions: +$("reps").value, warmup: false, ...overrides(), max_results: +$("maxres").value });
  const runs = await api(`/benchmark/runs?session_id=${res.session_id}&limit=500`);
  const detailed = await Promise.all(runs.map((r) => api(`/benchmark/runs/${r.run_id}`)));
  $("result").innerHTML = renderComparison(detailed.map((d) => ({ pipeline: d.pipeline, metrics: d.metrics, sources: d.sources, run_id: d.run_id, answer: d.answer, agent: d.agent, model: d.model, error: d.error })));
}

async function pollJob(id) {
  for (;;) {
    const j = await api(`/benchmark/jobs/${id}`);
    $("status").textContent = `benchmark ${j.status}: ${j.progress.length} runs`;
    if (j.status === "done") { $("result").innerHTML = `<div class="card">Sessão <b>${esc(j.result.session_id)}</b> concluída: ${j.result.runs} runs. Veja Histórico/Stats.</div>`; return; }
    if (j.status === "error") throw new Error(j.error);
    await new Promise((r) => setTimeout(r, 2000));
  }
}

// ---------- renderers ----------
const ROWS = [["Agent/model", (m, r) => r.agent ? `${r.agent} / ${r.model || "padrão"}` : "retrieval-only"],
  ["Latency ms", (m) => m.total_latency_ms], ["Retrieval ms", (m) => m.retrieval_latency_ms], ["Generation ms", (m) => m.generation_latency_ms],
  ["Documents found", (m) => m.documents_found], ["Docs → model", (m) => m.documents_sent_to_model],
  ["Candidate tokens", (m) => m.candidate_tokens_before_filter], ["Context tokens", (m) => m.context_tokens],
  ["JEV tokens", (m) => m.jev_tokens], ["Input tokens", (m) => m.model_input_tokens], ["Output tokens", (m) => m.model_output_tokens],
  ["Agent tokens", (m) => m.agent_tokens], ["JEV cost", (m) => m.jev_cost], ["Cost", (m) => m.total_cost ?? m.jev_cost]];

function renderComparison(items) {
  const by = Object.fromEntries(items.map((i) => [i.pipeline, i]));
  const cols = PIPES.filter((p) => by[p]);
  let h = `<div class="card"><h2>Comparação</h2><table><tr><th></th>${cols.map((p) => `<th>${p}</th>`).join("")}</tr>`;
  for (const [label, f] of ROWS) h += `<tr><th>${label}</th>${cols.map((p) => `<td class="num">${fmt(f(by[p].metrics || {}, by[p]))}</td>`).join("")}</tr>`;
  h += `<tr><th>Sources</th>${cols.map((p) => `<td>${(by[p].sources || []).map((s) => esc(s.file.split("/").pop())).join("<br>")}</td>`).join("")}</tr>`;
  if (items.some((i) => i.answer || i.error)) h += `<tr><th>Answer</th>${cols.map((p) => `<td><pre>${esc(by[p].answer || by[p].error || "")}</pre></td>`).join("")}</tr>`;
  h += "</table>";
  const j = by.graphify_jev?.metrics?.jev;
  if (j) h += renderJev(j);
  return h + "</div>";
}

function renderJev(j) {
  return `<h2>JEV</h2><table>
  <tr><th>Candidates</th><td>${j.candidates_received}</td><th>Kept</th><td class="KEEP">${j.candidates_kept}</td><th>Review</th><td class="REVIEW">${j.candidates_review}</td>
  <th>Dropped</th><td class="DROP">${j.candidates_dropped}</td><th>Quarantined</th><td class="QUARANTINE">${j.candidates_quarantined}</td></tr>
  <tr><th>Avg relevance</th><td>${fmt(j.average_relevance)}</td><th>Min</th><td>${fmt(j.min_relevance)}</td><th>Max</th><td>${fmt(j.max_relevance)}</td>
  <th>JEV tokens</th><td>${fmt(j.input_tokens)}</td><th>JEV latency</th><td>${fmt(j.latency_ms)} ms</td></tr>
  <tr><th>Model</th><td>${esc(j.jev_model_resolved || j.jev_model)}</td><th>SDK</th><td>${esc(j.jev_sdk_version)}</td><th>Mode</th><td>${esc(j.jev_mode)}</td>
  <th>Requests</th><td>${j.request_count}</td><th>Threshold</th><td>${j.relevance_threshold} (REVIEW→${esc(j.review_action)})</td></tr></table>`;
}

function renderSingle(r) {
  const m = r.metrics;
  let h = `<div class="card"><h2>${esc(r.pipeline)} <span class="muted">run ${esc(r.run_id)}</span></h2>
  <div class="muted">candidates=${m.candidates} survivors=${m.survivors} context_tokens=${m.context_tokens}
  (antes ${m.candidate_tokens_before_filter}, redução ${fmt(m.context_reduction)}) latência=${fmt(m.total_latency_ms)} ms ${m.error ? `<span class="bad">${esc(m.error)}</span>` : ""}</div>`;
  if (m.jev) h += renderJev(m.jev);
  if (r.candidates?.length) {
    h += `<table><tr><th>candidate</th><th>section</th><th>score</th><th>rel</th><th>inj</th><th>decision</th><th></th></tr>`;
    for (const c of r.candidates) h += `<tr><td>${esc(c.source_file)}</td><td>${esc(c.section.slice(0, 60))}</td><td class="num">${fmt(c.score)}</td>
      <td class="num">${fmt(c.relevance)}</td><td class="num">${fmt(c.injection)}</td><td class="${c.decision || ""}">${esc(c.decision || "")}</td><td></td></tr>`;
    h += "</table>";
  }
  return h + `<details><summary>Contexto final (${m.context_tokens} tokens)</summary><pre>${esc(r.context)}</pre></details></div>`;
}

// ---------- history ----------
async function loadHistory() {
  const ss = await api("/benchmark/sessions");
  $("sessions").innerHTML = `<table><tr><th>session</th><th>kind</th><th>runs</th><th>created</th></tr>${ss.map((s) =>
    `<tr><td><a onclick="loadRuns('${esc(s.session_id)}')">${esc(s.session_id)}</a></td><td>${esc(s.kind)}</td><td>${s.runs}</td><td>${new Date(s.created_at * 1000).toLocaleString()}</td></tr>`).join("")}</table>`;
  loadRuns();
}
async function loadRuns(session) {
  const rs = await api(`/benchmark/runs?limit=200${session ? "&session_id=" + encodeURIComponent(session) : ""}`);
  $("runs").innerHTML = `<table><tr><th>run</th><th>q</th><th>pipeline</th><th>agent/model</th><th>ctx tokens</th><th>lat ms</th><th>warm-up</th></tr>${rs.map((r) =>
    `<tr><td><a onclick="loadRun('${r.run_id}')">${r.run_id}</a></td><td>${esc(r.question_id || r.query.slice(0, 40))}</td><td>${r.pipeline}</td>
    <td>${esc(r.agent || "")} ${esc(r.model || "")}</td><td class="num">${fmt(r.metrics?.context_tokens)}</td><td class="num">${fmt(r.metrics?.total_latency_ms)}</td><td>${r.warmup ? "sim" : ""}</td></tr>`).join("")}</table>`;
}
async function loadRun(id) {
  const r = await api(`/benchmark/runs/${id}`);
  const rows = r.candidates.map((c) => `<tr><td>${esc(c.source_file)}</td><td class="num">${fmt(c.relevance)}</td><td class="${c.decision || ""}">${esc(c.decision || "")}</td>
    <td>${["DROP", "QUARANTINE", "REVIEW"].includes(c.decision) ? `<button onclick="markFN('${id}','${esc(c.candidate_id)}')">Mark as False Negative</button>` : ""}</td></tr>`).join("");
  $("run-detail").innerHTML = `<div class="card"><h2>Run ${id} — ${esc(r.pipeline)}</h2><div class="muted">${esc(r.query)}</div>
    ${r.answer ? `<h2>Resposta</h2><pre>${esc(r.answer)}</pre>` : ""}
    <h2>Avaliação humana (1–5)</h2>${["accuracy", "completeness", "groundedness", "citation_quality"].map((f) =>
      `<label>${f}<input id="ev-${f}" type="number" min="1" max="5"></label>`).join("")}
    <button onclick="saveEval('${id}')">Salvar avaliação</button>
    <h2>Candidatos</h2><table><tr><th>source</th><th>rel</th><th>decision</th><th></th></tr>${rows}</table>
    <details><summary>Métricas</summary><pre>${esc(JSON.stringify(r.metrics, null, 1))}</pre></details></div>`;
}
window.loadRuns = loadRuns; window.loadRun = loadRun;
window.markFN = async (run_id, candidate_id) => { await api("/feedback/false-negative", { run_id, candidate_id }); alert("Registrado como falso negativo"); };
window.saveEval = async (run_id) => {
  const body = { run_id };
  for (const f of ["accuracy", "completeness", "groundedness", "citation_quality"]) { const v = $("ev-" + f).value; if (v) body[f] = +v; }
  await api("/feedback/evaluation", body); alert("Avaliação salva");
};

// ---------- stats / sweep / system ----------
async function loadStats() {
  const s = await api("/benchmark/stats");
  const g = s.groups.map((x) => `<tr><td>${esc(x.agent)}</td><td>${esc(x.model)}</td><td>${x.pipeline}</td><td class="num">${x.runs}</td>
    <td class="num">${fmt(x.total_latency_ms.median)}</td><td class="num">${fmt(x.total_latency_ms.p95)}</td><td class="num">${fmt(x.context_tokens.median)}</td>
    <td class="num">${fmt(x.jev_input_tokens.mean)}</td><td class="num">${fmt(x.total_cost.mean)}</td></tr>`).join("");
  $("stats").innerHTML = `<div class="card">runs=${s.total_runs} sessões=${s.sessions} falsos negativos=${s.false_negatives.false_negatives}/${s.false_negatives.dropped_total} (rate ${fmt(s.false_negatives.false_negative_rate)})</div>
   <table><tr><th>agent</th><th>model</th><th>pipeline</th><th>n</th><th>lat mediana</th><th>lat p95</th><th>ctx mediana</th><th>JEV tokens médio</th><th>custo médio</th></tr>${g}</table>
   <p class="muted">Números observados; qualidade exige avaliação humana.</p>`;
}
$("btn-sweep").onclick = async () => {
  $("sweep").textContent = "executando…";
  const r = await api("/benchmark/threshold-sweep", {});
  $("sweep").innerHTML = `<table><tr><th>threshold</th><th>kept</th><th>context tokens</th><th>JEV cost</th><th>JEV latency</th><th>FN rate</th></tr>${r.rows.map((x) =>
    `<tr><td>${x.threshold}</td><td class="num">${x.documents_kept}</td><td class="num">${x.context_tokens}</td><td class="num">${fmt(x.jev_cost)}</td><td class="num">${fmt(x.jev_latency_ms)}</td><td class="num">${fmt(x.false_negative_rate)}</td></tr>`).join("")}</table>`;
};
async function loadSystem() {
  const s = await api("/system/info");
  const ag = s.integrations.agents.map((a) => `<tr><td>${a.agent}</td><td class="${a.available ? "ok" : "bad"}">${a.available ? "AVAILABLE" : "UNAVAILABLE"}</td>
    <td>${esc(a.version || "")}</td><td>${a.mcp ? "YES" : "NO"}</td><td>${a.cli ? "YES" : "NO"}</td><td>${a.metrics}</td><td class="muted">${esc(a.reason || "")}</td></tr>`).join("");
  $("system").innerHTML = `<div class="card">Vault: ${esc(s.vault)} (${s.markdown_files} .md) · Graphify: ${esc(s.graphify)} · JEV SDK ${esc(s.jev_sdk)} / ${esc(s.jev_model)} (${esc(s.jev_mode)}) · cache=${s.cache_enabled} · DB ${esc(s.db)}</div>
   <table><tr><th>agent</th><th>status</th><th>version</th><th>MCP</th><th>CLI</th><th>metrics</th><th></th></tr>${ag}</table>
   <pre>${esc(JSON.stringify(s.integrations.models, null, 1))}</pre>`;
}

(async () => {
  try { const h = await api("/health"); $("health").textContent = h.status; $("health").className = "pill ok"; } catch { $("health").textContent = "offline"; }
  loadIntegrations().catch((e) => $("status").textContent = e.message);
})();
