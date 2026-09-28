---
id: 20260118-1730
title: Inbox: Recorte de artigo 16
area: Inbox
type: ideia
tags: [recorte, inbox, triagem]
status: inbox
created: 2026-01-18 17:30
updated: 2026-02-21 18:33
---

## Como reproduzir

O comportamento so aparece quando o cache esta frio. A causa raiz estava na normalizacao dos acentos antes da busca.

## Detalhes tecnicos

This is a documentation note, not a runbook; keep the steps elsewhere. Recall@5 is the primary metric; exact match is only a sanity check. Deduplication happens before rerank, otherwise near-duplicates flood the top. Latency budget is split between retrieval, rerank and composition.

Relacionadas: [[estudo-grafos-de-conhecimento-002]]
