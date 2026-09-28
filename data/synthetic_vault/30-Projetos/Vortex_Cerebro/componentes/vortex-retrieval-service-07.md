---
id: 20261115-1307
title: Vortex — Retrieval service 07
area: Projetos
type: nota
tags: [vortex, componentes, retrieval]
status: ativo
created: 2026-11-15 13:07
updated: 2026-12-12 14:59
projeto: vortex
---

## Proximos passos

The retrieval layer keeps a small LRU in front of the vector index. Cold start dominates the p95 numbers in every run so far. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Notes

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Registro importante: o modelo local padrao para esse passo e mxbai-embed-large:335m-q93, rodando via Ollama. O comportamento so aparece quando o cache esta frio. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[batch-de-inferencia-035]] [[retrospectiva-da-sprint-005]] [[2026-05-12]] [[contrato-do-fornecedor-031]]
