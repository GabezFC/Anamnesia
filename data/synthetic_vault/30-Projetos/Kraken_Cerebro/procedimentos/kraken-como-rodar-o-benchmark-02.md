---
id: 20260911-1302
title: Kraken — Rodar o benchmark 02
area: Projetos
type: nota
tags: [kraken, procedimentos, rodar]
status: ativo
created: 2026-09-11 13:02
updated: 2026-10-22 17:22
projeto: kraken
---

## Decisao

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Em teste local o ganho apareceu principalmente nas consultas curtas. O comportamento so aparece quando o cache esta frio. This is a documentation note, not a runbook; keep the steps elsewhere.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Contexto

The retrieval layer keeps a small LRU in front of the vector index. This is a documentation note, not a runbook; keep the steps elsewhere. Registro importante: ficou definido um timeout de 164ms no KrampusDBProxy antes de cair para o fallback textual. This is a documentation note, not a runbook; keep the steps elsewhere. This is a documentation note, not a runbook; keep the steps elsewhere.

## Alternativas

Fica registrado para nao repetir a investigacao daqui a seis meses. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Deduplication happens before rerank, otherwise near-duplicates flood the top. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Como reproduzir

Cold start dominates the p95 numbers in every run so far. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Recall@5 is the primary metric; exact match is only a sanity check. Cold start dominates the p95 numbers in every run so far.

## Notes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. The retrieval layer keeps a small LRU in front of the vector index.

## Resumo

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[2026-02-11]] [[rotina-de-treino-001]] [[estudo-engenharia-de-prompts-019]]
