---
id: 20260309-0820
title: Revisao de escopo 26
area: Trabalho
type: nota
tags: [trabalho, revisao, cliente-acme]
status: ativo
created: 2026-03-09 08:20
updated: 2026-04-16 10:01
---

## Resumo

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O comportamento so aparece quando o cache esta frio. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

```sql
SELECT path, score FROM chunks ORDER BY score DESC LIMIT 10;
```

## Detalhes tecnicos

Em teste local o ganho apareceu principalmente nas consultas curtas. Vale revisitar isso quando o volume de notas dobrar.

## Decisao

Recall@5 is the primary metric; exact match is only a sanity check. This is a documentation note, not a runbook; keep the steps elsewhere. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[grafo-de-notas-020]]
