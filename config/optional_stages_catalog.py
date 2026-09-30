"""Catalog of optional retrieval stages evaluated for Memory Gateway (proposta 2026-09-28 §1.4).

Source: `memory-gateway-token-optimization-audit.md` §13 of the Cérebro vault (repository/technique
survey). Copied here as plain data so the frontend configuration page (proposta §3) can render
prós/contras/license without reading the vault at request time (the vault is READ ONLY and this data
does not change per-request).

`selectable=False` entries are the ones §13 marked "rejeitar": they are documented here for
transparency, but no flag exists for them in config/optimization.py and the frontend must never
expose a toggle for them (proposta §1.4: "não expor os rejeitados como opção ligável, só documentar
por que foram descartados").
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class StageInfo:
    name: str
    label: str
    category: str            # "compression" | "reranking" | "dedup" | "spotlighting" | "rejected"
    license: str
    model_size: str
    verdict: str              # "experimentar" | "integrado" | "rejeitar"
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    selectable: bool = True   # False => rejected candidate, no flag, no frontend toggle
    reason: str = ""          # only meaningful when selectable=False


CATALOG: dict[str, StageInfo] = {
    "llmlingua2": StageInfo(
        name="llmlingua2", label="LLMLingua-2", category="compression",
        license="MIT", model_size="~560M (xlm-roberta-large-meetingbank)", verdict="experimentar",
        pros=[
            "Compressão de prompt treinada para preservar tokens informativos (não é truncamento cego)",
            "Biblioteca oficial da Microsoft, mantida ativamente",
        ],
        cons=[
            "Requer baixar/rodar um modelo próprio (custo de latência e memória)",
            "Economia real de tokens não medida neste branch — lib não instalada "
            "(requirements-optional.txt, import tardio em app/retrieval/optional_stages.py)",
        ],
    ),
    "provence": StageInfo(
        name="provence", label="Provence (naver/provence-reranker-debertav3-v1)",
        category="compression", license="CC BY-NC-ND 4.0 — SOMENTE USO PESSOAL/NÃO COMERCIAL",
        model_size="~440M (DeBERTa-v3-large)", verdict="experimentar",
        pros=[
            "Reranking + compressão de contexto em um único passo",
            "Bom desempenho reportado em benchmarks públicos de RAG",
        ],
        cons=[
            "Licença NC-ND impede uso comercial — risco de compliance se o projeto for distribuído "
            "ou usado comercialmente; manter desligado por padrão é obrigatório, não só recomendado",
            "Não medido neste branch — lib não instalada",
        ],
    ),
    "bge_reranker_v2_m3": StageInfo(
        name="bge_reranker_v2_m3", label="BAAI/bge-reranker-v2-m3", category="reranking",
        license="MIT", model_size="~568M", verdict="experimentar",
        pros=[
            "Cross-encoder multilingue (inclui PT-BR), bom recall em benchmarks públicos",
            "Integra via sentence-transformers CrossEncoder ou FlagEmbedding",
        ],
        cons=[
            "Custo de inferência por par (query, candidato) — cresce linear com nº de candidatos",
            "Não medido neste branch — lib não instalada",
        ],
    ),
    "mxbai_rerank_base_v2": StageInfo(
        name="mxbai_rerank_base_v2", label="mixedbread-ai/mxbai-rerank-base-v2", category="reranking",
        license="Apache 2.0", model_size="~278M", verdict="experimentar",
        pros=[
            "Licença permissiva (Apache 2.0)",
            "Menor que bge-reranker-v2-m3 — latência de inferência menor",
        ],
        cons=[
            "Multilingue mas com menos validação publicada em PT-BR do que bge-reranker-v2-m3",
            "Não medido neste branch — lib não instalada",
        ],
    ),
    "sentence_dedup_mmr": StageInfo(
        name="sentence_dedup_mmr", label="Dedup de sentenças + MMR (sem modelo)", category="dedup",
        license="N/A — código local, determinístico", model_size="0 (sem modelo)", verdict="integrado",
        pros=[
            "Zero custo de modelo/rede — reaproveita o mesmo Jaccard de app/services/near_dup.py",
            "Determinístico: mesma entrada produz sempre a mesma saída",
            "Medido neste branch sobre contextos reais de benchmark.db — ver "
            "scripts/measure_optional_stages.py e o resumo no commit",
        ],
        cons=[
            "Similaridade lexical (Jaccard), não semântica — não pega paráfrases sem sobreposição de palavras",
            "Ganho depende de quanta redundância o vault/contexto já tem; pode ser zero em vaults limpos",
        ],
    ),
    "spotlight_nonce": StageInfo(
        name="spotlight_nonce", label="Spotlighting com nonce por requisição", category="spotlighting",
        license="N/A — técnica, sem modelo", model_size="0 (sem modelo)", verdict="integrado",
        pros=[
            "Mitigação adicional de prompt injection: delimitadores imprevisíveis ao redor de cada trecho",
            "Modo `hash` é determinístico — preserva o prompt cache do consumidor e o ResultCache do Gateway",
        ],
        cons=[
            "Modo `random` quebra bytes/prompt cache do consumidor a cada requisição (trade-off documentado)",
            "Não é uma defesa completa — complementa o `injection_flag` da MOL (config/optimizer.py), não o substitui",
        ],
    ),
    "omniroute": StageInfo(
        name="omniroute", label="OmniRoute", category="rejected",
        license="não publicada claramente no momento da avaliação", model_size="n/a", verdict="rejeitar",
        pros=[],
        cons=[
            "Roteamento de MODELO (qual LLM responde), não de CONTEXTO — fora do escopo de retrieval do Gateway",
            "Sem repositório/benchmark público verificável na avaliação (§13 do audit)",
        ],
        selectable=False,
        reason="Fora de escopo (roteador de modelo, não de contexto/retrieval) — ver §13 do audit.",
    ),
    "recomp_selective_context": StageInfo(
        name="recomp_selective_context", label="RECOMP / Selective Context", category="rejected",
        license="MIT (ambos)", model_size="variável (modelo de compressão próprio)", verdict="rejeitar",
        pros=[],
        cons=[
            "Medido no audit como perda líquida: custo de compressão supera a economia de tokens",
            "Mesmo padrão de um caso já registrado no Cérebro (filtro cortou 77% do contexto mas "
            "custou 10x mais no total) — ver proposta §1.5",
        ],
        selectable=False,
        reason="Medido como perda líquida de tokens totais (audit §13) — mesmo padrão de perda já registrado.",
    ),
    "gptcache_redisvl": StageInfo(
        name="gptcache_redisvl", label="GPTCache / RedisVL", category="rejected",
        license="MIT (GPTCache) / Apache 2.0 (RedisVL)", model_size="n/a — infraestrutura de cache",
        verdict="rejeitar",
        pros=[],
        cons=[
            "Requer infraestrutura externa (Redis) — o Gateway é local e não deve exigir dependências externas",
            "O Gateway já tem cache em camadas próprio (app/services/jev_cache.py, "
            "config/optimizer.py ResultCache) cobrindo o mesmo problema",
        ],
        selectable=False,
        reason="Dependência de infraestrutura externa (Redis); o Gateway já tem cache próprio em camadas.",
    ),
}


def selectable() -> list[StageInfo]:
    return [s for s in CATALOG.values() if s.selectable]


def rejected() -> list[StageInfo]:
    return [s for s in CATALOG.values() if not s.selectable]


def to_dict() -> dict:
    """Serializable form for a future REST endpoint / frontend page (§3). Not wired to a route
    here — that endpoint is out of this task's scope."""
    return {name: asdict(info) for name, info in CATALOG.items()}
