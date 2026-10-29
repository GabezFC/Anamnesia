# E2E do Workspace (navegador real)

Roda o servidor de verdade (`python -m app.main`), abre Chromium via Playwright e percorre o Workspace.
Não faz parte da CI: o pytest é pulado sem `ANAMNESIA_E2E=1`.

## Pré-requisitos
- Um venv **só para o servidor** com `requirements.txt`:
  `uv venv <dir> --python 3.12 && uv pip install --python <dir>/Scripts/python.exe -r requirements.txt`
- Um Python com `playwright` e Chromium (`playwright install chromium`).
- Porta 8123 livre (`E2E_PORT` muda; nunca use 8000).

## Executar
```
E2E_SERVER_PYTHON=<venv-servidor>/Scripts/python.exe \
  <python-playwright> scripts/e2e_workspace.py [--out DIR] [--headed] [--stop-on-fail]
# ou, via pytest:
ANAMNESIA_E2E=1 E2E_SERVER_PYTHON=... <python-playwright> -m pytest tests/e2e -q
```
Screenshots e `server.log` vão para `$TMPDIR/e2e` (ou `--out`). Código de saída 0 = tudo passou.

## Isolamento
`ANAMNESIA_HOME` = diretório temporário novo (token, `.env`, banco descartáveis); `MEMORY_GATEWAY_VAULT` =
`data/synthetic_vault`; `ANAMNESIA_ROUTING` removido do ambiente; `PORT=8123`. O `.env` real nunca é lido.
O servidor e a árvore de filhos são encerrados num `finally` e a porta é conferida ao final.

## Passos
1. `/#/workspace` abre o Workspace (e não há UI de terminal) · 2. adiciona projeto (pasta temp com `README.txt`) pelo modal ·
3. o explorador acha `README.txt` por nome · 4. recarrega: o projeto persiste · 5. remove o projeto (confirmação) e confere que a
pasta física continua intacta · 6. Conexões: chave fake `sk-test-…` salva, nunca aparece em DOM/inputs/localStorage/sessionStorage/
respostas, depois removida · 7. Config sem erros de console · 8. Custos: `/api/costs/summary` 200 e sem erros · 9. banner de
`/health` (se houver warning) · 10. servidor parado, porta livre.

O terminal embutido (xterm.js) foi removido da UI; os passos antigos de terminal/resize/split/órfãos saíram deste roteiro.
O explorador fica oculto em viewport ≤1100px (CSS). O script não foi executado nesta limpeza (Playwright ausente no `.venv`).
