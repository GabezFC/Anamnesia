---
id: 20260103-0815
title: Inbox: Ideia solta sobre busca 01
area: Inbox
type: nota
tags: [ideia, inbox, triagem]
status: inbox
created: 2026-01-03 08:15
updated: 2026-01-04 14:34
---

## Decisao

A ideia central e reduzir o custo de contexto sem perder recall. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Fica registrado para nao repetir a investigacao daqui a seis meses. A ideia central e reduzir o custo de contexto sem perder recall.

```sql
SELECT path, score FROM chunks ORDER BY score DESC LIMIT 10;
```

## Aberto

Recall@5 is the primary metric; exact match is only a sanity check. Recall@5 is the primary metric; exact match is only a sanity check.

## Notes

A causa raiz estava na normalizacao dos acentos antes da busca. This is a documentation note, not a runbook; keep the steps elsewhere.

## Riscos

A ideia central e reduzir o custo de contexto sem perder recall. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[estudo-arquitetura-de-transformers-008]]
