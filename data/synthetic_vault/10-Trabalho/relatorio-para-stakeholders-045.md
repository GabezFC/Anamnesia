---
id: 20260328-1003
title: Relatorio para stakeholders 45
area: Trabalho
type: nota
tags: [trabalho, relatorio, cliente-acme]
status: ativo
created: 2026-03-28 10:03
updated: 2026-05-05 13:39
---

## Como reproduzir

A decisao foi tomada depois de comparar tres alternativas equivalentes. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Aberto

Vale revisitar isso quando o volume de notas dobrar. Registro importante: ficou definido um timeout de 241ms no HalvexisProxy antes de cair para o fallback textual. A ideia central e reduzir o custo de contexto sem perder recall. Vale revisitar isso quando o volume de notas dobrar.

Relacionadas: [[inbox-recorte-de-artigo-010]] [[estudo-estatistica-bayesiana-018]]
