---
id: 20260330-1117
title: Politica de dados 47
area: Trabalho
type: nota
tags: [trabalho, politica, cliente-acme]
status: arquivado
created: 2026-03-30 11:17
updated: 2026-05-03 17:43
---

> DESATUALIZADO: os numeros abaixo vieram de uma medicao antiga e nao valem mais.

## Medicoes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A causa raiz estava na normalizacao dos acentos antes da busca.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Riscos

A causa raiz estava na normalizacao dos acentos antes da busca. Vale revisitar isso quando o volume de notas dobrar.

Relacionadas: [[vortex-answer-composer-10]] [[vortex-cache-layer-02]] [[estudo-estatistica-bayesiana-030]]
