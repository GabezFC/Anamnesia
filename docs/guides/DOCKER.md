# Docker — setup em clone limpo

Requisitos: Docker Engine/Desktop com Compose v2.24+ (usa `env_file.required`). Nenhum `.env`, banco ou vault pessoal é
necessário: a imagem não contém segredos e o vault padrão é o corpus sintético do repositório.

## Subir

    git clone <repo> && cd Memory_Gateway
    docker compose up -d --build          # http://127.0.0.1:8000
    docker compose ps                     # aguarde "healthy"

Porta alternativa no host (ex.: 8000 ocupada) — a sintaxe `VAR=valor comando` **só existe em bash/zsh**:

    # PowerShell:   $env:ANAMNESIA_PORT = '8010'; docker compose up -d
    # cmd.exe:      set ANAMNESIA_PORT=8010 && docker compose up -d
    # bash/zsh:     ANAMNESIA_PORT=8010 docker compose up -d
    # qualquer um:  docker compose --env-file docker/mgtest.env up -d      # arquivo de ambiente (portátil)

Readiness real: o `HEALTHCHECK` chama `GET /health` (rota existente, 200 = pronto) dentro do contêiner.
`docker compose up -d --wait` só retorna quando está `healthy`. Logs: `docker compose logs -f anamnesia`
(stdout, rotação 10 MB x 5) e `/data/logs` no volume.

## Variáveis (shell ou `.env` ao lado do compose — só interpolação)

| Variável | Efeito | Padrão |
|---|---|---|
| `ANAMNESIA_PORT` | porta no host (sempre publicada em 127.0.0.1) | 8000 |
| `ANAMNESIA_VAULT_HOST` | pasta do host montada **somente leitura** em `/vault` | `./data/synthetic_vault` |
| `ANAMNESIA_PROJECTS_HOST` | raiz de projetos do host montada **somente leitura** em `/projects` (opcional) | vazio → `docker/projects-empty` (diretório vazio) |
| `ANAMNESIA_PROJECTS_HOST2` | segunda raiz, RO, em `/projects2` (opcional) | vazio → `docker/projects-empty` |
| `ANAMNESIA_PATH_MAP` | pares `host=contêiner` separados por `;` para o app traduzir caminhos do host | vazio |
| `OLLAMA_HOST` | Ollama opcional, ex. `http://host.docker.internal:11434` | vazio |

Segredos (chaves de API etc.): arquivo `.env.docker` (ignorado por git e pela imagem, opcional). O token
local (`MG_LOCAL_TOKEN`) é gerado na 1ª subida em `/data/.env` (volume). Ver: `docker compose exec anamnesia sh -c 'grep MG_LOCAL_TOKEN /data/.env'`.

## Projetos do host no contêiner (somente leitura)

O contêiner enxerga o disco do host só pelo que for montado. Para registrar/explorar projetos no Workspace:

    # docker/mgtest.env (ou .env / variáveis de shell)
    ANAMNESIA_PROJECTS_HOST=C:/Users/voce/Projetos          # use barras "/" mesmo no Windows
    ANAMNESIA_PATH_MAP=C:/Users/voce/Projetos=/projects     # o app traduz o caminho do host p/ /projects
    # mais uma raiz: ANAMNESIA_PROJECTS_HOST2=D:/Code  e  ANAMNESIA_PATH_MAP=C:/Users/voce/Projetos=/projects;D:/Code=/projects2

Regras de segurança: monte **uma pasta de projetos**, nunca a unidade inteira (`C:/`) nem `$HOME`; o bind é `read_only: true`
(`touch /projects/x` falha com "Read-only file system"); não há `privileged` nem `docker.sock`. Escrita em projetos do host
exige outra decisão explícita (não existe aqui). Sem a variável, `/projects` aponta p/ um diretório vazio e nada do host é exposto.
Mais de duas raízes: copie o bloco `bind` do `docker-compose.yml` (ex. `/projects3`) e acrescente o par em `ANAMNESIA_PATH_MAP`.
Depois de alterar mounts/variáveis é preciso recriar: `docker compose up -d` (o Compose recria o contêiner; o volume é mantido).

## Ambiente de teste local "mgtest" (Windows / Docker Desktop)

Projeto Compose separado (`-p mgtest`, contêiner `mgtest-anamnesia-1`, volume `mgtest_anamnesia-data`, rede `mgtest_anamnesia`),
porta **8010** e raiz de projetos definidas no arquivo local `docker/mgtest.env` (ignorado pelo Git; o padrão 8000 de quem clona não muda).
Copie `docker/mgtest.env.example` para `docker/mgtest.env` antes de executar o script e configure apenas as pastas que deseja expor.
Para o teste opcional da Laya, copie `docker/laya-test.env.example` para `docker/laya-test.env` e configure o diretório dos pesos.
Os exemplos publicados usam o corpus sintético; nunca versione seus arquivos locais de ambiente, credenciais ou caminhos pessoais.

    python scripts/mgtest.py up        # PowerShell, cmd ou bash: valida `config`, checa porta, build, espera healthy, prova imagem==código
    python scripts/mgtest.py status    # id, imagem, porta, volume, mounts, saúde, hash do frontend repo x contêiner
    python scripts/mgtest.py logs 100  # com token/segredos mascarados
    python scripts/mgtest.py restart   # dados persistem
    python scripts/mgtest.py smoke     # scripts/docker_smoke.py: API, mounts RO, persistência, UI (Playwright), screenshots em data/reports-out/evidence/ (local, ignorado pelo Git)
    python scripts/mgtest.py down      # nunca usa -v

Equivalente manual: `docker compose -p mgtest --env-file docker/mgtest.env up -d --build`. Se `up` disser que a porta está
ocupada, outro processo a usa (`netstat -ano | findstr :8010`); o script não encerra processos de terceiros. A imagem carrega os
labels `org.opencontainers.image.revision` (HEAD, `+dirty` se há mudanças) e `io.anamnesia.frontend-sha256`. O smoke de UI
precisa de um Python com `playwright` + chromium (`MGTEST_PW_PYTHON=<python>`); sem ele as checagens de UI saem como SKIP.

**Nunca** use `docker compose down -v`, `docker volume rm/prune` nem `system prune` neste ambiente: apagam o token e os dados.

## Persistência

Volume nomeado `anamnesia-data` → `/data` (`ANAMNESIA_HOME`): bancos, memórias, índices, config, logs e `.env`.
Sobrevive a `restart`, `down` + `up` e rebuild. **Só `docker compose down -v` apaga** o volume. Backup:
`docker run --rm -v <projeto>_anamnesia-data:/d -v "$PWD":/b alpine tar czf /b/anamnesia-data.tgz -C /d .`.
Migrações de esquema rodam na subida do app, sobre o banco existente no volume.

## Causa-raiz das falhas ao clonar

1. **UI sem acesso (401/403)**: pelo port-publish o cliente chega ao contêiner do IP do *gateway* da rede
   (`172.x.0.1`), não de `127.0.0.1`; o app trata só loopback como "local" (token, escrita, leitura com bind 0.0.0.0).
   Correção: `MG_TRUSTED_LOCAL_CLIENTS` (novo, em `app/services/security.py`, vazio por padrão) + sub-rede/gateway
   fixos no compose (`172.29.240.0/24`, gateway `.1`). Seguro porque o host só publica em loopback.
2. **Porta 8000 fixa**: colide com qualquer outro serviço (ex.: dev server) → `ports are not available`. Agora `ANAMNESIA_PORT`.
3. **Vault** era opcional/comentado e `host.docker.internal` não existia no Linux → agora montagem RO configurável e `extra_hosts`.
4. Sub-rede fixa pode colidir com VPN/rede local: mude `subnet`/`gateway` **e** `MG_TRUSTED_LOCAL_CLIENTS` juntos.

## IA local opcional (Laya / Colibri / Ollama)

Nada disso bloqueia o núcleo. Ollama no host: `OLLAMA_HOST=http://host.docker.internal:11434` (a ligação com host
precisa escutar fora do loopback do host, ex. `OLLAMA_HOST=0.0.0.0` no Ollama). Laya em modo `serve` e Colibri exigem URL
**loopback** (`MG_LAYA_SERVE_URL`; Colibri 127.0.0.1:11500) e portanto não são alcançados a partir do contêiner; use no host
(bridge MCP) ou Laya in-proc. Terminais web ficam desabilitados no contêiner (bind 0.0.0.0) por segurança.

## Suíte de testes em Docker

    docker compose -f docker-compose.test.yml run --rm py312      # py313, py314; usa init: true
    docker run --rm --init anamnesia-test:3.12                     # à mão: --init é obrigatório

## Plataformas

Os binds usam o caminho do host: no Windows com Docker Desktop (WSL2) `C:/Users/...` funciona (compartilhamento de arquivos do
Docker Desktop; pastas fora de `C:\Users` podem precisar ser liberadas em Settings → Resources → File sharing). Linux/macOS:
use caminhos POSIX (`ANAMNESIA_PROJECTS_HOST=/home/voce/projetos`, `ANAMNESIA_PATH_MAP=/home/voce/projetos=/projects`); **não
testado** aqui. Em Linux o UID 10001 do contêiner precisa de leitura nas pastas montadas.

## Verificado / não verificado

Verificado em rodada anterior (Windows 11, Docker Desktop 29.8 / Compose v5.5, clone limpo via `git clone`, porta 8010): build, `healthy`,
`/health` 200, UI `/` 200, `/config/token` com cookie de UI 200, `GET /api/connections` 200, `POST /memory/search` com
token retorna contexto do vault sintético montado em `/vault`, persistência (restart e down+up) com o compose anterior.
**Não testado**: Linux/macOS e outra máquina; `extra_hosts: host-gateway` no Linux; colisão da sub-rede 172.29.240.0/24;
bind mount de `/data` (UID 10001 precisa de escrita); Ollama real no host; persistência re-executada com o compose novo;
suíte `docker-compose.test.yml` nesta rodada; imagem não usa `requirements.lock` (gerado para py3.12; dependências resolvidas no build).

Verificado com o compose atual (Windows 11, Docker Desktop, projeto `mgtest`, porta 8010, `scripts/docker_smoke.py`): build,
healthy, `/health` 200, volume `mgtest_anamnesia-data` em `/data`, bind RO em `/projects`, escrita em `/projects` negada,
projeto registrado via API persiste após `restart`, frontend sem `terminals.js`/xterm. Resultado e falhas de UI: nota sub_docker_mgtest.md no Cerebro IA (Anamnesia/Migracao-docs-repo-2026-10-24).
