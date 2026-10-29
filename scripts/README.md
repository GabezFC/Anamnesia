# scripts/

Índice dos utilitários de desenvolvimento. Nada aqui roda em produção/runtime.
Legenda — **CI**: executado em `.github/workflows/ci.yml` ou `.githooks`; **Teste**: coberto/executado por `pytest`
(gate indireto); **Manual**: rodar à mão. **Gerado**: o script produz arquivos versionados (rode e commite o resultado).
Todos assumem a raiz do repo como cwd: `python scripts/<nome>.py`.

## Gates (verificação)
| Script | Propósito | Uso |
|---|---|---|
| `check_architecture.py` + `layers.toml` | Contrato de camadas e ciclos de import (ANA-081) | Teste (`test_architecture.py`) |
| `check_import_cycles.py` | SCC Tarjan / arestas proibidas | Teste (`test_arch_cycles.py`) |
| `check_frontend_imports.mjs` | Todo `import` do frontend resolve e é exportado | **CI** |
| `check_contrast.py` | Contraste WCAG dos tokens de `frontend/css/tokens.css` | Teste (`test_frontend_a11y.py`) |
| `check_doc_links.py` | Links relativos em Markdown (sem rede) | Manual |
| `scan_publication_safety.py` | Segredos/dados privados na árvore e no histórico | **CI** + `.githooks/pre-push` |
| `ci_annotate_failures.py` | junit → anotações `::error::` | **CI** |
| `gen_config_reference.py`, `gen_interface_docs.py` | Geram `docs/` (variáveis de ambiente, INTERFACES) — `--check` falha se defasado | **CI**, **Gerado** |
| `check_flow_dimming.mjs` | Verificação antiga do frontend; importa `frontend/js/store.js`, que não existe mais — **quebrado/órfão** | Manual (não funciona) |
| `check_frontend_routes.sh` | Render headless de cada rota hash | Manual |
| `check_synthetic_corpus.py` | Verifica o corpus sintético | Manual |

## E2E / smoke (precisam de servidor/navegador)
| Script | Propósito | Uso |
|---|---|---|
| `e2e_workspace.py` | Workspace: add/remove projeto, explorador, Conexões, Config, Custos (Playwright). Ver `docs/guides/E2E.md` | Manual |
| `e2e_connections.py`, `e2e_a11y_keyboard.py` | E2E de Conexões / teclado | Manual |
| `mcp_smoke.py` | Sobe o servidor MCP (stdio) e chama `memory_search` | Teste (`test_mcp_smoke.py`) |
| `docker_smoke.py`, `mgtest.py` | Smoke/gestão do contêiner de teste (porta 8010) | Manual |
| `mcp_protocol_audit.py`, `cli_audit.py`, `security_audit.py` | Auditorias executáveis (MCP, CLI, segurança) | Manual |

## Geração de dados/benchmark
| Script | Propósito | Uso |
|---|---|---|
| `gen_synthetic_corpus.py`, `gen_routing_tasks.py`, `gen_code_tasks.py`, `gen_unanswerable.py`, `freeze_golden.py` | Corpus sintético, tarefas de roteamento, golden set | Manual, **Gerado** (`gen_code_tasks` também em teste) |
| `export_labeling_csv.py` | Exporta/pontua CSV de rotulagem humana | Teste |
| `gen_third_party_licenses.py` | `THIRD_PARTY_LICENSES.md` | Manual, **Gerado** |
| `persist_benchmark.py`, `run_routing_benchmark.py`, `verify_registry.py` | Persistir rodadas, benchmark de roteamento, conferir `config/models.yaml` | Manual / Teste |
| `archive/register_model_audit.py`, `archive/audit_models_2026_10_16*.py` | Auditoria de modelos 2026-10-16 (registro no `benchmark.db`) | Manual |

## Benchmarks e medições
`bench_*.py` (`bench_decision`, `bench_laya`, `bench_memory`, `bench_optimizations`, `bench_optimizer`, `bench_stages`,
`bench_anam_014_015_017`), `audit_pipeline*.py`, `audit_opt_report.py` (sem nenhum uso conhecido — candidato a arquivar),
`calibrate_*.py`, `validate_free_stages.py`, `measure_cache_hit_rate.py`, `measure_incremental_index.py`,
`measure_optional_stages.py`, `load_search.py` (Teste), `vault_lint.py` (wrapper do serviço, Teste). Todos **Manual**,
sem gerar arquivos versionados, salvo indicação no docstring.

## experiments/ (arquivados — reprodutibilidade histórica)
One-offs de ondas, movidos de `scripts/` para `scripts/experiments/` (sem papel em runtime; ainda usados por testes que os
carregam por caminho): `analyze_onda4e`, `run_onda4e_openrouter`, `_or_env`, `measure_onda9`, `measure_onda3_memory`,
`revise_router`, `eval_router_offline`, `spike_caveman_context`, `graphify_seed_experiment`, `jev_boilerplate_experiment`,
`final_comparison`, `measure_db_experiments`, `probe_jev_models`, `orchestration_experiment`, `sweep_prefilter`, `bench_ppr`,
`check_jev_snippet`, `_candidate_cache`. Os relatórios ONDA* (migrados para o Cerebro IA, Anamnesia/Migracao-docs-repo-2026-10-24/reports) ainda citam os caminhos antigos
(`scripts/<nome>.py`) — são documentos históricos.
