"""Technical diagrams for the Anamnésia paper (vector PDF + SVG + PNG@300). Every box maps to code read in the study (see TRACEABILITY.md)."""
from pathlib import Path
import re
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

from figure_support import OUT, finish_figure, fit_box, tr
plt.rcParams.update({"font.family": "DejaVu Sans", "pdf.fonttype": 42, "svg.fonttype": "none"})
PAL = dict(agent="#34495e", mcp="#2471a3", gw="#1f618d", opt="#148f77", ret="#2e86c1", jev="#7d3c98", store="#b9770e", model="#922b21", vault="#7f8c8d", cost="#6c3483", off="#b03a2e", ok="#1e8449")

def new(w, h):
    fig, ax = plt.subplots(figsize=(w * 1.55, h * 1.55)); ax.set_xlim(0, w); ax.set_ylim(0, h); ax.axis("off"); return fig, ax
def box(ax, x, y, w, h, title, sub=None, c="#1f618d", fs=7.5, sfs=6, tc="white", ls="-"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.015,rounding_size=0.08", fc=c, ec="#2c3e50" if ls != "-" else "none", lw=.8, ls=ls))
    fit_box(ax, x, y, w, h, tr(title), tr(sub) if sub else None, tc,
            max(8, fs * 1.2), max(6.2, sfs * 1.2), min_fontsize=6.2, padding=5.0)
def arr(ax, x1, y1, x2, y2, c="#34495e", ls="-", lbl=None, lw=1.2, rad=0.0, fs=5.8, off=(0, .07)):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=9, color=c, lw=lw, linestyle=ls, connectionstyle=f"arc3,rad={rad}"))
    if lbl: ax.text((x1 + x2) / 2 + off[0], (y1 + y2) / 2 + off[1], lbl, ha="center", va="bottom", fontsize=fs, color=c, bbox=dict(facecolor="white", edgecolor="none", pad=1.2, alpha=.97))
def save(fig, n):
    # Caption numbering belongs to LaTeX, never to the artwork.
    for text in (text for axis in fig.axes for text in axis.texts):
        if re.match(r'^Fig\. \d+\s+', text.get_text()):
            text.set_text(re.sub(r'^Fig\. \d+\s+', '', tr(text.get_text())))
    finish_figure(fig, n)
    for e in ("pdf", "svg"): fig.savefig(OUT / f"{n}.{e}", bbox_inches="tight")
    fig.savefig(OUT / f"{n}.png", dpi=300, bbox_inches="tight", facecolor="white"); plt.close(fig); print("ok", n)

# 1 ---- full architecture
fig, ax = new(7.3, 5.4)
ax.add_patch(FancyBboxPatch((.1, 4.35), 7.1, .95, boxstyle="round,pad=0.01", fc="#eaf2f8", ec="none")); ax.text(.2, 5.17, "Agents / clients", fontsize=6.5, color="#1f3a5f", fontweight="bold")
for i, (t, s) in enumerate([("Hermes", "adapter"), ("Claude Code", "adapter"), ("Codex", "adapter"), ("OpenCode", "detect only"), ("Browser UI", "vanilla JS"), ("anamnesia CLI", "doctor/start/mcp")]):
    box(ax, .25 + i * 1.18, 4.45, 1.08, .6, t, s, PAL["agent"], 6.5, 5)
ax.text(.2, 4.12, "Interfaces", fontsize=6.5, color="#1f3a5f", fontweight="bold")
box(ax, .25, 3.45, 2.2, .6, "MCP server (stdio)", "memory_search (minimal); +6 full; save opt-in", PAL["mcp"], 6.5, 4.8)
box(ax, 2.6, 3.45, 2.2, .6, "REST API (FastAPI)", "~130 operations · token-guarded writes", PAL["mcp"], 6.5, 4.8)
box(ax, 4.95, 3.45, 2.2, .6, "MCP→REST bridge", "forwards memory_search only (opt-in)", PAL["mcp"], 6.5, 4.8)
ax.add_patch(FancyBboxPatch((.1, 1.0), 7.1, 2.3, boxstyle="round,pad=0.01", fc="#f4f6f7", ec="#99a3a4", lw=.8)); ax.text(.2, 3.17, "Memory Gateway (_search_impl)", fontsize=6.5, color="#1f3a5f", fontweight="bold")
st = [("1 Freshness", "stat manifest\n≤ every 5 s", PAL["opt"]), ("2 Plan/route", "classify query\nauto→baseline", PAL["opt"]), ("3 Result cache", "LRU 256 · TTL 900 s\nhash re-check", PAL["opt"]), ("4 Retrieval", "FTS5 BM25 /\nGraphify hybrid", PAL["ret"]),
      ("5 Optimizer", "adaptive cut · near-dup\ninjection flag · demote", PAL["opt"]), ("6 Context", "6000-tok budget\n<note> blocks", PAL["gw"])]
for i, (t, s, c) in enumerate(st): box(ax, .22 + i * 1.17, 2.15, 1.07, .85, t, s, c, 6.3, 4.8)
for i in range(5): arr(ax, .22 + i * 1.17 + 1.07, 2.57, .22 + (i + 1) * 1.17, 2.57)
box(ax, 1.4, 1.15, 2.2, .7, "JEV judge (paid, optional)", "TypeSafe jev-1.13.0 · US$0.042/Mtok in", PAL["jev"], 6.3, 4.8)
box(ax, 3.8, 1.15, 1.7, .7, "Decision Engine", "EXPERIMENTAL · opt-in", "#8e7cc3", 6.3, 4.8, ls="--")
box(ax, 5.65, 1.15, 1.45, .7, "Ledger", "benchmark.db runs/metrics", PAL["cost"], 6.3, 4.8)
arr(ax, 3.1, 2.15, 2.6, 1.87, PAL["jev"], "--"); arr(ax, 6.0, 2.15, 6.4, 1.87, PAL["cost"])
ax.text(.2, .82, "State", fontsize=6.5, color="#1f3a5f", fontweight="bold")
box(ax, .25, .1, 2.0, .62, "Vault mirror (READ-ONLY)", "Obsidian notes · confined rb opens", PAL["vault"], 6.3, 4.8)
box(ax, 2.4, .1, 1.7, .62, "graph.json", "Graphify CLI output", PAL["ret"], 6.3, 4.8)
box(ax, 4.25, .1, 1.5, .62, "saved_context/", "memory_save notes (.md)", PAL["store"], 6.3, 4.8)
box(ax, 5.9, .1, 1.25, .62, "SQLite", "benchmark.db · usage.db", PAL["cost"], 6.3, 4.8)
for x in (1.25, 3.25, 5.0, 6.5): arr(ax, x, .74, x, 1.0, "#7f8c8d", "--")
arr(ax, 3.7, 4.43, 3.7, 4.07); arr(ax, 3.7, 3.43, 3.7, 3.32)
ax.text(3.7, 5.47, "Fig. 1  Anamnésia system architecture (as implemented)", ha="center", fontsize=8, fontweight="bold")
save(fig, "diag_architecture")

# 2 ---- query flow to answer
fig, ax = new(7.4, 2.95)
steps = [("Agent", "calls memory_search\n(query, scope, pipeline)", PAL["agent"]), ("MCP / REST", "enforce_scope\n(narrow only)", PAL["mcp"]), ("Gateway", "fresh? → plan →\ncache lookup", PAL["gw"]), ("Retrieve", "BM25 top-100 sections\n(+graph expand)", PAL["ret"]),
         ("Optimize", "cut · dedup ·\nflag · demote", PAL["opt"]), ("Context", "≤6000 tok, ≤1500/src\nuntrusted <note>", PAL["gw"]), ("Model", "agent's LLM answers\n(local or remote)", PAL["model"])]
w = .92; gap = .13
for i, (t, s, c) in enumerate(steps):
    x = .1 + i * (w + gap); box(ax, x, 1.55, w, 1.0, t, s, c, 6.6, 4.9)
    if i: arr(ax, x - gap, 2.05, x, 2.05)
ax.text(3.7, 2.8, "Fig. 2  Query-to-answer data flow", ha="center", fontsize=8, fontweight="bold")
box(ax, 2.5, .3, 2.0, .7, "Ledger write", "metrics_json: tokens, latency, cache, route", PAL["cost"], 6.3, 4.8)
box(ax, 4.85, .3, 2.3, .7, "JEV (only graphify_jev*)", "prefilter top-8 → judge → KEEP/REVIEW/DROP", PAL["jev"], 6.3, 4.8)
arr(ax, 3.4, 1.55, 3.5, 1.02, PAL["cost"])
# Separate request/return ports: parallel external arrows, no shared tip.
arr(ax, 6.1, 1.55, 6.1, 1.02, PAL["jev"], "--")
arr(ax, 5.65, 1.02, 5.65, 1.54, PAL["jev"], "--")
ax.text(.1, .55, "Result-cache hit short-circuits\nstages 4–5 (entry re-hashed vs. files)", fontsize=5.8, color=PAL["opt"])
save(fig, "diag_query_flow")

# 3 ---- Memory Optimization Layer
fig, ax = new(7.3, 3.4)
ax.text(3.65, 3.2, "Fig. 3  Memory Optimization Layer (optimizer.post_filter and context build)", ha="center", fontsize=8, fontweight="bold")
box(ax, .1, 1.85, 1.2, .8, "Candidates", "≤100 sections\nscope-filtered", PAL["ret"], 6.6, 5)
ops = [("Adaptive cut", "keep top-3 or\nscore ≥ 0.5·best\n(SIMPLE/MEDIUM,\nfree pipelines)", PAL["opt"]), ("Near-dup collapse", "SimHash+MinHash LSH\n→ SequenceMatcher\nratio ≥ 0.88", PAL["opt"]), ("Injection flag", "regex screen v2\nflag only, never drop;\nuncacheable", "#c0392b"),
       ("Demotion", "historical ×0.5\nconflict ×0.5\n(not for frozen JEV)", PAL["opt"]), ("Round-robin\n+ budget", "per-file interleave\ngreedy 6000-token fit\n≤1500 tok/source", PAL["gw"])]
for i, (t, s, c) in enumerate(ops):
    x = 1.55 + i * 1.12
    box(ax, x, 1.75, 1.0, 1.0, t, s, c, 6, 4.4)
    arr(ax, 1.32 if i == 0 else x - .105, 2.25, x - .015, 2.25)
box(ax, 1.55, .35, 2.4, .7, "Result cache (LRU 256, TTL 900 s)", "key = canonical query, pipeline, scope, budget,\nconfig digest, epoch · guard re-hash on hit", PAL["store"], 6, 4.5)
box(ax, 4.2, .35, 2.9, .7, "Token estimator", "ceil(max(chars/4, 1.3·words)·1.13)\nheuristic; tiktoken NOT a runtime dep", PAL["cost"], 6, 4.5)
arr(ax, 3.0, 1.07, 3.0, 1.73, PAL["store"], "--", "bypass", off=(.36, 0));
save(fig, "diag_optimization_layer")

# 4 ---- Graphify + JEV
fig, ax = new(7.3, 3.7)
ax.text(3.65, 3.52, "Fig. 4  Graphify hybrid retrieval and the JEV judge", ha="center", fontsize=8, fontweight="bold")
box(ax, .1, 2.35, 1.35, .75, "Vault mirror", "byte-identical copy", PAL["vault"], 6.5, 5)
box(ax, 1.75, 2.35, 1.5, .75, "graphify update", "external CLI, AST only\n→ graph.json (labels)", PAL["ret"], 6.3, 4.8)
box(ax, 3.55, 2.35, 1.5, .75, "GraphIndex", "adjacency + by_file\nreload on mtime", PAL["ret"], 6.3, 4.8)
arr(ax, 1.45, 2.72, 1.75, 2.72); arr(ax, 3.25, 2.72, 3.55, 2.72)
box(ax, 3.55, 1.15, 1.5, .85, "BM25 text seeds", "FTS5 on bodies\ntop-10 files", PAL["ret"], 6.3, 4.8)
arr(ax, 4.3, 2.0, 4.3, 2.33, "#34495e", "-", "expand", off=(-.42, -.04));
box(ax, 5.35, 1.75, 1.8, 1.35, "hybrid_search", "seed score 1.0→0.55\nBFS +≤15 graph-only\n(score 0.5→0.3)\nPPR off by default", PAL["gw"], 6.3, 4.8)
arr(ax, 5.05, 2.72, 5.35, 2.72); arr(ax, 5.05, 1.55, 5.35, 2.0)
box(ax, 5.35, .1, 1.8, .85, "JEV pipeline only", "prefilter top-8 (lex w=0.3)\nrel ≥.78 KEEP; ≥.55 REVIEW\ninj ≥.80 QUARANTINE", PAL["jev"], 6.1, 4.6)
arr(ax, 6.25, 1.75, 6.25, .97, PAL["jev"], "--")
box(ax, .1, .1, 3.0, 1.0, "Failure semantics", "UNJUDGED survives iff fail_open (default)\nUNSELECTED never survives\nsafety net: top-3 unjudged if all dropped", "#8e44ad", 6.3, 4.8)
box(ax, 3.3, .1, 1.85, .85, "Cost", "340·requests + 209·questions\ntokens × US$0.042/M", PAL["cost"], 6.1, 4.6)
arr(ax, 5.15, .5, 5.35, .5, PAL["cost"], "--")
save(fig, "diag_graphify_jev")

# 5 ---- persistence loop
fig, ax = new(7.3, 3.5)
ax.text(3.65, 3.32, "Fig. 5  Persistent-memory cycle: save, index, retrieve, feedback", ha="center", fontsize=8, fontweight="bold")
cyc = [("memory_save", "MG_MCP_SAVE=1\nsize/rate/secret scan\nproject gate", PAL["mcp"], .1, 1.9), ("saved_context/*.md", "atomic write (tmp+fsync+\nreplace) under FileLock\nfrontmatter v2, trust:untrusted", PAL["store"], 1.75, 1.9),
       ("Index refresh", "read-only extra root\nfingerprint ≤5 s → FTS5\nrebuild + cache clear", PAL["opt"], 3.4, 1.9), ("memory_search", "scope-filtered BM25\n(+graph) → context", PAL["ret"], 5.05, 1.9)]
for t, s, c, x, y in cyc: box(ax, x, y, 1.5, 1.0, t, s, c, 6.3, 4.6)
for i in range(3): arr(ax, .1 + 1.5 + i * 1.65, 2.4, .1 + (i + 1) * 1.65, 2.4)
box(ax, 5.05, .45, 2.1, .85, "memory_feedback", "useful +0.05 · wrong −0.2 · stale −0.05\n(confidence; rank v2 opt-in)", PAL["store"], 6.2, 4.6)
arr(ax, 6.1, 1.9, 6.1, 1.32, PAL["store"], "-")
# Return in the clear horizontal corridor above the read-only vault;
# the old curved chord grazed its top-right corner.
arr(ax, 5.05, 1.12, 2.9, 1.85, PAL["store"], "--", "updates note", rad=0, off=(0, .12))
box(ax, .1, .6, 3.3, .85, "Vault (user notes): never written", "NOT PART OF CYCLE · confined open(rb), ADS/reserved names rejected", PAL["vault"], 6.2, 4.6)
ax.text(.1, 3.05, "Evidence status: store/index/refresh verified by unit tests and the 24-Oct update scenario;\nlong-horizon agent recall NOT measured (see §10).", fontsize=5.8, color="#922b21")
save(fig, "diag_persistence_cycle")

# 6 ---- agent / MCP / gateway communication
fig, ax = new(7.3, 3.1)
ax.text(3.65, 2.95, "Fig. 6  Agent ↔ MCP ↔ Gateway communication paths", ha="center", fontsize=8, fontweight="bold")
box(ax, .1, 1.7, 1.5, .8, "Agent process", "Hermes / Claude Code /\nCodex (MCP client)", PAL["agent"], 6.5, 4.8)
box(ax, 2.1, 1.7, 1.9, .8, "anamnesia-mcp (stdio)", "tool schema ≈ 1 tool (minimal)\nMG_SCOPE pins project", PAL["mcp"], 6.5, 4.8)
box(ax, 4.5, 1.7, 1.45, .8, "In-process Gateway", "app.gateway.MemoryGateway", PAL["gw"], 6.3, 4.8)
arr(ax, 1.6, 2.1, 2.1, 2.1, lbl="JSON-RPC", off=(0, .05)); arr(ax, 4.0, 2.1, 4.5, 2.1, lbl="call", off=(0, .05))
box(ax, 2.1, .3, 1.9, .8, "MCP→REST bridge", "MG_MCP_BRIDGE_URL (opt-in)\nBearer token · egress allow-list", PAL["mcp"], 6.3, 4.6)
box(ax, 4.5, .3, 1.45, .8, "REST :8000", "POST /memory/search", PAL["mcp"], 6.3, 4.6)
arr(ax, 3.05, 1.7, 3.05, 1.12, "#34495e", "--"); arr(ax, 4.0, .7, 4.5, .7, "#34495e", "--"); arr(ax, 5.2, 1.12, 5.2, 1.7, "#34495e", "--")
box(ax, 6.2, 1.7, 1.0, .8, "Dashboard", "browser, hash router", PAL["agent"], 6.2, 4.6); arr(ax, 6.7, 1.7, 5.88, 1.13, "#34495e", "--", rad=.2)
ax.text(6.55, .45, "Writes require loopback +\nOrigin/Referer + X-MG-Token", fontsize=5.6, ha="center", color="#922b21")
save(fig, "diag_agent_mcp_gateway")

# 7 ---- with vs without
fig, ax = new(7.3, 2.9)
ax.text(3.65, 2.76, "Fig. 7  Experimental arms: Without vs. With Anamnésia (identical prompt, model, temperature 0)", ha="center", fontsize=7.6, fontweight="bold")
ax.add_patch(FancyBboxPatch((.1, 1.5), 7.1, .95, boxstyle="round,pad=0.01", fc="#fdedec", ec="none")); ax.text(.15, 2.3, "WITHOUT (independent harness, imports guarded)", fontsize=6, color=PAL["off"], fontweight="bold")
for i, (t, s, c) in enumerate([("Question", "", PAL["agent"]), ("BM25 over whole notes", "θ-calibrated abstention", PAL["off"]), ("Top-5 whole notes", "mean 10.9k tok", PAL["off"]), ("LLM", "", PAL["model"]), ("Judge", "gpt-4.1-mini", PAL["jev"])]):
    box(ax, .25 + i * 1.4, 1.58, 1.2, .6, t, s or None, c, 6.1, 4.8)
    if i: arr(ax, .25 + i * 1.4 - .2, 1.88, .25 + i * 1.4, 1.88)
ax.add_patch(FancyBboxPatch((.1, .1), 7.1, 1.3, boxstyle="round,pad=0.01", fc="#eafaf1", ec="none")); ax.text(.15, 1.25, "WITH (real MCP stdio, fresh home, OFFLINE=1)", fontsize=6, color=PAL["ok"], fontweight="bold")
box(ax, .25, .5, 1.2, .55, "Question", None, PAL["agent"], 6.1)
box(ax, 1.65, .15, 2.4, .95, "Anamnésia pipelines", "baseline · graphify · auto+optimizer\n· graphify+JEV (paid, only arm w/ JEV)", PAL["gw"], 6.1, 4.8)
box(ax, 4.25, .5, 1.2, .55, "Context", "1.6–2.9k tok", PAL["opt"], 6.1, 4.8); box(ax, 5.65, .5, .7, .55, "LLM", None, PAL["model"], 6.1); box(ax, 6.5, .5, .65, .55, "Judge", None, PAL["jev"], 6.1)
for a, b in [(1.45, 1.65), (4.05, 4.25), (5.45, 5.65), (6.35, 6.5)]: arr(ax, a, .78, b, .78)
save(fig, "diag_with_vs_without")

# 8 ---- cost accounting
fig, ax = new(7.3, 3.0)
ax.text(3.65, 2.86, "Fig. 8  Token and cost accounting used in the paper", ha="center", fontsize=8, fontweight="bold")
box(ax, .1, 1.7, 2.1, .85, "Generation", "usage.cost from OpenRouter\n(MEASURED, per call)", PAL["model"], 6.5, 5)
box(ax, 2.4, 1.7, 2.1, .85, "JEV", "jev_tokens × US$0.042/M\n(CALCULATED; no invoice)", PAL["jev"], 6.5, 5)
box(ax, 4.7, 1.7, 2.45, .85, "Local retrieval + optimizer", "US$0 (CPU, SQLite);\nenergy not measured", PAL["opt"], 6.5, 5)
ax.text(3.65, 1.52, "C_with = Σ C_gen(ctx_with) + C_JEV        C_without = Σ C_gen(ctx_notes)", ha="center", fontsize=7, family="DejaVu Sans Mono")
box(ax, 1.2, .35, 2.4, .7, "Judge (gpt-4.1-mini)", "benchmark overhead; EXCLUDED\nfrom C_with and C_without", PAL["vault"], 6.3, 4.8, ls="--")
box(ax, 3.9, .35, 3.2, .7, "Ledger (production path)", "metrics_json: jev_input_tokens, jev_cost,\ncontext_tokens, total_tokens_spent", PAL["cost"], 6.3, 4.8)
save(fig, "diag_cost_accounting")
