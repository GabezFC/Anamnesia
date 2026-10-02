# Pipeline otimizado: baseline `graphify_jev_opt` vs. `graphify_jev_opt` + estágios aprovados

Fonte dos números: `docs/OPTIONAL_STAGES_BENCHMARK.md` (método, tabelas completas, limitações) e
`docs/stages_benchmark_2026-10-01.json`. Medido em 2026-10-02; o que não foi medido está marcado **NÃO MEDIDO**.

## Onde cada estágio entra

```
retrieval (graphify) → dedup → [JEV: relevância/injeção — só graphify_jev_opt] → survivors
        → optimizer.post_filter()
        → ESTÁGIOS OPCIONAIS (app/retrieval/optional_stages.py, hook em MemoryGateway.search)
              ordem fixa: bge_reranker_v2_m3 → mxbai_rerank_base_v2 → llmlingua2 → provence
                          → sentence_dedup_mmr → spotlight_nonce
        → ModelContextBuilder.build()  (honra meta["rerank_rank"] do reranker)
```

`graphify_jev` (congelado) **nunca** passa pelo hook. O preset só atua em `graphify_jev_opt`.

## Os três modos (`OPT_STAGES_PRESET`)

| Modo | Estágios ligados em `graphify_jev_opt` | Dependências | Uso |
| --- | --- | --- | --- |
| `off` | nenhum | — | referência comparável: exatamente o `graphify_jev_opt` pré-M2 |
| `free` (**padrão**) | `sentence_dedup_mmr` | nenhuma (stdlib) | produção sem deps pesadas |
| `approved` | `sentence_dedup_mmr` + `bge_reranker_v2_m3` + `provence` | torch + `requirements-optional.txt` | máxima economia; só uso pessoal (Provence é CC BY-NC-ND) |

Flags individuais (`OPT_STAGE_*`, `config/local_settings.json`) continuam valendo em qualquer pipeline menos
`graphify_jev`, e a configuração local sempre vence o preset. Modelo ausente ⇒ *skip* + métrica
`optional_stage_skipped:<nome>`, nunca erro.

## Antes / depois — vault real (12 perguntas, JEV, mesmo baseline de replay)

| | baseline (`off`) | `free` (padrão) | `approved` |
| --- | --- | --- | --- |
| Tokens de contexto | 30 856 | 30 154 (−2,28%) | 14 236 (**−53,86%**) |
| Tokens totais (judge 60 411 + contexto) | 91 267 | 90 565 (−0,77%) | 74 647 (**−18,21%**) |
| Amplificação (total/contexto) | 2,96 | 3,00 | 5,24 |
| Recall (10 respondíveis) | 0,90 | 0,90 | 0,90 |
| hint_coverage (proxy de fatos) | 0,90 | 0,90 | 0,933 |
| MRR / P@3 | 0,80 / 0,617 | 0,80 / 0,617 | 0,90 / 0,65 |
| Latência do estágio (média/consulta) | 0 | 17 ms | 1 559 ms |
| VRAM de pico · carga a frio | — | 0 · 0 | 5 363 MB · 6,6 s |

## Antes / depois — corpus sintético (120 consultas, `graphify`, sem JEV)

| | baseline | dedup (`free`) | `approved` |
| --- | --- | --- | --- |
| Tokens de contexto | 130 553 | 96 973 (−25,72%) | 83 920 (**−35,72%**) |
| Recall / fact_in_context | 0,9045 / 100·110 | 0,9045 / 100·110 | 0,9045 / 100·110 |
| MRR | 0,8962 | 0,8962 | 0,9176 |
| Latência do estágio | 0 | 1,5 ms | 679 ms |
| VRAM de pico · carga a frio | — | 0 · 0 | 3 924 MB · 6,7 s |

Os dois conjuntos concordam em direção; o ganho de tokens do dedup é grande no sintético (notas com texto repetido) e
pequeno no vault real (poucas notas por pergunta). **O preset `free` não é um ganho grande no vault real do usuário;
o ganho grande vem do Provence (opt-in).**

## Mudanças de código que o preset exigiu

- `config/optimization.py`: `APPROVED_FREE_STAGES`, `APPROVED_MODEL_STAGES`, `APPROVED_STAGES`, `STAGES_PRESETS`,
  `PRESET_PIPELINES`, campo `OptionalStagesConfig.preset`, `for_pipeline()`, `resolved(pipeline)`; novos campos
  `llmlingua2_rate`, `provence_threshold` (0,05), `rerank_max_length`, `rerank_cache`.
- `app/retrieval/optional_stages.py`: modelos carregados uma vez (`_get_model`/`release_models`), cache de scores do
  reranker por (estágio, `query_fp`, hash do texto), correções de API (ver benchmark §3), `meta["rerank_rank"]`,
  neutralização de delimitador forjado no spotlight.
- `app/gateway/context_builder.py`: `rank()` usa `meta["rerank_rank"]` como chave primária — sem a chave, ordem idêntica
  à anterior (teste dedicado). Antes, a ordem dos rerankers era descartada.
- `config/optional_stages_catalog.py`, `requirements-optional.txt`, `frontend/js/pages-setup.js` (texto da página).

## Garantias verificadas por teste

Preset (`off`/`free`/`approved`/valor inválido), pipelines fora de `PRESET_PIPELINES` intocados, override local vence
o preset, ordem dos estágios (rerank → compress → dedup → spotlight por último), fallback sem biblioteca (modelos
pulados, dedup roda), `graphify_jev` com saída idêntica em qualquer preset, `rank()` idêntico sem `rerank_rank`.
