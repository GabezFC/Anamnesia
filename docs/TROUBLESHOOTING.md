# Solução de problemas

Comece sempre por `anamnesia doctor` (offline, não mostra segredos). Legenda: ✅ reproduzido/executado ·
📖 lido do código · ⚠️ não verificado.

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `anamnesia: command not found` | A pasta de scripts do pip/pipx/uv não está no `PATH`, ou o venv não está ativo | Ative o venv; ou use `python -m anamnesia doctor` ✅; com pipx/uv rode `pipx ensurepath` / `uv tool update-shell` ⚠️ |
| `pip install anamnesia` → "No matching distribution" | O pacote **não está no PyPI** | Instale pelo GitHub: `pipx install git+https://github.com/GabezFC/Anamnesia.git` ✅ |
| `requires a different Python` / erro de versão | Python < 3.12 | Instale Python 3.12+ (`python --version`) 📖 (`doctor`: linha `python` = `FAIL`) |
| `doctor`: `vault  FAIL  ... exists=no` | `MEMORY_GATEWAY_VAULT` aponta para pasta inexistente ✅ | Corrija o caminho ou apague a variável para usar o corpus de exemplo |
| Erro de que o vault é o próprio repositório / o banco ficaria dentro do vault | Proteção de segurança 📖 | Aponte para o vault real, fora da pasta do projeto |
| `doctor`: `port 8000  warn  in use` ✅ | Outro programa (ou um contêiner Docker do Anamnésia) usa a 8000 | Feche-o. A porta é fixa em 8000 no `doctor`; o serviço lê `PORT` (padrão 8000, `config/benchmark.py`) 📖, então com `PORT` diferente o `doctor` ainda checa a 8000 |
| `doctor`: `TYPESAFE_API_KEY  warn  no` | Sem chave do juiz pago | Normal. A busca básica não precisa. Para os pipelines pagos, ponha a chave no `.env` (modelo: `.env.example`), nunca no Git |
| `doctor`: `graphify  warn  not found` | `graphify` é opcional | Ignore; o `/health` avisa que os pipelines de grafo degradam, o padrão `auto` continua funcionando ✅ |
| `doctor`: `local token ... (created on first start)` | Token local ainda não existe | Rode `anamnesia start` uma vez 📖 |
| Navegador: `400 Bad Request` ao abrir pelo nome da máquina/IP | Proteção anti DNS-rebinding só aceita `localhost`/`127.0.0.1` ✅ | Acesse por `http://127.0.0.1:8000`. Para outro nome: `MG_ALLOWED_HOSTS=nome1,nome2` 📖 (entenda o risco) |
| `403 acesso restrito a 127.0.0.1/::1` em POST | Endpoints de escrita só aceitam loopback ✅ | Rode no mesmo computador. Em Docker isso é esperado (cliente chega pela ponte do Docker) ✅ |
| Terminais: `403 terminals_disabled` / WebSocket fecha 4403 | Terminais só ligam com bind em loopback 📖 | Rode localmente (sem `MG_HOST=0.0.0.0`). `ANAMNESIA_ALLOW_REMOTE_TERMINALS=1` destrava, mas dá acesso de shell a quem alcançar a porta: evite. Ver `docs/TERMINALS.md` |
| Windows: `pywinpty (optional)  warn  no` | Terminais no Windows precisam do `pywinpty` | `pip install "anamnesia[terminal]"` (a partir do clone: `pip install ".[terminal]"`) 📖 ⚠️ |
| Acesso pela rede não funciona | Padrão é só loopback; firewall | `MG_HOST=0.0.0.0` no `.env` expõe o serviço à rede local: leia `docs/SECURITY.md` antes. O `start` imprime a regra de firewall sugerida (não é aplicada sozinha) 📖 |
| Docker: contêiner reinicia / `unhealthy` | Veja `docker compose logs` | Reconstrua: `docker compose build --no-cache`. Se o erro for de banco, apague o volume `anamnesia-data` (perde dados locais do contêiner) |
| `pip install` demora/erra com muitas dependências | Rede ou versão fixada indisponível | Tente de novo; mantenha o pip atualizado (`python -m pip install -U pip`) ⚠️ |
| Testes falham no seu clone | Ver ambiente (Python, deps de dev) | `pip install -r requirements.txt -r requirements-dev.txt` e `python -m pytest tests -q -p no:cacheprovider --no-header` |

## Pedindo ajuda

Abra uma issue (modelo "Relato de bug") com a saída de `anamnesia doctor` e `anamnesia version`.
**Nunca** cole chaves, tokens ou conteúdo do seu vault. Vulnerabilidades: [SECURITY.md](../SECURITY.md).
