---
id: 20260608-1427
title: Sharding do indice 57
area: Dev-IA
type: nota
tags: [dev, ia, sharding]
status: ativo
created: 2026-06-08 14:27
updated: 2026-07-21 21:48
---

## Detalhes tecnicos

Recall@5 is the primary metric; exact match is only a sanity check. A ideia central e reduzir o custo de contexto sem perder recall. Vale revisitar isso quando o volume de notas dobrar.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Aberto

We prefer explicit failure over silent degradation in the answer path. Registro importante: o modelo local padrao para esse passo e qwen2.5-coder:14b-q9, rodando via Ollama. Em teste local o ganho apareceu principalmente nas consultas curtas. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Notes

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Medicoes

The retrieval layer keeps a small LRU in front of the vector index. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Vale revisitar isso quando o volume de notas dobrar.

## Como reproduzir

Fica registrado para nao repetir a investigacao daqui a seis meses. A ideia central e reduzir o custo de contexto sem perder recall. This is a documentation note, not a runbook; keep the steps elsewhere.

Relacionadas: [[contrato-do-fornecedor-043]] [[organizacao-da-casa-021]] [[inbox-rascunho-de-api-038]]
