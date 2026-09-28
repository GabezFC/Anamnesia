---
id: 20260717-0830
title: Aurora — Modelo local padrao 06
area: Projetos
type: decisao
tags: [aurora, decisoes, modelo]
status: ativo
created: 2026-07-17 08:30
updated: 2026-08-24 10:17
projeto: aurora
---

## Proximos passos

A ideia central e reduzir o custo de contexto sem perder recall. Deduplication happens before rerank, otherwise near-duplicates flood the top. Recall@5 is the primary metric; exact match is only a sanity check. Vale revisitar isso quando o volume de notas dobrar.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Como reproduzir

A decisao foi tomada depois de comparar tres alternativas equivalentes. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Resumo

Em teste local o ganho apareceu principalmente nas consultas curtas. Fica registrado para nao repetir a investigacao daqui a seis meses. This is a documentation note, not a runbook; keep the steps elsewhere.

## Referencias

Deduplication happens before rerank, otherwise near-duplicates flood the top. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Alternativas

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A causa raiz estava na normalizacao dos acentos antes da busca.

## Consequencias

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Deduplication happens before rerank, otherwise near-duplicates flood the top. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[2026-02-05]]
