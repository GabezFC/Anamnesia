# Checklist de publicação (Fase 1)

Estado em 2026-10-07. Fonte do plano: vault `arquitetura/plano-rede-local-multiusuario-tokens-e-acessibilidade.md`.
Evidência: `scripts/scan_publication_safety.py` (relatório local em `reports/`, ignorado pelo Git),
`scripts/gen_third_party_licenses.py`, execuções em Docker.

| Item | Status | Resultado |
|---|---|---|
| T1.1 Scanner de publicação (árvore + histórico) | **feito** | `scripts/scan_publication_safety.py`; 83 commits, 822 arquivos rastreados em ~3 s. 0 chaves reais; 3 `sk-...` são falsos em testes. Ver T1.1a |
| T1.1a Caminhos pessoais na árvore | **árvore saneada em 07/10/2026** (histórico não reescrito: dono decide) | `docs/EXTERNAL_RESEARCH_2026-10-02.md:3`, `docs/QUALITY_5_5.md:11`, `docs/SCOPE_BENCHMARK.md:5,113,114`, `docs/jev_snippet_check.json:2` contêm `C:\Users\<nome>` e o nome da pasta do vault. Presentes também no histórico |
| T1.1b `docs/jev_snippet_check.json` | **removido do índice e ignorado em 07/10/2026** (continua no histórico) | Estava rastreado; contém caminhos e perguntas de notas do vault real (`30-Projetos/<projeto privado>/...`). Mesma classe do `questions.json` removido. Decidir: remover do repo e reescrever histórico, ou aceitar |
| T1.1c `AGENTS.md`/`CLAUDE.md` rastreados | **precisa do dono** | Citam o vault pessoal (`30-Projetos/...`, `Cérebro_AI/AGENTS.md`) e nome de projeto privado. Decidir se ficam públicos |
| T1.1d E-mail pessoal nos metadados dos commits | **precisa do dono** | Autor de todos os commits usa um e-mail pessoal real (`fon***@gmail.com`). Só se resolve com reescrita de histórico ou aceitando |
| T1.1e Arquivos >1 MB / ignorados rastreados | **feito (sem ação)** | Rastreados >1 MB: `data/synthetic_vault/graphify-out/graph.json` (1,34 MB, intencional) e `assets/logo.png` (2,1 MB no histórico). `git ls-files -ci --exclude-standard`: vazio |
| T1.2 `benchmark/questions.json` / `data/vault_mirror` | **feito (verificado)** | Não rastreados hoje e **ausentes de todo o histórico** local e do remoto (`git log --all` e `rev-list --all --objects`: só `questions.example.json`). O commit `aca9c23` citado nas pendências não existe mais: o histórico já foi reescrito (primeiro commit atual `72c9220`) e `origin/main` == `main` local (`f65cc0a`) |
| T1.2a Cópias antigas no GitHub | **precisa do dono** | Commits antigos podem continuar acessíveis por SHA / forks / caches mesmo após reescrita. Pedir ao suporte do GitHub a remoção de objetos órfãos; verificar forks; considerar o conteúdo já exposto (trocar nada que seja segredo; o conteúdo era pessoal) |
| T1.3 Licenças de terceiros | **feito** | `THIRD_PARTY_LICENSES.md` (9 diretas + 34 transitivas, nenhuma sem licença nos metadados); Provence CC BY-NC-ND marcado como opcional e não redistribuído. Regerar com `scripts/gen_third_party_licenses.py` |
| T1.3a Titular em `LICENSE` | **precisa do dono** | Hoje: `Copyright (c) 2026 Memory Gateway contributors` (nome antigo do projeto e titular genérico). Proposta: `Copyright (c) 2026 <nome do dono> e colaboradores do Anamnésia` ou `Copyright (c) 2026 Anamnésia contributors`. Não alterado |
| T1.4 Guia para não desenvolvedores | **feito** | `docs/QUICKSTART.md`, `docs/TROUBLESHOOTING.md`; `README.md` não editado (README ainda diz "Python 3.14" e não menciona `anamnesia doctor`/`pipx`; o dono decide) |
| T1.5 Arquivos de comunidade | **feito, com pendência** | `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, issue templates (bug/feature), PR template. **Precisa do dono:** habilitar *Private vulnerability reporting* no GitHub e definir contato de conduta |
| T1.6 Instalação limpa (Docker) | **feito** | python:3.12-slim e 3.14-slim: `pip install -r requirements.txt`, `pip install .`, `anamnesia version`, `anamnesia doctor` OK; `pipx install git+URL` e `uv tool install` OK. Suíte em contêiner limpo (3.12 e 3.14): 977 passed, 2 failed, 9 skipped em ~28 s; as 2 falhas (`tests/test_budget_and_measurement.py`) são de código de outro trabalho ainda não commitado presente no working tree no momento da cópia, não do instalador (não reexecutado em contêiner depois) |
| T1.6a Dockerfile + compose | **feito** | Construídos; `anamnesia version` e `GET /health` = 200 (healthy); porta só `127.0.0.1:8000:8000`; `Host` estranho → 400; terminais desativados; escrita → 403 (esperado) |
| Visibilidade do repositório | **precisa do dono** | Repo é público (`GabezFC/Anamnesia`, API do GitHub: `visibility: public`). Só o dono decide manter, privar até a limpeza, ou reescrever |
| PyPI | **bloqueado/dono** | Não publicado. Exige conta, nome livre e `uv build`/`twine`; não testado |
| Regenerar relatório antes de publicar | **rotina** | `python scripts/scan_publication_safety.py --fail-on-findings` |
