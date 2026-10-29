"""Paper figures (English, vector PDF + SVG + PNG@300) built ONLY from existing result files. No model calls."""
import json, csv
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from figure_support import OUT, tr, wrap_pixels, audit
from matplotlib.text import Text


def finish_figure(fig, name):
    """Statistical layouts at IEEE print size; independent of diagram policy.

    Wide charts are authored at 7 inches, single-column charts at 3.5.
    Translate before wrapping, retain >=7 pt type, and never put a legend
    outside the canvas where tight bounding boxes would shrink the plot.
    """
    for text in fig.findobj(Text):
        text.set_text(tr(text.get_text()))
        text.set_fontsize(max(7, text.get_fontsize()))
    for ax in fig.axes:
        for axis in (ax.xaxis, ax.yaxis):
            labels = [t.get_text() for t in axis.get_ticklabels()]
            translated = [tr(label) for label in labels]
            if translated != labels:
                axis.set_ticks(axis.get_majorticklocs(), labels=translated)
        ax.title.set_linespacing(1.15)
    fig.set_layout_engine('constrained')
    fig.get_layout_engine().set(h_pad=.05, w_pad=.05, hspace=.08, wspace=.12)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for ax in fig.axes:
        ax.set_title(wrap_pixels(ax.title.get_text(), ax.title, renderer, ax.bbox.width), pad=8)
        # Short wrapped y-labels reserve room between adjacent panels.
        label = ax.yaxis.label
        label.set_text(wrap_pixels(label.get_text(), label, renderer,
                                   130 if len(fig.axes) == 3 else 230))
        xlabel = ax.xaxis.label
        xlabel.set_text(wrap_pixels(xlabel.get_text(), xlabel, renderer, ax.bbox.width))
    fig.canvas.draw()
    audit(fig, name)

SRC = RET = Path(__file__).resolve().parent / "figure_data"
S = json.load(open(SRC / "summary_gen.json", encoding="utf-8")); P = json.load(open(SRC / "paper_stats.json", encoding="utf-8"))
plt.rcParams.update({"font.family": "DejaVu Serif", "font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8, "legend.fontsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7,
                     "figure.constrained_layout.use": True,
                     "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.alpha": .25, "pdf.fonttype": 42, "svg.fonttype": "none"})
ARMS = ["off_a", "on_baseline_raw", "on_graphify_raw", "on_full", "on_jev"]
LAB = {"off_a": "Without Anamnésia (BM25, whole notes)", "on_baseline_raw": "With: baseline", "on_graphify_raw": "With: Graphify", "on_full": "With: auto+optimizer", "on_jev": "With: Graphify+JEV"}
SH = {"off_a": "Without", "on_baseline_raw": "Baseline", "on_graphify_raw": "Graphify", "on_full": "Auto+Opt.", "on_jev": "G+JEV"}
C = {"off_a": "#b03a2e", "on_baseline_raw": "#5dade2", "on_graphify_raw": "#48c9b0", "on_full": "#1f618d", "on_jev": "#7d3c98"}
models = sorted({o["model"] for o in S.values()}, key=lambda m: S[f"{m}|off_a"]["cost_effective"])
rem = [m for m in models if not m.startswith("ollama:")]
sh = lambda m: m.split("/")[-1].replace("ollama:", "local:").replace("-instruct", "").replace("-2507", "")
def save(fig, n):
    finish_figure(fig, n)
    for ext in ("pdf", "svg"): fig.savefig(OUT / f"{n}.{ext}", bbox_inches="tight")
    fig.savefig(OUT / f"{n}.png", dpi=300, bbox_inches="tight", facecolor="white"); plt.close(fig); print("ok", n)

# Fig: three-panel headline
fig, ax = plt.subplots(1, 3, figsize=(7.0, 3.05), layout="constrained")
x = np.arange(5)
ax[0].bar(x, [P["tin_mean"][a] for a in ARMS], color=[C[a] for a in ARMS]); ax[0].set_title("(a) Input tokens / query", pad=14); ax[0].set_ylabel("tokens (provider-reported)"); ax[0].set_ylim(0, 13500)
for i, a in enumerate(ARMS): ax[0].text(i, P["tin_mean"][a] + [150, 1200, 600, 150, 600][i], f"{P['tin_mean'][a]:,.0f}", ha="center", fontsize=7)
g = [P["cost_gen_remote"][a] for a in ARMS]; j = [P["cost_remote"][a] - P["cost_gen_remote"][a] for a in ARMS]
ax[1].bar(x, g, color=[C[a] for a in ARMS]); ax[1].bar(x, j, bottom=g, color="#f4d03f", hatch="///", edgecolor="#7d6608", lw=.4, label="JEV")
ax[1].set_title("(b) Effective cost (8 remote models)", pad=14); ax[1].set_ylabel("US$ per 82 queries/model, summed"); ax[1].legend(loc="upper right", fontsize=7, handlelength=1.0); ax[1].set_ylim(0, 2.85)
for i, a in enumerate(ARMS): ax[1].text(i, P["cost_remote"][a] + .03, f"{P['cost_remote'][a]:.2f}", ha="center", fontsize=7)
acc = [P["pooled_acc"][a] * 100 for a in ARMS]
d = {a: P["paired"].get(a) for a in ARMS}
err = [[0] + [P["paired"][a]["diff"] * 100 - P["paired"][a]["lo"] * 100 for a in ARMS[1:]], [0] + [P["paired"][a]["hi"] * 100 - P["paired"][a]["diff"] * 100 for a in ARMS[1:]]]
ax[2].bar(x, acc, color=[C[a] for a in ARMS], yerr=err, capsize=2, error_kw={"lw": .7}); ax[2].set_ylim(60, 100); ax[2].set_title("(c) Accuracy, 72 answerable Q"); ax[2].set_ylabel("% judged correct (9 models pooled)")
for i, a in enumerate(ARMS): ax[2].text(i, 61, f"{acc[i]:.1f}", ha="center", fontsize=7, color="white")
for a_ in ax: a_.set_xticks(x); a_.set_xticklabels([SH[a] for a in ARMS], rotation=75, ha="right")
save(fig, "fig_headline")

# Fig: cost per model (log)
fig, ax = plt.subplots(figsize=(7.0, 3.6)); w = .16; x = np.arange(len(rem))
for i, a in enumerate(ARMS): ax.bar(x + (i - 2) * w, [S[f"{m}|{a}"]["cost_effective"] for m in rem], w, color=C[a], label=SH[a])
ax.set_yscale("log"); ax.set_xticks(x); ax.set_xticklabels([sh(m) for m in rem], rotation=90, ha="center"); ax.set_ylabel("effective cost, US$ / 82 queries (log)"); fig.legend(*ax.get_legend_handles_labels(), ncols=5, loc="outside upper center", fontsize=7, frameon=False)
ax.set_title("Effective cost per model (JEV included)"); save(fig, "fig_cost_by_model")

# Fig: saving heatmap
arms_on = ARMS[1:]
M = np.array([[S[f"{m}|{a}"]["saving_cost_pct"] for a in arms_on] for m in rem])
fig, ax = plt.subplots(figsize=(7.0, 3.3)); im = ax.imshow(M, cmap="RdYlGn", vmin=0, vmax=95, aspect="auto"); ax.grid(False)
ax.set_xticks(range(4)); ax.set_xticklabels([SH[a] for a in arms_on], rotation=25, ha="right"); ax.set_yticks(range(len(rem))); ax.set_yticklabels([sh(m) for m in rem])
for i in range(M.shape[0]):
    for j_ in range(4): ax.text(j_, i, f"{M[i,j_]:.0f}", ha="center", va="center", fontsize=7)
ax.set_title("Cost saving vs. Without (%)"); fig.colorbar(im, ax=ax, fraction=.046); save(fig, "fig_saving_heatmap")

# Fig: accuracy by model
fig, ax = plt.subplots(figsize=(7.0, 4.0)); x = np.arange(len(models)); w = .16
for i, a in enumerate(ARMS): ax.bar(x + (i - 2) * w, [S[f"{m}|{a}"]["acc"] * 100 for m in models], w, color=C[a], label=LAB[a])
ax.set_ylim(50, 100); ax.set_xticks(x); ax.set_xticklabels([sh(m) for m in models], rotation=90, ha="center"); ax.set_ylabel("accuracy (%), n=72 per bar"); fig.legend(*ax.get_legend_handles_labels(), ncols=2, loc="outside lower center", fontsize=7, frameon=False)
ax.set_title("Accuracy per model and context pipeline (single run, temperature 0; per-bar 95% CI is roughly ±8 pp)"); save(fig, "fig_accuracy_by_model")

# Fig: Pareto
fig, ax = plt.subplots(figsize=(3.5, 3.4)); mk = dict(zip(models, "osD^v<>PX*h"))
for m in rem:
    for a in ARMS: ax.scatter(S[f"{m}|{a}"]["cost_effective"], S[f"{m}|{a}"]["acc"] * 100, s=22, color=C[a], marker=mk[m], edgecolor="k", lw=.3)
ax.set_xscale("log"); ax.set_xlabel("effective cost, US$ / 82 queries (log)"); ax.set_ylabel("accuracy (%)")
fig.legend([plt.Line2D([], [], marker="o", ls="", color=C[a]) for a in ARMS], [SH[a] for a in ARMS], ncols=2, loc="outside lower center", fontsize=7, frameon=False); ax.set_title("Cost–quality trade-off (marker = model)")
save(fig, "fig_pareto")

# Fig: accuracy by question class
cl = P["by_class"]; names = ["factual", "numero", "duplicata", "ambigua", "longdoc"]; en = {"factual": "factual\n(36)", "numero": "numeric\n(28)", "duplicata": "dup./version\n(3)", "ambigua": "ambiguous\n(3)", "longdoc": "long doc\n(2)"}
fig, ax = plt.subplots(figsize=(7.0, 2.9)); x = np.arange(len(names)); w = .16
for i, a in enumerate(ARMS): ax.bar(x + (i - 2) * w, [cl[n][a] * 100 for n in names], w, color=C[a], label=SH[a])
ax.set_xticks(x); ax.set_xticklabels([en[n] for n in names]); ax.set_ylabel("accuracy (%), 9 models pooled"); ax.set_title("Accuracy by question class"); fig.legend(*ax.get_legend_handles_labels(), ncols=5, loc="outside lower center", fontsize=7, frameon=False); save(fig, "fig_by_class")

# Fig: retrieval (24 Oct benchmark)
rows = list(csv.DictReader(open(RET / "summary.csv", encoding="utf-8")))
r = {x_["condition"]: x_ for x_ in rows if x_["dataset"] == "d2" and x_["split"] == "test"}
conds = ["off_a", "on_baseline_raw", "on_graphify_raw", "on_full", "on_laya"]; lab = {"off_a": "Without", "on_baseline_raw": "Baseline", "on_graphify_raw": "Graphify", "on_full": "Auto+Opt.", "on_laya": "Laya"}
fig, ax = plt.subplots(1, 3, figsize=(7.0, 2.75), layout="constrained")
for a_, (k, t) in zip(ax, [("tokens_mean", "(a) context tokens delivered"), ("recall@10", "(b) recall@10 of gold sources"), ("answer_in_ctx", "(c) answer present in context")]):
    v = [float(r[c][k]) for c in conds]; a_.bar([lab[c] for c in conds], v, color=["#b03a2e", "#5dade2", "#48c9b0", "#1f618d", "#d68910"]); a_.set_title(t); plt.setp(a_.get_xticklabels(), rotation=75, ha="right")
    a_.set_ylim(0, max(v) * 1.2)
    for i, vv in enumerate(v): a_.text(i, vv, f"{vv:,.0f}" if vv > 10 else f"{vv:.2f}", ha="center", va="bottom", fontsize=7)
save(fig, "fig_retrieval")
lat = list(csv.DictReader(open(RET / "summary_latency.csv", encoding="utf-8")))
lr = {(x_["condition"], x_["pass_"]): float(x_["p50_ms"]) for x_ in lat if x_["dataset"] == "d2"}
fig, ax = plt.subplots(figsize=(3.5, 2.9)); x = np.arange(len(conds))
ax.bar(x - .2, [lr[(c, "cold")] for c in conds], .4, color="#2e86c1", label="cold"); ax.bar(x + .2, [lr[(c, "hot")] for c in conds], .4, color="#e67e22", label="hot (cache)")
ax.set_yscale("log"); ax.set_xticks(x); ax.set_xticklabels([lab[c] for c in conds], rotation=25, ha="right"); ax.set_ylabel("retrieval latency p50 (ms, log)"); ax.legend(); ax.set_title("Retrieval latency, cold vs. hot (D2)")
save(fig, "fig_retrieval_latency")
