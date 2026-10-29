# Reproducing the paper figures

Run from this directory (or invoke either script by its full/relative path from any working directory):

```sh
python -m pip install -r requirements-figures.txt
python make_paper_figs.py --lang en
python make_diagrams.py --lang en
python make_paper_figs.py --lang pt
python make_diagrams.py --lang pt
python validate_figures.py
```

`--lang en` is the default. `--lang pt` writes to `figures_pt/`, not `figures/`. Both generators produce PDF + editable-text SVG + PNG at 300 dpi. These are eight statistical plots and eight technical diagrams **in each language**. Each artifact also has a `.layout.json` renderer-validation report. `validate_figures.py` requires all 16 names, all three formats, clean text-bound/box-containment reports, matching displayed numbers in EN/PT, and selected untranslated-label smoke checks.

The scripts require only local `figure_data/`, `figure_support.py`, and `figure_text_pt.json`, not the repository root, an Obsidian vault, a running gateway, credentials, or any paid model API. Nothing fetches data from the network. The numerical export is already included; **do not recalculate or synthesize metrics to regenerate the figures**.

## Data provenance and sanitization

`figure_data/provenance.json` records logical source filenames, SHA-256 hashes of the original metric files, retained columns and row filters. It contains no machine-specific paths. The export was checked against the existing source files, preserving JSON numerical values and CSV metric strings exactly:

- `summary_gen.json`: 45 model/arm aggregate records; only model ID, effective cost, accuracy and cost-saving fraction/percentage fields actually used by these plots. The saving field is absent where absent in the original.
- `paper_stats.json`: only mean input tokens, generation/effective remote costs, pooled accuracy, paired interval limits and question-class accuracy.
- `summary.csv`: only D2 test rows for the five displayed retrieval conditions and the six required columns (5 rows).
- `summary_latency.csv`: only D2 cold/hot rows for those conditions and four required columns (10 rows).

No prompts, responses, note content, personal absolute paths, API keys or per-question records are included. The retrieval condition ID `on_laya` and displayed technical name `Laya` intentionally remain as recorded in the earlier benchmark; Graphify+JEV is the separate generation arm `on_jev`. No result, denominator, interval, formula or diagram claim was changed.

## Layout changes

- `fig_headline` and `fig_retrieval`: three horizontal panels with wrapped titles, explicit inter-axis spacing and numeric-label headroom; use full report width.
- Compact cost/accuracy scatter and retrieval-latency plots use about half the report width; the other charts use full width. Figures are no longer subject to a universal height cap.
- Diagram numbering is provided exclusively by LaTeX captions. Renderer-based diagram checks also test arrow/text clearance.
- Model plots: larger canvases, vertical model-ID labels, external one-column legends; long titles are wrapped using the actual renderer font metrics.
- All charts: constrained layout with explicit margins; translation happens before final layout (including categorical tick labels).
- All diagrams: larger canvases; measured title/body stacks are wrapped and fitted into their actual box interiors. Arrow-label backgrounds keep connector lines from cutting through the text.
- PT labels, titles, prose and legends live in `figure_text_pt.json`; model IDs, code symbols, commands and technical names remain unchanged.

## Validation limits

The automatic check tests rendered text/text bounding-box intersections and diagram-text containment, not every possible arrow/curve/data-marker intersection. Main PNGs and full EN/PT contact sheets were also visually inspected, including headline, accuracy-by-model and the optimization-layer diagram. A `.layout.json` report is a diagnostic tied to the last generation run; rerun the generators before validating after source edits.
