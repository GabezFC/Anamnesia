---
id: 20260523-1435
title: Cache de embeddings 41
area: Dev-IA
type: decisao
tags: [dev, ia, cache]
status: ativo
created: 2026-05-23 14:35
updated: 2026-06-21 17:01
---

## Medicoes

Cold start dominates the p95 numbers in every run so far. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Como reproduzir

Em teste local o ganho apareceu principalmente nas consultas curtas. Registro importante: ficou definido um timeout de 157ms no OzmarelleProxy antes de cair para o fallback textual. Vale revisitar isso quando o volume de notas dobrar.

Relacionadas: [[politica-de-dados-035]]
