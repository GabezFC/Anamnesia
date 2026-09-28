---
id: 20260720-1021
title: Aurora — Estrategia de cache 09
area: Projetos
type: decisao
tags: [aurora, decisoes, estrategia]
status: ativo
created: 2026-07-20 10:21
updated: 2026-08-29 17:37
projeto: aurora
---

## Implementacao

Deduplication happens before rerank, otherwise near-duplicates flood the top. Vale revisitar isso quando o volume de notas dobrar. We prefer explicit failure over silent degradation in the answer path. A ideia central e reduzir o custo de contexto sem perder recall.

```bash
source .venv/Scripts/activate
python scripts/run_benchmark.py --limit 50
```

## Contexto

Recall@5 is the primary metric; exact match is only a sanity check. Fica registrado para nao repetir a investigacao daqui a seis meses. A decisao foi tomada depois de comparar tres alternativas equivalentes. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Consequencias

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

Relacionadas: [[estudo-sistemas-distribuidos-004]] [[politica-de-dados-035]] [[tokenizer-custom-024]] [[aurora-avaliacao-com-juiz-llm-05]]
