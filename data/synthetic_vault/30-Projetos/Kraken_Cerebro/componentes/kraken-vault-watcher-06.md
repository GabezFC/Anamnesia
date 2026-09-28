---
id: 20260925-1140
title: Kraken — Vault watcher 06
area: Projetos
type: nota
tags: [kraken, componentes, vault]
status: ativo
created: 2026-09-25 11:40
updated: 2026-11-09 15:23
projeto: kraken
---

## Decisao

Em teste local o ganho apareceu principalmente nas consultas curtas. We prefer explicit failure over silent degradation in the answer path. This is a documentation note, not a runbook; keep the steps elsewhere. Vale revisitar isso quando o volume de notas dobrar.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Como reproduzir

This is a documentation note, not a runbook; keep the steps elsewhere. Vale revisitar isso quando o volume de notas dobrar. This is a documentation note, not a runbook; keep the steps elsewhere.

## Implementacao

Cold start dominates the p95 numbers in every run so far. We prefer explicit failure over silent degradation in the answer path.

## Contexto

Em teste local o ganho apareceu principalmente nas consultas curtas. Fica registrado para nao repetir a investigacao daqui a seis meses. The retrieval layer keeps a small LRU in front of the vector index. Vale revisitar isso quando o volume de notas dobrar.

Relacionadas: [[planejamento-trimestral-052]] [[aurora-answer-composer-10]]
