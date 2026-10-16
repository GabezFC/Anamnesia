"""CLI (§7). Usable without any agent connected.

  python -m memory_gateway search "pergunta" [--pipeline auto] [--json]
  python -m memory_gateway benchmark [--pipeline P ...] [--agent hermes --provider P --model M] [--repetitions N]
  python -m memory_gateway sweep
  python -m memory_gateway stats
  python -m memory_gateway info
  python -m memory_gateway vault-check [--save FILE | --compare FILE]
  python -m memory_gateway vault-lint [--vault PATH] [--json]
  python -m memory_gateway memory-audit [--vault PATH] [--db benchmark.db] [--json] [-v]
  python -m memory_gateway decision status|test|history [--json]   (Decision Engine, ANAM-043)
  python -m memory_gateway index
  python -m memory_gateway db-maintenance [--older-than-days N] [--db PATH] [--apply] [--vacuum]
  python -m memory_gateway db-prune --keep-days N [--keep-sessions s1,s2] [--dry-run] [--vacuum]
  python -m memory_gateway backup-create --out FILE [--db PATH] [--memory-dir DIR] [--force]
  python -m memory_gateway backup-restore FILE [--db PATH] [--memory-dir DIR] [--force] [--verify-only]
"""
from __future__ import annotations

import argparse
import json
import sys

from app.schemas.models import DEFAULT_PIPELINES, PIPELINES
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
    from app.core.request_context import request_scope      # ANAM-012: CLI invocation = one trace
    with request_scope():
        r = g.search(a.query, a.pipeline, a.max_results, jev_overrides=ov or None, run_meta={"kind": "cli", "agent": "cli"})
        mode = getattr(a, "mode", "context")
        extras = {}
        if mode != "context":
            from app.routing.answer import apply_mode
            extras = apply_mode(g, r, mode, risk=getattr(a, "risk", "medium"))
    from app.routing.answer import merge_mode
    if _print(merge_mode(r.to_dict(), extras) if extras else r.to_dict(), a.json):
        return
    m = r.metrics
    print(f"pipeline={r.pipeline} run_id={r.run_id}")
    if extras:
        print(f"mode_used={extras.get('mode_used')} fallback_reason={extras.get('fallback_reason')}")
        if extras.get("mode_used") == "answer":
            print(extras["answer"])
            for s in extras.get("answer_sources", []):
                print(f"  [{s['n']}] {s['file']} :: {s['section'][:70]}")
            return
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
    pipelines = a.pipeline or list(DEFAULT_PIPELINES)
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
    if a.fail_on_regression:  # ANA-202: CI gate -- exit 1 when recent runs regressed against the previous ones
        from app.services import dashboard_insights, settings_store
        rep = dashboard_insights.regression_alerts(
            g.db.list_runs(limit=400), thresholds=settings_store.load_settings(g.db).regression_thresholds)
        for al in rep["alerts"]:
            print(f"REGRESSÃO {al['pipeline']} {al['metric']}: {al['baseline']} -> {al['current']} "
                  f"(+{al['change_pct']}% > {al['threshold_pct']}%)", file=sys.stderr)
        if rep["alerts"]:
            sys.exit(1)


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


def cmd_decision(a):
    """ANAM-043: Decision Engine. `status` e `history` não chamam provider; `test` usa itens SINTÉTICOS embutidos
    (nunca o vault) e, com JEV remoto configurado, só gasta se --provider/--strategy o acionarem."""
    from app.decision import DecisionRequest, Item, get_engine
    eng = get_engine()
    if a.action == "status":
        out = eng.status()
    elif a.action == "history":
        from app.decision.telemetry import DecisionHistory, default_history_path
        out = {"records": DecisionHistory.read_persisted(default_history_path(), a.limit, a.project),
               "privacy": "IDs/hashes apenas"}
    else:
        items = [Item("demo-1", "Durnathil 5.73.1 replaced the old parser in the retrieval layer.", "demo"),
                 Item("demo-2", "Weekly grocery list: apples, rice and coffee.", "demo")]
        res = eng.decide(DecisionRequest("What replaced the old parser: Durnathil?", items, a.op, a.project or ""),
                         provider=a.provider, strategy=a.strategy)
        out = res.to_public()
    if a.json or a.action != "status":
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return
    print(f"Decision Engine ({out['stage']}): provider ativo = {out['active_provider']}"
          f"{' [JEV-only, padrão]' if out['default_is_jev_only'] else ''}; pipeline padrão = {out['default_pipeline']}")
    for n, h in out["providers"].items():
        print(f"  {n:<6} disponível={h.get('available')} ({h.get('label')}) {h.get('reason', '')}")
    print(f"  cache: {out['cache']}")
    print(f"  fallback: {out['fallback_policy']}")
    print(f"  JEV real: {out['measurements']['jev_real']['label']}; Laya vs lexical: {out['measurements']['laya_vs_lexical']['value']}")


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
    """§5.3 + ANAM-006: delete old runs (cascade, no orphans) after a mandatory backup.

    --keep-days is required (no silent default retention window). Sessions listed in
    --keep-sessions are never deleted, regardless of age. Without --dry-run, asks for confirmation
    unless --yes. A ``<db>.bak-v<N>`` copy is written next to the DB before deleting (restore =
    copy it back over the DB). --purge-text [DAYS] also blanks query/context/answer of old runs
    (default DAYS from ANAMNESIA_RUNS_TEXT_RETENTION_DAYS, 30 - decisão D-4 pendente, revisável).
    """
    from app.database.db import Database
    from config.benchmark import BenchmarkConfig

    bc = BenchmarkConfig()
    db = Database(getattr(a, "db", None) or bc.db_path, compress_context=bc.db_compress_context)
    try:
        _db_prune_run(a, db)
    finally:
        db.close()


def _db_prune_run(a, db):
    keep_sessions = [s.strip() for s in a.keep_sessions.split(",") if s.strip()] if a.keep_sessions else []
    purge = getattr(a, "purge_text", None)
    if purge is not None and purge < 0:           # flag given without a value -> env/default
        purge = db.runs_text_retention_days()
    result = db.prune(a.keep_days, keep_sessions, dry_run=True)
    result["dry_run"] = a.dry_run
    if purge:
        result["would_purge_text"] = db.purge_run_text(purge, keep_sessions, dry_run=True)["would_purge"]
    if a.dry_run:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if not getattr(a, "yes", False):
        try:
            ans = input(f"Apagar {result['would_delete']} run(s) de {db.path}? Um backup será criado antes. [s/N] ")
        except EOFError:
            ans = ""
        if ans.strip().lower() not in {"s", "sim", "y", "yes"}:
            print(json.dumps({"aborted": True, "reason": "sem confirmação (use --yes)", **result},
                             ensure_ascii=False, indent=2))
            return
    backup = db.backup_before_prune()
    result = db.prune(a.keep_days, keep_sessions, dry_run=False)
    result["backup"] = backup
    if purge:
        result["text_purged"] = db.purge_run_text(purge, keep_sessions)["purged"]
    if a.vacuum:
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


def cmd_backup_create(a):
    """ANAM-026: zip com manifest sha256 de benchmark.db (+ memory store). Não altera a origem."""
    from pathlib import Path

    from app.services.backup import BackupError, create_backup
    from config.paths import benchmark_db_path, saved_context_dir

    db = None if a.no_db else (a.db or benchmark_db_path())
    mem = None if a.no_memory else (a.memory_dir or saved_context_dir())
    if mem is not None and not Path(mem).is_dir():
        mem = None                                   # memory store ainda não criado: só o banco
    try:
        print(json.dumps(create_backup(a.out, db, mem, force=a.force), ensure_ascii=False, indent=2))
    except BackupError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_backup_restore(a):
    """ANAM-026: valida sha256 e restaura; nunca sobrescreve sem --force."""
    from app.services.backup import BackupError, restore_backup, verify_backup
    from config.paths import benchmark_db_path, saved_context_dir

    try:
        if a.verify_only:
            m = verify_backup(a.archive)
            print(json.dumps({"ok": True, "files": len(m["files"])}, indent=2))
            return
        print(json.dumps(restore_backup(a.archive, a.db or benchmark_db_path(),
                                        a.memory_dir or saved_context_dir(), force=a.force),
                         ensure_ascii=False, indent=2))
    except BackupError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        sys.exit(1)


def _add_backup_parsers(sub) -> None:
    bc = sub.add_parser("backup-create", help="backup (zip + sha256) de benchmark.db e do memory store")
    bc.add_argument("--out", required=True, help="arquivo .zip de saída")
    bc.add_argument("--db", help="caminho do banco (padrão: config)")
    bc.add_argument("--memory-dir", help="pasta do memory store (padrão: saved_context)")
    bc.add_argument("--no-db", action="store_true")
    bc.add_argument("--no-memory", action="store_true")
    bc.add_argument("--force", action="store_true", help="sobrescreve o .zip se existir")
    bc.set_defaults(fn=cmd_backup_create)
    br = sub.add_parser("backup-restore", help="restaura um backup verificando sha256 (sem --force não sobrescreve)")
    br.add_argument("archive")
    br.add_argument("--db", help="destino do banco (padrão: config)")
    br.add_argument("--memory-dir", help="destino do memory store (padrão: saved_context)")
    br.add_argument("--force", action="store_true", help="permite sobrescrever destinos existentes")
    br.add_argument("--verify-only", action="store_true", help="só valida a integridade")
    br.set_defaults(fn=cmd_backup_restore)


def _add_db_prune_parser(sub) -> None:
    dp = sub.add_parser("db-prune", help="remove runs antigas de benchmark.db (nunca as sessões protegidas)")
    dp.add_argument("--keep-days", type=int, required=True, help="idade máxima (dias) das runs mantidas")
    dp.add_argument("--keep-sessions", help="session_ids (separados por vírgula) que nunca são apagados")
    dp.add_argument("--dry-run", action="store_true", help="só conta quantas runs seriam apagadas")
    dp.add_argument("--vacuum", action="store_true", help="roda VACUUM após apagar (ignora com --dry-run)")
    dp.add_argument("--yes", action="store_true", help="não pergunta confirmação (ANAM-006)")
    dp.add_argument("--purge-text", nargs="?", type=float, const=-1, default=None, metavar="DAYS",
                    help="também apaga query/context/answer de runs mais velhas que DAYS "
                         "(padrão: env ANAMNESIA_RUNS_TEXT_RETENTION_DAYS, 30; decisão D-4 revisável)")
    dp.add_argument("--db", help="caminho do banco (padrão: config)")
    dp.set_defaults(fn=cmd_db_prune)


def _add_decision_parser(sub) -> None:
    """Subcomando `decision` (ANAM-043)."""
    dc = sub.add_parser("decision", help="Decision Engine (ANAM-043): status | test (itens sintéticos) | history (IDs/hashes)")
    dc.add_argument("action", choices=["status", "test", "history"])
    dc.add_argument("--provider", choices=["jev", "laya", "hybrid", "adaptive"], help="test: força o provider")
    dc.add_argument("--strategy", choices=["laya_then_jev", "jev_then_laya", "ensemble"], help="test: estratégia do hybrid")
    dc.add_argument("--op", choices=["retrieval", "memory", "security"], default="retrieval")
    dc.add_argument("--project", help="isolamento por projeto (limiares/cache/histórico)")
    dc.add_argument("--limit", type=int, default=20)
    dc.add_argument("--json", action="store_true")
    dc.set_defaults(fn=cmd_decision)


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
    s.add_argument("--mode", choices=["context", "answer", "delegate"], default="context")
    s.add_argument("--risk", choices=["low", "medium", "high"], default="medium")
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
    b.add_argument("--fail-on-regression", action="store_true",
                   help="exit 1 se as runs recentes regrediram (tokens/latência p95/custo) contra as anteriores (ANA-202)")
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
    _add_decision_parser(sub)
    sub.add_parser("index").set_defaults(fn=cmd_index)
    dm = sub.add_parser("db-maintenance", help="retenção opt-in de benchmark.db (dry-run por padrão; --apply altera)")
    dm.add_argument("--older-than-days", type=int, default=90, help="idade (dias) a partir da qual limpar (padrão 90)")
    dm.add_argument("--db", help="caminho do banco (padrão: config)")
    dm.add_argument("--apply", action="store_true", help="executa de fato (sem isso só relata)")
    dm.add_argument("--vacuum", action="store_true", help="VACUUM após aplicar (exige --apply)")
    dm.set_defaults(fn=cmd_db_maintenance)
    _add_db_prune_parser(sub)
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
    _add_backup_parsers(sub)
    return p


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    a = build_parser().parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
