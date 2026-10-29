# Configuração e precedência

Ordem de precedência (maior vence):

1. Argumentos de CLI / parâmetros explícitos da requisição.
2. Variáveis de ambiente do processo.
3. Arquivo `.env` (modelo: `.env.example`; veja `app/services/envfile.py`).
4. Valores padrão no código (`config/`).

Referência completa de variáveis (gerada por `scripts/gen_config_reference.py`):
[ENVIRONMENT_REFERENCE.md](../ENVIRONMENT_REFERENCE.md). Guia manual: Cérebro IA (Anamnesia/Guias-de-usuario-2026-10-24/ENVIRONMENT.md).

## Flags de recuperação (Onda 2)

- `GRAPHIFY_STALE_FALLBACK_S` (padrão 0 = desligado, ANA-080): se o grafo estiver desatualizado em relação ao vault por mais de N segundos, a busca devolve só BM25. A impressão digital do vault fica em `graphify-out/vault_fp.json` (gravada em cada build; a staleness é calculada só com stat).
- `MG_INCREMENTAL_INDEX=1` (padrão desligado, ANA-102): índice FTS5 incremental em `baseline_fts.db`, ao lado do `benchmark.db` (nunca dentro do vault). Relatório de medição: nota ANA102_ANA109_ANA113_RELATORIO.md no Cerebro IA (Anamnesia/Migracao-docs-repo-2026-10-24).
