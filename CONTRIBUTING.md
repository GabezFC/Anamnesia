# Contribuindo com o Anamnésia

Obrigado por querer ajudar. Este guia é curto de propósito.

## Antes de começar

- Procure uma issue existente; se não houver, abra uma (modelos em `.github/ISSUE_TEMPLATE/`).
- Mudanças grandes (arquitetura, novos endpoints, novas dependências): abra a issue **antes** do PR.
- Vulnerabilidades: **não** abra issue pública. Veja [SECURITY.md](SECURITY.md).

## Ambiente de desenvolvimento

Requer Python >= 3.12 (o CI roda 3.14).

```bash
git clone https://github.com/GabezFC/Anamnesia.git
cd Anamnesia
python -m venv .venv
# Linux/macOS: source .venv/bin/activate     Windows (PowerShell): .venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests -q -p no:cacheprovider --no-header
```

Os testes não usam rede, API paga, binário `graphify` nem o seu vault real: tudo é simulado
(`tests/conftest.py`). Se um teste novo precisar de qualquer um deles, ele está errado.

## Regras que valem para todo PR

1. **Dados pessoais fora do repositório.** Nada derivado de um vault real: nem `benchmark/questions.json`,
   nem `data/vault_mirror`, bancos `.db`, logs, `.env`, caminhos absolutos pessoais, nomes de notas
   reais. Use o corpus sintético (`data/synthetic_vault`). Rode antes de abrir o PR:
   `python scripts/scan_publication_safety.py --no-history`
2. **Sem segredos.** Chaves em testes devem ser claramente falsas.
3. **Teste junto com a mudança.** Bug corrigido = teste que falhava antes; recurso novo = teste do
   comportamento. A suíte inteira deve passar.
4. **Dependências**: versões fixas (`==`) em `requirements.txt` e em `pyproject.toml`, e justificativa
   no PR. Regenere `THIRD_PARTY_LICENSES.md` com `python scripts/gen_third_party_licenses.py`.
5. **Segurança por padrão**: o serviço escuta só em `127.0.0.1`; escrita só de loopback. Não enfraqueça
   isso sem discussão prévia.
6. **Commits pequenos e descritivos** (o histórico usa prefixos como `fix(...)`, `feat(...)`, `docs(...)`).

## Abrindo o PR

Preencha o modelo do PR. Diga o que mudou, por quê, e como você verificou (comando + resultado real).
Não afirme "funciona" sem ter rodado.

## Licença

Ao contribuir você concorda que sua contribuição é licenciada sob a licença MIT do projeto (`LICENSE`).
