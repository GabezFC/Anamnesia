---
id: 20260425-1719
title: Guardrails de prompt 13
area: Dev-IA
type: nota
tags: [dev, ia, guardrails]
status: ativo
created: 2026-04-25 17:19
updated: 2026-05-01 18:08
---

## Alternativas

Em teste local o ganho apareceu principalmente nas consultas curtas. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Recall@5 is the primary metric; exact match is only a sanity check.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Contexto

Recall@5 is the primary metric; exact match is only a sanity check. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Riscos

Vale revisitar isso quando o volume de notas dobrar. Vale revisitar isso quando o volume de notas dobrar. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Notes

Em teste local o ganho apareceu principalmente nas consultas curtas. A decisao foi tomada depois de comparar tres alternativas equivalentes. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Proximos passos

A causa raiz estava na normalizacao dos acentos antes da busca. A causa raiz estava na normalizacao dos acentos antes da busca. Cold start dominates the p95 numbers in every run so far.

## Resumo

Cold start dominates the p95 numbers in every run so far. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

Relacionadas: [[kraken-como-regerar-o-grafo-09]]
