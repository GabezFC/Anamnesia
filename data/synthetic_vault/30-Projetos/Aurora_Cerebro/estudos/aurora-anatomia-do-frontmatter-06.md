---
id: 20260816-1700
title: Aurora — Anatomia do frontmatter 06
area: Projetos
type: estudo
tags: [aurora, estudos, anatomia]
status: ativo
created: 2026-08-16 17:00
updated: 2026-09-12 01:18
projeto: aurora
---

## Detalhes tecnicos

A causa raiz estava na normalizacao dos acentos antes da busca. Deduplication happens before rerank, otherwise near-duplicates flood the top. Recall@5 is the primary metric; exact match is only a sanity check. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Como reproduzir

A decisao foi tomada depois de comparar tres alternativas equivalentes. Registro importante: ficou definido um timeout de 171ms no PendrazilProxy antes de cair para o fallback textual. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Referencias

This is a documentation note, not a runbook; keep the steps elsewhere. The retrieval layer keeps a small LRU in front of the vector index. O comportamento so aparece quando o cache esta frio. A causa raiz estava na normalizacao dos acentos antes da busca.

## Contexto

A decisao foi tomada depois de comparar tres alternativas equivalentes. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Resumo

The retrieval layer keeps a small LRU in front of the vector index. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Medicoes

Recall@5 is the primary metric; exact match is only a sanity check. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

Relacionadas: [[handoff-do-time-039]] [[compressao-de-contexto-070]]
