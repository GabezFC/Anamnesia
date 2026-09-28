---
id: 20260125-1519
title: Estudo: Amostragem e vies 23
area: Estudos
type: estudo
tags: [estudo, amostragem]
status: ativo
created: 2026-01-25 15:19
updated: 2026-03-03 23:23
---

## Como reproduzir

A causa raiz estava na normalizacao dos acentos antes da busca. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Alternativas

Latency budget is split between retrieval, rerank and composition. Registro importante: a dependencia critica aqui e a lib Wexpolium 8.136.0, que substituiu o parser antigo. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Detalhes tecnicos

The retrieval layer keeps a small LRU in front of the vector index. We prefer explicit failure over silent degradation in the answer path. Vale revisitar isso quando o volume de notas dobrar.

## Implementacao

The retrieval layer keeps a small LRU in front of the vector index. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[2026-03-19]] [[leitura-da-semana-003]] [[pipeline-de-ingestao-062]]
