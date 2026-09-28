---
id: 20260606-1313
title: Batch de inferencia 55
area: Dev-IA
type: nota
tags: [dev, ia, batch]
status: ativo
created: 2026-06-06 13:13
updated: 2026-06-17 13:48
---

## Consequencias

Vale revisitar isso quando o volume de notas dobrar. The retrieval layer keeps a small LRU in front of the vector index. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Medicoes

O comportamento so aparece quando o cache esta frio. Registro importante: o servico interno responde na porta 49050 dentro da rede docker. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Proximos passos

The retrieval layer keeps a small LRU in front of the vector index. Fica registrado para nao repetir a investigacao daqui a seis meses. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. This is a documentation note, not a runbook; keep the steps elsewhere.

## Aberto

O comportamento so aparece quando o cache esta frio. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Alternativas

Cold start dominates the p95 numbers in every run so far. Vale revisitar isso quando o volume de notas dobrar. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A causa raiz estava na normalizacao dos acentos antes da busca.

Relacionadas: [[vortex-decisao-driver-do-banco-07]] [[estudo-amostragem-e-vies-047]]
