# Anamnésia Decision Engine (ANAM-043) — EXPERIMENTAL

Camada única de decisão (`KEEP / REVIEW / DROP / QUARANTINE`) com providers intercambiáveis. Código em `app/decision/`.
**O padrão não mudou: JEV-only (`graphify_jev_opt`).** Laya e os híbridos são opt-in; medição em
`docs/bench/decision-engine.md` (JEV real: **não medido**).

## Rótulos de números

| Rótulo | Significado |
|---|---|
| `MEASURED` | contado/medido aqui (contagens, latência do engine, AUC/P/R/F1 sobre dados reais da amostra) |
| `ESTIMATED` | modelo ou extrapolação (tokens do JEV = `340·req + 209·perguntas`; limiares; latência do Laya replay) |
| `UNKNOWN` | não medido (custo/latência/qualidade do JEV real; divergência com o JEV real) |

## Providers e estratégias

| Provider | O que faz | Custo JEV |
|---|---|---|
| `jev` (padrão) | `JevService.evaluate` (TypeSafe ou Colibrì local) | todos os itens |
| `laya` | `LayaService.score` (`app/services/laya_decider.py`); também `memory` (`triage_write`) e `security` (`classify_privacy`) | 0 |
| `hybrid` `laya_then_jev` | Laya em todos; JEV só nos incertos (REVIEW, confidence baixa, sinal lexical de injeção) | só incertos |
| `hybrid` `jev_then_laya` | JEV em todos; Laya desempata só o REVIEW do JEV (nunca derruba KEEP/DROP) | = JEV-only |
| `hybrid` `ensemble` | Laya e JEV em todos; voto ponderado (KEEP=1, REVIEW=.5, DROP=0); QUARANTINE de qualquer lado vence | = JEV-only |
| `adaptive` | Laya primeiro; JEV só abaixo de `thresholds.adaptive.min_confidence` (REVIEW confiante **não** escala) | só baixa confiança |

`DecisionProvider`: `decide`, `batch`, `health`, `capabilities`, `version`, `provider_name` (+ `checkpoint`).
`health()` nunca chama o JEV nem carrega pesos (JEV aparece como `UNKNOWN` até ser usado).

## Fallback por tipo de operação (nunca em silêncio)

| Operação | Se o provider falha | Marca |
|---|---|---|
| `retrieval` | passa (`UNJUDGED`, `fallback_action=allow`) | `fallback=true`, `reason` |
| `memory` | `REVIEW` (`fallback_action=review`); nada é gravado sozinho | idem |
| `security` | `QUARANTINE` (`fallback_action=block`, fail-closed) | idem |

Nos híbridos, se só um lado cai o outro decide e o item sai com `fallback=true`; se os dois caem vale a tabela acima.
Resultados de fallback e `UNJUDGED` nunca entram no cache.

## Cache

Chave (SHA-256, só hashes): operação, projeto, provider, estratégia, hash da query, hash do candidato, `schema`,
`checkpoint` do modelo, `version` do provider e hash da política (limiares, pesos, `review_action`). Mudou qualquer
campo → entrada nova. LRU em memória (`MG_DECISION_CACHE_SIZE`, 0 desliga).

## Configuração

`MG_DECISION_*` em `.env.example` (referência gerada: `docs/ENVIRONMENT_REFERENCE.md`). Limiares são **por provider**
(`jev`, `laya`, `ensemble`, `adaptive`) e **por projeto**, em JSON apontado por `MG_DECISION_CONFIG_FILE`:

```json
{"thresholds": {"laya": {"keep": 0.25, "review": 0.10}, "adaptive": {"min_confidence": 0.05}},
 "ensemble_weights": {"laya": 0.5, "jev": 0.5},
 "projects": {"meu-projeto": {"provider": "adaptive", "thresholds": {"jev": {"keep": 0.7, "review": 0.5}}}}}
```

Isolamento: a entrada de um projeto só vale para requisições com esse `project`; **não há herança** entre projetos,
e o hash de política (logo, o cache) difere por projeto. Slugs: `[A-Za-z0-9_.-]{1,64}`. Valores inválidos
(`review > keep`, provider/estratégia desconhecidos) falham ao carregar.

**Presets** (`MG_DECISION_PRESET`) são só configuração, **experimentais**: `fast` = `laya`; `balanced` = `adaptive`;
`quality` = `hybrid/ensemble`. Variáveis explícitas vencem o preset. Nenhum foi validado com o JEV real.

## Telemetria e privacidade

Histórico por **IDs/hashes**: hash da query, hash do ID e do conteúdo do candidato, decisão, provider, score,
confidence, flags (cache/fallback/escalonado), latência, contagem de chamadas. Nunca texto de query/candidato nem
caminhos de nota. Memória (`MG_DECISION_HISTORY_SIZE`) + JSONL opcional `logs/decision_history.jsonl`
(`MG_DECISION_HISTORY_PERSIST`). Métricas: p50/p95, chamadas JEV evitadas, hit-rate do cache, taxa de fallback e
divergência Laya×JEV (`agreement_rate`, `survival_agreement_rate`, `cohen_kappa`, matriz, discordâncias).

## Interfaces

- **REST** (`/api/decision/…`, **loopback-only** via `require_localhost`): `GET status|config|history|metrics|evaluation`;
  `POST decision|batch` (podem acionar o JEV pago → exigem também `require_local_write`: mesma origem + `X-MG-Token`).
  Limites: 50 itens/requisição, 4000 chars/item, 20 requisições/batch. Respostas só levam IDs/hashes.
  Não há rota que altere a config.
- **CLI**: `python -m memory_gateway decision status|test|history` (`test` usa itens sintéticos embutidos).
- **MCP**: UMA tool read-only, `decision_status`, **opt-in** (`MG_MCP_DECISION=1`; padrão off para não aumentar o
  schema de todo turno). Não decide nem chama JEV/Laya.
- **Pipeline**: `app/retrieval/pipelines_laya.py::run_graphify_decision` (+ `decision_engine(gw)`, que reutiliza o
  `LayaService` e o JEV do gateway). **Não está em `PIPELINES`** de propósito (lista é contrato de UI/CLI/MCP/benchmark);
  registrá-lo exige alterar `app/schemas/models.py`, testes e frontend — decisão pendente, só se os dados justificarem.

## Benchmark

`python scripts/bench_decision.py` → `docs/bench/decision-engine.{md,json}`. Mesmos 192 pares sintéticos de
`scripts/bench_laya.py`; Laya = replay das probabilidades reais de ANAM-042; **JEV = fake lexical** (rotulado).
Sem vault real, sem rede, sem torch.

## Limites conhecidos

- Laya não superou o lexical neste corpus (AUC 0,64 vs 0,975); economia de JEV vem às custas de precisão.
- Qualidade/custo/latência do JEV real: `UNKNOWN`. Colibrì local não foi medido.
- Limiares do `adaptive`/`ensemble` são estimativas sobre dados sintéticos pequenos.
- `ensemble` no benchmark usa o mesmo limiar de `laya` (0,25) para o lado Laya: herda sua baixa precisão.
