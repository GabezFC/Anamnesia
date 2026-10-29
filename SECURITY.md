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
- Há proteção de `Host` (anti DNS-rebinding) e cabeçalhos CSP (ver [docs/guides/SECURITY.md](docs/guides/SECURITY.md)).
- Não existem rotas, WebSocket nem UI de terminal: o PTY é apenas um launcher interno e não visual do
  orquestrador (`ANAMNESIA_DELEGATE_LAUNCHER=terminal`), sem superfície de rede — ver
  Cérebro IA (Anamnesia/Guias-de-usuario-2026-10-24/TERMINALS.md).
- O serviço **lê** um vault Obsidian seu. O vault e os arquivos derivados dele (bancos, logs, espelhos)
  são privados e não devem ser publicados.

### Leituras abertas (o que NÃO é protegido)

Com o bind padrão (`127.0.0.1`), **qualquer processo local** pode chamar as rotas de **leitura** da API
(`/memory/search`, `/benchmark/*`, `/api/costs/*`, `/system/*` …) sem token: o token (`X-MG-Token`) protege
**escrita**. Isso inclui ler trechos do vault via busca. Se `MG_HOST` abrir o serviço para a rede, as leituras
de clientes não-loopback passam a exigir o token (exceto `/health` e o shell estático) — mas o transporte é
HTTP simples, sem TLS. Outros usuários da mesma máquina e qualquer software que rode como você estão
**fora** do modelo de ameaça.

### Tabela de isolamento: hard / soft / best-effort

- **hard** — o código recusa a operação e há teste automatizado; contornar exige mudar o código.
- **soft** — heurística ou modo configurável (`enforce|warn|off`); reduz risco, tem falso negativo/positivo.
- **best-effort** — redução de dano sem garantia; pode falhar sem aviso.

| Controle | Nível | Onde / como | Limite conhecido |
| --- | --- | --- | --- |
| Vault somente leitura | **hard** | `app/services/obsidian.py` (`READ_ONLY_OPERATIONS`; não existe função de escrita); `vault-check` prova por hash | Só vale para o caminho de código do Gateway; um agente com shell pode escrever no vault por conta própria |
| Escrita na API só de loopback + token | **hard** | `require_local_write`: IP loopback + Origin/Referer coerentes + `X-MG-Token` | Qualquer processo local que consiga ler o `.env` obtém o token |
| Anti DNS-rebinding (`Host`) | **hard** | `TrustedHostMiddleware` (`MG_ALLOWED_HOSTS` amplia a lista) | — |
| Leitura exige token fora de loopback | **hard** | `read_auth_required` quando o bind é exposto | Sem TLS |
| Limites de corpo/upload e taxa | **hard** | `request_guards` (413 / 429; `MG_MAX_BODY_BYTES`, `MG_RATE_LIMIT_PER_MIN`) | Taxa por cliente, em memória |
| Guarda de URL de provider (SSRF) | **hard** (modo `enforce`) | `MG_PROVIDER_URL_GUARD`; bloqueia metadata/link-local e hosts não-loopback sem `MG_ALLOW_REMOTE_PROVIDERS=1` | `warn`/`off` desligam |
| Caminhos dos runs de orquestração | **hard** | `safe_join` rejeita `..`, absolutos e symlinks que escapam | — |
| Segredos nunca devolvidos pela API | **hard** | chaves só aparecem mascaradas (`mask_secret`) | O `.env` fica em texto claro (opt-in `MG_SECRETS_BACKEND=keyring`) |
| CSP do dashboard | **hard** no navegador | `app/main.py::_security_headers` | `style-src 'unsafe-inline'`; ver [docs/guides/SECURITY.md](docs/guides/SECURITY.md) |
| Injection screen / `QUARANTINE` | **soft** | JEV strict + `injection_screen`; trecho suspeito é descartado | Heurística/modelo: pode errar nos dois sentidos |
| Recusa de segredo em `memory_save` | **soft** | `scan_secrets` (padrões de token/chave) | Não pega segredo sem padrão conhecido |
| Exec guard (allowlist de executáveis) | **soft** | `ANAMNESIA_EXEC_GUARD`: `enforce` para verifiers, `warn` (padrão) para launchers de terminal | Allowlist por nome de executável; um interpretador permitido executa qualquer coisa |
| Guarda de projetos | **soft** | `ANAMNESIA_PROJECT_GUARD=enforce` (padrão) recusa diretórios sensíveis; `MG_PROJECT_ROOTS` restringe | Lista de diretórios sensíveis é heurística |
| Fundamentação do `mode=answer` | **soft** | `check_grounding` lexical | Prova reuso de termos, não implicação lógica |
| Redação de logs e caminhos | **best-effort** | `MG_LOG_REDACT`, `MG_REDACT_PATHS` (`lan` por padrão) | Regex; formatos novos de segredo escapam |
| Limites do PTY (Job Object / rlimits) | **best-effort** | `MG_PTY_LIMITS`, `MG_PTY_AGENT_IDLE_SECONDS` | Contém fork-bomb/ociosidade, **não é sandbox** |
| Ambiente do PTY | **best-effort** | remove tokens conhecidos (`ENV_NEVER`); `MG_PTY_NO_HOME` | Lista fixa; o agente roda com seus privilégios |

Regra de documentação: não descreva um controle **soft** ou **best-effort** como garantia. Ao mudar o nível de
um controle, atualize esta tabela, `CLAUDE.md`/`AGENTS.md` e o teste correspondente.

## O que já considerar fora de escopo

- Exposição deliberada do serviço na internet pública sem proxy/autenticação próprios.
- Problemas que exigem acesso local já privilegiado à máquina do usuário.

## Se você publicou um segredo por engano

Revogue/rotacione a chave primeiro, depois limpe o histórico. `scripts/scan_publication_safety.py` ajuda
a achar o que vazou.

## Auditoria executável (fases 9 e 14)

Três scripts herméticos (porta efêmera, `ANAMNESIA_HOME` descartável, vault sintético, sem rede nem segredos reais):
`python scripts/mcp_protocol_audit.py` (protocolo MCP/stdio), `python scripts/cli_audit.py` (CLI) e
`python scripts/security_audit.py` (scanner de segredos, loopback/token/Origin/Host, limite de corpo, cabeçalhos, publicação).
Resultado e achados: nota fase9_fase14_mcp_cli_seguranca.md no Cerebro IA (Anamnesia/Migracao-docs-repo-2026-10-24).

Limites conhecidos confirmados pela auditoria (não descreva como garantia):

- `scan_secrets` pega ofuscação Unicode (fullwidth, zero-width, ZWJ, soft-hyphen) mas **não** pega segredo em
  base64/hex, com espaço entre caracteres, ROT13 ou dividido por quebra de linha.
- Notas gravadas por `memory_save` sob `MG_SCOPE=projeto:X` recebem `projeto: X` no frontmatter, mas a busca
  escopada considera esse `projeto:` (achado F9-01, **resolvido**): a nota é recuperada só no próprio projeto e em buscas
  sem escopo; outro projeto e notas sem `projeto:` ficam de fora de buscas `projeto:X`.
