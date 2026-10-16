# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Versionamento: ver `pyproject.toml`.

## [Não lançado]

### Adicionado
- ANAM-026: comandos `backup-create` / `backup-restore` (zip + manifest sha256 de `benchmark.db` e do memory store;
  restore valida a integridade antes de escrever e não sobrescreve sem `--force`). `app/services/backup.py`.
- ANAM-026: allow-list de licenças (`app/services/license_policy.py`) validada por teste contra
  `config/model_catalog.json`, `THIRD_PARTY_LICENSES.md` e os defaults de estágios opcionais
  (Provence CC BY-NC-ND só opcional, desligado por padrão; Qwen Community License = restrita).
- ANAM-026: `requirements.lock` com hashes sha256 (`uv pip compile requirements.txt --generate-hashes --python-version 3.12`),
  `.github/dependabot.yml`, `NOTICE` e `THIRD_PARTY_NOTICES.md` (Colibrì Apache-2.0, Laya Apache-2.0, ds4 MIT).

### Alterado
- Nenhuma dependência foi atualizada; o lock reproduz as versões fixadas em `requirements.txt`.
