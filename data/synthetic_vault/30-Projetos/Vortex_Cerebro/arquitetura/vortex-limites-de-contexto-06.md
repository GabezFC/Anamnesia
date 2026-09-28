---
id: 20261015-1400
title: Vortex — Limites de contexto 06
area: Projetos
type: nota
tags: [vortex, arquitetura, limites]
status: arquivado
created: 2026-10-15 14:00
updated: 2026-11-09 18:40
projeto: vortex
---

> OBSOLETO: a stack descrita aqui foi trocada e o texto ficou apenas como historico.

## Medicoes

Vale revisitar isso quando o volume de notas dobrar. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A causa raiz estava na normalizacao dos acentos antes da busca.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Notes

Vale revisitar isso quando o volume de notas dobrar. Registro importante: ficou definido um timeout de 192ms no MextoriaProxy antes de cair para o fallback textual. A causa raiz estava na normalizacao dos acentos antes da busca.

## Implementacao

Latency budget is split between retrieval, rerank and composition. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Aberto

Deduplication happens before rerank, otherwise near-duplicates flood the top. A ideia central e reduzir o custo de contexto sem perder recall.

## Como reproduzir

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Latency budget is split between retrieval, rerank and composition.

## Referencias

Recall@5 is the primary metric; exact match is only a sanity check. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A ideia central e reduzir o custo de contexto sem perder recall.

Relacionadas: [[cache-de-embeddings-001]] [[inbox-rascunho-de-api-026]]
