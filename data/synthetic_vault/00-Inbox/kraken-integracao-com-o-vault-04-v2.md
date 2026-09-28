---
id: 20260904-1203
title: Kraken — Integracao com o vault 04
area: Projetos
type: nota
tags: [kraken, arquitetura, integracao]
status: ativo
created: 2026-09-04 12:03
updated: 2026-10-03 18:59
projeto: kraken
---

## Contexto

Fica registrado para nao repetir a investigacao daqui a seis meses. A decisao foi tomada depois de comparar tres alternativas equivalentes.

```bash
source .venv/Scripts/activate
python scripts/run_benchmark.py --limit 50
```

## Medicoes

Em teste local o ganho apareceu principalmente nas consultas curtas. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Consequencias

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Latency budget is split between retrieval, rerank and composition.

## Aberto

We prefer explicit failure over silent degradation in the answer path. A causa raiz estava na normalizacao dos acentos antes da busca.

## Resumo

A causa raiz estava na normalizacao dos acentos antes da busca. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Notes

Recall@5 is the primary metric; exact match is only a sanity check. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[orcamento-de-infra-054]] [[aurora-licencas-das-dependencias-07]] [[vortex-custos-de-inferencia-04]]
