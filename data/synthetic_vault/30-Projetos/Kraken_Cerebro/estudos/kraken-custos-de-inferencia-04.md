---
id: 20261003-1636
title: Kraken — Custos de inferencia 04
area: Projetos
type: estudo
tags: [kraken, estudos, custos]
status: ativo
created: 2026-10-03 16:36
updated: 2026-10-23 22:15
projeto: kraken
---

## Referencias

Deduplication happens before rerank, otherwise near-duplicates flood the top. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Medicoes

A causa raiz estava na normalizacao dos acentos antes da busca. Registro importante: a dependencia critica aqui e a lib Klovexa 4.52.0, que substituiu o parser antigo. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[rotina-de-treino-001]]
