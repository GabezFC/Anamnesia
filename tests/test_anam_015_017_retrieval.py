"""ANAM-015 (fusão híbrida: ordem estável, magnitude BM25) e ANAM-017 (near-dup LSH, cosseno sumprod)."""
from __future__ import annotations

import math
import random

import pytest

from app.retrieval import experiments as X
from app.retrieval.experiments import RetrievalExperiments as E
from app.retrieval.similarity import cosine, normalize, rank_by_cosine
from app.schemas.models import Candidate
from app.services.near_dup import cluster_near_duplicates, minhash_signature, simhash, similarity


def _c(i, score=1.0, file=None, text="x"):
    return Candidate(candidate_id=f"c{i}", source_file=file or f"f{i}.md", section="s", snippet=text,
                     score=score, origin="t")


# ---------------------------------------------------------------- ANAM-015
def test_escada_descarta_magnitude_e_magnitude_preserva():
    """Dois arquivos com BM25 10.0 e 9.9 (quase empate) e um terceiro com 0.1: a escada separa os três por
    degraus fixos; a magnitude mantém os dois primeiros colados e o terceiro bem abaixo."""
    bm = [_c(1, 10.0), _c(2, 9.9), _c(3, 0.1)]
    files = [c.source_file for c in bm]
    text, _ = X.hybrid_text_scores("magnitude", bm, files, [], [], E())
    ladder = [round(1.0 - 0.45 * (i / 3), 4) for i in range(3)]
    assert ladder[0] - ladder[1] == pytest.approx(0.15, abs=1e-3)
    assert text["c1"] - text["c2"] < 0.01 < text["c2"] - text["c3"]


@pytest.mark.parametrize("mode", ["magnitude", "rrf"])
def test_fusao_ordem_estavel_e_deterministica(mode):
    bm = [_c(i, score=5.0, file=f"f{i % 3}.md") for i in range(9)]        # empates totais
    files = ["f0.md", "f1.md", "f2.md"]
    first = X.hybrid_text_scores(mode, bm, files, ["g.md", "h.md"], ["g.md"], E())
    for _ in range(5):
        assert X.hybrid_text_scores(mode, list(bm), files, ["g.md", "h.md"], ["g.md"], E()) == first
    text, graph = first
    order = sorted(bm, key=lambda c: -text[c.candidate_id])                # sort estável: empate mantém a ordem de entrada
    same = [c.candidate_id for c in order if text[c.candidate_id] == text[order[0].candidate_id]]
    assert same == [c.candidate_id for c in bm if c.candidate_id in same]


def test_default_continua_rank():
    assert E().hybrid_score == "rank" and E.from_env().hybrid_score == "rank"


# ---------------------------------------------------------------- ANAM-017: near-dup
def _edit(words, p, rnd, vocab):
    return [(rnd.choice(vocab) if rnd.random() < p else w) for w in words]


def _detected(p, lsh, n=40, thr=0.88):
    rnd = random.Random(11)
    vocab = [f"w{i}" for i in range(400)]
    det = 0
    for _ in range(n):
        a = [rnd.choice(vocab) for _ in range(120)]
        b = _edit(a, p, rnd, vocab)
        cs = [_c("a", 1.0, "a.md", " ".join(a)), _c("b", 0.9, "b.md", " ".join(b))]
        det += cluster_near_duplicates(cs, threshold=thr, lsh=lsh)[1]["dedup_near_collapsed"]
    return det / n


def test_edicao_de_20pct_com_limiar_075_antes_0_depois_alto():
    assert _detected(0.2, lsh=False, thr=0.75) < 0.1
    assert _detected(0.2, lsh=True, thr=0.75) > 0.8


def test_edicao_de_12pct_recuperada_no_limiar_088():
    assert _detected(0.12, lsh=False) < 0.4
    assert _detected(0.12, lsh=True) > _detected(0.12, lsh=False) + 0.3


@pytest.mark.parametrize("p", [0.02, 0.05, 0.08])
def test_lsh_nunca_perde_recall_do_gerador_antigo(p):
    assert _detected(p, lsh=True) >= _detected(p, lsh=False)


def test_lsh_sem_falso_positivo_em_textos_independentes():
    rnd = random.Random(5)
    vocab = [f"w{i}" for i in range(400)]
    for _ in range(60):
        cs = [_c(k, 1 - k / 10, f"{k}.md", " ".join(rnd.choice(vocab) for _ in range(120))) for k in range(2)]
        assert cluster_near_duplicates(cs, threshold=0.88, lsh=True)[1]["dedup_near_collapsed"] == 0


def test_lsh_so_confirma_com_o_arbitro_similarity():
    """O LSH só gera pares; quem decide é similarity() >= limiar (mesma regra de antes)."""
    rnd = random.Random(9)
    vocab = [f"w{i}" for i in range(400)]
    a = [rnd.choice(vocab) for _ in range(120)]
    b = _edit(a, 0.12, rnd, vocab)
    sim = similarity(" ".join(a), " ".join(b))
    cs = [_c("a", 1.0, "a.md", " ".join(a)), _c("b", 0.9, "b.md", " ".join(b))]
    assert cluster_near_duplicates(cs, threshold=sim + 0.01, lsh=True)[1]["dedup_near_collapsed"] == 0
    assert cluster_near_duplicates(cs, threshold=sim - 0.01, lsh=True)[1]["dedup_near_collapsed"] == 1


def test_representante_e_o_melhor_ranqueado_com_lsh():
    t = " ".join(f"w{i}" for i in range(100))
    t2 = t.replace("w3 ", "z3 ").replace("w50 ", "z50 ").replace("w77 ", "z77 ")
    cl, m = cluster_near_duplicates([_c(1, 1.0, "a.md", t), _c(2, 0.9, "b.md", t2)], lsh=True)
    assert m["dedup_near_collapsed"] == 1 and cl[0].rep.candidate_id == "c1"


def test_env_desliga_lsh(monkeypatch):
    monkeypatch.setenv("MG_NEAR_DUP_LSH", "0")
    rnd = random.Random(11)
    vocab = [f"w{i}" for i in range(400)]
    a = [rnd.choice(vocab) for _ in range(120)]
    b = _edit(a, 0.2, rnd, vocab)
    cs = [_c("a", 1.0, "a.md", " ".join(a)), _c("b", 0.9, "b.md", " ".join(b))]
    assert cluster_near_duplicates(cs, threshold=0.75)[1]["dedup_near_collapsed"] == 0


def test_minhash_assinatura_estavel_e_simhash_inalterado():
    assert minhash_signature("a b c d e f") == minhash_signature("a b c d e f")
    assert minhash_signature("") == [None] * 32
    assert simhash("o gato preto comeu o rato cinza do vault") == 2385897561717551581      # valor do código antigo


# ---------------------------------------------------------------- ANAM-017: cosseno
def _legacy_cos(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def test_cosseno_igual_ao_legado_e_vetor_nulo():
    rnd = random.Random(1)
    for _ in range(20):
        a = [rnd.random() - .5 for _ in range(64)]
        b = [rnd.random() - .5 for _ in range(64)]
        assert cosine(a, b) == pytest.approx(_legacy_cos(a, b), abs=1e-12)
        assert X.cosine(a, b) == pytest.approx(_legacy_cos(a, b), abs=1e-12)
    assert cosine([0.0] * 4, [1.0, 2, 3, 4]) == 0.0 and normalize([0.0] * 3) == [0.0] * 3


def test_rank_by_cosine_top_igual_ao_legado():
    rnd = random.Random(2)
    vs = [[rnd.random() - .5 for _ in range(48)] for _ in range(300)]
    q = [rnd.random() - .5 for _ in range(48)]
    new = [i for _, i in rank_by_cosine(q, [normalize(v) for v in vs])][:25]
    old = [i for _, i in sorted(((_legacy_cos(q, v), i) for i, v in enumerate(vs)), reverse=True)][:25]
    assert new == old
