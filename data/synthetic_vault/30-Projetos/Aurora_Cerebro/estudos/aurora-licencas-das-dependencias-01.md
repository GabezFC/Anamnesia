---
id: 20260811-1355
title: Aurora — Licencas das dependencias 01
area: Projetos
type: estudo
tags: [aurora, estudos, licencas]
status: ativo
created: 2026-08-11 13:55
updated: 2026-09-02 15:42
projeto: aurora
---

## Decisao

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Alternativas

A ideia central e reduzir o custo de contexto sem perder recall. Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[plano-de-viagem-028]] [[auditoria-de-acessos-058]]
