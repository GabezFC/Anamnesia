---
id: 20260501-1101
title: Parser de frontmatter 19
area: Dev-IA
type: nota
tags: [dev, ia, parser]
status: ativo
created: 2026-05-01 11:01
updated: 2026-05-07 11:32
---

## Aberto

Vale revisitar isso quando o volume de notas dobrar. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Resumo

Recall@5 is the primary metric; exact match is only a sanity check. Registro importante: o snapshot foi validado contra KrampusDB v2.27-rc0 em ambiente isolado. A ideia central e reduzir o custo de contexto sem perder recall. O comportamento so aparece quando o cache esta frio.

## Medicoes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Detalhes tecnicos

A ideia central e reduzir o custo de contexto sem perder recall. Em teste local o ganho apareceu principalmente nas consultas curtas. A decisao foi tomada depois de comparar tres alternativas equivalentes. Vale revisitar isso quando o volume de notas dobrar.

## Implementacao

Recall@5 is the primary metric; exact match is only a sanity check. The retrieval layer keeps a small LRU in front of the vector index. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Riscos

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[aurora-graph-loader-03]] [[relatorio-para-stakeholders-057]] [[2026-04-24]]
