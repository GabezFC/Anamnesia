---
id: 20261030-1315
title: Vortex — Subir o ambiente 01
area: Projetos
type: nota
tags: [vortex, procedimentos, subir]
status: ativo
created: 2026-10-30 13:15
updated: 2026-11-14 18:59
projeto: vortex
---

## Implementacao

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Ajuste na revisao: o paragrafo foi reescrito nesta versao do documento. O comportamento so aparece quando o cache esta frio.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Proximos passos

A causa raiz estava na normalizacao dos acentos antes da busca. A ideia central e reduzir o custo de contexto sem perder recall. Vale revisitar isso quando o volume de notas dobrar.

## Riscos

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Em teste local o ganho apareceu principalmente nas consultas curtas. The retrieval layer keeps a small LRU in front of the vector index.

## Como reproduzir

O comportamento so aparece quando o cache esta frio. Deduplication happens before rerank, otherwise near-duplicates flood the top. A causa raiz estava na normalizacao dos acentos antes da busca. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Medicoes

Vale revisitar isso quando o volume de notas dobrar. The retrieval layer keeps a small LRU in front of the vector index. Vale revisitar isso quando o volume de notas dobrar. A ideia central e reduzir o custo de contexto sem perder recall.

## Resumo

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. This is a documentation note, not a runbook; keep the steps elsewhere.

Relacionadas: [[2026-02-05]] [[inbox-pergunta-para-investigar-035]]
