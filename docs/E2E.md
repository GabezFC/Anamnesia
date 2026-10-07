# E2E do Workspace (navegador real + PTY real)

Roda o servidor de verdade (`python -m app.main`), abre Chromium via Playwright e percorre o Workspace.
Não faz parte da CI: o pytest é pulado sem `ANAMNESIA_E2E=1`.

## Pré-requisitos
- Um venv **só para o servidor** com `requirements.txt` + `pywinpty` (Windows):
  `uv venv <dir> --python 3.12 && uv pip install --python <dir>/Scripts/python.exe -r requirements.txt pywinpty`
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
1. `/` abre o Workspace · 2. adiciona projeto (pasta temp com `README.txt`) pela UI · 3. `+ Terminal` (perfil shell),
`echo e2e-anamnesia`, lido de `term.buffer.active` · 4. redimensiona o viewport e compara `mode con` com cols/rows do xterm ·
5. divide o painel com o prefixo (`Ctrl+]` depois `h`) · 6. recarrega: sessão reconecta e o buffer é reexibido ·
7. explorador acha `README.txt` por nome · 8. Conexões: chave fake `sk-test-…` salva, nunca aparece em DOM/inputs/
localStorage/sessionStorage/respostas, depois removida · 9. Config sem erros de console · 10. Custos: `/api/costs/summary` 200 e sem
erros · 11. banner de `/health` (se houver warning) · 12. fecha o terminal e confere que não sobra `cmd.exe`/conhost sob o
servidor (CIM) · 13. servidor parado, porta livre.

O `Terminal` do xterm é capturado por um `add_init_script` que embrulha `window.Terminal` (o app não expõe as instâncias).
`mode con` é localizado (pt-BR: Linhas/Colunas); o regex aceita os dois idiomas. O explorador fica oculto em viewport ≤1100px (CSS).
