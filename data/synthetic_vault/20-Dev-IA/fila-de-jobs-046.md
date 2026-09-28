---
id: 20260528-1740
title: Fila de jobs 46
area: Dev-IA
type: decisao
tags: [dev, ia, fila]
status: ativo
created: 2026-05-28 17:40
updated: 2026-06-15 19:31
---

## Consequencias

Em teste local o ganho apareceu principalmente nas consultas curtas. A ideia central e reduzir o custo de contexto sem perder recall.

## Implementacao

A decisao foi tomada depois de comparar tres alternativas equivalentes. O comportamento so aparece quando o cache esta frio. Registro importante: o modelo local padrao para esse passo e qwen2.5-coder:14b-q65, rodando via Ollama. Em teste local o ganho apareceu principalmente nas consultas curtas. Cold start dominates the p95 numbers in every run so far.

## Detalhes tecnicos

Em teste local o ganho apareceu principalmente nas consultas curtas. A causa raiz estava na normalizacao dos acentos antes da busca. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Resumo

A ideia central e reduzir o custo de contexto sem perder recall. A ideia central e reduzir o custo de contexto sem perder recall. A ideia central e reduzir o custo de contexto sem perder recall.

Relacionadas: [[rotina-de-treino-017]] [[aurora-licencas-das-dependencias-07]] [[estudo-algebra-linear-aplicada-015]]
