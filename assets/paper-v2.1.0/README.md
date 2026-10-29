# Anamnésia — technical report v2.1.0 / relatório técnico

This is an independent technical report, not an accepted IEEE publication. The report uses the IEEEtran typesetting class. This version changes presentation and adds a full Brazilian Portuguese edition; it does not introduce new benchmark runs or change measured results. The v2.1.0 tag identifies this report delivery, not a new tested application/package release.

## Read / leitura

- English: [Anamnesia_Research_Paper.pdf](Anamnesia_Research_Paper.pdf)
- Português brasileiro: [Anamnesia_Research_Paper_PT.pdf](Anamnesia_Research_Paper_PT.pdf)

Both editions include translated captions, tables, statistical charts and technical diagrams. Model IDs, API commands and technical identifiers are intentionally preserved.

## Build the PDFs

Install Tectonic separately (the build was exercised with version 0.17.0), then run from this directory:

```sh
python build.py
# Or specify an installed engine:
python build.py --tectonic /path/to/tectonic
```

The first Tectonic run may download TeX packages. No model API is invoked. All vector figure PDFs needed for compilation are included.

## Regenerate figures and verify

Use an isolated Python environment. Install the figure requirements and PyMuPDF (needed only for the final PDF verifier):

```sh
python -m pip install -r requirements-figures.txt
python -m pip install PyMuPDF
python build.py --regenerate-figures
python validate_figures.py
python verify.py
```

See [FIGURES.md](FIGURES.md) for direct bilingual generation commands and layout-validation limits. Automatic checks supplement, but do not replace, visual inspection.

## What is public

- Both PDFs and complete LaTeX sources, shared layout, tables and bibliography.
- Eight statistical charts and eight diagrams per language in PDF/SVG/PNG, with renderer diagnostics.
- Plotting scripts, translations and selected aggregate data used to regenerate the figures.
- Aggregate provenance in `figure_data/provenance.json`, including hashes of the original metric inputs.

## What is not public

The private vault, prompts, answers, per-question records, API credentials and raw generation/judgment logs are not included. These aggregate exports reproduce the figures, not the full generative experiment. The report discusses the original judge's abstention-scoring defect and limitations; presentation fixes do not resolve those scientific limitations.

## Changes in this delivery

- Full PT-BR translation, including figure text.
- Corrected chart title/axis/legend spacing and diagram text containment.
- Shared single-column report layout, figure-specific sizing and nearby table placement; long equations broken across lines. The IEEEtran class is used for typography, not to claim compliance with a journal submission template.
- Public, machine-independent figure data and generation scripts.

Application code and unrelated local changes are outside this delivery.
