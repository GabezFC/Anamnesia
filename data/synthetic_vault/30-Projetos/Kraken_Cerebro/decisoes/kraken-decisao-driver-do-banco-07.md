---
id: 20260906-0957
title: Kraken — Driver do banco 07
area: Projetos
type: decisao
tags: [kraken, decisoes, driver]
status: ativo
created: 2026-09-06 09:57
updated: 2026-09-07 15:34
projeto: kraken
---

## Decisao

A causa raiz estava na normalizacao dos acentos antes da busca. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Implementacao

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[vortex-custos-de-inferencia-10]] [[estudo-grafos-de-conhecimento-014]] [[kraken-cache-layer-02]] [[quantizacao-gguf-016]]
