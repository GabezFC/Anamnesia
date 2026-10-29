"""Offline, non-destructive reanalysis. Standard library only. Never imports API harnesses.
Run from repository root: python scripts/research_reanalysis.py --question-source PATH
Private answer text/question text is not exported. Audit uses source line + SHA256.
Historical question definitions are read via ast.literal_eval, never executed.
"""
from __future__ import annotations
import argparse
import ast
import collections
import csv
import hashlib
import json
import math
import random
import re
from pathlib import Path

ARMS = ['off_a', 'on_baseline_raw', 'on_graphify_raw', 'on_full', 'on_jev']
PREFIX = re.compile(r'^\W*n[ãa]o encontrei essa informa', re.I)
EXACT = re.compile(r'^n[ãa]o encontrei essa informa[çc][ãa]o no contexto[.!]?$', re.I)

def classify_abstention(text):
    stripped = text.strip().strip('"\'“”‘’` ').strip()
    if EXACT.fullmatch(stripped):
        return 'bare'
    return 'mixed_prefix' if PREFIX.match(text) else 'other'

def corrected_verdict(verdict, text, answerable, rule):
    if not answerable or verdict != 'CORRECT':
        return verdict
    label = classify_abstention(text)
    if (rule == 'strict' and label == 'bare') or (rule == 'r1' and PREFIX.match(text)):
        return 'ABSTAIN'
    return verdict

def key(row):
    return row['model'], row['arm'], row['qid'], row['rep']

def index_rows(rows):
    index = {}
    groups = collections.defaultdict(list)
    for line, row in rows:
        index[key(row)] = (line, row)
        groups[key(row)].append((line, row))
    duplicates = []
    for k, group in groups.items():
        if len(group) > 1:
            duplicates.append(dict(zip(['model','arm','qid','rep'], k), lines=[x[0] for x in group],
                                   conflicting_verdicts=len({x[1].get('verdict') for x in group}) > 1))
    return index, duplicates

def pair_category(off, on):
    if off is None or on is None:
        return 'missing'
    return 'both_correct' if off and on else 'off_only' if off else 'on_only' if on else 'neither_correct'

def cluster_interval(groups, repetitions=4000, seed=20261028):
    qs = sorted(groups)
    total_n = sum(len(groups[q]) for q in qs)
    if not total_n:
        return dict(questions=0, pairs=0, difference=None, lo=None, hi=None)
    sums = [sum(groups[q]) for q in qs]
    counts = [len(groups[q]) for q in qs]
    rng = random.Random(seed)
    samples = []
    for _ in range(repetitions):
        ix = [rng.randrange(len(qs)) for _ in qs]
        samples.append(sum(sums[i] for i in ix) / sum(counts[i] for i in ix))
    samples.sort()
    return dict(questions=len(qs), pairs=total_n, difference=sum(sums)/total_n,
                lo=samples[math.floor(.025*(repetitions-1))], hi=samples[math.ceil(.975*(repetitions-1))])

def read_jsonl(path):
    rows, invalid = [], []
    for line, text in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not text.strip():
            continue
        try:
            obj = json.loads(text)
            if not isinstance(obj, dict):
                raise ValueError('not object')
            rows.append((line, obj))
        except (ValueError, json.JSONDecodeError):
            invalid.append(line)
    return rows, invalid

def question_metadata(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    value = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'Q' for t in n.targets))
    if not isinstance(value, (ast.List, ast.Tuple)):
        raise ValueError('Q must be a literal sequence')
    result = {}
    for i, entry in enumerate(value.elts, 1):
        if not isinstance(entry, ast.Tuple) or len(entry.elts) != 4:
            raise ValueError('invalid question definition')
        result[f'd2q{i:03d}'] = {'classe': ast.literal_eval(entry.elts[0]),
                                'answer_regex': ast.literal_eval(entry.elts[3])}
    return result

def csv_write(path, rows):
    if not rows:
        path.write_text('', encoding='utf-8')
        return
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

def run(args):
    root = Path(__file__).resolve().parents[1]
    src = root/'data/reports-out/benchmark-generativo-2026-10-25'
    out = root/'data/reports-out/finalizacao-2026-10-28/evaluation'
    out.mkdir(parents=True, exist_ok=True)
    call_rows, ci = read_jsonl(src/'calls.jsonl')
    judge_rows, ji = read_jsonl(src/'judge.jsonl')
    calls, cd = index_rows([(n,r) for n,r in call_rows if 'text' in r])
    judges, jd = index_rows(judge_rows)
    first_judges = {}
    for n,r in judge_rows:
        first_judges.setdefault(key(r),(n,r))
    ctx = {a: json.loads((src/f'ctx_{a}.json').read_text(encoding='utf-8')) for a in ARMS}
    models = sorted({k[0] for k in calls})
    answerability = collections.defaultdict(set)
    for _,r in call_rows:
        answerability[r['qid']].add(r['answerable'])
    assert all(len(v)==1 for v in answerability.values()), 'conflicting answerability'
    answerable = sorted(q for q,v in answerability.items() if next(iter(v)))
    noanswer = sorted(q for q,v in answerability.items() if not next(iter(v)))
    meta = question_metadata(Path(args.question_source)) if args.question_source else {}
    if meta:
        assert set(meta) == set(answerable), 'recovered metadata IDs differ'
    def verdict(k, rule, index=judges):
        if k not in calls or k not in index:
            return None
        row = calls[k][1]
        return corrected_verdict(index[k][1]['verdict'], row['text'], row['answerable'], rule)
    cases=[]
    for k,(line,c) in sorted(calls.items()):
        if k not in judges:
            continue
        jline,j=judges[k]
        label=classify_abstention(c['text'])
        if label != 'other':
            cases.append(dict(model=k[0],arm=k[1],qid=k[2],rep=k[3],answerable=c['answerable'],
                label=label,original=j['verdict'],strict=verdict(k,'strict'),r1=verdict(k,'r1'),
                call_line=line,judge_line=jline,text_sha256=hashlib.sha256(c['text'].encode()).hexdigest()))
    csv_write(out/'abstention_audit.csv',cases)
    (out/'judge_duplicates.json').write_text(json.dumps(jd,indent=2),encoding='utf-8')
    summaries={}
    pairs=[]
    for rule in ['original','strict','r1']:
        result={}
        for a in ARMS:
            kk=[(m,a,q,1) for m in models for q in answerable]
            vv=[verdict(k,rule) for k in kk]
            valid=[v for v in vv if v in {'CORRECT','INCORRECT','ABSTAIN'}]
            flips=sum(judges[k][1]['verdict']=='CORRECT' and verdict(k,rule)=='ABSTAIN' for k in kk if k in calls and k in judges)
            strata={}
            for label,qs in [('all',answerable),('off_retrieved',[q for q in answerable if not ctx['off_a'][q]['abstained']]),
                             ('off_empty',[q for q in answerable if ctx['off_a'][q]['abstained']])]:
                group=collections.defaultdict(list)
                counts=collections.Counter()
                for m in models:
                    for q in qs:
                        b=verdict((m,'off_a',q,1),rule)
                        v=verdict((m,a,q,1),rule)
                        b=None if b not in {'CORRECT','INCORRECT','ABSTAIN'} else b=='CORRECT'
                        v=None if v not in {'CORRECT','INCORRECT','ABSTAIN'} else v=='CORRECT'
                        cat=pair_category(b,v)
                        counts[cat]+=1
                        if cat!='missing':
                            assert v is not None and b is not None
                            group[q].append(int(v)-int(b))
                        if label=='all' and a!='off_a':
                            pairs.append(dict(rule=rule,model=m,arm=a,qid=q,rep=1,category=cat,
                                              off_verdict=verdict((m,'off_a',q,1),rule),on_verdict=verdict((m,a,q,1),rule)))
                strata[label]=dict(counts=dict(counts),**cluster_interval(group))
            noans=[verdict((m,a,q,1),rule) for m in models for q in noanswer]
            result[a]=dict(n_expected=len(kk),n_evaluable=len(valid),n_missing=len(vv)-len(valid),
                          correct=valid.count('CORRECT'),accuracy=valid.count('CORRECT')/len(valid) if valid else None,
                          flips=flips,unanswerable_expected=len(noans),unanswerable_evaluable=sum(v is not None for v in noans),
                          appropriate_abstentions=noans.count('ABSTAIN'),strata=strata)
        summaries[rule]=result
    csv_write(out/'paired_outcomes.csv',pairs)
    first_last_changed=sum(first_judges[k][1]['verdict']!=judges[k][1]['verdict'] for k in judges)
    costs={}
    for a in ARMS:
        remote=[r for _,r in calls.values() if r['arm']==a and not r['model'].startswith('ollama:')]
        gen=sum(r['cost'] for r in remote if r.get('cost') is not None)
        jev=sum((ctx[a][r['qid']].get('jev_cost') or 0) for r in remote) if a=='on_jev' else 0
        costs[a]=dict(provider_reported_generation=gen,missing_generation_cost=sum(r.get('cost') is None for r in remote),
                      jev_calculated_per_deployment=jev,effective_gen_plus_calculated_jev=gen+jev,
                      mean_input_tokens=sum(r['tin'] for r in remote if r.get('tin') is not None)/len(remote),
                      mean_context_tokens=sum(r['ctx_tokens_tiktoken'] for r in remote)/len(remote))
    baseline=costs['off_a']['effective_gen_plus_calculated_jev']
    for a in costs:
        costs[a]['saving_fraction']=1-costs[a]['effective_gen_plus_calculated_jev']/baseline
    input_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [src/'calls.jsonl',src/'judge.jsonl',*[src/f'ctx_{a}.json' for a in ARMS]]}
    if args.question_source:
        input_hashes['recovered_question_source']=hashlib.sha256(Path(args.question_source).read_bytes()).hexdigest()
    coverage={a:dict(answerable_with_regex=len(meta),hits=sum(bool(re.search(meta[q]['answer_regex'],ctx[a][q]['ctx'],re.I|re.S)) for q in meta)) for a in ARMS}
    by_model={rule:{m:{a:sum(verdict((m,a,q,1),rule)=='CORRECT' for q in answerable)/len(answerable) for a in ARMS} for m in models} for rule in summaries}
    by_class={}
    for cl in sorted({v['classe'] for v in meta.values()}):
        qs=[q for q,v in meta.items() if v['classe']==cl]
        by_class[cl]=dict(n=len(qs),**{a:sum(verdict((m,a,q,1),'strict')=='CORRECT' for m in models for q in qs)/(len(models)*len(qs)) for a in ARMS})
    first_policy_accuracy={a:sum(verdict((m,a,q,1),'strict',first_judges)=='CORRECT' for m in models for q in answerable)/(len(models)*len(answerable)) for a in ARMS}
    prior_r1=json.loads((src/'paper_sensitivity.json').read_text(encoding='utf-8'))
    r1_reproduces=all(abs(summaries['r1'][a]['accuracy']-prior_r1['all']['acc'][a])<1e-12 for a in ARMS)
    outdata=dict(schema=1,by_class_strict=by_class,first_judgment_strict_accuracy=first_policy_accuracy,r1_historical_point_estimates_reproduced=r1_reproduces,seed=20261028,bootstrap_repetitions=4000,bootstrap_unit='question; fixed observed models pooled',
                 policy='last valid success + last judge per (model,arm,qid,rep), matching historical scripts; duplicates retained in audit',
                 limitations=['strict is deterministic bare-abstention correction, not human factual regrading',
                              'R1 includes mixed-prefix responses and is sensitivity only',
                              'original frozen question JSON absent; class/regex recovered from retained definition source; gold/alt source verification not recreated',
                              'confidence intervals conditional on this corpus and fixed models; no equivalence margin or equivalence test',
                              'historical failures without cost do not prove zero charges; no invoice or live balance verification'],
                 volume=dict(call_rows=len(call_rows),valid_calls=len(calls),call_duplicate_keys=len(cd),
                             failed_rows=sum('error'in r for _,r in call_rows),judge_rows=len(judge_rows),unique_judgments=len(judges),
                             duplicate_judge_keys=len(jd),extra_judge_rows=len(judge_rows)-len(judges),
                             conflicting_duplicate_keys=sum(x['conflicting_verdicts'] for x in jd),first_last_verdict_changes=first_last_changed,
                             invalid_call_lines=ci,invalid_judge_lines=ji,models=len(models),answerable_questions=len(answerable),unanswerable_questions=len(noanswer)),
                 rules=summaries,by_model=by_model,costs=costs,coverage_proxy=coverage,
                 historical_spending=dict(generation_all_logged=sum(r.get('cost') or 0 for _,r in call_rows),
                      judge_all_logged=sum(r.get('judge_cost') or 0 for _,r in judge_rows),
                      judge_last_only=sum(r.get('judge_cost') or 0 for _,r in judges.values())),inputs_sha256=input_hashes,
                 new_benchmark_api_spend=0)
    (out/'reanalysis.json').write_text(json.dumps(outdata,indent=2,ensure_ascii=False),encoding='utf-8')
    table=['# Evaluation addendum — 28 October 2026','','Offline reanalysis; historical inputs unchanged. No new model calls.',
           'No private question or answer text is reproduced. Audit cases by input line and SHA256.',
           '', '| Arm | Original judged % | Strict bare-abstention correction % | R1 sensitivity % | Strict flips |',
           '|---|---:|---:|---:|---:|']
    for a in ARMS:
        table.append(f"| {a} | {100*summaries['original'][a]['accuracy']:.2f} | {100*summaries['strict'][a]['accuracy']:.2f} | {100*summaries['r1'][a]['accuracy']:.2f} | {summaries['strict'][a]['flips']} |")
    table += ['','## Criteria','Strict: only the entire mandated abstention sentence (optional final punctuation, whitespace and enclosing quotes) is reclassified from CORRECT to ABSTAIN, only for answerable questions. Unanswerable cases retain their original verdict. Prefix followed by additional text is ambiguous and is NOT automatically corrected under strict.',
              'R1: historical broad prefix regex, including mixed answers; reproduced as sensitivity, not a definitive factual reassessment.',
              'Not all other abstention paraphrases are detected. Remaining factual verdicts have not been independently human-validated.',
              '', '## Paired comparisons (strict; percentage points)',
              '| Arm | Pairs | Both correct | OFF only | ON only | Neither correct | Difference | 95% question-cluster bootstrap CI |',
              '|---|---:|---:|---:|---:|---:|---:|---|']
    for a in ARMS[1:]:
        s=summaries['strict'][a]['strata']['all']; c=s['counts']
        table.append(f"| {a} | {s['pairs']} | {c.get('both_correct',0)} | {c.get('off_only',0)} | {c.get('on_only',0)} | {c.get('neither_correct',0)} | {100*s['difference']:+.2f} | [{100*s['lo']:+.2f}, {100*s['hi']:+.2f}] |")
    table += ['','Bootstrap resamples questions and retains all observed models for each question (4,000 draws, seed 20261028). Models are fixed, not nine independent replications of each question. Missing judgments are excluded explicitly, never counted as errors. No equivalence test was specified; a confidence interval spanning zero is not evidence of equivalence. No unclustered pooled McNemar test is reported.',
              '', '## Completeness and repeated judgments',json.dumps(outdata['volume'],indent=2),
              'Last-write policy matches historical scripts. All judge rows, including duplicate charges, count in experimental overhead. Selecting only final judgments undercounts spending. Duplicate verdict conflicts are a source of scoring uncertainty; see judge_duplicates.json.',
              '', '## Cost accounting',json.dumps(outdata['historical_spending'],indent=2),
              'Provider-reported generation and tariff-calculated JEV are separate in reanalysis.json. JEV is charged per deployed pipeline/model comparison (amortized reuse across benchmark models is not presumed); this is not an invoice for actual TypeSafe spend. Evaluation judging is experiment overhead, not deployment savings. Missing failed-request costs, energy and agent/subscription operation are unmeasured. No balances were checked.',
              '', '## Reproduction and limitations',
              'Run scripts/research_reanalysis.py with --question-source pointing to the retained d2_questions_src.py. Core accuracy/pairs do not require question text; regex coverage is optional. The original scratch questions_d2.json is absent; ast.literal_eval recovers question classes/regex, not the frozen gold-source validation. Source SHA256 values are recorded in reanalysis.json.',
              'Full candidate answers remain only in historical calls.jsonl. abstention_audit.csv links line numbers and hashes without copying private content. paired_outcomes.csv includes all pairs, not just selected wins. Historical PDFs remain original; use this addendum and revised paper for interpretation.',
              '', 'New benchmark API charges during this reanalysis: US$0. Agent/subscription fees and electricity: not metered.']
    (out/'ADDENDUM.md').write_text('\n'.join(table)+'\n',encoding='utf-8')
    print(json.dumps(dict(volume=outdata['volume'],historical_spending=outdata['historical_spending'],
                          strict_accuracy={a:summaries['strict'][a]['accuracy'] for a in ARMS},out=str(out)),indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--question-source',help='retained source definitions; optional and read-only')
    run(p.parse_args())
