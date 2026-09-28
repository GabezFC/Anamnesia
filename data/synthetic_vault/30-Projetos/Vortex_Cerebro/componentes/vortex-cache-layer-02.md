---
id: 20261110-1002
title: Vortex — Cache layer 02
area: Projetos
type: nota
tags: [vortex, componentes, cache]
status: ativo
created: 2026-11-10 10:02
updated: 2026-12-11 13:26
projeto: vortex
---

## Referencias

Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A causa raiz estava na normalizacao dos acentos antes da busca.

```bash
source .venv/Scripts/activate
python scripts/run_benchmark.py --limit 50
```

## Riscos

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. The retrieval layer keeps a small LRU in front of the vector index.

## Implementacao

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. This is a documentation note, not a runbook; keep the steps elsewhere.

Relacionadas: [[kraken-anatomia-do-frontmatter-06]] [[estudo-amostragem-e-vies-047]] [[politica-de-dados-023]] [[2026-04-15]]
