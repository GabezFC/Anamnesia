---
id: 20260421-1451
title: Roteador de modelos 09
area: Dev-IA
type: nota
tags: [dev, ia, roteador]
status: ativo
created: 2026-04-21 14:51
updated: 2026-05-27 19:46
---

## Riscos

A decisao foi tomada depois de comparar tres alternativas equivalentes. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Detalhes tecnicos

O comportamento so aparece quando o cache esta frio. Registro importante: o modelo local padrao para esse passo e nomic-embed-text:v1.5-q107, rodando via Ollama. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[parser-de-frontmatter-079]] [[2026-02-26]] [[reranker-local-043]]
