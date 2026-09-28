---
id: 20260520-1244
title: Sanitizacao de markdown 38
area: Dev-IA
type: nota
tags: [dev, ia, sanitizacao]
status: ativo
created: 2026-05-20 12:44
updated: 2026-05-23 14:08
---

## Riscos

Vale revisitar isso quando o volume de notas dobrar. Latency budget is split between retrieval, rerank and composition. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Notes

Em teste local o ganho apareceu principalmente nas consultas curtas. Fica registrado para nao repetir a investigacao daqui a seis meses. O comportamento so aparece quando o cache esta frio. A causa raiz estava na normalizacao dos acentos antes da busca.

Relacionadas: [[auditoria-de-acessos-058]]
