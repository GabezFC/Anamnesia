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

Buffer de replay: 1 MB por sessão. Expiração: 12 h sem cliente conectado (`TerminalManager(idle_seconds=...)`), avaliada por `create()`/`list()`/`reap()` e por uma thread de faxina (ver "Faxina").

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
`tests/test_terminals_{manager,projects,api,real,hardening,jobobject}.py`. O teste real de pywinpty (`cmd /c echo anamnesia`) só roda no Windows com `pywinpty` importável; os de PTY POSIX só fora do Windows. `test_terminals_hardening.py` usa um repositório git temporário real (precisa de `git` no PATH). `test_terminals_jobobject.py` só roda com Windows + pywinpty (no venv do projeto é pulado; rodado à parte num venv com pywinpty, `PYTHONPATH=<repo>;<repo>/.venv/Lib/site-packages` e `--noconftest`).

## Busca por conteúdo (T10.8)
`GET /api/projects/{id}/files?q=texto&content=1[&path=sub]` → `{query, mode:"content", results:[{path,line,snippet}], truncated, files_scanned, bytes_scanned}`. Busca por substring sem diferenciar maiúsculas, só em texto (binários descartados: byte NUL ou UTF-8 inválido nos primeiros 8 KB). Ignora `.git`, `node_modules`, `.venv`, `venv`, `__pycache__`, caches; ignora arquivos > 1 MB; symlinks (arquivo ou diretório) nunca são seguidos; `path` passa por `safe_join` (403 `path_escape`). Tetos: 200 resultados, 64 MB lidos, 5 s; ao atingir qualquer um `truncated:true`. Snippet ≤ ~160 caracteres. Sem `content=1`, `q` continua sendo busca por nome.

## Worktrees git (T10.7, opcional)
Módulo `app/terminals/worktrees.py`; só `git` via argv (sem shell), `GIT_TERMINAL_PROMPT=0`, timeout 30 s (120 s para add/remove), ambiente reduzido.
| Rota | Resposta |
| --- | --- |
| `GET /api/projects/{id}/worktrees` | `{worktrees:[{id,path,branch,head,primary,managed}]}`; 422 `not_a_git_repo` |
| `POST /api/projects/{id}/worktrees` `{branch}` | 201 worktree; cria `<projeto>/../.anamnesia-worktrees/<nome>-<branch com / → ->`; branch existente é reaproveitada, senão `-b` novo; 422 `invalid_branch`, 409 se a branch já está em uso ou o diretório existe |
| `DELETE /api/projects/{id}/worktrees/{wid}?confirm=true[&force=true]` | sem `confirm` 403; principal nunca (403); fora de `.anamnesia-worktrees` nunca (403); alterações não commitadas → 409 `dirty` salvo `force=true`; encerra as sessões desse worktree |
Branch: `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}(/segmento){0,3}$`, sem `..`, `//`, `/.`, `.lock`/`.` no fim (nada começa com `-`: sem injeção de opção). `POST /api/sessions` aceita `worktree_id`; o cwd da sessão passa a ser o worktree (a sessão expõe `worktree_id` e `cwd`). O id é um hash do caminho real.

## Faxina (janitor)
Thread daemon `pty-janitor`, iniciada com a primeira sessão (preguiçosa) e parada por `close_all()` (reinicia na próxima sessão). A cada `janitor_interval` (60 s; parâmetro do construtor) chama `reap()`: sessões sem cliente por mais de `idle_seconds` (12 h) são encerradas. Relógio injetável (`clock`) para testes.

## Windows Job Object
Após o spawn, `WinPtyBackend` põe o processo-filho num Job Object `KILL_ON_JOB_CLOSE` (ctypes, sem pywin32). Fechar a sessão faz `taskkill /T` e depois fecha o handle do job: tudo o que sobrou no job morre, inclusive netos órfãos. Se o job não puder ser criado, registra aviso em `anamnesia.terminals` e segue só com `taskkill`. Se o servidor morrer, o SO fecha o handle e mata as sessões.
Medido (pywinpty 3.0.x, Windows 11): neto iniciado com `cmd /c start /b` **sobrevive** ao `taskkill /T` sem job (órfão, o pai já saiu) e **morre** com o job. Neto criado com `CREATE_BREAKAWAY_FROM_JOB` (0x01000000) a partir da sessão **também morreu**: o job não define `BREAKAWAY_OK`, então a flag não o liberou nesse teste (observado uma vez, com Python como processo-pai; não é garantia de contrato do Windows). Não há nenhum hack contra breakaway; processos que o próprio SO libera de jobs (serviços, tarefas agendadas, COM/WMI `Win32_Process.Create`) continuam fora do alcance.

## Ctrl+C
Os backends encaminham bytes sem alteração: `\x03` (e `\x04`, `\x1a`) chegam ao PTY como estão; o manager não os interpreta nem encerra a sessão (teste `test_ctrl_c_forwarded_unmodified`). Observado na validação real: na tela de confiança de pasta do `claude`, Ctrl+C não a fechou. É comportamento do programa (a TUI trata a tecla), não perda de byte; use Esc/uma opção da tela ou encerre a sessão pela UI/`DELETE /api/sessions/{id}`.

## Limitações conhecidas
- O corte do buffer circular pode cair no meio de uma sequência UTF-8/ANSI; o xterm.js tolera.
- Breakaway de Job Object: ver acima; só foi testado o caso descrito.
- Busca por conteúdo é varredura linear, sem índice; projetos enormes batem nos tetos e voltam `truncated:true`.
- Worktrees: remoção só dos criados pela Anamnésia; `git worktree` precisa de git ≥ 2.17.
