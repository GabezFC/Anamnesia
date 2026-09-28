---
id: 20261114-1230
title: Vortex — Vault watcher 06
area: Projetos
type: nota
tags: [vortex, componentes, vault]
status: ativo
created: 2026-11-14 12:30
updated: 2026-11-20 19:08
projeto: vortex
---

## Alternativas

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O comportamento so aparece quando o cache esta frio. The retrieval layer keeps a small LRU in front of the vector index. A ideia central e reduzir o custo de contexto sem perder recall.

## Detalhes tecnicos

A decisao foi tomada depois de comparar tres alternativas equivalentes. A ideia central e reduzir o custo de contexto sem perder recall. Registro importante: o snapshot foi validado contra KrampusDB v8.132-rc0 em ambiente isolado. Vale revisitar isso quando o volume de notas dobrar. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Aberto

Deduplication happens before rerank, otherwise near-duplicates flood the top. Fica registrado para nao repetir a investigacao daqui a seis meses. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[parser-de-frontmatter-019]]
