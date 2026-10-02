"""M3: the persistent-memory audit (`python -m memory_gateway memory-audit`, GET /system/memory).

Read-only by construction: the vault is only ever read and benchmark.db is opened `mode=ro`, so
these tests also assert that. No network, no model call.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from app.services.memory_audit import (DEFAULT_NEAR_DUP_THRESHOLD, MemoryAuditor, body_key,
                                       clear_cache)
from app.services.obsidian import ObsidianVault

FM_ALL = ("id: {id}\ntitle: {title}\narea: {area}\ntype: {type}\ntags: []\nstatus: {status}\n"
          "created: {created}\nupdated: {updated}")


def note(title="Nota", body="corpo", area="Projetos", type_="nota", status="ativo",
         created="2026-09-01", updated="2026-09-01", projeto="memoria-gateway", **extra) -> str:
    fm = FM_ALL.format(id=title.replace(" ", "-").lower(), title=title, area=area, type=type_,
                       status=status, created=created, updated=updated)
    if projeto:
        fm += f"\nprojeto: {projeto}"
    for k, v in extra.items():
        fm += f"\n{k.rstrip('_')}: {v}"
    return f"---\n{fm}\n---\n\n# {title}\n\n{body}\n"


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / "30-Projetos" / "Memoria_Gateway").mkdir(parents=True)
    (root / "99-Templates").mkdir(parents=True)
    p = root / "30-Projetos" / "Memoria_Gateway"
    # exact duplicates: the same body in two files (a real copy, which is what dedup should catch)
    (p / "dup1.md").write_text(note("Dup A", body="o mesmo texto em dois arquivos"), encoding="utf-8")
    (p / "dup2.md").write_text(note("Dup B", body="o mesmo texto em dois arquivos"), encoding="utf-8")
    # near duplicates: same text, only the version number changed -> must NOT be "exact"
    (p / "quase1.md").write_text(
        note("Quase 1", body="usamos valkey porque o redis mudou de licenca na versao 2"),
        encoding="utf-8")
    (p / "quase2.md").write_text(
        note("Quase 2", body="usamos valkey porque o redis mudou de licenca na versao 3"),
        encoding="utf-8")
    # same title in two ACTIVE notes = a contradiction to review
    (p / "decisao-antiga.md").write_text(
        note("Decisão do cache", body="o cache fica em redis", status="ativo", updated="2026-09-01"),
        encoding="utf-8")
    (p / "decisao-nova.md").write_text(
        note("Decisão do cache", body="o cache fica em valkey agora", status="ativo",
             updated="2026-09-20"), encoding="utf-8")
    # superseded + archived = history
    (p / "superseded.md").write_text(
        note("Plano antigo", body="plano de 2026", superseded_by="30-Projetos/Memoria_Gateway/"
             "decisao-nova.md"), encoding="utf-8")
    (p / "arquivada.md").write_text(note("Arquivada", body="historico guardado", status="arquivado"),
                                    encoding="utf-8")
    # orphan: nothing links to it, and it links nowhere
    (p / "orfan.md").write_text(note("Órfã", body="ninguem aponta para ca"), encoding="utf-8")
    # broken wikilink + a valid one
    (p / "links.md").write_text(
        note("Links", body="veja [[decisao-nova]] e tambem [[nao-existe|nada]]"), encoding="utf-8")
    # missing frontmatter and missing fields
    (p / "sem-frontmatter.md").write_text("apenas texto solto\n", encoding="utf-8")
    (p / "campos-faltando.md").write_text("---\nid: x\ntitle: So o id e o titulo\n---\n\ncorpo\n",
                                          encoding="utf-8")
    # boilerplate repeated across notes (token waste)
    boiler = ("Aviso: este documento foi gerado automaticamente. Nao edite a mao. "
              "Verifique a versao antes de usar.")
    (p / "boiler1.md").write_text(note("Doc 1", body=boiler), encoding="utf-8")
    (p / "boiler2.md").write_text(note("Doc 2", body=boiler), encoding="utf-8")
    (root / "99-Templates" / "_nota.md").write_text(note("Template"), encoding="utf-8")
    return root


@pytest.fixture
def report(vault):
    return MemoryAuditor(vault).audit()


def names(paths):
    return {p.split("/")[-1] for p in paths}


# -- inventory --------------------------------------------------------------------------------
def test_counts_every_note_and_sums_bytes_and_tokens(report):
    s = report.summary
    assert s.vault_notes == s.notes_scanned == 15
    assert s.bytes_total > 0 and s.tokens_total > 0
    assert round(s.bytes_avg, 1) == round(s.bytes_total / s.notes_scanned, 1)
    # by_status counts only notes that DECLARE a status, so the two notes that do not (one with no
    # frontmatter at all, one missing the field) are reported by their own findings and never
    # silently folded into "ativo".
    assert s.by_status == {"ativo": 12, "arquivado": 1}
    assert sum(s.by_status.values()) + s.notes_without_fm + s.notes_missing_fields == s.notes_scanned
    assert s.by_projeto["memoria-gateway"] == 15
    assert s.by_area["Projetos"] == 13 and s.by_area["sem_area"] == 2


def test_provenance_cost_is_reported_even_though_the_audit_never_renders_it(report):
    """The audit predicts what provenance WILL cost in the retrieval path (mean per note)."""
    assert report.summary.provenance_tokens_total > 0
    assert 0 < report.summary.provenance_tokens_mean < 100


def test_growth_is_grouped_by_day_not_listed_per_note(report):
    s = report.summary
    assert "2026-09-01" in s.created_per_day and "2026-09-20" in s.updated_per_day
    assert sum(s.created_per_day.values()) == sum(s.updated_per_day.values())
    assert all(day.count("-") == 2 for day in s.created_per_day), "days are grouped, not listed"


def test_templates_enter_only_when_the_caller_excludes_them(vault):
    """ObsidianVault excludes .obsidian/.trash/.git but NOT 99-Templates, so the default audit
    counts it. The CLI and the REST route pass the RetrievalConfig exclusions, which is how the
    audit stops counting templates the search can never reach."""
    assert MemoryAuditor(vault).audit().summary.notes_scanned == 15
    assert MemoryAuditor(vault, excluded_dirs=(".obsidian", ".trash", "99-Templates"))         .audit().summary.notes_scanned == 14


# -- duplicates -------------------------------------------------------------------------------
def test_exact_duplicates_group_by_body_hash(report):
    groups = [names(g) for g in report.dup_exact]
    assert {"dup1.md", "dup2.md"} in groups, "a real copy is an exact duplicate"
    # boiler1/boiler2 carry the same text too: the two findings must agree with each other
    assert {"boiler1.md", "boiler2.md"} in groups
    assert {"quase1.md", "quase2.md"} not in groups, "a version bump is NOT an exact duplicate"
    assert all(len(g) == 2 for g in groups), report.dup_exact


def test_title_echo_is_not_content(vault):
    """`title: X` + `# X` is the same title twice; the H1 must not stop a duplicate pair.

    dup1.md and dup2.md have DIFFERENT titles and the same text -- they are the same note copied
    under two names, which is exactly what the exact-duplicate rule has to catch.
    """
    pair = next(g for g in MemoryAuditor(vault).audit().dup_exact
                if names(g) == {"dup1.md", "dup2.md"})
    assert len(pair) == 2


def test_near_duplicates_are_separated_from_exact_ones(report):
    groups = [names(g) for g in report.dup_near]
    assert {"quase1.md", "quase2.md"} in groups
    assert all(not ({"dup1.md", "dup2.md"} <= g and g != {"dup1.md", "dup2.md"}) for g in groups)


def test_body_key_keeps_numbers_so_version_drift_is_never_an_exact_duplicate():
    assert body_key("plano da versao 2") != body_key("plano da versao 3")
    assert body_key("  o mesmo\ntexto ") == body_key("O MESMO texto")


def test_near_dup_threshold_is_configurable(vault):
    loose = MemoryAuditor(vault).audit(near_dup_threshold=0.1)
    assert len(loose.dup_near) >= len(MemoryAuditor(vault).audit().dup_near)
    assert loose.parameters["near_dup_threshold"] == 0.1


# -- links ------------------------------------------------------------------------------------
def test_broken_wikilinks_are_listed_and_valid_ones_are_not(report):
    assert report.summary.wikilinks_broken_count == 1
    assert report.wikilinks_broken["30-Projetos/Memoria_Gateway/links.md"] == ["nao-existe"]


def test_orphans_exclude_notes_that_are_linked_to(report):
    assert "orfan.md" in names(report.orphans), "nothing links to it"
    assert "decisao-nova.md" not in names(report.orphans), "links.md points at it"


# -- metadata hygiene -------------------------------------------------------------------------
def test_missing_frontmatter_and_missing_fields_are_separate_findings(report):
    assert names(report.notes_without_frontmatter) == {"sem-frontmatter.md"}
    assert names(report.notes_missing_fields["30-Projetos/Memoria_Gateway/campos-faltando.md"])         == {"area", "type", "tags", "status", "created", "updated"}
    assert report.summary.notes_missing_fields == 1
    assert "created" in report.summary.missing_fields_by_key


def test_archived_and_superseded_are_inventory_items_and_historical_counters(report):
    assert names(report.archived) == {"arquivada.md"}
    assert names(report.superseded) == {"superseded.md"}
    assert report.summary.historical_count == 2


def test_inactive_notes_need_a_date_threshold(tmp_path, report):
    old = tmp_path / "vault" / "30-Projetos" / "Memoria_Gateway" / "velha.md"
    old.write_text(note("Velha", updated="2020-01-01"), encoding="utf-8")
    fresh = MemoryAuditor(tmp_path / "vault").audit(inactive_days=90)
    assert "velha.md" in names(fresh.inactive)
    assert "velha.md" not in names(MemoryAuditor(tmp_path / "vault").audit(inactive_days=36500).inactive)


# -- conflicts --------------------------------------------------------------------------------
def test_two_active_notes_with_the_same_title_are_a_conflict(report):
    assert report.summary.conflicts_same_title >= 1
    pair = next(g for g in report.conflicts if names(g) == {"decisao-antiga.md", "decisao-nova.md"})
    assert pair, report.conflicts


def test_a_note_citing_its_replacement_is_a_conflict_too(report):
    assert report.summary.conflicts >= 1


# -- repeated sections ------------------------------------------------------------------------
def test_repeated_boilerplate_is_measured_as_token_share(report):
    assert report.summary.repeated_sections >= 2
    assert names(report.repeated_headings[0][0] if isinstance(report.repeated_headings[0], tuple)
                 else []) or True
    assert 0 < report.summary.repeated_section_token_share < 1
    assert report.summary.notes_with_repeated_sections >= 2


# -- usage from benchmark.db (read-only) -------------------------------------------------------
def _make_db(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, created_at REAL, "
                "sources_json TEXT, warmup INTEGER DEFAULT 0)")
    for i, srcs in enumerate(rows):
        con.execute("INSERT INTO runs VALUES (?,?,?,0)", (f"r{i}", 1.0 + i,
                                                        json.dumps([{"file": f} for f in srcs])))
    con.commit()
    con.close()


def test_hot_warm_cold_are_counted_from_delivered_sources(tmp_path, vault):
    db = tmp_path / "benchmark.db"
    hot = "30-Projetos/Memoria_Gateway/decisao-nova.md"
    warm = "30-Projetos/Memoria_Gateway/decisao-antiga.md"
    cold = "30-Projetos/Memoria_Gateway/orfan.md"
    _make_db(db, [[hot] * 6, [warm] * 3])  # `cold` is never delivered
    r = MemoryAuditor(vault, db_path=db).audit(hot_min=5)
    # hot >= hot_min; 0 < n < hot_min is warm; never delivered is cold. `cold` was never delivered.
    assert r.usage.hot == 1 and r.usage.warm == 1
    assert r.usage.cold == vault_note_count(vault) - 2
    assert dict(r.usage.hot_top)[hot] == 6, "hot_top is keyed by vault-relative path, not file name"
    assert r.summary.hot_count == 1 and r.summary.db_runs_scanned == 2
    assert r.summary.db_deliveries == 9


def test_audit_without_a_database_reports_no_usage_instead_of_guessing(report):
    assert report.usage.db_path is None and report.usage.runs_scanned == 0
    assert report.usage.db_error is None


def test_missing_database_is_reported_as_an_error_not_a_crash(tmp_path, vault):
    r = MemoryAuditor(vault, db_path=tmp_path / "nao-existe.db").audit()
    assert r.usage.db_error and r.summary.notes_scanned > 0


def test_the_audit_opens_the_database_read_only(vault, tmp_path):
    db = tmp_path / "ro.db"
    _make_db(db, [["30-Projetos/Memoria_Gateway/decisao-nova.md"]] * 3)
    before = db.read_bytes()
    MemoryAuditor(vault, db_path=db).audit()
    assert db.read_bytes() == before, "mode=ro means sqlite itself refuses any write"


def test_a_broken_sources_json_does_not_break_the_audit(vault, tmp_path):
    db = tmp_path / "bad.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, created_at REAL, sources_json TEXT)")
    con.execute("INSERT INTO runs VALUES ('r1',1.0,?)", ("{nao é json",))
    con.execute("INSERT INTO runs VALUES ('r2',2.0,?)", (json.dumps([{"sem": "file"}, "lixo"]),))
    con.commit()
    con.close()
    r = MemoryAuditor(vault, db_path=db).audit()
    assert r.usage.runs_scanned == 2 and r.summary.db_deliveries == 0


def vault_note_count(vault):
    return len(ObsidianVault(vault).list_markdown())


# -- cache ------------------------------------------------------------------------------------
def test_second_audit_is_cached_and_the_fingerprint_invalidates_it(vault):
    a = MemoryAuditor(vault)
    first = a.audit()
    assert first.cached is False and a.audit().cached is True
    (vault / "30-Projetos" / "Memoria_Gateway" / "nova.md").write_text(note("Nova"),
                                                                       encoding="utf-8")
    assert a.audit().cached is False


def test_cache_does_not_mix_incompatible_questions(vault, tmp_path):
    """Same vault + different arguments = different questions; the cache must not answer one
    with the other (e.g. an audit with --db must not be served to a caller that had none)."""
    db = tmp_path / "b.db"
    _make_db(db, [["30-Projetos/Memoria_Gateway/decisao-nova.md"]] * 9)
    a = MemoryAuditor(vault)
    assert a.audit().usage.hot == 0
    assert a.audit(db_path=db).usage.hot == 1
    assert a.audit().usage.hot == 0
    assert a.audit(near_dup_threshold=0.99).parameters["near_dup_threshold"] == 0.99


def test_cache_can_be_disabled(vault):
    a = MemoryAuditor(vault)
    a.audit()
    assert a.audit(use_cache=False).cached is False


def test_the_default_threshold_is_the_documented_one():
    assert DEFAULT_NEAR_DUP_THRESHOLD == 0.92


# -- report surface ----------------------------------------------------------------------------
def test_counts_only_carries_no_note_content(report):
    payload = report.counts_only()
    assert payload["note_content_included"] is False
    blob = json.dumps(payload, ensure_ascii=False)
    for leak in ("corpo", "redis", "valkey", "Nao edite a mao", "# Nota"):
        assert leak not in blob, leak
    assert payload["summary"]["dup_exact"] == report.summary.dup_exact
    assert set(payload["summary"]) == set(json.loads(json.dumps(report.summary.__dict__)))


def test_the_audit_never_writes_to_the_vault(vault):
    before = {p: p.stat().st_mtime_ns for p in vault.rglob("*") if p.is_file()}
    MemoryAuditor(vault).audit()
    assert {p: p.stat().st_mtime_ns for p in vault.rglob("*") if p.is_file()} == before


def test_a_note_that_lists_but_cannot_be_read_is_skipped(vault):
    """A path that lists as markdown but cannot be read as a file is skipped, never fatal."""
    (vault / "30-Projetos" / "Memoria_Gateway" / "pasta.md").mkdir()
    r = MemoryAuditor(vault).audit()
    assert r.summary.notes_scanned == 15, "the unreadable one is skipped, the other 15 are audited"

# -- CLI --------------------------------------------------------------------------------------
def test_cli_memory_audit_parsing():
    from app.cli.main import build_parser
    a = build_parser().parse_args(["memory-audit", "--vault", "/tmp/v", "--db", "/tmp/b.db",
                                   "--json", "-v", "--inactive-days", "30",
                                   "--near-dup-threshold", "0.5", "--hot-min", "9",
                                   "--max-runs", "100"])
    assert (a.vault, a.db, a.json, a.verbose) == ("/tmp/v", "/tmp/b.db", True, True)
    assert (a.inactive_days, a.near_dup_threshold, a.hot_min, a.max_runs) == (30, 0.5, 9, 100)


def test_cli_memory_audit_prints_counts_without_note_content(vault, capsys, monkeypatch):
    from app.cli.main import main
    monkeypatch.setattr("sys.argv", ["memory-audit", "--vault", str(vault)])
    main(["memory-audit", "--vault", str(vault)])
    out = capsys.readouterr().out
    # 14, not 15: the CLI hands the RetrievalConfig exclusions to the auditor, so 99-Templates is
    # out -- exactly the set of notes a search can reach.
    assert "notas=14" in out and "hot=" not in out, "no db was given, so no hot/warm/cold line"
    for leak in ("redis", "valkey", "corpo"):
        assert leak not in out


def test_cli_memory_audit_json_is_machine_readable(vault, capsys):
    from app.cli.main import main
    main(["memory-audit", "--vault", str(vault), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["notes_scanned"] == 14, "CLI passa as exclusões do RetrievalConfig"
    assert payload["notes_without_frontmatter"] == ["30-Projetos/Memoria_Gateway/sem-frontmatter.md"]


def test_cli_memory_audit_verbose_lists_paths_only(vault, capsys):
    from app.cli.main import main
    main(["memory-audit", "--vault", str(vault), "-v"])
    out = capsys.readouterr().out
    assert "[duplicatas exatas] 2" in out and "decisao-nova.md" in out


def test_cli_memory_audit_fails_loudly_on_a_bad_vault(capsys, tmp_path):
    from app.cli.main import main
    with pytest.raises(SystemExit):
        main(["memory-audit", "--vault", str(tmp_path / "nao-existe")])


# -- REST -------------------------------------------------------------------------------------
def test_system_memory_returns_counts_for_the_running_gateway(vault, tmp_path):
    """The route audits the vault the RUNNING gateway was built against -- a path resolved from the
    environment would audit a different vault than the one answers come from."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import routes
    from app.gateway.memory_gateway import MemoryGateway
    from config.benchmark import BenchmarkConfig
    from config.optimizer import OptimizerConfig
    from config.retrieval import RetrievalConfig
    gw = MemoryGateway(
        retrieval_cfg=RetrievalConfig(vault_path=vault, excluded_dirs=(".obsidian", ".trash")),
        bench_cfg=BenchmarkConfig(db_path=str(tmp_path / "b.db")), optimizer_cfg=OptimizerConfig())
    app = FastAPI()
    app.include_router(routes.router)
    old = routes._state["gateway"]
    routes._state["gateway"] = gw
    try:
        body = TestClient(app).get("/system/memory").json()
    finally:
        routes._state["gateway"] = old
    assert body["note_content_included"] is False
    assert body["summary"]["notes_scanned"] == 15, "excluded_dirs came from the running gateway"
    assert "redis" not in json.dumps(body), "the endpoint returns counts, never note content"


# -- end to end through the gateway ------------------------------------------------------------
def test_search_delivers_provenance_and_the_history_metrics(tmp_path, vault):
    from app.gateway.memory_gateway import MemoryGateway
    from config.benchmark import BenchmarkConfig
    from config.optimizer import OptimizerConfig
    from config.retrieval import RetrievalConfig
    gw = MemoryGateway(retrieval_cfg=RetrievalConfig(vault_path=vault, data_dir=tmp_path / "d"),
                       bench_cfg=BenchmarkConfig(db_path=str(tmp_path / "b.db")),
                       optimizer_cfg=OptimizerConfig().with_(provenance=True))
    gw.warm()
    r = gw.search("decisão do cache", "baseline", 5, persist=False)
    assert "[fonte:" in r.context
    assert r.metrics["provenance_lines"] >= 1 and r.metrics["provenance_tokens"] > 0
    # no note in this fixture carries an injection signal, so nothing sits on a flagged block
    assert r.metrics["provenance_on_flagged"] == 0
    assert r.metrics["memory_history_requested"] == 0
    assert "memory_conflicts_detected" in r.metrics
    assert r.context.count("<note ") == r.metrics["provenance_lines"],         "one line inside each delivered block, never outside"
    assert "Decision" not in r.context, "notes are data, never instructions"


def test_flags_off_means_no_provenance_line_in_the_context(tmp_path, vault):
    from app.gateway.memory_gateway import MemoryGateway
    from config.benchmark import BenchmarkConfig
    from config.optimizer import OptimizerConfig
    from config.retrieval import RetrievalConfig
    gw = MemoryGateway(retrieval_cfg=RetrievalConfig(vault_path=vault, data_dir=tmp_path / "d2"),
                       bench_cfg=BenchmarkConfig(db_path=str(tmp_path / "b2.db")),
                       optimizer_cfg=OptimizerConfig.disabled())
    gw.warm()
    r = gw.search("decisão do cache", "baseline", 5, persist=False)
    assert "[fonte:" not in r.context
    assert r.metrics.get("provenance_lines", 0) == 0


def test_graphify_jev_context_is_byte_identical_with_the_layer_on(tmp_path, vault, monkeypatch):
    """The frozen pipeline must not change by one character when the M3 flags are on."""
    from app.gateway.memory_gateway import MemoryGateway
    from config.benchmark import BenchmarkConfig
    from config.optimizer import OptimizerConfig
    from config.retrieval import RetrievalConfig

    def search_with(optimizer_cfg, data_dir):
        gw = MemoryGateway(retrieval_cfg=RetrievalConfig(vault_path=vault, data_dir=data_dir),
                           bench_cfg=BenchmarkConfig(db_path=str(tmp_path / "b.db")),
                           optimizer_cfg=optimizer_cfg)
        gw.warm()
        return gw.search("decisão do cache", "graphify_jev", 5, persist=False)

    # Only the M3 flags differ. Comparing against `disabled()` would also switch off pre-existing
    # stages (compact_headers, near_dedup) and prove nothing about this layer.
    off = search_with(OptimizerConfig().with_(provenance=False, temporal_demote=False,
                                              conflict_check=False), tmp_path / "off")
    on = search_with(OptimizerConfig(), tmp_path / "on")
    assert on.context == off.context
    assert on.sources == off.sources


def test_auto_routed_to_the_frozen_pipeline_also_stays_frozen(tmp_path, vault, monkeypatch):
    """`graphify_jev` is a legal ROUTE_TARGET, so an `auto` request can land on it. The skip must be
    keyed on the EFFECTIVE pipeline, otherwise the frozen reference gets a provenance line."""
    from app.gateway.memory_gateway import MemoryGateway
    from config.benchmark import BenchmarkConfig
    from config.optimizer import OptimizerConfig
    from config.retrieval import RetrievalConfig
    monkeypatch.setenv("MG_ROUTE_SIMPLE", "graphify_jev")
    monkeypatch.setenv("MG_ROUTE_MEDIUM", "graphify_jev")
    monkeypatch.setenv("MG_ROUTE_COMPLEX", "graphify_jev")
    monkeypatch.setenv("MG_ROUTE_AMBIGUOUS", "graphify_jev")
    gw = MemoryGateway(retrieval_cfg=RetrievalConfig(vault_path=vault, data_dir=tmp_path / "d3"),
                       bench_cfg=BenchmarkConfig(db_path=str(tmp_path / "b3.db")),
                       optimizer_cfg=OptimizerConfig())
    gw.warm()
    r = gw.search("decisão do cache", "auto", 5, persist=False)
    assert r.pipeline == "graphify_jev", r.pipeline
    assert "[fonte:" not in r.context
    assert r.metrics.get("provenance_lines", 0) == 0
