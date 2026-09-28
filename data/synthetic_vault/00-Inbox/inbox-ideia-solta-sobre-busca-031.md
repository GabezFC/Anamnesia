---
id: 20260202-1645
title: Inbox: Ideia solta sobre busca 31
area: Inbox
type: nota
tags: [ideia, inbox, triagem]
status: inbox
created: 2026-02-02 16:45
updated: 2026-03-17 19:31
---

## Resumo

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Deduplication happens before rerank, otherwise near-duplicates flood the top.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Detalhes tecnicos

A causa raiz estava na normalizacao dos acentos antes da busca. A ideia central e reduzir o custo de contexto sem perder recall. Registro importante: o snapshot foi validado contra KrampusDB v7.104-rc2 em ambiente isolado. Em teste local o ganho apareceu principalmente nas consultas curtas. A causa raiz estava na normalizacao dos acentos antes da busca.

## Referencias

A decisao foi tomada depois de comparar tres alternativas equivalentes. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Como reproduzir

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Recall@5 is the primary metric; exact match is only a sanity check. A causa raiz estava na normalizacao dos acentos antes da busca.

## Riscos

This is a documentation note, not a runbook; keep the steps elsewhere. This is a documentation note, not a runbook; keep the steps elsewhere. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Implementacao

Fica registrado para nao repetir a investigacao daqui a seis meses. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Recall@5 is the primary metric; exact match is only a sanity check. Latency budget is split between retrieval, rerank and composition.

Relacionadas: [[estudo-metricas-de-ranqueamento-034]] [[vortex-integracao-com-o-vault-10]] [[batch-de-inferencia-055]] [[kraken-decisao-politica-de-retries-05]]
