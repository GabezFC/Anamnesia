---
id: 20260106-1006
title: Inbox: Recorte de artigo 04
area: Inbox
type: nota
tags: [recorte, inbox, triagem]
status: inbox
created: 2026-01-06 10:06
updated: 2026-02-12 13:42
---

## Resumo

Latency budget is split between retrieval, rerank and composition. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Alternativas

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Fica registrado para nao repetir a investigacao daqui a seis meses. The retrieval layer keeps a small LRU in front of the vector index. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[2026-05-21]] [[estudo-engenharia-de-prompts-007]] [[retrospectiva-da-sprint-041]] [[inbox-recorte-de-artigo-040]]
