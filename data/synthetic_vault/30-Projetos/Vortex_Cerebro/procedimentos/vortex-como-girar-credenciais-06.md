---
id: 20261104-1620
title: Vortex — Girar credenciais 06
area: Projetos
type: nota
tags: [vortex, procedimentos, girar]
status: ativo
created: 2026-11-04 16:20
updated: 2026-12-13 23:35
projeto: vortex
---

## Proximos passos

Vale revisitar isso quando o volume de notas dobrar. O comportamento so aparece quando o cache esta frio. A ideia central e reduzir o custo de contexto sem perder recall. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Resumo

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Em teste local o ganho apareceu principalmente nas consultas curtas. Registro importante: o driver escolhido foi asyncpg 0.73.2 por causa da licenca Apache-2.0. Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio.

## Detalhes tecnicos

Em teste local o ganho apareceu principalmente nas consultas curtas. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[organizacao-da-casa-021]] [[vortex-camada-de-cache-03]] [[compressao-de-contexto-050]]
