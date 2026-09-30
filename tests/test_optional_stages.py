"""Optional retrieval stages (§1.4/§5.5). No network, no model — the four model-backed stages are
exercised only on their "dependency missing" path (none of llmlingua/transformers/
sentence-transformers/mxbai_rerank are in requirements.txt, so import always fails here)."""
from __future__ import annotations

import json

import pytest

from app.retrieval import optional_stages as os_mod
from app.retrieval.optional_stages import (
    STAGE_FUNCS, STAGE_ORDER, apply_optional_stages, bge_reranker_v2_m3, llmlingua2,
    mxbai_rerank_base_v2, provence, sentence_dedup_mmr, spotlight_nonce, split_sentences,
)
from app.schemas.models import Candidate
from config.optimization import OPTIONAL_STAGE_NAMES, OptionalStagesConfig


def C(cid, src, snippet, score=1.0, section="Sec", chash=None):
    return Candidate(candidate_id=cid, source_file=src, section=section, snippet=snippet,
                     score=score, content_hash=chash or cid)


@pytest.fixture(autouse=True)
def _reset_warnings():
    os_mod.reset_warnings()
    yield
    os_mod.reset_warnings()


# -- config: off by default, registry consistency -------------------------------------------------
def test_all_stages_off_by_default():
    cfg = OptionalStagesConfig()
    assert cfg.active_flags() == []


def test_stage_registry_matches_config_names():
    assert set(STAGE_ORDER) == set(STAGE_FUNCS) == set(OPTIONAL_STAGE_NAMES)


def test_apply_optional_stages_noop_when_everything_disabled():
    cfg = OptionalStagesConfig()
    cands = [C("a", "x.md", "Texto único sobre o assunto.")]
    full: dict[str, str] = {}
    m = apply_optional_stages("assunto", cands, full, cfg)
    assert m["optional_stages_active"] == []
    assert cands[0].snippet == "Texto único sobre o assunto."


# -- config: local_settings.json overrides the frontend can flip --------------------------------
def test_resolved_applies_local_settings_override(tmp_path, monkeypatch):
    import config.local_settings as ls_mod

    local = tmp_path / "local_settings.json"
    local.write_text(json.dumps({"optional_stages": {"sentence_dedup_mmr": True}}), encoding="utf-8")
    monkeypatch.setattr(ls_mod, "LOCAL_SETTINGS_PATH", local)
    cfg = OptionalStagesConfig().resolved()
    assert cfg.sentence_dedup_mmr is True
    assert cfg.spotlight_nonce is False  # untouched key stays at its default


def test_resolved_ignores_unknown_keys_and_missing_file(tmp_path, monkeypatch):
    import config.local_settings as ls_mod

    monkeypatch.setattr(ls_mod, "LOCAL_SETTINGS_PATH", tmp_path / "does-not-exist.json")
    cfg = OptionalStagesConfig().resolved()
    assert cfg.active_flags() == []


# -- sentence_dedup_mmr: deterministic, no model ---------------------------------------------------
def test_split_sentences_splits_on_punctuation_and_blank_lines():
    text = "Primeira frase. Segunda frase!\n\nTerceiro parágrafo."
    assert split_sentences(text) == ["Primeira frase.", "Segunda frase!", "Terceiro parágrafo."]


def test_sentence_dedup_mmr_removes_cross_candidate_duplicate_sentence():
    cfg = OptionalStagesConfig(sentence_dedup_mmr_threshold=0.85, sentence_dedup_mmr_lambda=0.5)
    a = C("a", "x.md", "O projeto usa Python e FastAPI no backend.", score=2.0)
    b = C("b", "y.md", "O projeto usa Python e FastAPI no backend. Além disso usa SQLite.", score=1.0)
    full: dict[str, str] = {}
    m = sentence_dedup_mmr("stack do projeto", [a, b], full, cfg)
    assert m["stage_sentence_dedup_mmr_sentences_dropped"] >= 1
    # the duplicated sentence must not appear twice across both candidates' final text
    combined = a.snippet + "\n" + b.snippet
    assert combined.count("O projeto usa Python e FastAPI no backend") == 1
    # the unique sentence in b must survive
    assert "SQLite" in b.snippet


def test_sentence_dedup_mmr_is_deterministic():
    cfg = OptionalStagesConfig()
    mk = lambda: [C("a", "x.md", "Frase A. Frase A repetida quase igual."),
                  C("b", "y.md", "Frase A repetida quase igual mesmo. Frase B única.")]
    r1 = mk()
    m1 = sentence_dedup_mmr("frase", r1, {}, cfg)
    r2 = mk()
    m2 = sentence_dedup_mmr("frase", r2, {}, cfg)
    assert [c.snippet for c in r1] == [c.snippet for c in r2]
    m1.pop("stage_sentence_dedup_mmr_latency_ms")
    m2.pop("stage_sentence_dedup_mmr_latency_ms")
    assert m1 == m2


def test_sentence_dedup_mmr_never_empties_a_candidate():
    cfg = OptionalStagesConfig(sentence_dedup_mmr_threshold=0.5)
    a = C("a", "x.md", "Texto repetido aqui.", score=2.0)
    b = C("b", "y.md", "Texto repetido aqui.", score=1.0)
    sentence_dedup_mmr("q", [a, b], {}, cfg)
    assert a.snippet.strip() and b.snippet.strip()


def test_sentence_dedup_mmr_prefers_the_more_query_relevant_duplicate():
    cfg = OptionalStagesConfig(sentence_dedup_mmr_threshold=0.5, sentence_dedup_mmr_lambda=1.0)
    # near-duplicate pair; only one has the query term ("postgres"), lambda=1.0 -> pure relevance.
    a = C("a", "x.md", "O banco de dados usado é postgres.", score=1.0)
    b = C("b", "y.md", "O banco de dados usado é sqlite.", score=2.0)
    sentence_dedup_mmr("postgres", [a, b], {}, cfg)
    # exactly one of the two near-duplicate sentences must have survived, and it is the relevant one
    assert ("postgres" in a.snippet) != ("postgres" in b.snippet)


def test_sentence_dedup_mmr_operates_on_full_texts_when_present():
    cfg = OptionalStagesConfig(sentence_dedup_mmr_threshold=0.5)
    a = C("a", "x.md", "snippet curto")
    full = {"a": "Frase completa repetida. Frase completa repetida."}
    m = sentence_dedup_mmr("q", [a], full, cfg)
    assert a.snippet == "snippet curto"  # snippet untouched
    assert full["a"].count("Frase completa repetida") == 1
    assert m["stage_sentence_dedup_mmr_sentences_dropped"] == 1


# -- spotlight_nonce: hash mode deterministic, random mode is not -----------------------------------
def test_spotlight_nonce_hash_mode_is_deterministic_across_calls():
    cfg = OptionalStagesConfig(spotlight_nonce_mode="hash", spotlight_nonce_secret="local-secret")
    mk = lambda: [C("a", "x.md", "conteudo", chash="hash-a")]
    r1 = mk()
    spotlight_nonce("q", r1, {}, cfg)
    r2 = mk()
    spotlight_nonce("q", r2, {}, cfg)
    assert r1[0].snippet == r2[0].snippet
    assert "SPOTLIGHT:" in r1[0].snippet and "conteudo" in r1[0].snippet


def test_spotlight_nonce_random_mode_differs_across_requests():
    cfg = OptionalStagesConfig(spotlight_nonce_mode="random")
    r1 = [C("a", "x.md", "conteudo", chash="hash-a")]
    spotlight_nonce("q", r1, {}, cfg)
    r2 = [C("a", "x.md", "conteudo", chash="hash-a")]
    spotlight_nonce("q", r2, {}, cfg)
    assert r1[0].snippet != r2[0].snippet


def test_spotlight_nonce_random_mode_shares_one_nonce_per_request():
    cfg = OptionalStagesConfig(spotlight_nonce_mode="random")
    a = C("a", "x.md", "um")
    b = C("b", "y.md", "dois")
    spotlight_nonce("q", [a, b], {}, cfg)
    nonce_a = a.snippet.split("SPOTLIGHT:")[1].split(" ")[0]
    nonce_b = b.snippet.split("SPOTLIGHT:")[1].split(" ")[0]
    assert nonce_a == nonce_b


def test_spotlight_nonce_hash_mode_differs_per_content():
    cfg = OptionalStagesConfig(spotlight_nonce_mode="hash")
    a = C("a", "x.md", "conteudo um", chash="hash-a")
    b = C("b", "y.md", "conteudo dois", chash="hash-b")
    spotlight_nonce("q", [a, b], {}, cfg)
    nonce_a = a.snippet.split("SPOTLIGHT:")[1].split(" ")[0]
    nonce_b = b.snippet.split("SPOTLIGHT:")[1].split(" ")[0]
    assert nonce_a != nonce_b


# -- model-backed stages: missing dependency is a skip, never an exception --------------------------
@pytest.mark.parametrize("fn,name", [
    (llmlingua2, "llmlingua2"), (provence, "provence"),
    (bge_reranker_v2_m3, "bge_reranker_v2_m3"), (mxbai_rerank_base_v2, "mxbai_rerank_base_v2"),
])
def test_model_backed_stage_skips_when_dependency_missing(fn, name):
    cfg = OptionalStagesConfig()
    cands = [C("a", "x.md", "algum texto")]
    result = fn("q", cands, {}, cfg)
    assert result == {"optional_stage_skipped": name}
    assert cands[0].snippet == "algum texto"  # untouched


def test_apply_optional_stages_records_skip_in_metrics():
    cfg = OptionalStagesConfig(llmlingua2=True, sentence_dedup_mmr=True)
    cands = [C("a", "x.md", "Frase única aqui.")]
    m = apply_optional_stages("q", cands, {}, cfg)
    assert m["optional_stages_skipped"] == ["llmlingua2"]
    assert m["optional_stage_skipped:llmlingua2"] is True
    assert m["stage_sentence_dedup_mmr_enabled"] is True
    assert "llmlingua2" in m["optional_stages_active"]


def test_apply_optional_stages_never_raises_on_stage_exception(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(STAGE_FUNCS, "sentence_dedup_mmr", boom)
    cfg = OptionalStagesConfig(sentence_dedup_mmr=True)
    cands = [C("a", "x.md", "texto")]
    m = apply_optional_stages("q", cands, {}, cfg)
    assert m["optional_stages_skipped"] == ["sentence_dedup_mmr"]


# -- integration through MemoryGateway.search(): off = unchanged, on = applied, never on
# graphify_jev (frozen reference) even when every flag is on ------------------------------------
class _FakeJevBackend:
    def evaluate(self, state, questions):
        answers = {}
        for name, q in questions.items():
            answers[name] = 0.9 if name.startswith("rel_") else 0.0
        return answers, {"input_tokens": 10, "output_tokens": 2}, "jev-test"


class _FakeGraphify:
    """Same shape as app.services.graphify.GraphifyService, no binary required (tests/test_api_mcp.py)."""

    def __init__(self, vault_root, mirror):
        self.vault_root = vault_root
        self.graph_path = mirror / "graphify-out" / "graph.json"

    def search(self, query, limit=100):
        from app.services.obsidian import split_sections

        cands = []
        files = sorted(p for p in self.vault_root.rglob("*.md") if ".obsidian" not in p.parts)
        for i, p in enumerate(files[:limit]):
            rel = p.relative_to(self.vault_root).as_posix()
            sec = split_sections(p.read_text(encoding="utf-8"))[0]
            cands.append(C(f"g{i:03d}:{rel}#L{sec.line}", rel, sec.text, score=1.0 - i * 0.1,
                          section=sec.heading_path))
        return cands, {"graphify_nodes_returned": len(cands)}

    def build(self):
        return {"files": 0}

    def version(self):
        return "fake-graphify 0.0"


def _make_gateway(tiny_vault, tmp_path, **kw):
    from app.gateway.memory_gateway import MemoryGateway
    from config.benchmark import BenchmarkConfig
    from config.jev import JevConfig
    from config.retrieval import RetrievalConfig

    rcfg = RetrievalConfig(vault_path=tiny_vault, data_dir=tmp_path / "data")
    bcfg = BenchmarkConfig(db_path=str(tmp_path / "b.db"), profile="benchmark")
    jcfg = JevConfig(model="jev-test", mode="performance", relevance_threshold=0.5, review_threshold=0.3,
                     injection_threshold=0.8, review_action="keep", failure_mode="fail_open",
                     second_pass=False)
    gw = MemoryGateway(retrieval_cfg=rcfg, jev_cfg=jcfg, bench_cfg=bcfg, jev_backend=_FakeJevBackend(),
                       graphify_service=_FakeGraphify(tiny_vault, rcfg.mirror_dir), **kw)
    gw.warm()
    return gw


def test_search_baseline_unaffected_when_stages_off(tiny_vault, tmp_path):
    gw = _make_gateway(tiny_vault, tmp_path)
    result = gw.search("stack do projeto", pipeline="baseline", persist=False)
    assert not any(k.startswith("stage_") for k in result.metrics)


def test_search_applies_sentence_dedup_mmr_on_free_pipeline(tiny_vault, tmp_path):
    gw = _make_gateway(tiny_vault, tmp_path,
                       optional_stages_cfg=OptionalStagesConfig(sentence_dedup_mmr=True))
    result = gw.search("stack do projeto", pipeline="baseline", persist=False)
    assert result.metrics.get("stage_sentence_dedup_mmr_enabled") is True
    assert result.metrics["optional_stages_active"] == ["sentence_dedup_mmr"]


def test_search_applies_spotlight_nonce_on_graphify_pipeline(tiny_vault, tmp_path):
    gw = _make_gateway(tiny_vault, tmp_path,
                       optional_stages_cfg=OptionalStagesConfig(spotlight_nonce=True))
    result = gw.search("stack do projeto", pipeline="graphify", persist=False)
    assert result.metrics.get("stage_spotlight_nonce_enabled") is True
    if result.context:
        assert "SPOTLIGHT:" in result.context


def test_search_never_applies_stages_on_frozen_graphify_jev(tiny_vault, tmp_path):
    gw = _make_gateway(
        tiny_vault, tmp_path,
        optional_stages_cfg=OptionalStagesConfig(sentence_dedup_mmr=True, spotlight_nonce=True))
    result = gw.search("stack do projeto", pipeline="graphify_jev", persist=False)
    assert not any(k.startswith("stage_") for k in result.metrics)
    assert "optional_stages_active" not in result.metrics


def test_local_settings_toggle_reaches_search_without_restart(tiny_vault, tmp_path, monkeypatch):
    import config.local_settings as ls_mod

    local = tmp_path / "local_settings.json"
    local.write_text(json.dumps({"optional_stages": {"sentence_dedup_mmr": True}}), encoding="utf-8")
    monkeypatch.setattr(ls_mod, "LOCAL_SETTINGS_PATH", local)
    gw = _make_gateway(tiny_vault, tmp_path)  # constructed with every stage OFF
    result = gw.search("stack do projeto", pipeline="baseline", persist=False)
    assert result.metrics.get("stage_sentence_dedup_mmr_enabled") is True
