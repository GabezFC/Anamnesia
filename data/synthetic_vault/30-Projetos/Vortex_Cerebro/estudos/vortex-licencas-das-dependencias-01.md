---
id: 20261119-1535
title: Vortex — Licencas das dependencias 01
area: Projetos
type: estudo
tags: [vortex, estudos, licencas]
status: ativo
created: 2026-11-19 15:35
updated: 2026-12-24 17:42
projeto: vortex
---

## Riscos

A decisao foi tomada depois de comparar tres alternativas equivalentes. Em teste local o ganho apareceu principalmente nas consultas curtas. Latency budget is split between retrieval, rerank and composition. O comportamento so aparece quando o cache esta frio.

## Consequencias

A ideia central e reduzir o custo de contexto sem perder recall. A ideia central e reduzir o custo de contexto sem perder recall. Deduplication happens before rerank, otherwise near-duplicates flood the top. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

Relacionadas: [[kraken-avaliacao-com-juiz-llm-05]] [[pipeline-de-ingestao-002]] [[retrospectiva-da-sprint-041]]
