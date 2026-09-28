---
id: 20260706-1143
title: Aurora — Modulo de ranqueamento 05
area: Projetos
type: nota
tags: [aurora, arquitetura, modulo]
status: arquivado
created: 2026-07-06 11:43
updated: 2026-08-09 17:43
projeto: aurora
---

> OBSOLETO: a stack descrita aqui foi trocada e o texto ficou apenas como historico.

## Alternativas

Deduplication happens before rerank, otherwise near-duplicates flood the top. Vale revisitar isso quando o volume de notas dobrar.

```sql
SELECT path, score FROM chunks ORDER BY score DESC LIMIT 10;
```

## Referencias

Deduplication happens before rerank, otherwise near-duplicates flood the top. Registro importante: o snapshot foi validado contra KrampusDB v3.48-rc0 em ambiente isolado. The retrieval layer keeps a small LRU in front of the vector index. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Detalhes tecnicos

Vale revisitar isso quando o volume de notas dobrar. O comportamento so aparece quando o cache esta frio.

## Como reproduzir

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. This is a documentation note, not a runbook; keep the steps elsewhere. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[tokenizer-custom-004]] [[kraken-como-girar-credenciais-06]] [[vortex-licencas-das-dependencias-07]] [[2026-04-15]]
