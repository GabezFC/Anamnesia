---
id: 20260919-1758
title: Kraken — Publicar release 10
area: Projetos
type: nota
tags: [kraken, procedimentos, publicar]
status: ativo
created: 2026-09-19 17:58
updated: 2026-10-16 20:54
projeto: kraken
---

## Notes

The retrieval layer keeps a small LRU in front of the vector index. This is a documentation note, not a runbook; keep the steps elsewhere.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Riscos

Cold start dominates the p95 numbers in every run so far. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O comportamento so aparece quando o cache esta frio.

## Aberto

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Vale revisitar isso quando o volume de notas dobrar. A ideia central e reduzir o custo de contexto sem perder recall.

## Contexto

A causa raiz estava na normalizacao dos acentos antes da busca. Cold start dominates the p95 numbers in every run so far.

## Alternativas

O comportamento so aparece quando o cache esta frio. A decisao foi tomada depois de comparar tres alternativas equivalentes. Vale revisitar isso quando o volume de notas dobrar. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[estudo-sistemas-distribuidos-028]] [[handoff-do-time-027]] [[roteador-de-modelos-049]]
