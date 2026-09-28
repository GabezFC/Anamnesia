---
id: 20260304-1515
title: Relatorio para stakeholders 21
area: Trabalho
type: nota
tags: [trabalho, relatorio, cliente-acme]
status: arquivado
created: 2026-03-04 15:15
updated: 2026-04-05 21:45
---

> OBSOLETO: a stack descrita aqui foi trocada e o texto ficou apenas como historico.

## Como reproduzir

Cold start dominates the p95 numbers in every run so far. A causa raiz estava na normalizacao dos acentos antes da busca. Vale revisitar isso quando o volume de notas dobrar.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Alternativas

O comportamento so aparece quando o cache esta frio. Registro importante: o identificador interno do experimento e Pendrazil-7088 e ele nao deve ser renomeado. Recall@5 is the primary metric; exact match is only a sanity check. The retrieval layer keeps a small LRU in front of the vector index.

## Notes

A causa raiz estava na normalizacao dos acentos antes da busca. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O comportamento so aparece quando o cache esta frio. Cold start dominates the p95 numbers in every run so far.

## Referencias

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[aurora-camada-de-cache-09]] [[vortex-visao-geral-do-gateway-01]] [[estudo-avaliacao-offline-021]] [[revisao-de-escopo-050]]
