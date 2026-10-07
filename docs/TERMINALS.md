# Terminais (Fase 10 backend)

Terminal Manager da Anamnésia: PTY real por sessão, ligado a um projeto registrado e a um perfil de lançamento. Promovido do spike `spikes/pty_windows` (pywinpty + uma thread de leitura por sessão + `call_soon_threadsafe`).

## Instalação
- Windows: `pip install 'anamnesia[terminal]'` (instala `pywinpty>=3.0`; validado com 3.0.5). Sem ele, criar sessão devolve 500 `spawn_failed` (`BackendUnavailable`).
- Linux/macOS: nada a instalar (módulo `pty` da biblioteca padrão; **testado só se rodar na CI deles**, ver "Não verificado").

## Módulos
| Arquivo | Papel |
| --- | --- |
| `app/terminals/backend.py` | `PtyBackend`/`PtyHandle` (Protocol); `WinPtyBackend`, `PosixPtyBackend`, `FakePtyBackend` (testes). Imports específicos de SO são tardios. |
| `app/terminals/manager.py` | `TerminalManager`: criar/listar/obter/escrever/redimensionar/encerrar, limites, buffer circular, expiração. |
| `app/terminals/projects.py` | Registro de projetos (SQLite), `safe_join`, listagem e busca de arquivos. |
| `app/terminals/profiles.py` + `config/profiles.yaml` | Perfis: `shell`, `powershell`, `hermes`, `claude-code`, `codex`, `opencode`. |
| `app/api/workspace.py` | `router = APIRouter(prefix="/api")` (o `main.py` precisa fazer `include_router`). |

## Configuração
| Variável | Padrão | Efeito |
| --- | --- | --- |
| `ANAMNESIA_MAX_SESSIONS` | 8 | máximo de sessões **ativas**; acima disso 429 (nenhuma sessão antiga é morta) |
| `ANAMNESIA_ALLOW_REMOTE_TERMINALS` | (vazio) | `1` permite terminais mesmo com `MG_HOST` não loopback (aviso: ver segurança) |
| `MG_HOST` | `127.0.0.1` | host de bind lido via `BenchmarkConfig` |
| `MG_LOCAL_TOKEN` | gerado | token existente (`X-MG-Token` / subprotocolo `tok.<token>`) |

Buffer de replay: 1 MB por sessão. Expiração: 12 h sem cliente conectado (`TerminalManager(idle_seconds=...)`). A expiração é avaliada de forma oportunista em `create()`/`list()`/`reap()`; não há thread de faxina própria (o orquestrador pode chamar `get_manager().reap()` periodicamente).

## API
Erros: `{"error": {"code", "message", "hint"}}`. Falhas de autenticação vêm de `require_local_write` (`{"detail": ...}`, 403).

| Rota | Auth | Resposta |
| --- | --- | --- |
| `GET /api/projects` | loopback | `{projects:[{id,name,path,created_at}]}` |
| `POST /api/projects` `{name,path}` | token | 201 projeto; 422 se o caminho não existe / não é diretório / duplicado |
| `DELETE /api/projects/{id}` | token | remove só o registro (nunca arquivos) e encerra suas sessões |
| `GET /api/projects/{id}/files?path=&q=` | token | listagem (`path`) ou busca por nome (`q`), somente leitura, tetos 500/200 itens; `..`, absolutos e symlink para fora → 403 `path_escape`; symlinks que saem do projeto ficam ocultos na listagem |
| `GET /api/profiles` | loopback | perfis com `available`, `env_keys`, `missing_env_keys` (nunca valores) |
| `POST /api/sessions` `{project,profile,cols,rows}` | token | 201 `{session_id, ws_url, session}`; 404/422/429 conforme o caso |
| `GET /api/sessions` | token | `{sessions:[...]}` (sem env, sem segredo) |
| `DELETE /api/sessions/{id}` | token | encerra a árvore de processos |
| `WS /api/sessions/{id}/ws` | ver abaixo | |

### WebSocket
- Handshake: subprotocolo `tok.<token>` (nunca na URL), `Origin` igual ao `Host` do servidor, `Host` loopback (anti DNS-rebinding, salvo `ANAMNESIA_ALLOW_REMOTE_TERMINALS=1`), cliente TCP loopback. Qualquer falha fecha com **4403 antes de aceitar** (token errado e sessão inexistente são indistinguíveis); sessão inexistente com auth válida fecha com 4404.
- Cliente → servidor: binário = stdin; texto JSON `{"t":"resize","cols","rows"}` ou, compatível com o spike, `{"t":"in","d":"..."}` e `{"t":"rs","rows","cols"}`. JSON inválido é ignorado. Mensagens > 1 MB descartadas.
- Servidor → cliente: `{"t":"replay","bytes":N}` + (se N>0) um quadro binário com o buffer; `{"t":"state","v":"active"}`; depois binário de stdout; ao fim `{"t":"state","v":"ended","code":N}` e fechamento 1000.
- Fechar o WebSocket **não** encerra a sessão (sobrevive a recarregar); vários clientes podem se conectar à mesma sessão.

## Segurança (S1, S2, S4, S5, S9)
- **S2** default-deny: com `MG_HOST` fora de loopback, criar/listar/encerrar sessões dá 403 `terminals_disabled` e o WebSocket fecha 4403. `ANAMNESIA_ALLOW_REMOTE_TERMINALS=1` só destrava o gate de bind; as checagens de cliente loopback + token + Origin continuam valendo, então clientes remotos ainda são recusados. Use somente atrás de um publish `127.0.0.1:` (Docker).
- **S4** ambiente por allowlist: `PATH, HOME, USERPROFILE, LANG, TERM, SystemRoot, COMSPEC, TEMP` (+ `TMP`, `PATHEXT`, que o `cmd` e os shims `.cmd` precisam) mais **somente** as `env_keys` do perfil escolhido e `MG_SCOPE=<nome do projeto>`. Nunca o `.env` inteiro.
- **S5** `safe_join` resolve o caminho real e exige prefixo do projeto; rejeita `..`, absolutos, letra de drive/streams NTFS e NUL.
- **S9** encerramento: Windows = `taskkill /F /T /PID` (com o processo-raiz ainda vivo) + `close(force=True)`; POSIX = `killpg` SIGHUP e depois SIGKILL. Sessões sem cliente expiram.
- Auditoria (logger `anamnesia.terminals.audit`): `session_open`, `session_close`, `ws_attach/detach`, `ws_rejected`; sem token e sem teclas.
- O cwd é sempre o diretório do projeto (caminho real).

## Perfis
`config/profiles.yaml` (YAML simplificado, sem PyYAML). Campos: `id, name, kind, command, windows_command, args, windows_args, env_keys, description`. O comando é resolvido com `shutil.which` e executado sem shell. Perfil `shell` no POSIX tenta `$SHELL`, `bash`, `sh`. Perfil cujo comando não existe: `available:false` na listagem e 422 `profile_unavailable` ao criar (a UI deve oferecer o `shell`).

## Testes
`tests/test_terminals_{manager,projects,api,real}.py`. O teste real de pywinpty (`cmd /c echo anamnesia`) só roda no Windows com `pywinpty` importável; os de PTY POSIX só fora do Windows.

## Limitações conhecidas
- O corte do buffer circular pode cair no meio de uma sequência UTF-8/ANSI; o xterm.js tolera.
- Neto que se destaca do console (breakaway) e Job Object não foram implementados; fica só `taskkill /T`.
- Busca por conteúdo de arquivos (T10.8) não implementada, só por nome.
- Worktrees (T10.7) fora deste escopo.
