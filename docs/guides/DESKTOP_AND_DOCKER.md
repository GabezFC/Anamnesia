# Executável (Windows) e Docker

## Executável sem terminal
    .venv/Scripts/python.exe -m pip install pyinstaller
    .venv/Scripts/python.exe packaging/build_exe.py          # -> dist/Anamnesia/Anamnesia.exe (--onefile opcional)
Dê dois cliques em `Anamnesia.exe`: sobe o servidor local (só loopback), espera `/health` e abre o navegador. Se já
houver uma instância na porta (`PORT`, padrão 8000), apenas abre o navegador. Dados e `.env` ficam em
`%LOCALAPPDATA%\Anamnesia` (ou `ANAMNESIA_HOME`), logs em `logs\launcher.log`. Para encerrar: finalize `Anamnesia.exe`
no Gerenciador de Tarefas. O exe não é assinado: o SmartScreen pode avisar.

## Docker
    docker compose up -d --build                                  # imagem de produção em 127.0.0.1:8000
    docker compose -f docker-compose.test.yml run --rm py312      # suíte completa em Python 3.12 (py313, py314)
O Linux dos contêineres exercita o caminho POSIX de PTY que o Windows pula. Use `--init` ao rodar a suíte à mão.
