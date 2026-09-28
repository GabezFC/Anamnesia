---
id: 20260210-1141
title: Inbox: Anotacao de podcast 39
area: Inbox
type: ideia
tags: [anotacao, inbox, triagem]
status: inbox
created: 2026-02-10 11:41
updated: 2026-03-19 15:20
---

## Medicoes

A decisao foi tomada depois de comparar tres alternativas equivalentes. Cold start dominates the p95 numbers in every run so far. Vale revisitar isso quando o volume de notas dobrar. O comportamento so aparece quando o cache esta frio.

## Como reproduzir

A decisao foi tomada depois de comparar tres alternativas equivalentes. Registro importante: o modelo local padrao para esse passo e llama3.2-vision:11b-q114, rodando via Ollama. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Decisao

The retrieval layer keeps a small LRU in front of the vector index. Recall@5 is the primary metric; exact match is only a sanity check. A ideia central e reduzir o custo de contexto sem perder recall. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[kraken-licencas-das-dependencias-07]] [[aurora-como-regerar-o-grafo-03]]
