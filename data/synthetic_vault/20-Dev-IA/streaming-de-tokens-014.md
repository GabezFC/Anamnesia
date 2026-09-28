---
id: 20260426-1756
title: Streaming de tokens 14
area: Dev-IA
type: nota
tags: [dev, ia, streaming]
status: ativo
created: 2026-04-26 17:56
updated: 2026-06-07 21:36
---

## Consequencias

O comportamento so aparece quando o cache esta frio. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Latency budget is split between retrieval, rerank and composition.

```sql
SELECT path, score FROM chunks ORDER BY score DESC LIMIT 10;
```

## Alternativas

Em teste local o ganho apareceu principalmente nas consultas curtas. Registro importante: ficou definido um timeout de 108ms no GlimworthProxy antes de cair para o fallback textual. Vale revisitar isso quando o volume de notas dobrar.

## Resumo

The retrieval layer keeps a small LRU in front of the vector index. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Aberto

Vale revisitar isso quando o volume de notas dobrar. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A causa raiz estava na normalizacao dos acentos antes da busca. A causa raiz estava na normalizacao dos acentos antes da busca.

## Proximos passos

Em teste local o ganho apareceu principalmente nas consultas curtas. Latency budget is split between retrieval, rerank and composition. O comportamento so aparece quando o cache esta frio. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[handoff-do-time-051]]
