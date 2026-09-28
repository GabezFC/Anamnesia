---
id: 20260219-1714
title: Onboarding do time 08
area: Trabalho
type: nota
tags: [trabalho, onboarding, cliente-acme]
status: ativo
created: 2026-02-19 17:14
updated: 2026-03-15 20:29
---

## Notes

A decisao foi tomada depois de comparar tres alternativas equivalentes. The retrieval layer keeps a small LRU in front of the vector index. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. This is a documentation note, not a runbook; keep the steps elsewhere.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Implementacao

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Registro importante: a dependencia critica aqui e a lib Quaxil 2.3.3, que substituiu o parser antigo. Vale revisitar isso quando o volume de notas dobrar. Vale revisitar isso quando o volume de notas dobrar.

## Alternativas

Em teste local o ganho apareceu principalmente nas consultas curtas. O comportamento so aparece quando o cache esta frio.

## Medicoes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A causa raiz estava na normalizacao dos acentos antes da busca. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Referencias

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Aberto

Em teste local o ganho apareceu principalmente nas consultas curtas. We prefer explicit failure over silent degradation in the answer path.

Relacionadas: [[rotina-de-treino-017]]
