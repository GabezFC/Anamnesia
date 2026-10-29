"""Prepare revised paper sources without touching historical outputs; no network/model calls.
Run after research_reanalysis.py. Rendering/build is a separate explicit step.
"""
import collections
import copy
import csv
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'data/reports-out'
OLD=BASE/'anamnesia-research-paper'
NEW=BASE/'finalizacao-2026-10-28/paper'
GEN=BASE/'benchmark-generativo-2026-10-25'
D=json.loads((BASE/'finalizacao-2026-10-28/evaluation/reanalysis.json').read_text(encoding='utf-8'))
A=['off_a','on_baseline_raw','on_graphify_raw','on_full','on_jev']
NEW.mkdir(exist_ok=True)
for name in ['Anamnesia_Research_Paper.tex','references.bib','tables.tex','TRACEABILITY.md','README.md','make_paper_figs.py','make_diagrams.py','gen_tables.py']:
    if not (NEW/name).exists():
        shutil.copy2(OLD/name,NEW/name)
if not (NEW/'figures').exists():
    shutil.copytree(OLD/'figures',NEW/'figures')
P=json.loads((GEN/'paper_stats.json').read_text(encoding='utf-8'))
S=json.loads((GEN/'summary_gen.json').read_text(encoding='utf-8'))
P['pooled_acc']={a:D['rules']['strict'][a]['accuracy'] for a in A}
P['paired']={a:{'diff':D['rules']['strict'][a]['strata']['all']['difference'],'lo':D['rules']['strict'][a]['strata']['all']['lo'],'hi':D['rules']['strict'][a]['strata']['all']['hi']} for a in A[1:]}
P['by_class']=D['by_class_strict']
for k,v in S.items():
    v['acc']=D['by_model']['strict'][v['model']][v['arm']]
    v['n_correct']=round(v['acc']*72)
    v['cost_per_correct']=v['cost_effective']/v['n_correct'] if v['n_correct'] else None
for a in A:
    denominator=sum(v['n_correct'] for v in S.values() if v['arm']==a and not v['local'])
    P['cost_per_correct_remote'][a]=P['cost_remote'][a]/denominator
(NEW/'revised_stats.json').write_text(json.dumps(P,indent=2),encoding='utf-8')
(NEW/'revised_summary.json').write_text(json.dumps(S,indent=2),encoding='utf-8')
for name in ['make_paper_figs.py','gen_tables.py']:
    # Regenerate deterministic source from historical copy on each run.
    t=(OLD/name).read_text(encoding='utf-8')
    t=t.replace('OUT = BASE / "anamnesia-research-paper"','OUT = Path(__file__).parent')
    t=t.replace('OUT = BASE / "anamnesia-research-paper" / "figures"','OUT = Path(__file__).parent / "figures"')
    t=t.replace('open(SRC / "summary_gen.json"','open(Path(__file__).parent / "revised_summary.json"')
    t=t.replace('open(SRC / "paper_stats.json"','open(Path(__file__).parent / "revised_stats.json"')
    if name=='make_paper_figs.py':
        t=t.replace('yerr=err, capsize=2, error_kw={"lw": .7}', 'linewidth=0.4')
        t=t.replace('set_ylim(60, 100)','set_ylim(0, 100)').replace('set_ylim(50, 100)','set_ylim(0, 100)')
        t=t.replace('text(i, 61,','text(i, 3,')
        t=t.replace('single run, temperature 0; per-bar 95% CI is roughly ±8 pp','strict correction; single run, temperature 0')
        t=t.replace('ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.32)','ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.42)')
        t=t.replace('figsize=(7.2, 2.4)','figsize=(7.2, 3.0)')
        t=t.replace('Accuracy, 72 answerable Q','Strict accuracy, 72 answerable Q')
        t=t.replace('Accuracy per model and context pipeline','Strict accuracy per model and context pipeline')
    else:
        t=t.replace('Pooled results over nine models','Strict-corrected results over nine models')
        t=t.replace('actual JEV spend was about US\\$0.010','tariff-calculated single-pass JEV cost was about US\\$0.010, not invoice-verified')
        t=t.replace('4000 resamples, seed 20261025','4000 resamples, seed 20261028; strict correction')
        t=t.replace('Per-model results (single run','Strict-corrected per-model results (single run')
        t=t.replace('Accuracy (\\%) by question class','Strict-corrected accuracy (\\%) by question class')
        # Keep original/R1 stratification table as historical, never pass strict P as original.
        t=t.replace('"acc": P["pooled_acc"], "paired": P["paired"]','"acc": json.load(open(SRC / "paper_stats.json", encoding="utf-8"))["pooled_acc"], "paired": json.load(open(SRC / "paper_stats.json", encoding="utf-8"))["paired"]')
        t=t.replace('Stratified accuracy (\\%), nine models pooled.','Historical original/R1 stratified accuracy (\\%), nine models pooled; strict correction is reported separately in the text.')
    (NEW/name).write_text(t,encoding='utf-8')
tex=(OLD/'Anamnesia_Research_Paper.tex').read_text(encoding='utf-8')
# Do not assume the earlier author/affiliation block was approved.
a=tex.index('\\author{'); b=tex.index('\\maketitle',a)
tex=tex[:a]+r'''\author{\IEEEauthorblockN{Authorship pending confirmation}
\IEEEauthorblockA{Affiliation pending confirmation\\
Technical report revised with the Hermes agent, 28 October 2026}}

'''+tex[b:]

def replace_line(prefix, replacement):
    global tex
    lines=tex.splitlines()
    matches=[i for i,l in enumerate(lines) if l.startswith(prefix)]
    if len(matches)!=1:
        raise ValueError(f'expected one source line for {prefix!r}, got {len(matches)}')
    lines[matches[0]]=replacement
    tex='\n'.join(lines)+'\n'

replace_line('Coding agents and chat assistants',r'''Coding agents repeatedly re-read project notes and need explicit mechanisms to retain knowledge across sessions. \anam{} is an agent-independent local memory gateway over a read-only Markdown vault, with lexical retrieval, optional graph enrichment and relevance judging, and budgeted context construction. We reanalyse two stored studies rather than repeat paid experiments: retrieval-only tests of 24 October and generation on 82 questions, nine models and five context pipelines on 25 October 2026. Across eight remote models, provider-reported generation cost falls by 81.7\% for auto+optimizer versus thresholded whole-note BM25. The original LLM judge mistakenly counted bare abstentions as factual answers. A strict, auditable correction yields 83.64\% versus 77.78\% accuracy on 72 answerable questions, paired difference $+5.86$ percentage points with question-cluster bootstrap 95\% CI $[-3.40,+15.28]$: neither superiority nor equivalence is established. Graphify falls to 59.26\%, and the default pipeline loses 7.78 percentage points on questions where the whole-note baseline supplies context. Broader prefix rule R1 is sensitivity only. Persistent storage is implemented, but historical tests do not establish real-agent long-horizon memory benefits. Source audits, limitations and non-invoiced cost components are explicitly separated from observations.''')
replace_line(r'\textbf{Volume.}',r'''\textbf{Volume and repeated judgments.} The generation log contains 3,797 rows: 3,690 unique successful answers and 107 failed attempts. All 45 model/arm cells have 82 successful answers. The judge log contains 3,847 records, not 3,690: 157 keys were judged twice, with one conflicting verdict. Scoring keeps the last judgment per (model, arm, question, repetition), matching the historical scripts; the duplicate audit is retained. All logged generation costs sum to US\$4.596553 and all judge records to US\$0.784137. Summing only final judgments gives US\$0.751408 and undercounts experiment overhead. These are provider-reported log amounts, not an invoice or a newly verified balance; unrecorded failure costs remain unknown.''')
replace_line(r'\textbf{Scoring.}',r'''\textbf{Scoring and uncertainty.} The historical gpt-4.1-mini judge returned CORRECT, INCORRECT or ABSTAIN. We preserve these labels and derive a strict correction: only a complete reply equal to the mandated abstention sentence, allowing whitespace, enclosing quotation marks and terminal punctuation, is changed from CORRECT to ABSTAIN on an answerable question. Appropriate abstention on unanswerable questions is not penalized. Mixed replies are not automatically corrected. R1 instead uses the original broad prefix expression and is reported separately as sensitivity. Remaining factual labels are not human-validated. Paired intervals resample the 72 questions with replacement, retaining all nine observed models within each question (4,000 draws; seed 20261028). Inference is conditional on this corpus and fixed model set, not independent over model/question rows. No equivalence margin or equivalence test was specified. Missing/invalid labels are excluded explicitly; none are missing for the primary pairs.''')
replace_line('Accuracy is statistically indistinguishable',r'''Under the strict correction, auto+optimizer has accuracy 83.64\% versus 77.78\% for \emph{Without}, a paired difference of $+5.86$ pp with 95\% question-cluster CI $[-3.40,+15.28]$ (Table~\ref{tab:paired}). The baseline pipeline scores 85.49\%, Graphify 59.26\%, and Graphify+JEV 81.48\%. Graphify's paired loss is $-18.52$ pp, CI $[-32.56,-4.48]$. An interval spanning zero does not establish statistical equivalence or absence of a quality cost. These are descriptive single-run outcomes on a small fixed corpus, not claims of universal model performance.''')
replace_line(r'\caption{Pooled headline results.',r'''\caption{Strict-corrected pooled results. (a) Provider-reported input tokens per query (nine-model descriptive mean). (b) Generation cost over eight remote models plus hatched, tariff-calculated JEV, not invoice-verified. (c) Strict-corrected accuracy; no absolute-proportion error bars are inferred from paired-difference intervals.}\label{fig:headline}''')
replace_line('Table~\\ref{tab:class} and Fig.',r'''Table~\ref{tab:class} and Fig.~\ref{fig:class} report strict-corrected class results; classes with only two or three questions are anecdotal. On stored contexts, answer-regex coverage is 38/72 for Graphify, 58/72 for \emph{Without}, 61/72 for baseline, 60/72 for auto+optimizer and 59/72 for JEV. This is a surface-match proxy, not a semantic answer check. Labels-only graph structure, section ranking and context trimming are candidate mechanisms, but these aggregate results alone cannot isolate a cause. The retained question definitions reproduce this proxy; the original scratch JSON with validated gold and alternative sources is absent.''')
replace_line('The \\emph{Without} harness abstains',r'''The \emph{Without} harness delivered empty context for 12 of 72 answerable questions. With strict correction, on the 60 remaining questions auto+optimizer loses $7.78$ pp versus \emph{Without} (95\% CI $[-14.63,-1.67]$); on the 12 empty-context questions its difference is $+74.07$ pp. The aggregate is not evidence of uniformly preserved quality. For auto+optimizer versus \emph{Without}, all 648 model/question pairs are available: 446 both correct, 58 correct only Without, 96 correct only With, and 48 neither correct. The latter category includes wrong answers and abstentions, not only factual errors. The machine-readable pair table preserves the actual verdicts for each case.''')
replace_line('The \\emph{Without} score on those',r'''The original judged headline was 86.88\% versus 86.57\%. Strict correction changes 57 Without, 21 baseline, 80 Graphify, 21 auto+optimizer and 23 JEV verdicts. Historical R1 changes 63, 31, 102, 34 and 31, respectively; its point estimates are reproduced exactly (76.85\%, 83.95\%, 55.86\%, 81.64\%, 80.25\%). Unlike strict correction, R1 also includes replies with further text after an abstention prefix, whose factual adequacy is uncertain without review. Table~\ref{tab:strata} is explicitly historical original/R1 evidence, not the strict headline. Audit files identify each reply by model, arm, question, source line and SHA256, without exporting private text. Neither deterministic rule is a new LLM judgment or a full human reassessment.''')
replace_line(r'\textbf{What is demonstrated.}',r'''\textbf{What is demonstrated.} The default pipeline reduced generation cost by 81.7\% against the historical whole-note baseline, on this fixed workload. Strict-corrected quality has both wins and losses; its aggregate interval does not demonstrate superiority or equivalence. Retrieval-only recall gains are specific to the evaluated source metrics and do not imply that the answer-bearing passage reaches the generator. Token reduction is not automatically net economic benefit after auxiliary services, retries, maintenance and energy.''')
replace_line(r'\textbf{What is not shown, or is contradicted.}',r'''\textbf{What is not shown, or is contradicted.} The JEV arm has larger input context and calculated deployment overhead, with strict accuracy 81.48\% versus 83.64\% for auto+optimizer. A causal JEV benefit is not isolated because the candidate pipelines differ. Graphify's low answer-bearing-context coverage is observed; attributing all losses to label indexing or adaptive truncation without per-question reproduction would overstate the evidence. The stratified deficit where Without retrieves remains a negative result.''')
replace_line(r'\textbf{Why trimmed context can lose.}',r'''\textbf{Why trimmed context can lose.} Candidate coverage, rank-based cutoffs and snippet budgets can remove answer-bearing text. These are testable hypotheses, not interchangeable diagnoses. Any correction must be validated on independent synthetic fixtures and later on a held-out development/test split, rather than tuned to hide the current negative result.''')
replace_line(r'\textbf{Internal validity.}',r'''\textbf{Internal validity.} One generation repetition per cell; a single LLM judge without human calibration; 157 repeated judgments and one label conflict. Last-write scoring matches history but is not intrinsically ground truth. Strict correction addresses an identifiable bare-abstention error, not paraphrased abstentions or all factual grading errors. R1 is broader sensitivity, not a definitive correction. The thresholded Without empty-context gate changes the comparison substantially. Regular-expression context presence is a proxy. Shared judge/generator model families may induce self-preference. The frozen question JSON is no longer available, preventing complete reproduction of gold-source validation.''')
replace_line('\\anam{} is a working, local, agent-independent memory gateway',r'''\anam{} implements a local, agent-independent retrieval and memory gateway. On the stored experiment, auto+optimizer reduced provider-reported generation cost by 81.7\% against thresholded whole-note BM25. Strict bare-abstention correction yields 83.64\% versus 77.78\% accuracy, but the paired interval spans zero and is not evidence of equivalence. Quality is lower when the baseline retrieves, and Graphify loses 18.52 pp overall. JEV deployment cost is tariff-calculated and its pipeline does not outperform auto+optimizer here. Implemented persistence mechanisms and small synthetic checks must not be presented as proof of robust memory across real long conversations. These negative results and remaining audit limits constrain the claims.''')
replace_line('All logs (',r'''Historical logs and PDFs remain unchanged under \texttt{data/reports-out/benchmark-generativo-2026-10-25/} and \texttt{anamnesia-research-paper/}. Revised sources, statistics, addendum, audit and reproduction scripts are under \texttt{data/reports-out/finalizacao-2026-10-28/} and \texttt{scripts/research\_reanalysis.py}. These ignored local artifacts are not a claim of public availability. Raw historical contexts contain private project material and must not be published without a separate review. This offline correction made no paid benchmark calls.''')
# Source observations are not historical effective configuration.
tex=tex.replace('(the graph is built per session)', '(historical observation; graph lifecycle and cache configuration require separate diagnosis)')
tex=tex.replace('the author\'s real project notes','the project owner\'s real project notes')
# Label defaults uniformly, not as evidence that the historical execution used them.
tex=tex.replace('Fig.~\\ref{fig:flow} summarizes the stages of a search;', 'The following numeric settings describe code defaults, not independently verified historical environment overrides. Fig.~\\ref{fig:flow} summarizes the stages of a search;')
tex=tex.replace('The paper adds no new experiments and no new API spending.','The revision adds offline reanalysis and separately labelled local checks, not paid benchmark calls.')
# Break long equations inside their column and paths at explicit URL breakpoints.
tex=tex.replace(r'\hat n_{\mathrm{JEV}}\approx 340\,R+209\,Q\quad\text{(input tokens)},\qquad C_{\mathrm{JEV}}=\frac{n_{\mathrm{JEV}}}{10^{6}}\cdot 0.042\ \text{US\$},\label{eq:jev}',r'''\begin{aligned}
\hat n_{\mathrm{JEV}}&\approx 340R+209Q,\\
C_{\mathrm{JEV}}&=\frac{n_{\mathrm{JEV}}}{10^{6}}\cdot0.042\ \text{US\$}.
\end{aligned}\label{eq:jev}''')
tex=tex.replace(r'C^{\text{with}}_m=\sum_{q}\Bigl[C_{\mathrm{gen}}\bigl(m,\mathrm{ctx}_q\bigr)+C_{\mathrm{JEV}}(q)\Bigr],\quad C^{\text{without}}_m=\sum_{q}C_{\mathrm{gen}}\bigl(m,\mathrm{notes}_q\bigr),\label{eq:cost}',r'''\begin{aligned}
C^{\text{with}}_m&=\sum_q\bigl[C_{\mathrm{gen}}(m,\mathrm{ctx}_q)+C_{\mathrm{JEV}}(q)\bigr],\\
C^{\text{without}}_m&=\sum_q C_{\mathrm{gen}}(m,\mathrm{notes}_q).
\end{aligned}\label{eq:cost}''')
tex=tex.replace(r'\usepackage{url}',r'\usepackage{url}'+ '\n' +r'\usepackage{seqsplit}')
tex=tex.replace(r'\texttt{data/reports-out/benchmark-generativo-2026-10-25/}',r'\path{data/reports-out/benchmark-generativo-2026-10-25/}')
tex=tex.replace(r'\texttt{data/reports-out/finalizacao-2026-10-28/}',r'\path{data/reports-out/finalizacao-2026-10-28/}')
tex=tex.replace(r'\texttt{scripts/research\_reanalysis.py}',r'\path{scripts/research_reanalysis.py}')
tex=tex.replace('with local retrieval and optimization costing zero dollars (CPU only; energy not measured).','with no API fee for deterministic local retrieval and optimization; local compute, maintenance and electricity are unmetered, not economically free.')
# Table columns are naturally ragged-right instead of creating long justified gaps.
tex=tex.replace(r'\usepackage{booktabs}',r'\usepackage{booktabs}'+ '\n' +r'\usepackage{array}'+ '\n' +r'\newcolumntype{P}[1]{>{\raggedright\arraybackslash}p{#1}}')
tex=tex.replace('p{0.22\\columnwidth}p{0.70\\columnwidth}','P{0.22\\columnwidth}P{0.70\\columnwidth}')
(NEW/'Anamnesia_Research_Paper.tex').write_text(tex,encoding='utf-8')
# Diagram titles do not embed manual figure numbers that conflict with LaTeX floats.
import re
u=(OLD/'make_diagrams.py').read_text(encoding='utf-8')
u=re.sub(r'Fig\. \d+  ', '', u)
u=u.replace('w = .92; gap = .13','w = .90; gap = .13')
u=u.replace('tool schema ≈ 1 tool (minimal)','1 exposed tool (minimal)')
u=u.replace('≤6000 tok, ≤1500/src', '≤6000 tokens\\n≤1500 per source')
u=u.replace('sfs=6, tc=', 'sfs=6, tc=')
u=u.replace('import matplotlib.pyplot as plt','import matplotlib.pyplot as plt\nimport textwrap')
u=u.replace('    ax.add_patch(FancyBboxPatch((x, y), w, h,', '    fs=max(fs,6.5); sfs=max(sfs,5.3)\n    title="\\n".join(textwrap.fill(line, width=max(9,int(w*72/(fs*.58)))) for line in title.split("\\n"))\n    if sub: sub="\\n".join(textwrap.fill(line, width=max(12,int(w*72/(sfs*.56)))) for line in sub.split("\\n"))\n    ax.add_patch(FancyBboxPatch((x, y), w, h,')
(NEW/'make_diagrams.py').write_text(u,encoding='utf-8')
print('prepared',NEW)
