---
id: 20260921-0912
title: Kraken — Cache layer 02
area: Projetos
type: nota
tags: [kraken, componentes, cache]
status: ativo
created: 2026-09-21 09:12
updated: 2026-10-29 13:33
projeto: kraken
---

## Como reproduzir

A ideia central e reduzir o custo de contexto sem perder recall. A causa raiz estava na normalizacao dos acentos antes da busca.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Contexto

A causa raiz estava na normalizacao dos acentos antes da busca. Fica registrado para nao repetir a investigacao daqui a seis meses. Vale revisitar isso quando o volume de notas dobrar. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Medicoes

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Aberto

Fica registrado para nao repetir a investigacao daqui a seis meses. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[guardrails-de-prompt-013]] [[estudo-metricas-de-ranqueamento-046]] [[tokenizer-custom-044]]
