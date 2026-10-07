"""CLI (§7). Usable without any agent connected.

  python -m memory_gateway search "pergunta" [--pipeline auto] [--json]
  python -m memory_gateway benchmark [--pipeline P ...] [--agent hermes --provider P --model M] [--repetitions N]
  python -m memory_gateway sweep
  python -m memory_gateway stats
  python -m memory_gateway info
  python -m memory_gateway vault-check [--save FILE | --compare FILE]
  python -m memory_gateway vault-lint [--vault PATH] [--json]
  python -m memory_gateway memory-audit [--vault PATH] [--db benchmark.db] [--json] [-v]
  python -m memory_gateway index
  python -m memory_gateway db-maintenance [--older-than-days N] [--db PATH] [--apply] [--vacuum]
  python -m memory_gateway db-prune --keep-days N [--keep-sessions s1,s2] [--dry-run] [--vacuum]
"""
from __future__ import annotations

import argparse
import json
import sys

from app.schemas.models import PIPELINES
from app.services.vault_lint import MAX_NOTE_CHARS as MAX_NOTE_CHARS_LITERAL


def _gw():
    from app.gateway.memory_gateway import MemoryGateway
    g = MemoryGateway()
    g.warm()
    return g


def _print(obj, as_json: bool):
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
        return True
    return False


def cmd_search(a):
    g = _gw()
    ov = {}
    if a.jev_mode:
        ov["mode"] = a.jev_mode
    if a.threshold is not None:
        ov["relevance_threshold"] = a.threshold
        ov["review_threshold"] = min(a.threshold, g.jev_cfg.review_threshold)
    r = g.search(a.query, a.pipeline, a.max_results, jev_overrides=ov or None, run_meta={"kind": "cli", "agent": "cli"})
    if _print(r.to_dict(), a.json):
        return
    m = r.metrics
    print(f"pipeline={r.pipeline} run_id={r.run_id}")
    print(f"candidatos={m.get('candidates')} sobreviventes={m.get('survivors')} "
          f"tokens_candidatos={m.get('candidate_tokens_before_filter')} tokens_contexto={m.get('context_tokens')} "
          f"latência={m.get('total_latency_ms')}ms jev_tokens={m.get('jev_tokens')} jev_cost={m.get('jev_cost')}")
    for s in r.sources:
        rel = f" rel={s.relevance:.2f} {s.decision}" if s.relevance is not None else ""
        print(f"  - {s.file} :: {s.section[:70]}{rel}")
    if a.show_context:
        print("\n" + r.context)


def cmd_benchmark(a):
    from app.benchmark.runner import BenchmarkRunner, estimate_plan, load_questions
    g = _gw()
    qs = load_questions(g.bench_cfg.questions_path)
    if a.questions:
        qs = [q for q in qs if q["id"] in set(a.questions)]
    consumers = [{"agent": a.agent, "provider": a.provider, "model": a.model}] if a.agent else []
    pipelines = a.pipeline or list(PIPELINES)
    plan = estimate_plan(len(qs), pipelines, consumers, a.repetitions)
    print(f"plano: {plan}", file=sys.stderr)
    if a.dry_run:
        return
    ov = {"mode": a.jev_mode} if a.jev_mode else None
    runner = BenchmarkRunner(g, progress=lambda e: print(
        f"  {e['question_id']} {e['pipeline']:<13} ctx={e['metrics'].get('context_tokens')} "
        f"lat={e['metrics'].get('total_latency_ms')}ms", file=sys.stderr))
    res = runner.run(qs, pipelines=pipelines, consumers=consumers, repetitions=a.repetitions,
                     warmup=not a.no_warmup, jev_overrides=ov)
    if not _print(res, a.json):
        print(json.dumps({"session_id": res["session_id"], "runs": res["runs"]}, ensure_ascii=False))
        from app.benchmark.report import render_session
        print(render_session(g.db, res["session_id"]))


def cmd_sweep(a):
    from config.benchmark import SWEEP_THRESHOLDS, SWEEP_THRESHOLDS_EXTENDED
    from app.benchmark.runner import BenchmarkRunner, load_questions
    g = _gw()
    qs = load_questions(g.bench_cfg.questions_path)
    if a.questions:
        qs = [q for q in qs if q["id"] in set(a.questions)]
    res = BenchmarkRunner(g).threshold_sweep(qs, thresholds=SWEEP_THRESHOLDS_EXTENDED if a.extended else SWEEP_THRESHOLDS)
    if not _print(res, a.json):
        print(f"{'thr':>5} {'kept':>5} {'ctx_tokens':>10} {'jev_cost':>10} {'recall':>7} {'FN rate':>8}")
        for r in res["rows"]:
            print(f"{r['threshold']:>5.2f} {r['documents_kept']:>5} {r['context_tokens']:>10} "
                  f"{r['jev_cost']!s:>10} {r['expected_source_recall']!s:>7} {r['false_negative_rate']!s:>8}")


def cmd_stats(a):
    from app.benchmark.report import render_session
    from app.benchmark.statistics import aggregate_stats
    g = _gw()
    if a.session:
        print(render_session(g.db, a.session))
        return
    s = aggregate_stats(g.db)
    if _print(s, a.json):
        return
    print(f"runs={s['total_runs']} sessões={s['sessions']} falsos_negativos={s['false_negatives']}")
    for grp in s["groups"]:
        lat, ctx = grp["total_latency_ms"], grp["context_tokens"]
        print(f"  {grp['agent']:<10} {grp['model']:<14} {grp['pipeline']:<13} n={grp['runs']:<3} "
              f"lat_mediana={lat['median']}ms ctx_mediana={ctx['median']} jev_tokens_médio={grp['jev_input_tokens']['mean']}")


def cmd_info(a):
    from app.gateway.memory_gateway import MemoryGateway
    info = MemoryGateway().system_info()
    print(json.dumps(info, ensure_ascii=False, indent=2, default=str))


def cmd_vault_check(a):
    from config.retrieval import RetrievalConfig
    from app.services.obsidian import ObsidianVault
    rc = RetrievalConfig()
    v = ObsidianVault(rc.vault_path, (".obsidian", ".trash", ".git"))
    state = v.state_hash()
    digest = ObsidianVault.digest(state)
    print(f"vault={v.root} markdown={len(state)} digest={digest}")
    if a.save:
        from pathlib import Path
        target = Path(a.save).resolve()
        if target == v.root or v.root in target.parents:
            sys.exit("recusado: não é permitido gravar dentro do vault (READ ONLY)")
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=0)
        print(f"estado salvo em {a.save}")
    if a.compare:
        with open(a.compare, encoding="utf-8") as fh:
            before = json.load(fh)
        changed = [k for k in state if k in before and before[k] != state[k]]
        added = [k for k in state if k not in before]
        removed = [k for k in before if k not in state]
        ok = not (changed or added or removed)
        print(json.dumps({"unchanged": ok, "modified": changed, "added": added, "removed": removed},
                         ensure_ascii=False, indent=2))
        sys.exit(0 if ok else 1)


def cmd_vault_lint(a):
    from config.retrieval import fell_back_to_default, resolve_vault_path, validate_vault_path
    from app.services.vault_lint import MAX_NOTE_CHARS, lint
    if fell_back_to_default(a.vault):
        print("vault-lint: usando o vault sintético (passe --vault)", file=sys.stderr)
    try:
        vault = validate_vault_path(resolve_vault_path(a.vault))
    except (FileNotFoundError, NotADirectoryError) as exc:
        sys.exit(str(exc))
    report = lint(vault, max_note_chars=a.max_note_chars or MAX_NOTE_CHARS)
    if not _print(report.to_dict(), a.json):
        print(report.render(verbose=a.verbose))
    sys.exit(0 if report.total == 0 else 1)



def cmd_memory_audit(a):
    """Read-only inventory of the persistent memory (`app/services/memory_audit.py`).

    Prints COUNTS by default. `--verbose` adds the candidate file lists (paths only — never note
    content) and `--json` returns the whole report, still without any note body.
    """
    from pathlib import Path
    from app.services.memory_audit import MemoryAuditor
    from config.retrieval import (RetrievalConfig, fell_back_to_default, resolve_vault_path,
                                  validate_vault_path)
    if fell_back_to_default(a.vault):
        print("memory-audit: usando o vault sintético (passe --vault)", file=sys.stderr)
    try:
        vault = validate_vault_path(resolve_vault_path(a.vault))
    except (FileNotFoundError, NotADirectoryError) as exc:
        sys.exit(str(exc))
    db = getattr(a, "db", None)
    # Audit exactly the notes a search can reach (same excluded_dirs as RetrievalConfig).
    auditor = MemoryAuditor(Path(vault), db_path=Path(db) if db else None,
                            excluded_dirs=RetrievalConfig().excluded_dirs)
    report = auditor.audit(inactive_days=a.inactive_days, near_dup_threshold=a.near_dup_threshold,
                           hot_min=a.hot_min, max_runs=a.max_runs)
    if _print(report.to_dict(), a.json):
        return
    s = report.summary
    u = report.usage
    print(f"vault={report.vault} notas={s.notes_scanned} bytes={s.bytes_total} "
          f"tokens_estimados={s.tokens_total} linha_de_proveniencia_media={s.provenance_tokens_mean}")
    print(f"  por_status={s.by_status}")
    print(f"  duplicatas exatas={s.dup_exact} grupos_quase_duplicados={s.dup_near_groups} "
          f"orfas={s.orphan_count} wikilinks_quebrados={s.wikilinks_broken_count}/{s.wikilinks_total}")
    print(f"  sem_frontmatter={s.notes_without_fm} com_campo_faltando={s.notes_missing_fields} "
          f"inativas_ha_{s.inactive_days}d={s.inactive_gt_n} arquivadas={s.archived_count} "
          f"substituidas={s.superseded_count}")
    print(f"  conflitos_candidatos={s.conflicts} (mesmo_title={s.conflicts_same_title}, "
          f"citando_substituicao={s.conflicts_superseded})")
    print(f"  secoes_repetidas={s.repeated_sections} em {s.notes_with_repeated_sections} notas "
          f"({s.repeated_section_token_share:.4f} dos tokens)")
    if u.db_path or u.db_error:
        print(f"  hot={u.hot} warm={u.warm} cold={u.cold} "
              f"(runs lidos={u.runs_scanned}, entregas={u.deliveries})"
              + (f" ERRO={u.db_error}" if u.db_error else ""))
    print(f"  varredura={report.scan_ms}ms cache={report.cached}")
    if a.verbose:
        for label, items in (("duplicatas exatas", report.dup_exact),
                             ("quase-duplicadas", report.dup_near),
                             ("conflitos", report.conflicts),
                             ("orfas", [report.orphans]),
                             ("sem frontmatter", report.notes_without_frontmatter),
                             ("inativas", report.inactive),
                             ("arquivadas", report.archived),
                             ("substituidas", report.superseded)):
            if items:
                print(f"  [{label}] {len(items)}")
                for it in items[:40]:
                    print("   -", " / ".join(it) if isinstance(it, list) else it)
        if report.usage.hot_top:
            print("  [hot]", ", ".join(f"{p}={c}" for p, c in report.usage.hot_top[:15]))
            print("  [warm]", ", ".join(f"{p}={c}" for p, c in report.usage.warm_top[:15]))



def cmd_index(a):
    print(json.dumps(_gw().warm(), ensure_ascii=False, indent=2, default=str))


def cmd_db_prune(a):
    """§5.3: delete old runs (and their candidates) to keep benchmark.db small.

    --keep-days is required (no silent default retention window). Sessions listed in
    --keep-sessions are never deleted, regardless of age.
    """
    from app.database.db import Database
    from config.benchmark import BenchmarkConfig

    bc = BenchmarkConfig()
    db = Database(bc.db_path, compress_context=bc.db_compress_context)
    keep_sessions = [s.strip() for s in a.keep_sessions.split(",") if s.strip()] if a.keep_sessions else []
    result = db.prune(a.keep_days, keep_sessions, dry_run=a.dry_run)
    if a.vacuum and not a.dry_run:
        db.vacuum()
        result["vacuumed"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _fmt_bytes(n: int) -> str:
    return f"{n / 1048576:.2f} MB"


def cmd_db_maintenance(a):
    """T0.4: opt-in retention. Default = dry run (reports only); --apply is required to change data."""
    from app.database.db import Database
    from config.benchmark import BenchmarkConfig

    bc = BenchmarkConfig()
    db = Database(a.db or bc.db_path, compress_context=bc.db_compress_context)
    r = db.maintenance(a.older_than_days, apply=a.apply, vacuum=a.vacuum)
    f = r["found"]
    print(f"db-maintenance [{'APPLY' if a.apply else 'DRY-RUN'}] older_than_days={a.older_than_days} db={db.path}")
    print(f"{'item':<36}{'rows':>8}{'size':>14}")
    print(f"{'runs: context/answer/sources_json':<36}{f['runs_heavy_rows']:>8}{_fmt_bytes(f['runs_heavy_bytes']):>14}")
    print(f"{'jev_cache (old)':<36}{f['jev_cache_rows']:>8}{_fmt_bytes(f['jev_cache_bytes']):>14}")
    print(f"{'candidates (orphan)':<36}{f['orphan_candidates']:>8}{'-':>14}")
    print(f"{'file before':<36}{'':>8}{_fmt_bytes(r['size_before']):>14}")
    print(f"{'file after':<36}{'':>8}{_fmt_bytes(r['size_after']):>14}")
    if not a.apply:
        print("dry-run: nada foi alterado. Use --apply para executar (--vacuum só vale com --apply).")
    elif not a.vacuum:
        print("espaço só é devolvido ao disco com --vacuum.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="memory_gateway", description="Memory Gateway CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--pipeline", default="auto", choices=["auto", *PIPELINES])
    s.add_argument("--max-results", type=int, default=10)
    s.add_argument("--jev-mode", choices=["performance", "strict"])
    s.add_argument("--threshold", type=float)
    s.add_argument("--show-context", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_search)
    b = sub.add_parser("benchmark")
    b.add_argument("--pipeline", action="append", choices=list(PIPELINES))
    b.add_argument("--questions", nargs="*")
    b.add_argument("--agent", choices=["hermes", "claude_code", "codex", "opencode", "generic"])
    b.add_argument("--provider")
    b.add_argument("--model")
    b.add_argument("--repetitions", type=int, default=1, choices=[1, 3, 5, 10])
    b.add_argument("--jev-mode", choices=["performance", "strict"])
    b.add_argument("--no-warmup", action="store_true")
    b.add_argument("--dry-run", action="store_true")
    b.add_argument("--json", action="store_true")
    b.set_defaults(fn=cmd_benchmark)
    w = sub.add_parser("sweep")
    w.add_argument("--questions", nargs="*")
    w.add_argument("--extended", action="store_true", help="inclui 0.10–0.40 além dos valores da spec")
    w.add_argument("--json", action="store_true")
    w.set_defaults(fn=cmd_sweep)
    st = sub.add_parser("stats")
    st.add_argument("--session")
    st.add_argument("--json", action="store_true")
    st.set_defaults(fn=cmd_stats)
    sub.add_parser("info").set_defaults(fn=cmd_info)
    v = sub.add_parser("vault-check")
    v.add_argument("--save")
    v.add_argument("--compare")
    v.set_defaults(fn=cmd_vault_check)
    sub.add_parser("index").set_defaults(fn=cmd_index)
    dm = sub.add_parser("db-maintenance", help="retenção opt-in de benchmark.db (dry-run por padrão; --apply altera)")
    dm.add_argument("--older-than-days", type=int, default=90, help="idade (dias) a partir da qual limpar (padrão 90)")
    dm.add_argument("--db", help="caminho do banco (padrão: config)")
    dm.add_argument("--apply", action="store_true", help="executa de fato (sem isso só relata)")
    dm.add_argument("--vacuum", action="store_true", help="VACUUM após aplicar (exige --apply)")
    dm.set_defaults(fn=cmd_db_maintenance)
    dp = sub.add_parser("db-prune", help="remove runs antigas de benchmark.db (nunca as sessões protegidas)")
    dp.add_argument("--keep-days", type=int, required=True, help="idade máxima (dias) das runs mantidas")
    dp.add_argument("--keep-sessions", help="session_ids (separados por vírgula) que nunca são apagados")
    dp.add_argument("--dry-run", action="store_true", help="só conta quantas runs seriam apagadas")
    dp.add_argument("--vacuum", action="store_true", help="roda VACUUM após apagar (ignora com --dry-run)")
    dp.set_defaults(fn=cmd_db_prune)
    ma = sub.add_parser("memory-audit",
                        help="inventário somente leitura da memória persistente (contagens, sem conteúdo)")
    ma.add_argument("--vault", help="caminho do vault")
    ma.add_argument("--near-dup-threshold", type=float, default=0.92)
    ma.add_argument("--inactive-days", type=int, default=90,
                    help="notas 'ativo' sem update há mais dias que isto entram em 'inativas'")
    ma.add_argument("--hot-min", type=int, default=5,
                    help="entregas mínimas em benchmark.db para a nota ser HOT (>=) ; 1..N-1 = warm, 0 = cold")
    ma.add_argument("--db", help="benchmark.db lido em mode=ro para contar hot/warm/cold")
    ma.add_argument("--max-runs", type=int, default=0,
                    help="limita quantas runs (0 = todas) são lidas para o hot/warm/cold")
    ma.add_argument("--json", action="store_true")
    ma.add_argument("-v", "--verbose", action="store_true", help="lista os arquivos candidatos")
    ma.set_defaults(fn=cmd_memory_audit)

    vl = sub.add_parser("vault-lint", help="lint determinístico READ-ONLY do vault (saída 1 se houver itens)")
    vl.add_argument("--vault", help="caminho do vault (default: vault configurado no projeto)")
    vl.add_argument("--max-note-chars", type=int, help=f"limite de tamanho de nota (default {MAX_NOTE_CHARS_LITERAL})")
    vl.add_argument("--json", action="store_true")
    vl.add_argument("-v", "--verbose", action="store_true",
                    help="lista todos os itens em vez do resumo por categoria")
    vl.set_defaults(fn=cmd_vault_lint)
    return p


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    a = build_parser().parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
