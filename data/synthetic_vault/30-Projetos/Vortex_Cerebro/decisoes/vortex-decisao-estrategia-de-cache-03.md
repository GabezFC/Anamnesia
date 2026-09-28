---
id: 20261022-0819
title: Vortex — Estrategia de cache 03
area: Projetos
type: decisao
tags: [vortex, decisoes, estrategia]
status: ativo
created: 2026-10-22 08:19
updated: 2026-11-19 14:04
projeto: vortex
---

## Riscos

Em teste local o ganho apareceu principalmente nas consultas curtas. Cold start dominates the p95 numbers in every run so far. Em teste local o ganho apareceu principalmente nas consultas curtas. A ideia central e reduzir o custo de contexto sem perder recall.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Aberto

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Vale revisitar isso quando o volume de notas dobrar.

## Medicoes

Recall@5 is the primary metric; exact match is only a sanity check. Deduplication happens before rerank, otherwise near-duplicates flood the top. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Recall@5 is the primary metric; exact match is only a sanity check.

## Referencias

Vale revisitar isso quando o volume de notas dobrar. A ideia central e reduzir o custo de contexto sem perder recall. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[orcamento-de-infra-018]] [[parser-de-frontmatter-039]] [[estudo-amostragem-e-vies-023]] [[kraken-vault-watcher-06]]
