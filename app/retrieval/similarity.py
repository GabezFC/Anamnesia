"""Similaridade vetorial (ANAM-017 / AUD-022): cosseno com math.sumprod e vetores pré-normalizados.

O cosseno antigo (`experiments.cosine`) recalculava as duas normas a cada par com geradores em Python puro:
185 ms para 2000 vetores x 768 dims. Com vetores unitários o cosseno é só o produto interno
(`math.sumprod`, em C) e a norma da consulta é calculada uma vez: ~18 ms, ranking idêntico.
"""
from __future__ import annotations

import math
from typing import Sequence


def normalize(v: Sequence[float]) -> list[float]:
    """Vetor unitário. O vetor nulo fica nulo (cosseno 0 contra qualquer coisa, como no código antigo)."""
    n = math.sqrt(math.sumprod(v, v))
    return [x / n for x in v] if n else [0.0] * len(v)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    na, nb = math.sqrt(math.sumprod(a, a)), math.sqrt(math.sumprod(b, b))
    return math.sumprod(a, b) / (na * nb) if na and nb else 0.0


def rank_by_cosine(query: Sequence[float], normalized: Sequence[Sequence[float]]) -> list[tuple[float, int]]:
    """[(cosseno, índice)] em ordem decrescente; `normalized` já são vetores unitários (ver `normalize`).
    Empates desempatam como o código antigo (índice maior primeiro)."""
    q = normalize(query)
    return sorted(((math.sumprod(q, v), i) for i, v in enumerate(normalized)), reverse=True)
