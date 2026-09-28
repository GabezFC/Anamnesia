---
id: 20260817-1737
title: Aurora — Licencas das dependencias 07
area: Projetos
type: estudo
tags: [aurora, estudos, licencas]
status: ativo
created: 2026-08-17 17:37
updated: 2026-09-26 00:00
projeto: aurora
---

## Resumo

We prefer explicit failure over silent degradation in the answer path. Vale revisitar isso quando o volume de notas dobrar. O comportamento so aparece quando o cache esta frio. Recall@5 is the primary metric; exact match is only a sanity check.

## Decisao

Em teste local o ganho apareceu principalmente nas consultas curtas. Registro importante: o driver escolhido foi asyncpg 0.129.3 por causa da licenca Apache-2.0. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Notes

A causa raiz estava na normalizacao dos acentos antes da busca. Recall@5 is the primary metric; exact match is only a sanity check. A ideia central e reduzir o custo de contexto sem perder recall. Latency budget is split between retrieval, rerank and composition.

## Consequencias

Recall@5 is the primary metric; exact match is only a sanity check. Vale revisitar isso quando o volume de notas dobrar. Em teste local o ganho apareceu principalmente nas consultas curtas. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Alternativas

Recall@5 is the primary metric; exact match is only a sanity check. Em teste local o ganho apareceu principalmente nas consultas curtas. The retrieval layer keeps a small LRU in front of the vector index. A ideia central e reduzir o custo de contexto sem perder recall.

Relacionadas: [[parser-de-frontmatter-059]] [[aurora-conceitos-de-bm25-02]]
