"""Audit the v2 optimization benchmark report. Read-only; prints the table the README needs."""
import json
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/opt_stack_v2.json")
d = json.loads(path.read_text(encoding="utf-8"))

ds = d["dataset"]
print(f"questions={ds['questions']}  notes={ds['notes']}  sections={ds['sections_indexed']}")
print(f"vault={Path(ds['vault']).name}  passes={d['config']['passes']}  generated={d['generated_at']}")
print()

hdr = (f"{'arm':<26}{'judge':>8}{'vs_base':>9}{'warm':>8}{'ctx':>8}{'total':>9}{'amp':>6}"
       f"{'recall':>8}{'prec':>7}{'req':>5}{'quest':>7}{'unsel':>7}{'cache':>7}{'regr':>5}")
print(hdr)
print("-" * len(hdr))

for name, a in d["arms"].items():
    pq = d["per_question"][name]
    unsel = sum((r.get("metrics") or {}).get("documents_unselected", 0) for r in pq)
    sv = a.get("savings_vs_baseline") or {}
    # savings_vs_baseline is a SAVING (positive = cheaper than baseline). Print it as a signed
    # delta against the baseline so it reads the same way as the runner's own table.
    pct = f"{-sv['judge_tokens_saved_pct']*100:+.1f}%" if sv.get("judge_tokens_saved_pct") is not None else "-"
    warm = a.get("warm_pass", {}).get("judge_tokens_total")
    regr = a.get("recall_vs_baseline", {}).get("questions_regressed_n", "-")
    print(f"{name:<26}{a['judge_tokens_total']:>8}{pct:>9}{str(warm):>8}"
          f"{a['context_tokens_total']:>8}{a['total_tokens_total']:>9}"
          f"{str(a['amplification_overall']):>6}{str(a['recall']['mean']):>8}"
          f"{str(a['precision']['mean']):>7}{a['jev_calls_total']:>5}"
          f"{a['relevance_questions_total'] + a['injection_questions_total']:>7}"
          f"{unsel:>7}{a['cache_hits_total']:>7}{str(regr):>5}")

print()
print("integrity checks")
print("-" * 60)
for name, a in d["arms"].items():
    sh = d["shadow"][name]
    cl = sh["cache_layers"]
    print(f"{name:<26} empty_ctx={a['empty_contexts']} fallback={a['fallbacks']} "
          f"agree={a.get('routing_agreement', {}).get('agreement_rate')} "
          f"lookups={cl['lookups']} hits_l1={cl['hits_l1']} hits_l2={cl['hits_l2']} "
          f"hits_l3={cl['hits_l3']} hitrate={sh['cache_hit_rate']}")

print()
print("early stopping / injection gating")
print("-" * 60)
for name, sh in d["shadow"].items():
    if sh["early_stop_reasons"] or sh["injection_skip_reasons"]:
        print(f"{name:<26} stop={sh['early_stop_reasons']} inj_skip={sh['injection_skip_reasons']}")

print()
print("zero-evidence shadow (must never be promoted)")
for name, sh in d["shadow"].items():
    ze = sh["zero_evidence"]
    if ze["agreements"] or ze["disagreements"]:
        print(f"  {name:<24} agree={ze['agreements']} disagree={ze['disagreements']} "
              f"precision={ze['precision']} verdict={ze['verdict']}")

print()
print("cross-check: summary totals recomputed from per_question rows")
print("-" * 60)
for name, a in d["arms"].items():
    pq = d["per_question"][name]
    recomputed = sum((r["jev_input"] or 0) + (r["jev_output"] or 0) for r in pq)
    reported = a["judge_tokens_total"]
    flag = "OK" if recomputed == reported else "MISMATCH"
    print(f"  {name:<26} reported={reported:>8} recomputed={recomputed:>8} "
          f"rows={len(pq):>4} {flag}")
    if recomputed != reported:
        print(f"      per-question mean = {recomputed / max(1, len(pq)):.0f} tokens/question")

print()
print("leak invariant: every candidate sent must land in exactly one routing state")
print("-" * 60)
for name, a in d["arms"].items():
    ok = a.get("routing_accounts_for_all_candidates")
    print(f"  {name:<26} sent={a['candidates_sent_total']:>5} "
          f"routed={sum(a['routing'].values()):>5} "
          f"unselected={a['routing'].get('UNSELECTED', 'n/a'):>5} "
          f"{'OK' if ok else 'MISMATCH (' + str(a.get('routing_unaccounted')) + ')'}")

print()
print("cost model check: input_tokens ~ 340*requests + 209*questions")
for name, a in d["arms"].items():
    req = a["jev_calls_total"]
    q = a["relevance_questions_total"] + a["injection_questions_total"]
    pred = 340 * req + 209 * q
    actual = a["judge_tokens_total"]
    err = (actual - pred) / actual * 100 if actual else 0
    print(f"  {name:<26} predicted={pred:>8} actual={actual:>8} error={err:>+6.1f}%")

