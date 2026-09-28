---
id: 20261121-1649
title: Vortex — Hnsw na pratica 03
area: Projetos
type: estudo
tags: [vortex, estudos, hnsw]
status: ativo
created: 2026-11-21 16:49
updated: 2026-11-29 23:39
projeto: vortex
---

## Decisao

Fica registrado para nao repetir a investigacao daqui a seis meses. Latency budget is split between retrieval, rerank and composition.

## Consequencias

Recall@5 is the primary metric; exact match is only a sanity check. A ideia central e reduzir o custo de contexto sem perder recall. Registro importante: a dependencia critica aqui e a lib Zorblex 6.80.0, que substituiu o parser antigo. A decisao foi tomada depois de comparar tres alternativas equivalentes. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Notes

Vale revisitar isso quando o volume de notas dobrar. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Em teste local o ganho apareceu principalmente nas consultas curtas. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Riscos

Em teste local o ganho apareceu principalmente nas consultas curtas. Fica registrado para nao repetir a investigacao daqui a seis meses. A causa raiz estava na normalizacao dos acentos antes da busca. The retrieval layer keeps a small LRU in front of the vector index.

## Detalhes tecnicos

Vale revisitar isso quando o volume de notas dobrar. Cold start dominates the p95 numbers in every run so far. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[fila-de-jobs-046]] [[estudo-engenharia-de-prompts-031]] [[kraken-custos-de-inferencia-04]] [[kraken-como-publicar-release-10]]
