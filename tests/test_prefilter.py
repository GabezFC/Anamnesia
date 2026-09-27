"""Tests for the deterministic pre-filter (app/services/prefilter.py).

The pre-filter must be: pure, zero-token, order-stable, and never silently lose candidates.
"""
from __future__ import annotations

from app.schemas.models import Candidate
from app.services.prefilter import lexical_overlap, prefilter, rank, terms


def c(cid: str, path: str, section: str = "", snippet: str = "", score: float = 0.5) -> Candidate:
    return Candidate(candidate_id=cid, source_file=path, section=section, snippet=snippet,
                     score=score, token_estimate=10)


def test_terms_strips_diacritics_and_stopwords():
    t = terms("Por que a decisão do driver asyncpg?")
    assert "decisao" in t          # diacritics folded
    assert "asyncpg" in t
    assert "por" not in t and "que" not in t  # stopwords removed


def test_lexical_overlap_rewards_path_and_heading():
    q = terms("driver asyncpg postgres")
    hit = c("1", "30-Projetos/X/decisoes/decisao-driver-asyncpg.md", "## Postgres")
    miss = c("2", "50-Pessoal/treino/corrida.md", "## Semana 3")
    assert lexical_overlap(q, hit) > lexical_overlap(q, miss)
    assert lexical_overlap(q, miss) == 0.0


def test_lexical_overlap_is_bounded():
    q = terms("asyncpg driver")
    cand = c("1", "asyncpg-driver.md", "## asyncpg driver", "asyncpg driver asyncpg driver")
    assert 0.0 <= lexical_overlap(q, cand) <= 1.0


def test_rank_is_deterministic_and_total():
    cands = [c(str(i), f"note-{i}.md", score=0.5) for i in range(10)]
    a = [x.candidate_id for x in rank("qualquer coisa", cands)]
    b = [x.candidate_id for x in rank("qualquer coisa", list(reversed(cands)))]
    assert a == b                      # stable regardless of input order
    assert len(a) == len(set(a)) == 10  # nothing lost, nothing duplicated


def test_prefilter_disabled_passes_everything_through():
    cands = [c(str(i), f"n{i}.md") for i in range(30)]
    sent, withheld, m = prefilter("q", cands, top_k=0)
    assert len(sent) == 30 and withheld == []
    assert m["prefilter_enabled"] is False


def test_prefilter_noop_when_fewer_than_k():
    cands = [c(str(i), f"n{i}.md") for i in range(5)]
    sent, withheld, m = prefilter("q", cands, top_k=25)
    assert len(sent) == 5 and withheld == []
    assert m["prefilter_sent"] == 5 and m["prefilter_withheld"] == 0


def test_prefilter_cuts_to_k_and_conserves_candidates():
    cands = [c(str(i), f"n{i}.md", score=i / 50) for i in range(50)]
    sent, withheld, m = prefilter("q", cands, top_k=25)
    assert len(sent) == 25 and len(withheld) == 25
    # no candidate may be dropped on the floor: the union must be the original set
    assert {x.candidate_id for x in sent + withheld} == {x.candidate_id for x in cands}
    assert m["prefilter_in"] == 50 and m["prefilter_sent"] == 25


def test_prefilter_keeps_the_obviously_relevant_note():
    """A note whose filename matches the query must survive a tight cut."""
    target = c("target", "30-Projetos/N/decisoes/decisao-driver-asyncpg.md", "## Driver",
               "asyncpg foi escolhido", score=0.30)
    noise = [c(f"n{i}", f"50-Pessoal/diario/2026-09-{i:02d}.md", "## Dia", "corrida e treino", score=0.99)
             for i in range(1, 30)]
    sent, withheld, _ = prefilter("Qual driver do Postgres e por que asyncpg?", noise + [target], top_k=5)
    assert "target" in {x.candidate_id for x in sent}


def test_prefilter_reports_token_savings():
    cands = [c(str(i), f"n{i}.md", score=i / 40) for i in range(40)]
    _, withheld, m = prefilter("q", cands, top_k=10)
    assert m["prefilter_tokens_saved_estimate"] == sum(x.token_estimate for x in withheld)
