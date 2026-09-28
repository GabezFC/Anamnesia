---
id: 20260829-1501
title: Kraken — Camada de cache 09
area: Projetos
type: nota
tags: [kraken, arquitetura, camada]
status: ativo
created: 2026-08-29 15:01
updated: 2026-10-12 15:56
projeto: kraken
---

## Aberto

The retrieval layer keeps a small LRU in front of the vector index. We prefer explicit failure over silent degradation in the answer path. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Vale revisitar isso quando o volume de notas dobrar.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Implementacao

Fica registrado para nao repetir a investigacao daqui a seis meses. The retrieval layer keeps a small LRU in front of the vector index. Vale revisitar isso quando o volume de notas dobrar. The retrieval layer keeps a small LRU in front of the vector index.

## Consequencias

A ideia central e reduzir o custo de contexto sem perder recall. O comportamento so aparece quando o cache esta frio. Recall@5 is the primary metric; exact match is only a sanity check. Vale revisitar isso quando o volume de notas dobrar.

Relacionadas: [[2026-05-24]] [[aurora-como-publicar-release-10]] [[aurora-anatomia-do-frontmatter-06]]
