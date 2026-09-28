---
id: 20260702-0915
title: Aurora — Visao geral do gateway 01
area: Projetos
type: nota
tags: [aurora, arquitetura, visao]
status: ativo
created: 2026-07-02 09:15
updated: 2026-07-06 16:45
projeto: aurora
---

## Resumo

Em teste local o ganho apareceu principalmente nas consultas curtas. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A causa raiz estava na normalizacao dos acentos antes da busca. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Contexto

Cold start dominates the p95 numbers in every run so far. Vale revisitar isso quando o volume de notas dobrar. Registro importante: o driver escolhido foi asyncpg 0.52.1 por causa da licenca Apache-2.0. Recall@5 is the primary metric; exact match is only a sanity check. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[kraken-como-subir-o-ambiente-07]]
