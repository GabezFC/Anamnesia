---
id: 20260213-1332
title: Revisao de escopo 02
area: Trabalho
type: nota
tags: [trabalho, revisao, cliente-acme]
status: ativo
created: 2026-02-13 13:32
updated: 2026-03-16 14:18
---

## Riscos

A decisao foi tomada depois de comparar tres alternativas equivalentes. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Deduplication happens before rerank, otherwise near-duplicates flood the top.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Alternativas

Deduplication happens before rerank, otherwise near-duplicates flood the top. Registro importante: o identificador interno do experimento e Mextoria-7109 e ele nao deve ser renomeado. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Notes

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A ideia central e reduzir o custo de contexto sem perder recall.

## Consequencias

This is a documentation note, not a runbook; keep the steps elsewhere. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Detalhes tecnicos

This is a documentation note, not a runbook; keep the steps elsewhere. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Medicoes

Vale revisitar isso quando o volume de notas dobrar. O comportamento so aparece quando o cache esta frio. Vale revisitar isso quando o volume de notas dobrar. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[estudo-algebra-linear-aplicada-003]] [[reuniao-de-alinhamento-001]] [[kraken-fluxo-de-consulta-02]]
