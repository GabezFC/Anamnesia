---
id: 20260917-1644
title: Kraken — Rodar o benchmark 08
area: Projetos
type: nota
tags: [kraken, procedimentos, rodar]
status: ativo
created: 2026-09-17 16:44
updated: 2026-10-03 17:03
projeto: kraken
---

## Medicoes

A decisao foi tomada depois de comparar tres alternativas equivalentes. A ideia central e reduzir o custo de contexto sem perder recall. O comportamento so aparece quando o cache esta frio.

```bash
source .venv/Scripts/activate
python scripts/run_benchmark.py --limit 50
```

## Implementacao

Fica registrado para nao repetir a investigacao daqui a seis meses. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Alternativas

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Vale revisitar isso quando o volume de notas dobrar. This is a documentation note, not a runbook; keep the steps elsewhere. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Consequencias

A ideia central e reduzir o custo de contexto sem perder recall. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Decisao

Vale revisitar isso quando o volume de notas dobrar. The retrieval layer keeps a small LRU in front of the vector index.

## Resumo

Fica registrado para nao repetir a investigacao daqui a seis meses. Vale revisitar isso quando o volume de notas dobrar. A ideia central e reduzir o custo de contexto sem perder recall.

Relacionadas: [[inbox-rascunho-de-api-020]] [[cache-de-embeddings-041]] [[politica-de-dados-059]] [[politica-de-dados-035]]
