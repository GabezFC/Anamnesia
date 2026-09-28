---
id: 20261116-1344
title: Vortex — Cache layer 08
area: Projetos
type: nota
tags: [vortex, componentes, cache]
status: ativo
created: 2026-11-16 13:44
updated: 2026-11-27 20:35
projeto: vortex
---

## Contexto

This is a documentation note, not a runbook; keep the steps elsewhere. A ideia central e reduzir o custo de contexto sem perder recall. A causa raiz estava na normalizacao dos acentos antes da busca. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Notes

Fica registrado para nao repetir a investigacao daqui a seis meses. Registro importante: o identificador interno do experimento e Grubnash-7137 e ele nao deve ser renomeado. This is a documentation note, not a runbook; keep the steps elsewhere. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Decisao

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Cold start dominates the p95 numbers in every run so far.

## Riscos

The retrieval layer keeps a small LRU in front of the vector index. Fica registrado para nao repetir a investigacao daqui a seis meses. A decisao foi tomada depois de comparar tres alternativas equivalentes. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[auditoria-de-acessos-058]] [[2026-04-06]] [[vortex-limites-de-contexto-06]]
