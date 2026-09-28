---
id: 20260802-0822
title: Aurora — Cache layer 02
area: Projetos
type: nota
tags: [aurora, componentes, cache]
status: ativo
created: 2026-08-02 08:22
updated: 2026-09-15 16:04
projeto: aurora
---

## Referencias

A decisao foi tomada depois de comparar tres alternativas equivalentes. Latency budget is split between retrieval, rerank and composition. Fica registrado para nao repetir a investigacao daqui a seis meses. Latency budget is split between retrieval, rerank and composition.

```bash
source .venv/Scripts/activate
python scripts/run_benchmark.py --limit 50
```

## Riscos

Deduplication happens before rerank, otherwise near-duplicates flood the top. A ideia central e reduzir o custo de contexto sem perder recall. Recall@5 is the primary metric; exact match is only a sanity check. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Como reproduzir

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Fica registrado para nao repetir a investigacao daqui a seis meses. Latency budget is split between retrieval, rerank and composition.

Relacionadas: [[vortex-licencas-das-dependencias-07]] [[streaming-de-tokens-034]] [[habitos-de-foco-007]]
