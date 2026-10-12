"""ANA-003 / ANA-004: cache keys must never collide for semantically different queries."""
from __future__ import annotations

import pytest

from app.services import query_fp
from app.services.jev import cache_key
from config.jev import JevConfig
from app.schemas.models import Candidate

NEGATION_PAIRS = [
    ("Qual porta o serviço usa?", "Qual porta o serviço NÃO usa?"),
    ("O deploy usa cache", "O deploy nunca usa cache"),
    ("com autenticação", "sem autenticação"),
    ("is it allowed", "is it not allowed"),
    ("quais notas têm tag", "quais notas nem têm tag"),
]

NUMBER_PAIRS = [
    ("porta 80", "porta 90"),
    ("api v2", "api v3"),
    ("python 3", "python 4"),
]


@pytest.mark.parametrize("a,b", NEGATION_PAIRS)
def test_negation_changes_canonical_and_fingerprint(a, b):
    assert query_fp.canonical(a) != query_fp.canonical(b)
    assert query_fp.term_key(a) != query_fp.term_key(b)


def test_negators_are_not_stopwords():
    for w in ("nao", "nem", "sem", "not", "no", "never", "nunca", "without"):
        assert w not in query_fp.STOPWORDS or w == "no", w
    assert "nao" not in query_fp.STOPWORDS and "sem" not in query_fp.STOPWORDS


def test_normalizer_version_bumped():
    assert query_fp.QUERY_NORMALIZER_VERSION != "qn-v2"


def _cand() -> Candidate:
    import inspect
    sig = inspect.signature(Candidate)
    kwargs = {}
    for name, p in sig.parameters.items():
        if p.default is inspect.Parameter.empty:
            kwargs[name] = "x" if p.annotation in (str, "str") else 0
    kwargs["content_hash"] = "h1" if "content_hash" in sig.parameters else None
    return Candidate(**{k: v for k, v in kwargs.items() if v is not None})


@pytest.mark.parametrize("a,b", NUMBER_PAIRS + NEGATION_PAIRS)
def test_jev_cache_key_distinct(a, b):
    cfg = JevConfig()
    c = _cand()
    assert cache_key(a, c, cfg) != cache_key(b, c, cfg)


def test_jev_cache_key_still_unifies_paraphrase_order():
    cfg = JevConfig()
    c = _cand()
    assert cache_key("Qual driver do Postgres o Norteia usa?", c, cfg) == \
        cache_key("Que driver de Postgres o Norteia usa?", c, cfg)
