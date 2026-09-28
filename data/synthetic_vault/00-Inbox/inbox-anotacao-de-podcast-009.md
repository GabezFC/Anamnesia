---
id: 20260111-1311
title: Inbox: Anotacao de podcast 09
area: Inbox
type: ideia
tags: [anotacao, inbox, triagem]
status: inbox
created: 2026-01-11 13:11
updated: 2026-01-11 19:39
---

## Contexto

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. We prefer explicit failure over silent degradation in the answer path.

## Detalhes tecnicos

Em teste local o ganho apareceu principalmente nas consultas curtas. Em teste local o ganho apareceu principalmente nas consultas curtas. Registro importante: o modelo local padrao para esse passo e llama3.2-vision:11b-q2, rodando via Ollama. Deduplication happens before rerank, otherwise near-duplicates flood the top. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Alternativas

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Resumo

O comportamento so aparece quando o cache esta frio. A ideia central e reduzir o custo de contexto sem perder recall. Fica registrado para nao repetir a investigacao daqui a seis meses. Recall@5 is the primary metric; exact match is only a sanity check.

## Riscos

Fica registrado para nao repetir a investigacao daqui a seis meses. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Em teste local o ganho apareceu principalmente nas consultas curtas. Vale revisitar isso quando o volume de notas dobrar.

## Aberto

O comportamento so aparece quando o cache esta frio. Recall@5 is the primary metric; exact match is only a sanity check. Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[orcamento-de-infra-018]] [[estudo-metricas-de-ranqueamento-010]]
