# ANAM-025 — rigor do benchmark: relatório de poder estatístico (AUD-054)

Gerado com `app.benchmark.statistics` (aproximação normal, bicaudal, alfa 0,05, poder alvo 0,80).

## Onda4e (N = 197 tarefas)

| delta detectável | n/braço necessário (p0=0,5) | poder com N=197 |
|---|---|---|
| 5 pp  | 1565 | 0,167 |
| 10 pp | 388  | **0,514** (insuficiente) |
| 15 pp | 170  | 0,856 |
| 20 pp | 93   | 0,984 |

Sensibilidade ao p0 (n/braço, delta 10 pp): p0=0,3 → 356; p0=0,5 → 388; p0=0,7 → 294.

**Conclusão:** com N=197 só se detectam diferenças ≥ ~15 pp com poder ≥ 0,8. Diferenças de 10 pp entre braços
(o que o roteador precisa discriminar) exigem **N ≥ 388 por braço**; N=400 dá poder 0,8125.

## Mudanças de controle

- `scripts/run_onda4e_openrouter.py bench` agora executa `power_gate()` **antes** do preflight/gasto: se
  `N < required_n_two_proportions(0.5, 0.10)` (388) a execução é recusada (exit 2). Override explícito:
  `--allow-underpowered` (resultado deve ser tratado como exploratório).
- `verify_task` (`app/benchmark/routing_bench.py`): tarefa `fact_match+citation` sem `retrieved_ids` retorna
  `passed=False`, `failure_code="citation_unchecked"` (antes contava PASS). `run_controls` trata
  `citation_unchecked` como vazamento do verificador (controle NULL_ECHO acertou os fatos).
- `scripts/final_comparison.py --baseline <json> [--max-regression-pp 2.0]`: quality gate; exit 1 se o recall de
  algum pipeline cair > 2 pp, se contextos vazios aumentarem ou se um pipeline sumir.
- Teste do kill-switch: `tests/test_anam025_bench_rigor.py::test_spend_guard_trips_kill_switch_and_blocks_inner_call`.

## Limitação do corpus (AUD-057)

Os corpora atuais (`benchmark/questions.json`, `benchmark/routing_tasks*.json`) são sintéticos: escritos/derivados
por quem ajusta o sistema. Servem para detectar regressão (mesmo corpus, antes × depois), não para afirmar qualidade
absoluta. Registrado no docstring de `app/benchmark/external_corpus.py`.

## ANAM-021 (AUD-015) — conflito por valor

`app/services/provenance.py`: `value_conflict()` detecta mesmo assunto + valores divergentes dos dois lados
(números ou entidades), além do Jaccard de shingles; notas com mesma data continuam isentas. Métrica nova:
`memory_conflict_value`; razão `value_numbers` / `value_entities`. Fixtures em `tests/test_anam021_value_conflict.py`
(3 pares conflitantes onde Jaccard < 0,9 não pegava; 3 pares compatíveis sem falso positivo). Sem baseline de
retrieval: `resolve_conflicts` é opt-in (flags de provenance desligadas por padrão) e só rebaixa score, não remove.
