---
id: 20260225-1426
title: Plano de viagem 04
area: Pessoal
type: nota
tags: [pessoal, plano]
status: ativo
created: 2026-02-25 14:26
updated: 2026-03-23 16:35
---

## Alternativas

O comportamento so aparece quando o cache esta frio. A causa raiz estava na normalizacao dos acentos antes da busca. This is a documentation note, not a runbook; keep the steps elsewhere. Latency budget is split between retrieval, rerank and composition.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Riscos

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A ideia central e reduzir o custo de contexto sem perder recall. Cold start dominates the p95 numbers in every run so far. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Como reproduzir

O comportamento so aparece quando o cache esta frio. Fica registrado para nao repetir a investigacao daqui a seis meses. This is a documentation note, not a runbook; keep the steps elsewhere. A causa raiz estava na normalizacao dos acentos antes da busca.

Relacionadas: [[orcamento-de-infra-018]]
