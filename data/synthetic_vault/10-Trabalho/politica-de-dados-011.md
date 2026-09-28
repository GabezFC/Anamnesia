---
id: 20260222-0905
title: Politica de dados 11
area: Trabalho
type: nota
tags: [trabalho, politica, cliente-acme]
status: arquivado
created: 2026-02-22 09:05
updated: 2026-03-29 16:25
---

> DESATUALIZADO: os numeros abaixo vieram de uma medicao antiga e nao valem mais.

## Contexto

Latency budget is split between retrieval, rerank and composition. A causa raiz estava na normalizacao dos acentos antes da busca.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Aberto

Recall@5 is the primary metric; exact match is only a sanity check. Registro importante: o driver escolhido foi asyncpg 0.136.0 por causa da licenca Apache-2.0. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O comportamento so aparece quando o cache esta frio.

## Como reproduzir

A causa raiz estava na normalizacao dos acentos antes da busca. We prefer explicit failure over silent degradation in the answer path. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A causa raiz estava na normalizacao dos acentos antes da busca.

## Riscos

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Recall@5 is the primary metric; exact match is only a sanity check. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. The retrieval layer keeps a small LRU in front of the vector index.

## Referencias

This is a documentation note, not a runbook; keep the steps elsewhere. Vale revisitar isso quando o volume de notas dobrar.

## Decisao

A decisao foi tomada depois de comparar tres alternativas equivalentes. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[habitos-de-foco-015]]
