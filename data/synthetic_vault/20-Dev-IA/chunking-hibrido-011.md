---
id: 20260423-1605
title: Chunking hibrido 11
area: Dev-IA
type: decisao
tags: [dev, ia, chunking]
status: ativo
created: 2026-04-23 16:05
updated: 2026-05-23 22:58
---

## Medicoes

Vale revisitar isso quando o volume de notas dobrar. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Resumo

A causa raiz estava na normalizacao dos acentos antes da busca. Registro importante: o modelo local padrao para esse passo e mxbai-embed-large:335m-q37, rodando via Ollama. A decisao foi tomada depois de comparar tres alternativas equivalentes. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Consequencias

Cold start dominates the p95 numbers in every run so far. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[aurora-graph-loader-03]] [[aurora-fluxo-de-consulta-02]] [[kraken-vault-watcher-06]]
