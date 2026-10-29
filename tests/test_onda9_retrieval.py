"""Onda 9 (ANA-225..237): experiment flags are OFF by default, each hook does what it says, and the report is fresh."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from app.gateway.context_builder import ModelContextBuilder
from app.retrieval import experiments as X
from app.retrieval.baseline import BaselineIndex
from app.retrieval.experiments import RetrievalExperiments as E, with_flags as wf
from app.schemas.models import Candidate
from app.services.obsidian import ObsidianVault
from app.services.scope import parse_scope

ROOT = Path(__file__).resolve().parents[1]


def _vault(tmp_path, notes: dict[str, str]) -> BaselineIndex:
    for rel, text in notes.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    b = BaselineIndex(ObsidianVault(tmp_path))
    b.build()
    return b


def _c(i, section="s", snippet="", score=1.0, file=None):
    return Candidate(candidate_id=f"c{i}", source_file=file or f"n{i}.md", section=section, snippet=snippet, score=score)


# ---- defaults ---------------------------------------------------------------------------------
def test_every_flag_defaults_off(monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith("MG_EXP_"):
            monkeypatch.delenv(k)
    e = E.from_env()
    assert e == E() and e.active() == [] and not e.lexical_active and e.hybrid_score == "rank"


def test_env_flags_are_read(monkeypatch):
    monkeypatch.setenv("MG_EXP_HYBRID_SCORE", "rrf")
    monkeypatch.setenv("MG_EXP_PREFIX_MIN_LEN", "5")
    monkeypatch.setenv("MG_EXP_BUDGET_FIT", "1")
    e = E.from_env()
    assert e.hybrid_score == "rrf" and e.prefix_min_len == 5 and e.budget_fit
    assert set(e.active()) == {"hybrid_score", "prefix_min_len", "budget_fit"}
    monkeypatch.setenv("MG_EXP_HYBRID_SCORE", "bogus")
    assert E.from_env().hybrid_score == "rank"


# ---- ANA-226 ----------------------------------------------------------------------------------
def test_bm25_weight_lands_on_section_column(tmp_path):
    b = _vault(tmp_path, {
        "a.md": "# A\n\n## Zebrafish\n\nnada relevante aqui\n",
        "b.md": "# B\n\n## Outro\n\nzebrafish zebrafish mencionado no corpo do texto\n",
    })
    assert "0.0, 2.0, 1.0, 0.0, 0.0" in X.bm25_expr(None)
    heavy = [c.source_file for c in b.search("zebrafish", 10, exp=wf(E(), bm25_section_weight=50.0))]
    assert heavy[0] == "a.md"                 # heading match wins when the heading column is heavily weighted
    light = [c.source_file for c in b.search("zebrafish", 10, exp=wf(E(), bm25_section_weight=0.01))]
    assert light[0] == "b.md"
    # legacy search() uses the same corrected expression (default 2.0) and still returns both notes
    assert {c.source_file for c in b.search("zebrafish")} == {"a.md", "b.md"}


# ---- ANA-227 ----------------------------------------------------------------------------------
def test_scope_before_topn_keeps_in_scope_hits(tmp_path):
    notes = {f"10-Trabalho/ruido{i}.md": "# R\n\ntermoraro termoraro termoraro termoraro\n" for i in range(6)}
    notes["50-Pessoal/alvo.md"] = "# Alvo\n\ntermoraro e bastante texto de enchimento para diluir o ranking aqui\n"
    b = _vault(tmp_path, notes)
    scope = parse_scope("area:50-Pessoal")
    legacy = [c for c in b.search("termoraro", 3) if scope.matches(c.source_file)]   # top-3 then scope
    fixed = b.search("termoraro", 3, exp=wf(E(), scope_before_topn=True), scope=scope)
    assert legacy == []
    assert [c.source_file for c in fixed] == ["50-Pessoal/alvo.md"]


# ---- ANA-228 / 229 / 236 ----------------------------------------------------------------------
def test_unified_tokens_and_prefix_match(tmp_path):
    b = _vault(tmp_path, {"a.md": "# A\n\nmigracao do banco concluida\n", "b.md": "# B\n\nsem relacao\n"})
    assert b.search("migracoes", 5, exp=wf(E(), unified_tokens=True)) == []          # no stemming, no prefix
    got = b.search("migracoes", 5, exp=wf(E(), unified_tokens=True, prefix_min_len=5, stem_prefix=True))
    assert [c.source_file for c in got] == ["a.md"]


def test_fts_match_escapes_quotes_and_dedups():
    from app.retrieval.baseline import query_terms
    m = X.fts_match('"asyncpg" asyncpg 0.73.2', wf(E(), unified_tokens=True), query_terms)
    assert m == '"asyncpg" OR "0.73.2"'


def test_rewrite_keeps_identifiers_quotes_and_never_empties():
    assert X.rewrite_query('O que a nota diz exatamente sobre asyncpg 0.73.2?') == "exatamente asyncpg 0.73.2"
    assert "Foo Bar" in X.rewrite_query('qual o registro de "Foo Bar" no vault?')
    assert X.rewrite_query("o que o vault diz?") == "o que o vault diz?"           # all carrier -> original
    assert "nao" in X.rewrite_query("qual porta o servico nao usa")                  # negator kept (qn-v3)


# ---- ANA-230 ----------------------------------------------------------------------------------
def test_rrf_scores_and_magnitude():
    s = X.rrf_scores([(["a", "b"], 1.0), (["b", "c"], 0.5)], k=60)
    assert s["b"] > s["a"] > s["c"] or s["b"] > s["c"]
    bm = [_c(1, score=10.0, file="a.md"), _c(2, score=5.0, file="b.md"), _c(3, score=0.1, file="c.md")]
    text, graph = X.hybrid_text_scores("magnitude", bm, ["a.md", "b.md", "c.md"], ["g.md"], [], E())
    assert text["c1"] > text["c2"] > text["c3"] and text["c1"] == 1.0
    assert 0.55 <= text["c3"] < text["c2"] - 0.2                                    # magnitude, not a rank ladder
    t2, g2 = X.hybrid_text_scores("rrf", bm, ["a.md", "b.md", "c.md"], ["g.md"], [], E())
    assert t2["c1"] == 1.0 and 0 < g2["g.md"] < 1


# ---- ANA-231 ----------------------------------------------------------------------------------
class _GW:
    def __init__(self, exp):
        self.experiments = exp


def test_dedup_limit_only_for_complex():
    gw = _GW(wf(E(), complex_dedup_max=4))
    q_complex = "compare a decisao de retries com a politica de timeouts e quais as diferencas entre eles"
    assert X.dedup_limit(gw, q_complex, 2) == 4
    assert X.dedup_limit(gw, "porta do servico", 2) == 2
    assert X.dedup_limit(gw, q_complex, 2, frozen=True) == 2
    assert X.dedup_limit(_GW(E()), q_complex, 2) == 2


# ---- ANA-232 / 233 ----------------------------------------------------------------------------
def test_lexical_rerank_promotes_full_coverage_and_marks_rank():
    cands = [_c(0, snippet="apenas alfa aqui"), _c(1, snippet="alfa beta gama juntos"), _c(2, snippet="nada")]
    out = X.lexical_rerank("alfa beta gama", cands, 3, alpha=0.2)
    assert out[0].candidate_id == "c1"
    assert [c.meta["rerank_rank"] for c in out] == [0, 1, 2]
    assert X.lexical_rerank("x", cands[:1], 20) == cands[:1]


def test_relative_cutoff_keeps_min():
    cs = [_c(0, score=10), _c(1, score=9), _c(2, score=1), _c(3, score=0.5), _c(4, score=0.1)]
    assert [c.candidate_id for c in X.relative_cutoff(cs, 0.5, 3)] == ["c0", "c1", "c2"]
    assert len(X.relative_cutoff(cs, 0.99, 3)) == 3
    assert X.relative_cutoff(cs, 0.0) == cs


# ---- ANA-235 (fake local embedder) ------------------------------------------------------------
class FakeEmb:
    def embed(self, texts):
        return [[float("gato" in t.lower()), float("cachorro" in t.lower()), 0.1] for t in texts]


def test_semantic_channel_with_fake_backend(tmp_path):
    import logging
    b = _vault(tmp_path, {"a.md": "# A\n\ngato dorme no sofa\n", "b.md": "# B\n\ncachorro corre no parque\n"})

    class GW:
        experiments = wf(E(), semantic_rrf=True)
        embedder = FakeEmb()
        baseline = b
        log = logging.getLogger("t")
        active_scope = None

    out = X.lexical_search(GW(), "parque", 5)
    assert out[0].source_file == "b.md"
    out2 = X.lexical_search(GW(), "gato", 5)
    assert out2[0].source_file == "a.md" and out2[0].meta["via_semantic"]


def test_embedder_is_loopback_only():
    with pytest.raises(ValueError):
        X.OllamaEmbedder("m", host="https://api.example.com")
    assert X.OllamaEmbedder("m", host="http://localhost:11434").model == "m"


def test_semantic_unavailable_degrades_to_lexical(tmp_path, monkeypatch):
    import logging
    b = _vault(tmp_path, {"a.md": "# A\n\ngato dorme\n"})
    monkeypatch.setattr(X.OllamaEmbedder, "available", lambda self: False)

    class GW:
        experiments = wf(E(), semantic_rrf=True)
        baseline = b
        log = logging.getLogger("t")
        active_scope = None

    assert [c.source_file for c in X.lexical_search(GW(), "gato", 5)] == ["a.md"]


# ---- ANA-225 (fake HTTP) ----------------------------------------------------------------------
class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ollama_jev_backend_fake_http():
    from app.services.jev_ollama import OllamaJevBackend
    seen = {}

    def opener(req, timeout=None):
        if isinstance(req, str):
            return _Resp(json.dumps({"models": [{"name": "qwen3:8b"}]}).encode())
        seen["body"] = json.loads(req.data)
        return _Resp(json.dumps({"model": "qwen3:8b", "prompt_eval_count": 7, "eval_count": 3,
                                 "message": {"content": json.dumps({"relevance": 1.7, "injection": -0.2})}}).encode())

    be = OllamaJevBackend("qwen3:8b", opener=opener)
    assert be.available()
    ans, usage, model = be.evaluate({"query": "q"}, {"relevance": {"instructions": "i"}, "injection": {"instructions": "j"}})
    assert ans == {"relevance": 1.0, "injection": 0.0}          # clamped
    assert usage == {"input_tokens": 7, "output_tokens": 3} and model == "qwen3:8b"
    assert seen["body"]["options"]["temperature"] == 0 and seen["body"]["stream"] is False


def test_ollama_jev_backend_rejects_remote_and_missing_answers():
    from app.services.jev_ollama import OllamaJevBackend
    with pytest.raises(ValueError):
        OllamaJevBackend("m", host="http://10.0.0.5:11434")
    be = OllamaJevBackend("m", opener=lambda req, timeout=None: _Resp(json.dumps(
        {"message": {"content": "{}"}}).encode()))
    with pytest.raises(ValueError):
        be.evaluate({}, {"relevance": {"instructions": "i"}})


def test_jev_backend_config_and_cache_key():
    from app.services.jev import cache_key
    from app.services.jev_ollama import OllamaJevBackend, make_backend
    from config.jev import JevConfig
    paid, local = JevConfig(), JevConfig()
    local.backend = "ollama"
    assert paid.backend == "typesafe" and make_backend(paid) is None
    assert isinstance(make_backend(local), OllamaJevBackend)
    c = _c(1)
    c.content_hash = "h"
    assert cache_key("q", c, paid) != cache_key("q", c, local)


# ---- ANA-237 ----------------------------------------------------------------------------------
def test_budget_fit_replaces_drop():
    body = "linha de enchimento sem relação nenhuma\n" * 80 + "o valor procurado é zebrafish-77 no final\n"
    cands = [_c(0, snippet=body, score=2, file="a.md"), _c(1, snippet=body, score=1, file="b.md")]
    legacy = ModelContextBuilder(600, 1500)
    ctx_l, src_l, _ = legacy.build(cands)
    fit = ModelContextBuilder(600, 1500, fit_query="zebrafish-77")
    ctx_f, src_f, tok_f = fit.build(cands)
    assert tok_f <= 600
    assert legacy.blocks_dropped_budget >= fit.blocks_dropped_budget
    assert len(src_f) >= len(src_l)
    assert "zebrafish-77" in ctx_f


# ---- cache keys / frozen pipeline / report ----------------------------------------------------
def test_versions_bumped_and_digest_changes_with_flags():
    from app.gateway.optimizer import _experiments_digest
    from config.optimizer import OPTIMIZER_VERSION
    from app.services.query_fp import QUERY_NORMALIZER_VERSION
    assert OPTIMIZER_VERSION == "mol-v4" and QUERY_NORMALIZER_VERSION == "qn-v3"   # qn untouched: tokenizer for the cache is unchanged
    assert _experiments_digest(_GW(E())) is None
    d = _experiments_digest(_GW(wf(E(), query_rewrite=True)))
    assert d and d["query_rewrite"] is True


def test_frozen_flag_bypasses_every_hook():
    gw = _GW(wf(E(), complex_dedup_max=9, lex_rerank_top=20, rel_cutoff=0.9))
    cs = [_c(0, score=1), _c(1, score=0.1)]
    assert X.post_dedup(gw, "q", cs, frozen=True) is cs
    assert X.dedup_limit(gw, "compare a e b e todos os detalhes entre eles", 2, frozen=True) == 2


def test_default_gateway_search_unchanged_by_experiment_plumbing(tiny_vault):
    """With flags off, lexical_search() IS baseline.search(): same objects' content."""
    import logging
    b = BaselineIndex(ObsidianVault(tiny_vault))
    b.build()

    class GW:
        experiments = E()
        baseline = b
        log = logging.getLogger("t")
        active_scope = None

    a = [(c.source_file, c.line if hasattr(c, "line") else c.meta["line"], round(c.score, 9)) for c in X.lexical_search(GW(), "fastapi backend", 10)]
    z = [(c.source_file, c.meta["line"], round(c.score, 9)) for c in b.search("fastapi backend", 10)]
    assert a == z


def test_report_is_fresh_and_has_verdicts():
    import importlib.util
    spec = importlib.util.spec_from_file_location("measure_onda9", ROOT / "scripts" / "experiments" / "measure_onda9.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    res = json.loads((ROOT / "tests" / "fixtures" / "onda9" / "ONDA9_EXPERIMENTOS.json").read_text(encoding="utf-8"))
    md = (ROOT / "tests" / "fixtures" / "onda9" / "ONDA9_EXPERIMENTOS.md").read_text(encoding="utf-8")
    assert md.replace("\r\n", "\n").strip() == mod.render(res).strip(), "rode: python scripts/measure_onda9.py --render"
    allowed = {"ADOTAR", "MANTER_OPT_IN", "REJEITAR", "BLOCKED"}
    ids = set()
    for k, v in res["experiments"].items():
        vs = [v] if "verdict" in v else [x for x in v.values() if isinstance(x, dict) and "verdict" in x]
        assert vs and all(x["verdict"] in allowed for x in vs)
        ids.add(k)
    assert ids == {f"ANA-{n}" for n in range(225, 238)} - {"ANA-" + str(n) for n in ()}
