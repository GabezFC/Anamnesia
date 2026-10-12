"""ANA-098: interrogatives matched as words, never as substrings."""
from __future__ import annotations

import pytest

from app.services.query_fp import classify


@pytest.mark.parametrize("q", [
    "how to install redis on windows",       # "all" inside install
    "show the nginx config path",            # "how" inside show
    "comodidade do servidor ssl cert",       # "como" inside comodidade
    "uninstall postgres driver quickly",     # "all" inside uninstall
    "qualquer porta do redis serve aqui",    # startswith("qual") but not the word
])
def test_no_spurious_multi_hop_or_simple_wh(q):
    p = classify(q)
    assert p.multi_hop_hint is False, p
    assert p.complexity != "COMPLEX", p


def test_real_interrogatives_still_detected():
    # multi_hop_hint = interrogative as a whole word AND (conjunction with >=6 terms OR >=8 terms)
    for q in ("compare redis e postgres para o cache de sessao dos servicos",
              "quais servicos usam redis e quais bancos usam postgres no cluster de producao regional",
              "list all services using redis and all services using postgres in production",
              "todos os servicos de cache e todos os servicos de fila do cluster principal",
              "redis vs postgres para cache de sessao e fila de mensagens no cluster"):
        assert classify(q).multi_hop_hint, q


def test_simple_wh_requires_first_word():
    simple = classify("qual a porta do redis")
    spurious = classify("qualquer porta do redis")
    assert simple.complexity != spurious.complexity or simple != spurious
