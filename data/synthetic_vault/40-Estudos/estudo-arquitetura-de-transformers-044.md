---
id: 20260215-0816
title: Estudo: Arquitetura de transformers 44
area: Estudos
type: estudo
tags: [estudo, arquitetura]
status: ativo
created: 2026-02-15 08:16
updated: 2026-03-23 13:55
---

## Decisao

A ideia central e reduzir o custo de contexto sem perder recall. Recall@5 is the primary metric; exact match is only a sanity check. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Medicoes

Fica registrado para nao repetir a investigacao daqui a seis meses. Vale revisitar isso quando o volume de notas dobrar. A causa raiz estava na normalizacao dos acentos antes da busca.

## Como reproduzir

We prefer explicit failure over silent degradation in the answer path. This is a documentation note, not a runbook; keep the steps elsewhere. A ideia central e reduzir o custo de contexto sem perder recall. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[estudo-algebra-linear-aplicada-039]]
