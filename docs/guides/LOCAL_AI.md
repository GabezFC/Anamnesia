# IA local gerenciada (ANAM-034 / ANAM-035)

Pacote `app/services/local_ai/`. Nada instala, baixa ou inicia modelo sozinho; testes usam fakes (sem rede, sem Colibri real).

## Arquivos
| Arquivo | Papel |
|---|---|
| `base.py` | `LocalRuntime` (detect/status/plan/start/stop/health/base_url), runner de subprocess e HTTP injetaveis, `parse_json_tolerant` |
| `colibri.py` | `ColibriRuntime` |
| `ollama.py` | `OllamaRuntime` |
| `provider.py` | `LocalProvider` (generate/stream OpenAI-compativel, `count_tokens` estimado, `estimate_cost` = 0) |
| `policy.py` | bloqueio por licenca/proveniencia via `model_catalog` |
| `download.py` | download resumivel e seguro |

## Verificado (2026-10-15, leitura do codigo do Colibri v2.0.0 em `Example Colibri/colibri/c/`)
- `coli status --json` (sem `--model`), `coli plan --json --model D --ram N --ctx N`, `coli doctor --json --model D`
  (relatorio `schema_version:1`, `status` pass/warn/error; exit 1 se `error`), `coli serve --host --port --api-key --model`,
  `coli stop --port N`. A key tambem pode vir de `COLI_API_KEY` (argparse default).
- `setup.json` traz `launcher` (script python `coli`), `model_dir`, `model.id`, `env`, `port` (default 8000). Setup home:
  `COLI_SETUP_HOME` ou `%LOCALAPPDATA%/colibri`. Descoberta: `MG_COLIBRI_HOME` -> setup home.
- Saude: `GET /health` -> `{"status":"ok"}`; `GET /v1/models`. OpenAI em `http://127.0.0.1:PORT/v1`.
- Ollama (docs oficiais `docs/api.md`): `GET /api/version|/api/tags|/api/ps`, `POST /api/generate` (`keep_alive`; `0` descarrega).
  OpenAI-compativel em `/v1` (ver ENVIRONMENT.md). O adaptador NUNCA chama `/api/pull`.
- **NAO executado nesta tarefa**: `coli` real, servidor de 173 GiB, download real. Integracao com binario real = nao validada.

## Regras de seguranca
- Colibri em porta propria **11500** (nunca 8000 nem 11434; portas < 1024 recusadas), host fixo `127.0.0.1`.
- `--api-key` gerada com `secrets.token_urlsafe(32)`, so em memoria, apagada no `stop()`, nunca em `status()`.
  Padrao `key_via="env"`: a chave vai por `COLI_API_KEY` no ambiente do processo (nao aparece na linha de
  comando). Risco: `ColibriRuntime(key_via="arg")` passa `--api-key` na linha de comando, visivel a outros
  usuarios locais; use so se o ambiente nao puder ser usado (`COLI_API_KEY` verificado no argparse).
- `status/plan/doctor` rodam com timeout (30 s) e saida invalida vira `{ok:false}`, nunca excecao.
- `LocalProvider` so fala com loopback; respeita `OFFLINE=1`; nao passa pelo kill-switch de gasto (custo de API 0).
- Politica: modo comercial (default; `MG_LOCAL_AI_MODE`) bloqueia modelo fora do catalogo, UNVERIFIED ou non-commercial.
  Tags Ollama precisam de `aliases={tag: id_do_catalogo}`.

## Download (`download.py`)
- Exige `confirm=True` (exatamente), `max_bytes` declarado, `expected_size <= max_bytes` e `expected_sha256` (64 hex).
- Host: allow-list `huggingface.co` (+ subdominios; extensao por `MG_LOCAL_AI_DL_HOSTS`), https, sem credenciais; cada redirect revalidado.
  Ponto aberto: CDN real do HF pode redirecionar para dominio fora da lista (nao verificado) -> falha fechada; adicione o host explicitamente.
- `hf_resolve_url` exige revisao SHA de 40 hex (nada de `main`).
- Destino confinado (sem `..`, absoluto, drive, `\`, NUL, symlink); espaco livre >= restante + 256 MiB.
- Escreve `.part`; resume com `Range` (valida `Content-Range`; servidor sem Range => recomeca); `os.replace` so apos tamanho **e** sha256.
  sha errado => `.part` apagado; truncado => `.part` mantido para resume.
- Em pytest sem `opener` injetado a rede real e recusada (`network_in_tests`).

## Limites conhecidos
- `plan` do Ollama e heuristica rotulada `estimated` (Ollama nao expoe plano de recursos).
- Colibri: `stop` chama `coli stop --port` e termina o filho; nao ha reaproveitamento de servidor iniciado por fora com outra key.
- `OllamaRuntime.start()` so sobe `ollama serve` se o binario existir; nao altera `OLLAMA_*`.
- Nao ligado ao roteador/registro de modelos ainda (proximo passo).
