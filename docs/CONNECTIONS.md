# Connections (Fase 9 backend)

Catalog of agents, model providers and MCP servers, declared in `config/connections.yaml`
(parsed with the project's mini-YAML parser; no PyYAML). **Adding a connection = adding an entry**; no code change.

| Field | Meaning |
|---|---|
| `id`, `name` | stable id (`[a-z0-9_-]`), display name |
| `type` | `agent`, `model` or `mcp` |
| `command` | binary used for offline detection (`shutil.which` on the first token) |
| `env_keys` | env vars this connection may store as secrets (whitelist for the API) |
| `docs_url` | only URLs present in this repo, else `null` |
| `status` | `available` or `planned` |
| `mcp_snippet` | `hermes_yaml`, `claude_json`, `codex_toml` or `null` |

Invalid catalogs raise `CatalogError` (bad type/status/env_keys, duplicate ids, ...).

## API (`app/api/connections.py`, prefix `/api/connections`; router not yet wired in `app/main.py`)

- `GET /api/connections`: per entry `detected` (PATH / env var presence / module importable; **no network**),
  `has_key`, `masked`, per-key `keys`. Never the value.
- `PUT /api/connections/{id}/secret` body `{env_key, value}`: guarded by `require_local_write`
  (loopback + `X-MG-Token`). `env_key` must be in the entry's `env_keys`. The value is written to the `.env`
  under `user_data_dir()` and the process env; it is never echoed or logged.
- `DELETE /api/connections/{id}/secret` body `{env_key}`: same guard; removes it from `.env` and the process env.
- `POST /api/connections/{id}/test` (guarded): structural check (command on PATH, keys present, snippet
  available). `network_checked: false` always, unless `ANAMNESIA_ALLOW_NETWORK_TEST=1`, which currently only
  enables a probe of the local Ollama (`/api/tags`); other connections stay structural.
- `GET /api/connections/{id}/snippet`: MCP config snippet. Only formats confirmed in this repo are generated
  (Hermes `mcp_servers` in config.yaml, Claude Code `mcpServers` in .mcp.json, Codex `[mcp_servers.*]` in
  config.toml); anything else returns `{status: "unverified", note}`. `<PROJECT_ROOT>` is left as a placeholder.

## Secrets

`app/connections/secrets.py`: `has_key`, `masked` (last 4 chars only if the secret has >= 12 chars, otherwise a
fixed mask), `set_key`, `delete_key`. Storage is the `.env` at `security.ENV_PATH`. No `keyring` backend is used.
