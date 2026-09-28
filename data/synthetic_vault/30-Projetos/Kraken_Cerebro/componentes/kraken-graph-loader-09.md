---
id: 20260928-1331
title: Kraken — Graph loader 09
area: Projetos
type: nota
tags: [kraken, componentes, graph]
status: arquivado
created: 2026-09-28 13:31
updated: 2026-11-09 15:11
projeto: kraken
---

> DESATUALIZADO: os numeros abaixo vieram de uma medicao antiga e nao valem mais.

## Decisao

O comportamento so aparece quando o cache esta frio. Latency budget is split between retrieval, rerank and composition. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A ideia central e reduzir o custo de contexto sem perder recall.

```bash
source .venv/Scripts/activate
python scripts/run_benchmark.py --limit 50
```

## Contexto

The retrieval layer keeps a small LRU in front of the vector index. Registro importante: o snapshot foi validado contra KrampusDB v3.41-rc2 em ambiente isolado. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Referencias

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. This is a documentation note, not a runbook; keep the steps elsewhere. Recall@5 is the primary metric; exact match is only a sanity check. Vale revisitar isso quando o volume de notas dobrar.

Relacionadas: [[reuniao-de-alinhamento-037]] [[organizacao-da-casa-013]] [[orcamento-de-infra-054]] [[kraken-decisao-driver-do-banco-01]]
