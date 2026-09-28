---
id: 20260915-1530
title: Kraken — Girar credenciais 06
area: Projetos
type: nota
tags: [kraken, procedimentos, girar]
status: arquivado
created: 2026-09-15 15:30
updated: 2026-10-01 17:01
projeto: kraken
---

> DESATUALIZADO: os numeros abaixo vieram de uma medicao antiga e nao valem mais.

## Proximos passos

Em teste local o ganho apareceu principalmente nas consultas curtas. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Medicoes

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Detalhes tecnicos

Latency budget is split between retrieval, rerank and composition. A causa raiz estava na normalizacao dos acentos antes da busca.

Relacionadas: [[aurora-vault-watcher-06]]
