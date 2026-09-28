---
id: 20260411-0841
title: Politica de dados 59
area: Trabalho
type: nota
tags: [trabalho, politica, cliente-acme]
status: ativo
created: 2026-04-11 08:41
updated: 2026-04-25 08:44
---

## Decisao

This is a documentation note, not a runbook; keep the steps elsewhere. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Contexto

Em teste local o ganho apareceu principalmente nas consultas curtas. Vale revisitar isso quando o volume de notas dobrar. Registro importante: o modelo local padrao para esse passo e phi4-mini:3.8b-q30, rodando via Ollama. Em teste local o ganho apareceu principalmente nas consultas curtas. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Aberto

Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[kraken-licencas-das-dependencias-07]] [[vortex-fluxo-de-consulta-02]] [[planejamento-trimestral-004]] [[sanitizacao-de-markdown-058]]
