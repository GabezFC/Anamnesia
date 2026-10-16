"""Modelo de custo do JEV (ESTIMATED): reaproveita o ajuste de mínimos quadrados medido em app/services/jev.py.

input_tokens ≈ 340 x requisições + 209 x perguntas. O ajuste foi medido (10 requisições reais, corpus sintético),
mas aplicá-lo a outras cargas/modelos é estimativa; USD do JEV real permanece UNKNOWN.
"""
from __future__ import annotations

from app.services.jev import JEV_COST_PER_QUESTION, JEV_COST_PER_REQUEST


def estimate_jev_tokens(requests: int, questions: int) -> int:
    return JEV_COST_PER_REQUEST * max(0, int(requests)) + JEV_COST_PER_QUESTION * max(0, int(questions))
