---
id: 20260512-1748
title: Compressao de contexto 30
area: Dev-IA
type: nota
tags: [dev, ia, compressao]
status: ativo
created: 2026-05-12 17:48
updated: 2026-05-15 23:21
---

## Aberto

O comportamento so aparece quando o cache esta frio. O comportamento so aparece quando o cache esta frio. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

```sql
SELECT path, score FROM chunks ORDER BY score DESC LIMIT 10;
```

## Resumo

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Registro importante: o modelo local padrao para esse passo e qwen2.5-coder:7b-q72, rodando via Ollama. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Alternativas

A causa raiz estava na normalizacao dos acentos antes da busca. Cold start dominates the p95 numbers in every run so far.

## Implementacao

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Fica registrado para nao repetir a investigacao daqui a seis meses. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Proximos passos

We prefer explicit failure over silent degradation in the answer path. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[kraken-como-subir-o-ambiente-01]] [[aurora-como-publicar-release-04]]
