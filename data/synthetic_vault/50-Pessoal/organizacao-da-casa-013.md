---
id: 20260306-0959
title: Organizacao da casa 13
area: Pessoal
type: nota
tags: [pessoal, organizacao]
status: ativo
created: 2026-03-06 09:59
updated: 2026-03-07 15:17
---

## Notes

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Deduplication happens before rerank, otherwise near-duplicates flood the top. Vale revisitar isso quando o volume de notas dobrar.

```bash
source .venv/Scripts/activate
python scripts/run_benchmark.py --limit 50
```

## Medicoes

Fica registrado para nao repetir a investigacao daqui a seis meses. Registro importante: o identificador interno do experimento e Snorvath-7130 e ele nao deve ser renomeado. A ideia central e reduzir o custo de contexto sem perder recall.

## Referencias

Recall@5 is the primary metric; exact match is only a sanity check. Fica registrado para nao repetir a investigacao daqui a seis meses. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[vortex-como-rodar-o-benchmark-08]] [[aurora-cache-layer-02]] [[kraken-como-publicar-release-10]]
