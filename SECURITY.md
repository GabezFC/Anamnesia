# Política de segurança

## Como reportar uma vulnerabilidade

**Não abra uma issue pública.** Use o relato privado de vulnerabilidades do GitHub:

1. Abra a aba **Security** do repositório <https://github.com/GabezFC/Anamnesia>.
2. Clique em **Report a vulnerability**.
3. Descreva: o que é, como reproduzir, versão/commit afetado e o impacto que você enxerga.

> Requisito do mantenedor: o recurso "Private vulnerability reporting" precisa estar habilitado em
> *Settings → Code security*. Se o botão não aparecer, abra uma issue pública **sem detalhes técnicos**
> pedindo um canal privado.

Não há e-mail de contato publicado para segurança. Não há SLA formal; é um projeto mantido por poucas
pessoas. A intenção é confirmar o recebimento e dar uma resposta inicial em poucos dias.

## Versões suportadas

Apenas o último commit da branch `main` (projeto em versão `0.x`, sem releases de manutenção).

## Modelo de ameaça (resumo)

- O serviço é pensado para uso **local**: escuta em `127.0.0.1` por padrão.
- Endpoints de escrita recusam qualquer cliente que não seja loopback; há um token local
  (`MG_LOCAL_TOKEN`, criado no primeiro `start`).
- Há proteção de `Host` (anti DNS-rebinding) e cabeçalhos CSP (ver [docs/SECURITY.md](docs/SECURITY.md)).
- Terminais embutidos ficam desligados quando o serviço escuta fora de loopback, a menos que
  `ANAMNESIA_ALLOW_REMOTE_TERMINALS=1` (não recomendado) — ver [docs/TERMINALS.md](docs/TERMINALS.md).
- O serviço **lê** um vault Obsidian seu. O vault e os arquivos derivados dele (bancos, logs, espelhos)
  são privados e não devem ser publicados.

## O que já considerar fora de escopo

- Exposição deliberada do serviço na internet pública sem proxy/autenticação próprios.
- Problemas que exigem acesso local já privilegiado à máquina do usuário.

## Se você publicou um segredo por engano

Revogue/rotacione a chave primeiro, depois limpe o histórico. `scripts/scan_publication_safety.py` ajuda
a achar o que vazou.
