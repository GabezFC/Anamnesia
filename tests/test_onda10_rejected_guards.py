"""Onda 10 (ANA-239..246): itens REJEITADOS ficam fora do codigo ate haver evidencia.

Estes testes sao guardas de regressao de escopo, nao de funcionalidade: se alguem introduzir um dos itens rejeitados,
o teste falha e obriga a reabrir a decisao (nota ONDA10_REJEITADOS.md no Cerebro IA (Anamnesia/Migracao-docs-repo-2026-10-24)) com evidencia.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def _py():
    for f in APP.rglob("*.py"):
        yield f, f.read_text(encoding="utf-8", errors="ignore")


def _code_only(src: str) -> str:
    """Remove comentarios e docstrings: so conta uso real no codigo."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body \
                and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant) \
                and isinstance(n.body[0].value.value, str):
            n.body[0].value.value = ""
    return ast.unparse(tree)


def test_ana241_no_multi_tenant_or_device_sync():       # local-first, vault READ ONLY
    pat = re.compile(r"\b(tenant_id|multi_tenant|sync_device|device_sync|replicate_vault)\b", re.I)
    assert [f.name for f, s in _py() if pat.search(_code_only(s))] == []


def test_ana242_no_external_plugin_marketplace():       # Retriever Protocol interno basta
    pat = re.compile(r"\b(plugin_marketplace|install_plugin|entry_points\(group=.anamnesia)", re.I)
    assert [f.name for f, s in _py() if pat.search(_code_only(s))] == []


def test_ana243_no_numeric_memory_confidence_score():   # sem rotulos => falsa precisao
    pat = re.compile(r"\b(memory_confidence|confidence_score|trust_score)\b", re.I)
    assert [f.name for f, s in _py() if pat.search(_code_only(s))] == []


def test_ana244_api_is_not_versioned_yet():             # 0 consumidores externos; reavaliar com usuario externo
    prefixes = []
    for f, s in _py():
        prefixes += re.findall(r"APIRouter\(\s*prefix\s*=\s*[\"']([^\"']+)", s)
    assert prefixes and not any(p.startswith("/api/v") for p in prefixes), prefixes


def test_ana245_no_paid_embedding_or_reranker_api_by_default():
    pat = re.compile(r"text-embedding-|voyage-|cohere\.|api\.cohere|embed-english", re.I)
    assert [f.name for f, s in _py() if pat.search(_code_only(s))] == []


def test_ana246_no_automatic_routing_policy_promotion():  # HOLD medido na Onda 4e
    pat = re.compile(r"\b(auto_promote|autopromote|promote_policy_automatically)\b", re.I)
    assert [f.name for f, s in _py() if pat.search(_code_only(s))] == []
    import json
    rep = ROOT / "data" / "reports-out" / "ONDA4_ROUTING_REAL.json"
    if rep.exists():
        assert "HOLD" in json.dumps(json.loads(rep.read_text(encoding="utf-8")))


def test_ana239_prompts_stay_in_code_no_prompt_library():
    pat = re.compile(r"\b(prompt_library|prompt_registry|PromptStore)\b", re.I)
    assert [f.name for f, s in _py() if pat.search(_code_only(s))] == []


def test_ana240_long_function_ratchet():
    """ANA-240 foi rejeitado (refactor sem ganho medido), mas a divida nao pode CRESCER.
    Linha de base 2026-10-13: 11 funcoes > 80 linhas; a maior tem 174."""
    longs = []
    for f, s in _py():
        for n in ast.walk(ast.parse(s)):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = n.end_lineno - n.lineno + 1
                if length > 80:
                    longs.append((length, f.name, n.name))
    assert len(longs) <= 11, sorted(longs, reverse=True)
    assert max(length for length, _, _ in longs) <= 174, sorted(longs, reverse=True)[:3]
