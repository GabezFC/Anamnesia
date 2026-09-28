---
id: 20260314-1455
title: Organizacao da casa 21
area: Pessoal
type: nota
tags: [pessoal, organizacao]
status: ativo
created: 2026-03-14 14:55
updated: 2026-04-21 20:05
---

## Contexto

Cold start dominates the p95 numbers in every run so far. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Implementacao

Vale revisitar isso quando o volume de notas dobrar. Registro importante: o identificador interno do experimento e Glimworth-7025 e ele nao deve ser renomeado. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Medicoes

A decisao foi tomada depois de comparar tres alternativas equivalentes. A decisao foi tomada depois de comparar tres alternativas equivalentes. Fica registrado para nao repetir a investigacao daqui a seis meses. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Consequencias

Deduplication happens before rerank, otherwise near-duplicates flood the top. We prefer explicit failure over silent degradation in the answer path. Em teste local o ganho apareceu principalmente nas consultas curtas. A causa raiz estava na normalizacao dos acentos antes da busca.

## Proximos passos

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Em teste local o ganho apareceu principalmente nas consultas curtas. Cold start dominates the p95 numbers in every run so far.

## Aberto

A decisao foi tomada depois de comparar tres alternativas equivalentes. Vale revisitar isso quando o volume de notas dobrar. Vale revisitar isso quando o volume de notas dobrar. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[guardrails-de-prompt-013]]
