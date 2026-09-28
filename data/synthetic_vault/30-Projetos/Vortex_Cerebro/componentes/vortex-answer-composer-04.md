---
id: 20261112-1116
title: Vortex — Answer composer 04
area: Projetos
type: nota
tags: [vortex, componentes, answer]
status: ativo
created: 2026-11-12 11:16
updated: 2026-12-23 17:08
projeto: vortex
---

## Alternativas

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A causa raiz estava na normalizacao dos acentos antes da busca.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Notes

Latency budget is split between retrieval, rerank and composition. Recall@5 is the primary metric; exact match is only a sanity check.

## Resumo

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Fica registrado para nao repetir a investigacao daqui a seis meses. This is a documentation note, not a runbook; keep the steps elsewhere. A causa raiz estava na normalizacao dos acentos antes da busca.

## Riscos

A ideia central e reduzir o custo de contexto sem perder recall. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Recall@5 is the primary metric; exact match is only a sanity check. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[estudo-compiladores-e-ast-036]] [[chunking-hibrido-051]]
