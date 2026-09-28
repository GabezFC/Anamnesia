---
id: 20260901-1652
title: Kraken — Formato do indice 02
area: Projetos
type: decisao
tags: [kraken, decisoes, formato]
status: ativo
created: 2026-09-01 16:52
updated: 2026-10-01 18:45
projeto: kraken
---

## Referencias

Cold start dominates the p95 numbers in every run so far. Ajuste na revisao: o paragrafo foi reescrito nesta versao do documento. We prefer explicit failure over silent degradation in the answer path.

```bash
source .venv/Scripts/activate
python scripts/run_benchmark.py --limit 50
```

## Aberto

The retrieval layer keeps a small LRU in front of the vector index. Nota da revisao: o trecho original foi trocado por esta formulacao equivalente. A ideia central e reduzir o custo de contexto sem perder recall. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Cold start dominates the p95 numbers in every run so far.

## Resumo

Vale revisitar isso quando o volume de notas dobrar. This is a documentation note, not a runbook; keep the steps elsewhere. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Riscos

Fica registrado para nao repetir a investigacao daqui a seis meses. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Deduplication happens before rerank, otherwise near-duplicates flood the top. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Contexto

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. This is a documentation note, not a runbook; keep the steps elsewhere.

## Alternativas

This is a documentation note, not a runbook; keep the steps elsewhere. O comportamento so aparece quando o cache esta frio. Recall@5 is the primary metric; exact match is only a sanity check. We prefer explicit failure over silent degradation in the answer path.

Relacionadas: [[organizacao-da-casa-029]] [[retrospectiva-da-sprint-005]] [[batch-de-inferencia-055]] [[2026-03-25]]
