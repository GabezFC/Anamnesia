"""ANAM-043: Decision Engine (providers, estratégias, fallback, cache, telemetria, config, REST, CLI, MCP).

Sem rede, sem torch, sem vault: JEV e Laya são dublês determinísticos.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.decision import DecisionEngine, DecisionRequest, Item, load_config
from app.decision.analysis import divergence
from app.decision.cache import cache_key
from app.decision.config import Thresholds
from app.decision.telemetry import DecisionHistory
from app.decision.types import DROP, KEEP, QUARANTINE, REVIEW, UNJUDGED
from app.services.laya_decider import LayaAnswer, LayaMetrics

SECRET = "SEGREDO-PRIVADO-123 token abc"


class FakeJev:
    class cfg:  # noqa: N801
        model, mode, injection_threshold = "fake-jev", "performance", 0.8

    def __init__(self, rel: dict[str, float] | None = None, down: bool = False):
        self.rel, self.down, self.calls, self.requests = rel or {}, down, 0, 0

    def evaluate(self, query, cands):
        if self.down:
            raise RuntimeError("down")
        self.requests += 1
        self.calls += len(cands)
        for c in cands:
            c.relevance = self.rel.get(c.candidate_id, 0.9)
        return cands, type("M", (), {"request_count": 1, "errors": []})()


class FakeLaya:
    class _B:
        def status(self):
            return {"effective_mode": "fake", "reason": "fake", "errors": 0, "prompt_version": "t"}

        def resolve_mode(self):
            return "fake"

    cfg = None

    def __init__(self, table: dict[str, tuple[float, float]] | None = None, down: bool = False):
        self.backend, self.table, self.down, self.calls = self._B(), table or {}, down, 0

    def score(self, q, cands):
        if self.down:
            return [None] * len(cands), LayaMetrics(error="laya down")
        self.calls += len(cands)
        return [LayaAnswer(*self.table.get(c.candidate_id, (0.5, 0.5, 0.9))) for c in cands], LayaMetrics()

    def injection_gate(self, c):
        return False, ""


def engine(jev=None, laya=None, **cfg_kw) -> DecisionEngine:
    cfg = load_config({})
    cfg.history_persist = False
    for k, v in cfg_kw.items():
        setattr(cfg, k, v)
    return DecisionEngine(cfg, jev=jev, laya_service=laya, history=DecisionHistory(100, None, False))


def req(ids=("a", "b", "c"), op="retrieval", project="", text="texto neutro"):
    return DecisionRequest("pergunta", [Item(i, f"{text} {i}") for i in ids], op, project)


# LayaAnswer(p_yes, p_raw, confidence): a=forte, b=incerto, c=baixa
LAYA = {"a": (0.9, 0.9, 0.9), "b": (0.15, 0.15, 0.9), "c": (0.01, 0.01, 0.9)}


# ---------------------------------------------------------------- providers + padrão
def test_default_is_jev_only_and_laya_is_opt_in():
    eng = engine()
    st = eng.status()
    assert st["active_provider"] == "jev" and st["default_is_jev_only"] and st["default_pipeline"] == "graphify_jev_opt"
    assert st["stage"] == "EXPERIMENTAL" and st["measurements"]["jev_real"]["label"] == "UNKNOWN"


def test_jev_provider_uses_provider_thresholds():
    jev = FakeJev({"a": 0.9, "b": 0.6, "c": 0.1})
    r = engine(jev).decide(req())
    assert [d.decision for d in r.items] == [KEEP, REVIEW, DROP]
    assert r.jev_items == 3 and r.to_public()["jev_cost_usd"]["label"] == "UNKNOWN"


def test_laya_provider_bands():
    r = engine(laya=FakeLaya(LAYA)).decide(req(), provider="laya")
    assert [d.decision for d in r.items] == [KEEP, REVIEW, DROP] and r.jev_items == 0


# ---------------------------------------------------------------- estratégias
def test_laya_then_jev_sends_only_uncertain_to_jev():
    jev = FakeJev({"b": 0.9})
    r = engine(jev, FakeLaya(LAYA)).decide(req(), provider="hybrid", strategy="laya_then_jev")
    assert jev.calls == 1 and r.jev_calls_avoided == 2
    d = {i.candidate_id: i for i in r.items}
    assert d["b"].escalated and d["b"].decision == KEEP and d["b"].others["laya"]["decision"] == REVIEW
    assert d["a"].decision == KEEP and d["c"].decision == DROP and not d["a"].escalated


def test_jev_then_laya_laya_breaks_only_review():
    jev = FakeJev({"a": 0.9, "b": 0.6, "c": 0.1})
    laya = FakeLaya({"b": (0.9, 0.9, 0.9)})
    r = engine(jev, laya).decide(req(), provider="hybrid", strategy="jev_then_laya")
    d = {i.candidate_id: i for i in r.items}
    assert d["b"].decision == KEEP and d["b"].escalated and laya.calls == 1
    assert d["a"].decision == KEEP and d["c"].decision == DROP     # Laya nunca derruba KEEP/DROP do JEV
    assert r.jev_calls_avoided == 0


def test_ensemble_votes_and_quarantine_wins():
    jev = FakeJev({"a": 0.9, "b": 0.9, "c": 0.9})
    laya = FakeLaya({"a": (0.9, 0.9, 1), "b": (0.01, 0.01, 1), "c": (0.15, 0.15, 1)})
    r = engine(jev, laya).decide(req(), provider="hybrid", strategy="ensemble")
    d = {i.candidate_id: i for i in r.items}
    assert d["a"].decision == KEEP and d["b"].decision == REVIEW      # (1 + 0)/2 = 0.5
    assert set(d["b"].others) == {"laya", "jev"}


def test_adaptive_escalates_only_below_confidence():
    laya = FakeLaya({"a": (0.9, 0.9, 0.9), "b": (0.15, 0.15, 0.9), "c": (0.01, 0.01, 0.001)})
    jev = FakeJev({"c": 0.9})
    eng = engine(jev, laya)
    r = eng.decide(req(), provider="adaptive")
    d = {i.candidate_id: i for i in r.items}
    assert jev.calls == 1 and d["c"].escalated and d["c"].decision == KEEP
    assert d["b"].decision == REVIEW and not d["b"].escalated        # REVIEW confiante NÃO vai ao JEV no adaptive


# ---------------------------------------------------------------- fallback por tipo
def test_fallback_retrieval_passes_flagged_never_silent():
    r = engine(FakeJev(down=True)).decide(req())
    assert all(i.fallback and i.fallback_action == "allow" and i.decision == UNJUDGED for i in r.items)
    assert all(i.survives() for i in r.items) and r.errors


def test_fallback_memory_review_and_security_fail_closed():
    eng = engine(FakeJev(down=True))
    m = eng.decide(req(op="memory"), provider="jev")
    s = eng.decide(req(op="security"), provider="jev")
    assert {i.decision for i in m.items} == {REVIEW} and all(i.fallback for i in m.items)
    assert {i.decision for i in s.items} == {QUARANTINE} and all(i.fallback_action == "block" for i in s.items)
    assert not any(i.survives() for i in s.items)


def test_both_down_uses_op_fallback():
    r = engine(FakeJev(down=True), FakeLaya(down=True)).decide(req(op="security"), provider="hybrid")
    assert {i.decision for i in r.items} == {QUARANTINE} and all(i.fallback for i in r.items)


def test_one_side_down_other_decides_and_is_flagged():
    r = engine(FakeJev({"a": 0.9}), FakeLaya(down=True)).decide(req(("a",)), provider="hybrid", strategy="laya_then_jev")
    assert r.items[0].decision == KEEP and r.items[0].fallback and "Laya indisponível" in r.items[0].reason
    r2 = engine(FakeJev(down=True), FakeLaya(LAYA)).decide(req(), provider="hybrid", strategy="jev_then_laya")
    assert [i.fallback for i in r2.items] == [True] * 3


# ---------------------------------------------------------------- cache
def test_cache_hit_and_key_invalidation():
    jev = FakeJev()
    eng = engine(jev)
    eng.decide(req())
    r = eng.decide(req())
    assert r.cache_hits == 3 and jev.calls == 3 and all(i.cached for i in r.items)
    eng.cfg.thresholds["jev"] = Thresholds(0.95, 0.5)             # política mudou -> chave nova
    assert eng.decide(req()).cache_hits == 0
    base = dict(op="retrieval", project="", provider="jev", strategy="", query="q", content_hash="h", schema="s",
                checkpoint="c", version="v", policy="p")
    k = cache_key(**base)
    for field, val in (("project", "x"), ("schema", "s2"), ("checkpoint", "c2"), ("version", "v2"), ("policy", "p2"),
                       ("content_hash", "h2"), ("query", "q2"), ("provider", "laya")):
        assert cache_key(**{**base, field: val}) != k, field


def test_fallback_results_are_not_cached():
    jev = FakeJev(down=True)
    eng = engine(jev)
    eng.decide(req())
    jev.down = False
    assert eng.decide(req()).cache_hits == 0


# ---------------------------------------------------------------- config / projetos
def test_project_isolation_of_thresholds_and_cache():
    cfg = load_config({})
    cfg.projects = {"alfa": {"thresholds": {"jev": {"keep": 0.5, "review": 0.4}}}}
    jev = FakeJev({"a": 0.6})
    eng = DecisionEngine(cfg, jev=jev, history=DecisionHistory(10, None, False))
    assert eng.decide(req(("a",), project="alfa")).items[0].decision == KEEP
    assert eng.decide(req(("a",), project="beta")).items[0].decision == REVIEW   # sem herança entre projetos
    assert eng.decide(req(("a",), project="alfa")).cache_hits == 1
    assert cfg.thresholds_for("jev", "alfa").keep == 0.5 and cfg.thresholds_for("jev", "").keep == 0.78
    assert cfg.policy_hash("alfa") != cfg.policy_hash("beta")


def test_config_validation_and_file(tmp_path):
    with pytest.raises(ValueError):
        load_config({"MG_DECISION_PROVIDER": "xpto"})
    with pytest.raises(ValueError):
        load_config({"MG_DECISION_PRESET": "turbo"})
    p = tmp_path / "d.json"
    p.write_text(json.dumps({"thresholds": {"laya": {"keep": 0.3, "review": 0.2}}}), encoding="utf-8")
    assert load_config({"MG_DECISION_CONFIG_FILE": str(p)}).thresholds["laya"].keep == 0.3
    p.write_text(json.dumps({"thresholds": {"laya": {"keep": 0.1, "review": 0.2}}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config({"MG_DECISION_CONFIG_FILE": str(p)})


def test_presets_are_config_only_and_experimental():
    c = load_config({"MG_DECISION_PRESET": "balanced"})
    assert (c.provider, c.preset) == ("adaptive", "balanced") and c.to_public()["preset_status"] == "EXPERIMENTAL"
    assert load_config({}).provider == "jev"
    assert load_config({"MG_DECISION_PRESET": "quality", "MG_DECISION_PROVIDER": "jev"}).provider == "jev"  # env vence


# ---------------------------------------------------------------- telemetria / privacidade
def test_history_has_only_ids_and_hashes(tmp_path):
    hist = DecisionHistory(50, tmp_path / "h.jsonl", True)
    cfg = load_config({})
    eng = DecisionEngine(cfg, jev=FakeJev(), history=hist)
    eng.decide(DecisionRequest(SECRET, [Item("pasta/nota-privada.md", SECRET)]))
    raw = (tmp_path / "h.jsonl").read_text(encoding="utf-8") + json.dumps(hist.recent(10, include_items=True))
    assert "SEGREDO" not in raw and "nota-privada" not in raw and "neutro" not in raw
    rec = hist.recent(1, include_items=True)[0]
    assert len(rec["query_hash"]) == 16 and rec["items"][0]["h"]
    assert eng.decide(req()).to_public()  # smoke
    assert "SEGREDO" not in json.dumps(eng.decide(DecisionRequest(SECRET, [Item("x", SECRET)])).to_public())


def test_validation_limits():
    eng = engine(FakeJev())
    with pytest.raises(ValueError):
        eng.decide(DecisionRequest("q", [Item("a", "x"), Item("a", "y")]))
    with pytest.raises(ValueError):
        eng.decide(DecisionRequest("q", [Item("a", "x")], op="nope"))
    with pytest.raises(ValueError):
        eng.decide(DecisionRequest("q", [Item("a", "x")], project="../x"))
    with pytest.raises(ValueError):
        eng.decide(DecisionRequest("q", []))


def test_divergence_metrics():
    d = divergence([(KEEP, KEEP), (KEEP, DROP), (DROP, DROP), (REVIEW, KEEP)], [1, 0, 0, 1])
    assert d["agreement_rate"] == {"value": 0.5, "label": "MEASURED"}
    assert d["survival_agreement_rate"]["value"] == 0.5 or d["survival_agreement_rate"]["value"] == 0.75
    assert d["laya_keep_jev_drop"] == 1 and d["vs_labels"]["laya"]["recall"] == 1.0
    assert divergence([])["agreement_rate"]["label"] == "UNKNOWN"


def test_metrics_label_and_unknown_cost():
    eng = engine(FakeJev(), FakeLaya(LAYA))
    eng.decide(req(), provider="hybrid", strategy="ensemble")
    m = eng.history.metrics()
    assert m["jev_cost_usd"]["label"] == "UNKNOWN" and m["jev_tokens"]["label"] == "ESTIMATED"
    assert m["divergence"]["n"]["value"] == 3 and m["latency_ms_p95"]["label"] == "MEASURED"


# ---------------------------------------------------------------- REST
@pytest.fixture()
def client(monkeypatch):
    from app.api import decision as api
    from app.decision import engine as eng_mod
    eng = engine(FakeJev({"a": 0.9}))
    monkeypatch.setattr(eng_mod, "_ENGINE", eng)
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)), app


def _hdr():
    from app.services import security
    return {"X-MG-Token": security.get_or_create_local_token()}


def test_rest_routes_and_privacy(client):
    c, _ = client
    for path in ("status", "config", "history", "metrics", "evaluation"):
        assert c.get(f"/api/decision/{path}").status_code == 200, path
    body = {"query": SECRET, "items": [{"candidate_id": "a", "text": SECRET}]}
    assert c.post("/api/decision/decision", json=body).status_code == 403          # sem token
    r = c.post("/api/decision/decision", json=body, headers=_hdr())
    assert r.status_code == 200 and r.json()["items"][0]["decision"] == KEEP
    assert SECRET not in r.text
    rb = c.post("/api/decision/batch", json={"requests": [body, body]}, headers=_hdr())
    assert rb.status_code == 200 and len(rb.json()["results"]) == 2
    h = c.get("/api/decision/history")
    assert h.json()["total"] >= 3 and "SEGREDO" not in h.text
    assert c.post("/api/decision/decision", json={**body, "op": "x"}, headers=_hdr()).status_code == 422
    dup = {"query": "q", "items": [{"candidate_id": "a", "text": "x"}, {"candidate_id": "a", "text": "y"}]}
    assert c.post("/api/decision/decision", json=dup, headers=_hdr()).status_code == 422


def test_rest_is_loopback_only(client):
    _, app = client
    remote = TestClient(app, base_url="http://10.0.0.5", client=("10.0.0.5", 50000))
    for path in ("status", "config", "history", "metrics", "evaluation"):
        assert remote.get(f"/api/decision/{path}").status_code == 403, path
    assert remote.post("/api/decision/decision", json={"query": "q", "items": [{"candidate_id": "a", "text": "x"}]},
                       headers=_hdr()).status_code == 403


def test_all_decision_routes_exist_on_real_app():
    from app.main import create_app
    paths = set(create_app().openapi()["paths"])
    for p in ("status", "config", "decision", "batch", "history", "metrics", "evaluation"):
        assert f"/api/decision/{p}" in paths


# ---------------------------------------------------------------- CLI / MCP / pipeline
def test_cli_decision_status_and_history(capsys, monkeypatch, tmp_path):
    from app.cli.main import main
    from app.decision import engine as eng_mod
    monkeypatch.setattr(eng_mod, "_ENGINE", engine(FakeJev()))
    main(["decision", "status", "--json"])
    assert json.loads(capsys.readouterr().out)["active_provider"] == "jev"
    main(["decision", "test", "--provider", "jev"])
    out = json.loads(capsys.readouterr().out)
    assert out["provider"] == "jev" and len(out["items"]) == 2
    main(["decision", "history", "--limit", "5"])
    assert "records" in json.loads(capsys.readouterr().out)


def test_mcp_decision_status_is_opt_in_single_readonly_tool(monkeypatch):
    import importlib

    import anyio

    def tools(env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        import app.mcp.server as srv
        srv = importlib.reload(srv)
        return {t.name: t for t in anyio.run(srv.server.list_tools)}
    base = tools({"MG_MCP_TOOLSET": "minimal", "MG_MCP_SAVE": "0", "MG_MCP_DECISION": "0"})
    assert "decision_status" not in base
    on = tools({"MG_MCP_DECISION": "1"})
    assert set(on) - set(base) == {"decision_status"}
    ann = on["decision_status"].annotations
    assert ann is not None and ann.read_only_hint is True and ann.destructive_hint is False
    monkeypatch.setenv("MG_MCP_DECISION", "0")
    importlib.reload(importlib.import_module("app.mcp.server"))


def test_pipeline_integration_keeps_registry_and_default():
    from app.retrieval import pipelines_laya
    from app.retrieval.registry import PIPELINE_FUNCS
    from app.schemas.models import DEFAULT_EXPLICIT_PIPELINE, PIPELINES
    assert DEFAULT_EXPLICIT_PIPELINE == "graphify_jev_opt"
    assert "graphify_decision" not in PIPELINES and "graphify_decision" not in PIPELINE_FUNCS
    assert callable(pipelines_laya.run_graphify_decision) and callable(pipelines_laya.decision_engine)


def test_decision_package_is_import_light():
    import subprocess
    import sys
    code = "import sys, app.decision; print('torch' in sys.modules or 'laya' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "False"
