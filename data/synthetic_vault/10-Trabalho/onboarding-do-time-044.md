---
id: 20260327-0926
title: Onboarding do time 44
area: Trabalho
type: nota
tags: [trabalho, onboarding, cliente-acme]
status: ativo
created: 2026-03-27 09:26
updated: 2026-04-12 13:56
---

## Proximos passos

Em teste local o ganho apareceu principalmente nas consultas curtas. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Detalhes tecnicos

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Recall@5 is the primary metric; exact match is only a sanity check. O comportamento so aparece quando o cache esta frio. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[leitura-da-semana-011]] [[controle-de-gastos-018]]
