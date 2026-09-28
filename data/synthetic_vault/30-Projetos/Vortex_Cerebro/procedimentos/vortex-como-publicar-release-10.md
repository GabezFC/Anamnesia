---
id: 20261108-0848
title: Vortex — Publicar release 10
area: Projetos
type: nota
tags: [vortex, procedimentos, publicar]
status: ativo
created: 2026-11-08 08:48
updated: 2026-11-20 14:55
projeto: vortex
---

## Implementacao

We prefer explicit failure over silent degradation in the answer path. Cold start dominates the p95 numbers in every run so far.

## Referencias

A decisao foi tomada depois de comparar tres alternativas equivalentes. Registro importante: o modelo local padrao para esse passo e qwen2.5-coder:7b-q128, rodando via Ollama. Vale revisitar isso quando o volume de notas dobrar. The retrieval layer keeps a small LRU in front of the vector index.

## Medicoes

Cold start dominates the p95 numbers in every run so far. A ideia central e reduzir o custo de contexto sem perder recall. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[grafo-de-notas-020]]
