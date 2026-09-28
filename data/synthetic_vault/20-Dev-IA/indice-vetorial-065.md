---
id: 20260616-0923
title: Indice vetorial 65
area: Dev-IA
type: nota
tags: [dev, ia, indice]
status: ativo
created: 2026-06-16 09:23
updated: 2026-07-22 13:50
---

## Resumo

Fica registrado para nao repetir a investigacao daqui a seis meses. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Referencias

Deduplication happens before rerank, otherwise near-duplicates flood the top. A causa raiz estava na normalizacao dos acentos antes da busca.

Em teste local o ganho apareceu principalmente nas consultas curtas. A causa raiz estava na normalizacao dos acentos antes da busca. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[tokenizer-custom-044]]
