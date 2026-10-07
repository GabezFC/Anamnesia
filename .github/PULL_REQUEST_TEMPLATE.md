## O que muda e por quê

## Como foi verificado
(comando executado + resultado real; ex.: `python -m pytest tests -q` → N passed)

## Checklist
- [ ] A suíte de testes inteira passa
- [ ] Teste novo cobre a mudança (ou explico por que não)
- [ ] Nenhum segredo, caminho pessoal, `.env`, `.db`, log ou dado derivado de vault real
      (`python scripts/scan_publication_safety.py --no-history`)
- [ ] Dependência nova/alterada: versão fixada, justificada e `THIRD_PARTY_LICENSES.md` regenerado
- [ ] Não enfraquece os padrões de segurança (bind em 127.0.0.1, escrita só loopback, terminais desligados fora de loopback)
- [ ] Documentação atualizada, se o comportamento visível mudou
