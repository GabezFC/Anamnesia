---
id: 20260615-0846
title: Tokenizer custom 64
area: Dev-IA
type: nota
tags: [dev, ia, tokenizer]
status: ativo
created: 2026-06-15 08:46
updated: 2026-07-27 13:44
---

## Resumo

A decisao foi tomada depois de comparar tres alternativas equivalentes. Cold start dominates the p95 numbers in every run so far. A decisao foi tomada depois de comparar tres alternativas equivalentes.

```sql
SELECT path, score FROM chunks ORDER BY score DESC LIMIT 10;
```

## Medicoes

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A causa raiz estava na normalizacao dos acentos antes da busca. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Como reproduzir

A decisao foi tomada depois de comparar tres alternativas equivalentes. Vale revisitar isso quando o volume de notas dobrar. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[plano-de-viagem-020]] [[retrospectiva-da-sprint-017]]
