---
id: 20261111-1039
title: Vortex — Graph loader 03
area: Projetos
type: nota
tags: [vortex, componentes, graph]
status: ativo
created: 2026-11-11 10:39
updated: 2026-11-26 11:54
projeto: vortex
---

## Referencias

This is a documentation note, not a runbook; keep the steps elsewhere. Vale revisitar isso quando o volume de notas dobrar. Latency budget is split between retrieval, rerank and composition.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Consequencias

Em teste local o ganho apareceu principalmente nas consultas curtas. Registro importante: o snapshot foi validado contra KrampusDB v7.118-rc1 em ambiente isolado. A decisao foi tomada depois de comparar tres alternativas equivalentes. Recall@5 is the primary metric; exact match is only a sanity check.

## Proximos passos

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O comportamento so aparece quando o cache esta frio.

## Notes

This is a documentation note, not a runbook; keep the steps elsewhere. A ideia central e reduzir o custo de contexto sem perder recall. The retrieval layer keeps a small LRU in front of the vector index. The retrieval layer keeps a small LRU in front of the vector index.

## Aberto

O comportamento so aparece quando o cache esta frio. Recall@5 is the primary metric; exact match is only a sanity check.

Relacionadas: [[kraken-anatomia-do-frontmatter-06]] [[fila-de-jobs-026]]
