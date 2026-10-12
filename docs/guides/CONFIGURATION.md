# Configuração e precedência

Ordem de precedência (maior vence):

1. Argumentos de CLI / parâmetros explícitos da requisição.
2. Variáveis de ambiente do processo.
3. Arquivo `.env` (modelo: `.env.example`; veja `app/services/envfile.py`).
4. Valores padrão no código (`config/`).

Referência completa de variáveis (gerada por `scripts/gen_config_reference.py`):
[ENVIRONMENT_REFERENCE.md](../ENVIRONMENT_REFERENCE.md). Guia manual: [ENVIRONMENT.md](ENVIRONMENT.md).
