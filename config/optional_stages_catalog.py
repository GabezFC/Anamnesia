"""Catalog of optional retrieval-pipeline stages (§1.4, §3 da proposta 2026-09-28).

Static data only — no import of the libraries themselves (they stay optional dependencies). Each entry
in CATALOG is a stage the interactive configuration page lists with a toggle. Stages rejected outright
(OmniRoute, RECOMP/Selective Context, GPTCache/RedisVL) are informational only — REJECTED has no toggle
and the frontend must never render one for them.

MEDIDO (benchmark M2, 2026-10-02 — docs/OPTIONAL_STAGES_BENCHMARK.md, reports/stages_benchmark_2026-10-01.json):
corpus sintético (120 consultas, pipeline `graphify`, sem JEV) e vault real (12 perguntas, pipeline
`graphify_jev_opt`, JEV pago uma vez e reaproveitado em cache), RTX 3060 12 GB, torch 2.6.0+cu124.
Cada estágio isolado contra o MESMO baseline. Percentuais = tokens totais (judge + contexto) vs baseline;
valores negativos em `tokens_pct`/`tokens_totais_pct` significam MAIS tokens que o baseline.
Licenças conferidas na API do Hugging Face em 2026-10-02. Regra (§32): entra só se não perder recall nem
fact_in_context E reduzir tokens ou melhorar precisão (P@3/MRR). `veredito` abaixo é o resultado da regra;
o preset fica em config/optimization.py (APPROVED_*).

This file only describes the stages; wiring a toggled-on stage into a pipeline is a separate
concern (app/retrieval/optional_stages.py) and out of scope here.
"""
from __future__ import annotations

CATALOG: dict[str, dict] = {
    "llmlingua2": {
        "label": "LLMLingua-2",
        "licenca": "MIT (código llmlingua e modelo microsoft/llmlingua-2-xlm-roberta-large-meetingbank)",
        "tamanho": "2149 MB em disco; 2163 MB de VRAM; carga a frio ~2,6–3,0 s",
        "veredito": "REPROVADO (padrão rate=0.5 perde fatos); variante rate=0.85 passa a regra mas com ganho marginal",
        "medido": {
            "sintetico_rate0.5": {"economia_tokens_pct": 32.03, "fact_in_context": "69/110 (baseline 100/110)",
                                  "recall": 0.9045, "latencia_estagio_ms": 617},
            "sintetico_rate0.7": {"economia_tokens_pct": 15.24, "fact_in_context": "94/110"},
            "sintetico_rate0.85": {"economia_tokens_pct": 6.21, "fact_in_context": "100/110",
                                   "latencia_estagio_ms": 686},
            "real_rate0.5": {"economia_tokens_totais_pct": 6.64, "economia_contexto_pct": 19.64,
                             "hint_coverage": 0.90, "latencia_estagio_ms": 698},
            "real_rate0.85": {"economia_tokens_totais_pct": 0.99},
        },
        "pros": [
            "Licença permissiva (MIT), sem restrição de uso comercial.",
            "Compressão query-agnóstica: não precisa da pergunta, serve para qualquer pipeline.",
        ],
        "contras": [
            "Com rate=0.5 apagou 31 dos 110 fatos enterrados do corpus sintético (69/110): inaceitável.",
            "Com rate=0.85 preserva os fatos mas economiza só 6,2% (sintético) / 1,0% (real) por ~690 ms e "
            "2,1 GB de VRAM por consulta: não compensa.",
        ],
    },
    "provence": {
        "label": "Provence",
        "licenca": "CC BY-NC-ND 4.0 (uso pessoal apenas, não permite uso comercial)",
        "tamanho": "1668 MB em disco; 1721 MB (sint.) a 3197 MB (real) de VRAM; carga a frio ~2,4–2,6 s",
        "veredito": "APROVADO, opt-in (modelo + licença NC-ND); limiar 0.05",
        "medido": {
            "sintetico_thr0.05": {"economia_tokens_pct": 25.70, "fact_in_context": "100/110", "recall": 0.9045,
                                  "latencia_estagio_ms": 598},
            "sintetico_thr0.1_upstream": {"economia_tokens_pct": 25.47,
                                          "fact_in_context": "99/110 (perde 1 fato)"},
            "real_thr0.05": {"economia_tokens_totais_pct": 18.15, "economia_contexto_pct": 53.69,
                             "hint_coverage": 0.9333, "latencia_estagio_ms": 1249},
        },
        "pros": [
            "Poda orientada pela pergunta: maior economia de contexto medida no vault real (−53,7% de tokens de "
            "contexto, −18,2% do total incluindo o JEV) sem perder recall nem fatos.",
        ],
        "contras": [
            "Licença NC-ND bloqueia uso comercial e redistribuição de derivados — só uso pessoal; o projeto "
            "nunca deve habilitá-lo por padrão.",
            "Custa ~0,6 s (sintético) a ~1,25 s (real) por consulta e 1,7–3,2 GB de VRAM; precisa de "
            "trust_remote_code=True e do dado nltk 'punkt_tab' (segmentação em inglês).",
            "Com o limiar upstream 0.1 perdeu 1 fato do sintético; por isso o padrão do projeto é 0.05 "
            "(ajustado no sintético, confirmado no vault real).",
        ],
    },
    "bge_reranker_v2_m3": {
        "label": "bge-reranker-v2-m3",
        "licenca": "Apache-2.0 (modelo BAAI/bge-reranker-v2-m3 e sentence-transformers)",
        "tamanho": "2187 MB em disco; 2265–2366 MB de VRAM; carga a frio ~4,3–4,8 s",
        "veredito": "APROVADO, opt-in (modelo): melhora a ordenação (MRR), não economiza tokens",
        "medido": {
            "sintetico": {"mrr": "0.8962 -> 0.9176", "p_at_3": "0.3121 -> 0.3121", "economia_tokens_pct": 0.0,
                          "recall": 0.9045, "fact_in_context": "100/110", "latencia_estagio_ms": 145},
            "real": {"mrr": "0.80 -> 0.90", "p_at_3": "0.6167 -> 0.65", "economia_tokens_pct": 0.0,
                     "latencia_estagio_ms": 320},
            "cache_de_scores": "2.ª passada idêntica: 1172/1172 hits (sint.), 28/28 (real); estágio 144 ms -> 0,1 ms",
        },
        "pros": [
            "Único reranker que melhorou a ordenação nos DOIS corpora (MRR +0,021 sintético, +0,10 real).",
            "Licença permissiva (Apache-2.0), multilíngue (PT-BR).",
            "Cache de scores por (estágio, query_fp, hash do texto): repetição de pergunta não chama o modelo.",
        ],
        "contras": [
            "Ganho pequeno (MRR; P@3 do sintético não muda; no real é 1 pergunta em 10) e dentro do ruído "
            "de 12 perguntas — não é prova de ganho de recall.",
            "Custa ~145 ms (sint.) a ~320 ms (real) por consulta, 2,3 GB de VRAM e 2,2 GB de disco; "
            "dependência pesada (torch).",
        ],
    },
    "mxbai_rerank_base_v2": {
        "label": "mxbai-rerank-base-v2",
        "licenca": "Apache-2.0 (modelo mixedbread-ai/mxbai-rerank-base-v2 e mxbai-rerank)",
        "tamanho": "958 MB em disco; 1825 MB (sint.) a 5095 MB (real) de VRAM; carga a frio ~2,4–2,6 s",
        "veredito": "REPROVADO: piora a ordenação no sintético (MRR 0.8962 -> 0.8883)",
        "medido": {
            "sintetico": {"mrr": "0.8962 -> 0.8883", "p_at_3": "0.3121 -> 0.3061", "economia_tokens_pct": 0.0,
                          "latencia_estagio_ms": 148},
            "real": {"mrr": "0.80 -> 0.85", "p_at_3": "0.6167 -> 0.6167", "latencia_estagio_ms": 545,
                     "vram_pico_mb": 5095},
        },
        "pros": [
            "Licença permissiva (Apache-2.0); modelo menor em disco (958 MB).",
        ],
        "contras": [
            "Regrediu no corpus de 120 consultas e só ganhou levemente no de 12: não passa a regra nos dois "
            "corpora.",
            "Pico de VRAM de 5,1 GB no vault real (textos longos) e 545 ms por consulta.",
            "mxbai-rerank 0.1.6 QUEBRA com transformers>=5 (Qwen2Tokenizer.prepare_for_model removido): "
            "exige transformers<5.",
        ],
    },
    "sentence_dedup_mmr": {
        "label": "Dedup por sentença + MMR",
        "licenca": "sem modelo (heurística determinística, stdlib)",
        "tamanho": "N/A (sem modelo, sem VRAM)",
        "veredito": "APROVADO, ligado por padrão no graphify_jev_opt (preset free)",
        "medido": {
            "sintetico": {"economia_tokens_pct": 25.72, "recall": 0.9045, "fact_in_context": "100/110",
                          "latencia_estagio_ms": 1.5},
            "real": {"economia_tokens_totais_pct": 0.77, "economia_contexto_pct": 2.28, "hint_coverage": 0.90,
                     "latencia_estagio_ms": 17},
            "replay_300_runs_anterior": {"economia_tokens_pct": 31.56},
        },
        "pros": [
            "Sem modelo, sem dependência, determinístico, ~1,5–17 ms: −25,7% de contexto no sintético sem "
            "perder recall nem um fato (100/110 = baseline).",
            "Mesma família de técnica já calibrada em app/gateway/optimizer.py (near_dedup em nível de nota).",
        ],
        "contras": [
            "No vault real (poucas notas por consulta, quase sem repetição) o ganho é de ~0,8% do total: "
            "o valor aparece quando há notas duplicadas/ruidosas.",
            "Limiar de similaridade (0.85) ainda não calibrado isoladamente — mas zero fatos perdidos nas "
            "120 consultas.",
        ],
    },
    "spotlight_nonce": {
        "label": "Spotlighting com nonce",
        "licenca": "sem modelo (marcação determinística por requisição)",
        "tamanho": "N/A (sem modelo, sem VRAM)",
        "veredito": "REPROVADO como padrão (custo em tokens sem ganho de proteção medido); segue disponível como opt-in",
        "medido": {
            "sintetico": {"tokens_adicionais_pct": 60.71, "malicious_delivered": 13, "malicious_unflagged": 0,
                          "malicious_unprotected": 0},
            "real": {"tokens_adicionais_totais_pct": 1.45, "tokens_adicionais_contexto_pct": 4.28,
                     "malicious_delivered": 0},
        },
        "pros": [
            "Defesa em profundidade contra prompt injection: delimita o conteúdo não confiável e, nesta versão, "
            "neutraliza um delimitador falso dentro da nota.",
            "Sem modelo.",
        ],
        "contras": [
            "Adiciona +60,7% de tokens de contexto no sintético (notas curtas) e +4,3% no vault real: o "
            "cabeçalho de instrução é repetido em CADA nota.",
            "Proteção marginal medida = 0: das 13 notas maliciosas entregues no sintético, as 13 já saíam com o "
            "alerta `possible-prompt-injection` da camada de otimização (malicious_unflagged 0 antes e depois).",
            "Nonce por requisição (modo random) quebra o cache de bytes; modo hash é previsível por quem "
            "conhece o conteúdo.",
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
