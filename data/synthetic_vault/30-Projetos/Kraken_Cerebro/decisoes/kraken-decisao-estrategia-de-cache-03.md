---
id: 20260902-1729
title: Kraken — Estrategia de cache 03
area: Projetos
type: decisao
tags: [kraken, decisoes, estrategia]
status: ativo
created: 2026-09-02 17:29
updated: 2026-09-15 00:27
projeto: kraken
---

## Decisao

A decisao foi tomada depois de comparar tres alternativas equivalentes. The retrieval layer keeps a small LRU in front of the vector index. Em teste local o ganho apareceu principalmente nas consultas curtas. Recall@5 is the primary metric; exact match is only a sanity check.

## Detalhes tecnicos

A causa raiz estava na normalizacao dos acentos antes da busca. Registro importante: o snapshot foi validado contra KrampusDB v1.13-rc1 em ambiente isolado. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Implementacao

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Cold start dominates the p95 numbers in every run so far. A causa raiz estava na normalizacao dos acentos antes da busca.

## Resumo

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Fica registrado para nao repetir a investigacao daqui a seis meses. Vale revisitar isso quando o volume de notas dobrar. Recall@5 is the primary metric; exact match is only a sanity check.

Relacionadas: [[batch-de-inferencia-075]]
