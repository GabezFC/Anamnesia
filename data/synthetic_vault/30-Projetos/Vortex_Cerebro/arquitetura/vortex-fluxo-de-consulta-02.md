---
id: 20261011-1132
title: Vortex — Fluxo de consulta 02
area: Projetos
type: nota
tags: [vortex, arquitetura, fluxo]
status: ativo
created: 2026-10-11 11:32
updated: 2026-11-06 17:12
projeto: vortex
---

## Notes

O comportamento so aparece quando o cache esta frio. This is a documentation note, not a runbook; keep the steps elsewhere.

## Contexto

This is a documentation note, not a runbook; keep the steps elsewhere. Registro importante: ficou definido um timeout de 122ms no JorbistanProxy antes de cair para o fallback textual. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. This is a documentation note, not a runbook; keep the steps elsewhere.

## Resumo

A causa raiz estava na normalizacao dos acentos antes da busca. The retrieval layer keeps a small LRU in front of the vector index.

## Alternativas

The retrieval layer keeps a small LRU in front of the vector index. Vale revisitar isso quando o volume de notas dobrar. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Proximos passos

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. We prefer explicit failure over silent degradation in the answer path.

## Como reproduzir

A ideia central e reduzir o custo de contexto sem perder recall. Fica registrado para nao repetir a investigacao daqui a seis meses. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[reranker-local-023]] [[estudo-estatistica-bayesiana-006]]
