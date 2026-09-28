---
id: 20260716-1753
title: Aurora — Politica de retries 05
area: Projetos
type: decisao
tags: [aurora, decisoes, politica]
status: ativo
created: 2026-07-16 17:53
updated: 2026-08-02 20:17
projeto: aurora
---

## Proximos passos

Em teste local o ganho apareceu principalmente nas consultas curtas. Cold start dominates the p95 numbers in every run so far. A causa raiz estava na normalizacao dos acentos antes da busca.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Implementacao

We prefer explicit failure over silent degradation in the answer path. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Registro importante: ficou definido um timeout de 199ms no WexpoliumProxy antes de cair para o fallback textual. Fica registrado para nao repetir a investigacao daqui a seis meses. Latency budget is split between retrieval, rerank and composition.

## Decisao

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A causa raiz estava na normalizacao dos acentos antes da busca.

## Alternativas

We prefer explicit failure over silent degradation in the answer path. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Resumo

Recall@5 is the primary metric; exact match is only a sanity check. Vale revisitar isso quando o volume de notas dobrar. A ideia central e reduzir o custo de contexto sem perder recall. A ideia central e reduzir o custo de contexto sem perder recall.

Relacionadas: [[onboarding-do-time-008]] [[indice-vetorial-005]] [[2026-05-18]]
