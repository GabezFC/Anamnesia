# JEV local via Colibrì (ANAM-041)

O Colibrì expõe `POST /v1/systemone` com a mesma requisição/resposta do TypeSafe Jev. O Anamnésia usa o mesmo
`TypeSafeBackend` (SDK `typesafe_sdk`) e basta apontar `TYPESAFE_BASE_URL` para loopback.

## Configurar
```
TYPESAFE_BASE_URL=http://127.0.0.1:8000     # ou http://localhost:8000
TYPESAFE_LOCAL_API_KEY=                     # opcional; = COLI_API_KEY do servidor, se ele tiver uma
JEV_FAILURE_MODE=                           # vazio => fail_closed automático no modo local
```
- `TYPESAFE_API_KEY` **não é exigido** em loopback (se definida, tem prioridade sobre a chave local). Sem nenhuma,
  o SDK recebe a chave `local` (o SDK exige chave não vazia; o Colibrì sem `COLI_API_KEY` aceita qualquer).
- Egress: loopback é destino local — passa por `check_egress` mesmo em `OFFLINE=1` e sem allow-list. Hosts não
  loopback seguem `https` + `ANAMNESIA_EGRESS_ALLOW_HOSTS`. Não é egress remoto.
- Falha: se o servidor local não responde, o lote vira `UNJUDGED`; com `fail_closed` (default aqui) esses
  candidatos **não** sobrevivem. Defina `JEV_FAILURE_MODE=fail_open` para escolher o contrário.
- `/api/jev` status/test: `local: true`, estado não fica `not_configured` sem chave; o teste usa `GET /v1/models` + `POST /v1/systemone`.

## Compatibilidade do contrato (lido em Colibri `docs/systemone.md`)
Igual: `state`, `questions` (1–64) com `type` noul/choice/score, `instructions`, `criteria`; resposta `answers`
(`noul`, `choice`+`probabilities`+`confidence`, `score`+`legend`), `usage`, `model`; rotas `/v1/systemone` e `/v1/models`;
auth `Authorization: Bearer` (o SDK envia; Colibrì aceita Bearer).
Diferenças reais:
- `provider="colibri"`, `usage.cost=0`, `output_tokens` = tokens de opção *lidos*; `model` é o modelo servido (aceita qualquer nome, `jev-latest`).
- Probabilidades são do modelo local (normalização `sum`), **não batem** com as do Jev; limiares do Anamnésia (`JEV_RELEVANCE_THRESHOLD` etc.) foram calibrados para o Jev.
- Opcionais só do Colibrì (`normalize`, `pin_state`, `prefix`, `cache_slot`): o Anamnésia **não os envia**; o servidor decide sozinho (foto do state automática quando ≥2 perguntas leem o mesmo state — o que o batching do JEV já faz).
- Erros de validação: 422 com envelope próprio + `detail` do Jev. `x-api-key`: não usado pelo SDK 0.7.1 (só Bearer) — não verificado.

## Ressalvas
- **Qualidade não medida**: nenhum benchmark do Anamnésia (relevância/injeção) foi rodado com Colibrì; não assuma paridade com o Jev.
- Latência: um LLM grande (ex. 125B/35B em CPU, minutos por pedido segundo a doc) é muito mais lento que modelos de decisão
  (Laya/GLiNER/Clef), que não geram tokens. Para triagem em volume prefira um motor de decisão; use LLM grande só onde a precisão justificar.
- Testes usam servidor HTTP falso (`tests/test_anam041_jev_local.py`); o Colibrì real não foi iniciado.
