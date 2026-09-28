---
id: 20260731-1708
title: Aurora — Publicar release 10
area: Projetos
type: nota
tags: [aurora, procedimentos, publicar]
status: ativo
created: 2026-07-31 17:08
updated: 2026-09-04 17:12
projeto: aurora
---

## Contexto

A ideia central e reduzir o custo de contexto sem perder recall. A causa raiz estava na normalizacao dos acentos antes da busca. We prefer explicit failure over silent degradation in the answer path. This is a documentation note, not a runbook; keep the steps elsewhere.

## Como reproduzir

Fica registrado para nao repetir a investigacao daqui a seis meses. Registro importante: ficou definido um timeout de 220ms no GrubnashProxy antes de cair para o fallback textual. O comportamento so aparece quando o cache esta frio. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Proximos passos

Em teste local o ganho apareceu principalmente nas consultas curtas. Deduplication happens before rerank, otherwise near-duplicates flood the top. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Riscos

Fica registrado para nao repetir a investigacao daqui a seis meses. Deduplication happens before rerank, otherwise near-duplicates flood the top. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[inbox-recorte-de-artigo-034]] [[kraken-decisao-estrategia-de-cache-09]] [[inbox-anotacao-de-podcast-015]] [[aurora-como-regerar-o-grafo-09]]
