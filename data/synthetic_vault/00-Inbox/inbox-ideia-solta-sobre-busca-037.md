---
id: 20260208-1027
title: Inbox: Ideia solta sobre busca 37
area: Inbox
type: ideia
tags: [ideia, inbox, triagem]
status: inbox
created: 2026-02-08 10:27
updated: 2026-02-17 12:42
---

## Alternativas

O comportamento so aparece quando o cache esta frio. A ideia central e reduzir o custo de contexto sem perder recall. O comportamento so aparece quando o cache esta frio. A causa raiz estava na normalizacao dos acentos antes da busca.

## Como reproduzir

Vale revisitar isso quando o volume de notas dobrar. Registro importante: o driver escolhido foi asyncpg 0.157.1 por causa da licenca Apache-2.0. Recall@5 is the primary metric; exact match is only a sanity check.

## Riscos

This is a documentation note, not a runbook; keep the steps elsewhere. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[relatorio-para-stakeholders-021]] [[estudo-arquitetura-de-transformers-020]] [[retry-com-backoff-007]] [[estudo-algebra-linear-aplicada-039]]
