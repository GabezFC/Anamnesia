---
id: 20260821-1005
title: Kraken — Visao geral do gateway 01
area: Projetos
type: nota
tags: [kraken, arquitetura, visao]
status: ativo
created: 2026-08-21 10:05
updated: 2026-09-01 17:36
projeto: kraken
---

## Implementacao

Cold start dominates the p95 numbers in every run so far. This is a documentation note, not a runbook; keep the steps elsewhere.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Consequencias

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A decisao foi tomada depois de comparar tres alternativas equivalentes. Registro importante: o snapshot foi validado contra KrampusDB v6.97-rc1 em ambiente isolado. O comportamento so aparece quando o cache esta frio. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Medicoes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Resumo

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[guardrails-de-prompt-013]]
