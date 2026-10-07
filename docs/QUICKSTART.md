# Início rápido (para quem não é desenvolvedor)

Anamnésia é um serviço **local** que lê um vault de notas (Obsidian) e responde buscas por memória
(REST + MCP + painel web). Roda no seu computador e escuta só em `127.0.0.1`.

> **Importante: o pacote ainda NÃO está publicado no PyPI.** `pip install anamnesia` não funciona
> (ainda). Instale pelo repositório do GitHub, como abaixo.

Legenda: ✅ comando executado de verdade durante a preparação deste guia · 📖 lido do código, não
executado neste ambiente · ⚠️ não verificado.

## 1. Pré-requisitos

| Item | Detalhe |
|---|---|
| Python | **3.12 ou mais novo** (`requires-python = ">=3.12"`). Testado em 3.12 e 3.14 ✅ |
| Git | só para a instalação por `git clone` |
| Chave TypeSafe/JEV | **opcional**. Só para os pipelines que usam o juiz pago. Sem chave, a busca básica funciona 📖 |
| `graphify` | **opcional**. O repositório traz um grafo pré-calculado para o corpus de exemplo 📖 |
| Vault próprio | **opcional**. Sem configurar, usa o corpus de exemplo embutido (`data/synthetic_vault`) ✅ |

## 2. Instalar (escolha UMA forma)

### A) `git clone` (recomendado para testar/desenvolver)

```bash
git clone https://github.com/GabezFC/Anamnesia.git
cd Anamnesia
python -m venv .venv
# Linux/macOS:        source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install .
```
✅ `pip install .` em Python 3.12 e 3.14 limpos (Docker). Para só rodar os testes: `pip install -r requirements.txt -r requirements-dev.txt`.

### B) `pipx` (instala o comando `anamnesia` isolado)

```bash
pipx install git+https://github.com/GabezFC/Anamnesia.git
```
✅ Executado em Docker (python:3.14-slim): instalou e `anamnesia version` respondeu `anamnesia 0.1.0`.
Precisa de `git` instalado. **Não** use `pipx install anamnesia` (PyPI não publicado).

### C) `uv tool install`

```bash
uv tool install git+https://github.com/GabezFC/Anamnesia.git
```
✅ Executado em Docker (python:3.14-slim). A partir de um clone local também funciona:
`uv tool install --from . anamnesia` ✅.

## 3. Primeira execução

```bash
anamnesia doctor     # confere o ambiente, sem rede e sem imprimir segredos
anamnesia start      # sobe a API + painel em http://127.0.0.1:8000
```
✅ ambos executados. `doctor` mostra uma tabela `OK` / `warn` / `FAIL`:

- `FAIL` (e código de saída 1) só quando algo é obrigatório falha: Python antigo ou vault inexistente.
- `warn` é opcional: `graphify` ausente, sem `TYPESAFE_API_KEY`, token local "criado no primeiro `start`",
  `benchmark.db` "absent (created on demand)". Numa instalação limpa é normal ver esses `warn`.

Depois do `start`, abra <http://127.0.0.1:8000/> no navegador ✅ (a verificação de saúde é
`http://127.0.0.1:8000/health`, que retorna `{"status":"ok", ...}` ✅).

Se `anamnesia` não for encontrado como comando, use `python -m anamnesia doctor` / `python -m anamnesia start` ✅ (existe `anamnesia/__main__.py`).

### Onde ficam os dados

- Instalação por `pip`/`pipx`/`uv`: pasta do usuário (Linux `~/.local/share/anamnesia`, macOS
  `~/Library/Application Support/Anamnesia`, Windows `%LOCALAPPDATA%\Anamnesia`) 📖 (Linux ✅).
- Dentro de um clone: a própria pasta do repositório.
- Para escolher outra pasta: variável `ANAMNESIA_HOME`.

### Usar o SEU vault

```bash
# Linux/macOS
export MEMORY_GATEWAY_VAULT=/caminho/para/seu/vault
# Windows PowerShell
$env:MEMORY_GATEWAY_VAULT = "C:\caminho\para\seu\vault"
anamnesia doctor
```
📖 (variável lida em `config/retrieval.py`; também pode ficar no arquivo `.env`, modelo em `.env.example`).
O vault é **só lido**. O Anamnésia se recusa a gravar o banco dentro dele.

## 4. Docker

Existe `Dockerfile` e `docker-compose.yml` ✅ (construídos e testados: `anamnesia version` e `GET /health`
responderam dentro do contêiner).

```bash
docker compose build
docker compose up -d
curl http://127.0.0.1:8000/health
docker compose down
```

O que você precisa saber:

- A porta é publicada **só em `127.0.0.1:8000`** da sua máquina. Não troque por `8000:8000`: isso abriria o
  serviço para a sua rede.
- Dentro do contêiner o app escuta em `0.0.0.0` (necessário para o mapeamento de porta) e a proteção
  de `Host` aceita `localhost` e `127.0.0.1` (`MG_ALLOWED_HOSTS`). Um `Host` estranho recebe 400 ✅.
- **Terminais embutidos ficam desativados** no Docker (o app só os liga em bind de loopback) ✅.
- Endpoints de **escrita** recusam clientes que não sejam loopback *dentro do contêiner*; o tráfego vindo do host
  chega pela rede do Docker e leva `403` ✅. Ou seja, no Docker o uso é de **leitura/busca**. Para configurar
  (token, conexões) use a instalação local.
- Dados em um volume Docker (`/data`). Para usar seu vault, monte-o somente leitura e defina
  `MEMORY_GATEWAY_VAULT=/vault` (linhas comentadas no `docker-compose.yml`) ⚠️ (montagem do vault não testada).

## 5. Atualizar e desinstalar

- clone: `git pull` e `pip install .` de novo 📖.
- pipx: `pipx upgrade anamnesia` / `pipx uninstall anamnesia` ⚠️ (só `install` foi executado).
- uv: `uv tool upgrade anamnesia` / `uv tool uninstall anamnesia` ⚠️.

## 6. Problemas?

Veja [TROUBLESHOOTING.md](TROUBLESHOOTING.md). Para entender a arquitetura, o [README](../README.md).
