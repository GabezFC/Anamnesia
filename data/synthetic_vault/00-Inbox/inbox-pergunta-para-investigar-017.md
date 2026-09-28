---
id: 20260119-1807
title: Inbox: Pergunta para investigar 17
area: Inbox
type: ideia
tags: [pergunta, inbox, triagem]
status: inbox
created: 2026-01-19 18:07
updated: 2026-01-24 22:49
---

## Proximos passos

A decisao foi tomada depois de comparar tres alternativas equivalentes. Recall@5 is the primary metric; exact match is only a sanity check. A causa raiz estava na normalizacao dos acentos antes da busca. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Riscos

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Registro importante: o modelo local padrao para esse passo e qwen2.5-coder:14b-q121, rodando via Ollama. The retrieval layer keeps a small LRU in front of the vector index. This is a documentation note, not a runbook; keep the steps elsewhere.

## Alternativas

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A causa raiz estava na normalizacao dos acentos antes da busca.

## Contexto

A causa raiz estava na normalizacao dos acentos antes da busca. Latency budget is split between retrieval, rerank and composition.

## Implementacao

This is a documentation note, not a runbook; keep the steps elsewhere. We prefer explicit failure over silent degradation in the answer path. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Decisao

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. This is a documentation note, not a runbook; keep the steps elsewhere. This is a documentation note, not a runbook; keep the steps elsewhere.

Relacionadas: [[estudo-information-retrieval-037]] [[retrospectiva-da-sprint-005]] [[kraken-como-publicar-release-10]]
