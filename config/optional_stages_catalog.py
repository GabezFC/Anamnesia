"""Catalog of optional retrieval-pipeline stages (§1.4, §3 da proposta 2026-09-28).

Static data only — no import of the libraries themselves (they stay optional dependencies; see
`memory-gateway-token-optimization-audit.md` §13 in the cérebro for the source table). Each entry
in CATALOG is a candidate stage the interactive configuration page lists with a toggle. Stages
rejected outright (OmniRoute, RECOMP/Selective Context, GPTCache/RedisVL) are informational only —
REJECTED has no toggle and the frontend must never render one for them.

This file only describes the stages; wiring a toggled-on stage into a pipeline is a separate
concern (app/retrieval/optional_stages.py) and out of scope here.
"""
from __future__ import annotations

CATALOG: dict[str, dict] = {
    "llmlingua2": {
        "label": "LLMLingua-2",
        "licenca": "MIT",
        "tamanho": "~560MB (xlm-roberta-large-based)",
        "veredito": "experimentar",
        "pros": [
            "Compressão de prompt treinada para preservar informação verificável (datas, números, nomes).",
            "Licença permissiva (MIT), sem restrição de uso comercial.",
        ],
        "contras": [
            "Modelo extra para baixar e manter (~560MB) e rodar (custo de latência/CPU-GPU).",
            "Ainda não medido neste vault: economia de tokens vs custo de processamento é desconhecida.",
        ],
    },
    "provence": {
        "label": "Provence",
        "licenca": "CC BY-NC-ND (uso pessoal apenas, não permite uso comercial)",
        "tamanho": "~430MB",
        "veredito": "experimentar",
        "pros": [
            "Poda de contexto (context pruning) focada em manter só o texto relevante à pergunta.",
        ],
        "contras": [
            "Licença NC-ND bloqueia qualquer uso comercial ou redistribuição modificada — inviável para o "
            "projeto open-source publicar como padrão habilitado.",
            "Ainda não medido neste vault.",
        ],
    },
    "bge_reranker_v2_m3": {
        "label": "bge-reranker-v2-m3",
        "licenca": "Apache-2.0",
        "tamanho": "~568M parâmetros",
        "veredito": "experimentar (1ª opção)",
        "pros": [
            "Licença permissiva (Apache-2.0), uso comercial livre.",
            "Reranker multilíngue, cobre PT-BR nativamente.",
            "1ª opção recomendada na auditoria de repositórios (§13) entre os rerankers avaliados.",
        ],
        "contras": [
            "Modelo grande (~568M parâmetros): custo de latência e memória por candidato reordenado.",
            "Ainda não medido neste vault.",
        ],
    },
    "mxbai_rerank_base_v2": {
        "label": "mxbai-rerank-base-v2",
        "licenca": "Apache-2.0",
        "tamanho": "~0.5B parâmetros",
        "veredito": "experimentar (2ª opção)",
        "pros": [
            "Licença permissiva (Apache-2.0), uso comercial livre.",
            "Menor que bge-reranker-v2-m3 para o mesmo propósito — candidato caso a latência do 1ª opção "
            "não compense.",
        ],
        "contras": [
            "2ª opção na auditoria: sem medição própria ainda que justifique preferência sobre a 1ª.",
            "Ainda não medido neste vault.",
        ],
    },
    "sentence_dedup_mmr": {
        "label": "Dedup por sentença + MMR",
        "licenca": "sem modelo (heurística determinística)",
        "tamanho": "N/A",
        "veredito": "experimentar",
        "pros": [
            "Sem custo de modelo: deduplicação por sentença e Maximal Marginal Relevance sobre o contexto "
            "final, custo zero de tokens.",
            "Mesma família de técnica já calibrada em app/gateway/optimizer.py (near_dedup em nível de nota).",
        ],
        "contras": [
            "Escopo mais fino (sentença, não nota inteira) ainda não medido: risco de cortar uma frase que "
            "carregava o único fato citável de uma nota.",
        ],
    },
    "spotlight_nonce": {
        "label": "Spotlighting com nonce",
        "licenca": "sem modelo (marcação determinística por requisição)",
        "tamanho": "N/A",
        "veredito": "experimentar",
        "pros": [
            "Mitigação de segurança contra prompt injection: delimita o conteúdo não confiável do vault com "
            "um nonce por requisição, dificultando que uma nota finja ser uma instrução de sistema.",
            "Sem custo de modelo.",
        ],
        "contras": [
            "Um nonce por requisição quebra a determinística de bytes que o cache/MOL depende hoje (mesma "
            "entrada -> mesmos bytes, §5.7) — precisa ser medido junto com o efeito no prompt cache do "
            "consumidor antes de virar padrão.",
        ],
    },
}

# Avaliados e descartados (memory-gateway-token-optimization-audit.md §13). Informativo apenas —
# NUNCA expor toggle para estes: a decisão já foi tomada e não é reversível pela UI.
REJECTED: dict[str, str] = {
    "OmniRoute": "Rejeitado: gateway de API de LLM (roteia provedores, fallback, compressão de "
        "prompt); fica entre o agente e o provedor, não entre o agente e o vault. Ganho alegado "
        "não verificado (audit §13).",
    "RECOMP / Selective Context": "Rejeitado: RECOMP exige treino de compressor; Selective "
        "Context é projeto parado (audit §13).",
    "GPTCache / RedisVL": "Rejeitado: cache de RESPOSTAS de LLM; o Gateway não gera resposta, e "
        "cache semântico tem falso-positivo (audit §13).",
}
