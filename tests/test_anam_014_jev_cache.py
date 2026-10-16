"""ANAM-014 (AUD-014): chave L2 do cache JEV, operações por candidato e validade por versão."""
from __future__ import annotations

import pytest

from app.database.db import Database
from app.services.jev_cache import CacheIdentity, LayeredCache, is_directional, l2_repr


def ident(**kw):
    base = dict(model="m", prompt_version="p", jev_mode="performance", relevance_threshold=0.78, review_threshold=0.55)
    return CacheIdentity(**{**base, **kw})


def pair():
    store: dict = {}
    return store, store.get, lambda k, v: store.__setitem__(k, v)


@pytest.mark.parametrize("a,b", [
    ("migrar de mysql para postgres", "migrar de postgres para mysql"),
    ("mysql -> postgres", "postgres -> mysql"),
    ("mysql → postgres", "postgres → mysql"),
    ("from redis to memcached", "from memcached to redis"),
])
def test_direcao_oposta_nao_compartilha_veredito(a, b):
    _, g, p = pair()
    c = LayeredCache(g, p, ident())
    c.put_judgement(a, "h1", {"relevance": 0.9})
    assert c.get_judgement(b, "h1") == (None, None)
    v, layer = c.get_judgement(a, "h1")                  # a própria consulta continua acertando (L1)
    assert v["relevance"] == 0.9 and layer == "l1_exact"


def test_reordenacao_sem_direcao_continua_acertando_l2():
    _, g, p = pair()
    c = LayeredCache(g, p, ident())
    c.put_judgement("driver postgres norteia", "h1", {"relevance": 0.8})
    assert c.get_judgement("norteia postgres driver", "h1")[1] == "l2_normalized"


def test_is_directional_e_l2_repr():
    assert is_directional("migrar mysql para postgres") and l2_repr("migrar mysql para postgres") is None
    assert not is_directional("licenca do software")
    assert l2_repr("redis licenca versao") == l2_repr("versao licenca redis")


def test_operacoes_por_candidato_unitario_3_gets_3_puts():
    store, g, p = pair()
    c = LayeredCache(g, p, ident(), enable_l3_shadow=True)
    assert c.get_judgement("q driver", "h1") == (None, None)
    c.put_judgement("q driver", "h1", {"relevance": 0.2})
    assert (c.stats.store_gets, c.stats.store_puts) == (3, 3)


def test_batch_consolida_em_1_get_e_1_put_por_candidato():
    store: dict = {}
    calls = {"g": 0, "p": 0}

    def gm(keys):
        calls["g"] += 1
        return {k: store[k] for k in keys if k in store}

    def pm(items):
        calls["p"] += 1
        store.update(items)

    c = LayeredCache(store.get, store.__setitem__, ident(), get_many=gm, put_many=pm)
    assert c.get_judgement("q driver", "h1") == (None, None)
    c.put_judgement("q driver", "h1", {"relevance": 0.2})
    assert calls == {"g": 1, "p": 1} and len(store) == 3
    assert c.get_judgement("q driver", "h1")[1] == "l1_exact"
    assert calls["g"] == 2


def test_batch_mesmo_resultado_que_unitario():
    s1, g1, p1 = pair()
    s2: dict = {}
    a = LayeredCache(g1, p1, ident())
    b = LayeredCache(s2.get, s2.__setitem__, ident(), get_many=lambda ks: {k: s2[k] for k in ks if k in s2},
                     put_many=lambda it: s2.update(it))
    for c in (a, b):
        c.put_judgement("licenca de software", "h1", {"relevance": 0.7})
    for q in ("licenca de software", "software licenca de", "licencas de software", "outra coisa"):
        va, la = a.get_judgement(q, "h1")
        vb, lb = b.get_judgement(q, "h1")
        assert (la, (va or {}).get("relevance")) == (lb, (vb or {}).get("relevance")), q
    assert s1.keys() == s2.keys()


def test_database_cache_e_auto_detectada_em_lote(tmp_path):
    db = Database(tmp_path / "t.db")
    c = LayeredCache(db.cache_get, db.cache_put, ident())
    assert c._get_many is not None
    c.put_judgement("driver postgres norteia", "h1", {"relevance": 0.6})
    assert c.get_judgement("driver postgres norteia", "h1")[0]["relevance"] == 0.6
    assert c.get_judgement("norteia postgres driver", "h1")[1] == "l2_normalized"
    assert (c.stats.store_gets, c.stats.store_puts) == (2, 1)
    # mesma tabela/linhas que o caminho unitário usa
    assert db.cache_get(next(iter(db.query("SELECT key FROM jev_cache")))["key"])["relevance"] == 0.6


@pytest.mark.parametrize("change", [{"index_version": "idx-2"}, {"judge_policy_version": "pol-2"}])
def test_versao_do_indice_e_da_politica_invalida(change):
    _, g, p = pair()
    LayeredCache(g, p, ident(index_version="idx-1", judge_policy_version="pol-1")).put_judgement(
        "q driver", "h1", {"relevance": 0.9})
    base = dict(index_version="idx-1", judge_policy_version="pol-1")
    assert LayeredCache(g, p, ident(**base)).get_judgement("q driver", "h1")[0] is not None
    assert LayeredCache(g, p, ident(**{**base, **change})).get_judgement("q driver", "h1") == (None, None)


def test_versoes_vazias_nao_alteram_digest_legado():
    assert ident().digest() == ident(index_version="", judge_policy_version="").digest()
    assert ident().digest() != ident(index_version="x").digest()
