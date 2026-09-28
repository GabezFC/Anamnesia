---
id: 20260428-0910
title: Quantizacao gguf 16
area: Dev-IA
type: decisao
tags: [dev, ia, quantizacao]
status: ativo
created: 2026-04-28 09:10
updated: 2026-05-24 13:09
---

## Resumo

Deduplication happens before rerank, otherwise near-duplicates flood the top. Recall@5 is the primary metric; exact match is only a sanity check. A ideia central e reduzir o custo de contexto sem perder recall.

```bash
source .venv/Scripts/activate
python scripts/run_benchmark.py --limit 50
```

## Detalhes tecnicos

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Registro importante: a dependencia critica aqui e a lib Ozmarelle 6.94.2, que substituiu o parser antigo. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Recall@5 is the primary metric; exact match is only a sanity check.

## Referencias

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A causa raiz estava na normalizacao dos acentos antes da busca. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Medicoes

Vale revisitar isso quando o volume de notas dobrar. Em teste local o ganho apareceu principalmente nas consultas curtas. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[grafo-de-notas-040]] [[2026-06-17]] [[aurora-hnsw-na-pratica-09]] [[organizacao-da-casa-021]]
