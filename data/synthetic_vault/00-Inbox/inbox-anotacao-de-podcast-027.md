---
id: 20260129-1417
title: Inbox: Anotacao de podcast 27
area: Inbox
type: nota
tags: [anotacao, inbox, triagem]
status: inbox
created: 2026-01-29 14:17
updated: 2026-03-08 19:42
---

## Riscos

Vale revisitar isso quando o volume de notas dobrar. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Detalhes tecnicos

A causa raiz estava na normalizacao dos acentos antes da busca. Deduplication happens before rerank, otherwise near-duplicates flood the top. Registro importante: o servico interno responde na porta 49071 dentro da rede docker. A causa raiz estava na normalizacao dos acentos antes da busca. A ideia central e reduzir o custo de contexto sem perder recall.

## Decisao

A causa raiz estava na normalizacao dos acentos antes da busca. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Aberto

A ideia central e reduzir o custo de contexto sem perder recall. O comportamento so aparece quando o cache esta frio. Vale revisitar isso quando o volume de notas dobrar. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

Relacionadas: [[vortex-licencas-das-dependencias-07]] [[vortex-integracao-com-o-vault-04]]
