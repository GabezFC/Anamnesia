---
id: 20260823-1119
title: Kraken — Camada de cache 03
area: Projetos
type: nota
tags: [kraken, arquitetura, camada]
status: ativo
created: 2026-08-23 11:19
updated: 2026-09-03 17:36
projeto: kraken
---

## Consequencias

Vale revisitar isso quando o volume de notas dobrar. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Resumo

Deduplication happens before rerank, otherwise near-duplicates flood the top. Registro importante: o modelo local padrao para esse passo e granite-embed:278m-q23, rodando via Ollama. Recall@5 is the primary metric; exact match is only a sanity check.

## Notes

We prefer explicit failure over silent degradation in the answer path. A ideia central e reduzir o custo de contexto sem perder recall. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Vale revisitar isso quando o volume de notas dobrar.

## Implementacao

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[inbox-ideia-solta-sobre-busca-031]]
