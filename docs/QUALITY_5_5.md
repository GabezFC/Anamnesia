# §5.5 / §5.8 — PPR, recorte do JEV, sweep do pré-filtro, CI

Medições reais, geradas pelos scripts descritos abaixo (`scripts/bench_ppr.py`,
`scripts/check_jev_snippet.py`, `scripts/sweep_prefilter.py`). Nenhum número aqui foi estimado —
onde algo não foi medido, está escrito "não medido". JSON bruto de cada corrida fica em
`docs/ppr_bench.json`, `docs/jev_snippet_check.json`, `docs/prefilter_sweep.json`.

Corpora usados:
- **synthetic** — `data/synthetic_vault` (bundled) + `benchmark/synthetic_questions.json` (120
  perguntas, 110 respondíveis, 10 `qclass=multi_hop`).
- **real** — vault `C:/Users/fonse/Cérebro_AI` (somente leitura) + `benchmark/questions.json` do
  repositório principal (12 perguntas, 10 respondíveis, 1 "cruzamento"/multi-fonte: q09).

Bug encontrado e corrigido durante a medição: `data/vault_mirror` é compartilhado entre qualquer
vault passado a `RetrievalConfig` (o caminho não depende do vault), e `MemoryGateway.warm()`
absorve silenciosamente uma falha de `graphify update` (comportamento correto em produção — o
gateway não deve cair por causa do grafo opcional). Isso significa que, num script que troca de
vault entre chamadas, uma falha silenciosa deixaria o `graph.json` do vault ANTERIOR no lugar sem
erro nenhum. Os três scripts agora verificam, após `warm()`, se o primeiro nó do grafo carregado
pertence de fato ao vault pedido; se não, forçam `graphify.build(force=True)` e recarregam. Os
números abaixo foram coletados já com essa verificação ativa (grafo real confirmado: 1420 nós /
1760 arestas, `source_file` resolvendo dentro do vault real).

A geração de candidatos (`_graphify_candidates(..., allow_ppr=False)`, o BM25 + expansão de grafo
inteiro) é a parte cara e determinística: `scripts/check_jev_snippet.py` e `scripts/sweep_prefilter.py`
passam por `scripts/_candidate_cache.py`, que guarda `uniq` em
`data/cache/candidates/<sha1(fingerprint+pergunta)>.pkl`. A fingerprint cobre (caminho relativo,
mtime_ns, tamanho) de cada `.md` do vault mais o mtime de `graphify-out/graph.json`, então editar
uma nota ou rebuildar o grafo invalida tudo. `--no-cache` nos dois scripts desliga.

## Parte 1 — PPR (HippoRAG-style), §5.5

`app/retrieval/ppr.py`: power iteration pura em Python (sem dependência nova) sobre o `adj` que
`GraphIndex` já carrega. Sementes = arquivos retornados pelo BM25 do próprio híbrido, peso
proporcional ao score (piso 1e-4 para sempre ter massa positiva). Atrás de `PPR_ENABLED=false`
(default): com a flag desligada a saída é idêntica à BFS, byte a byte (`tests/test_ppr.py`, 6/6
verdes, incluindo o teste que trava `graphify_jev` para nunca chamar PPR mesmo com a flag ligada).

Integração: `app/retrieval/graphify_hybrid.hybrid_search` ganhou `allow_ppr` (default `True`);
quando `rc.ppr_enabled` e `allow_ppr`, a expansão de grafo usa `ppr.expand` em vez de `GraphIndex.expand`
(BFS) e o metric `graphify_expand_mode` passa a `"ppr"`. `run_graphify_jev` chama
`_graphify_candidates(..., allow_ppr=False)` explicitamente — o pipeline congelado nunca usa PPR,
independente da flag (testado).

### Recall e custo, pipeline `graphify`, sem LLM (`scripts/bench_ppr.py`)

| corpus | arm | recall geral | recall completo | recall COMPLEX/multi-hop | tokens médios | latência mediana |
|---|---|---|---|---|---|---|
| synthetic (110 resp., 10 multi_hop) | BFS (atual) | 90.45% | 95/110 | 55.0% (1/10 completo) | 1175.5 | 3.0 ms |
| synthetic | PPR | 90.45% | 95/110 | 55.0% (1/10 completo) | 1175.7 | 51.5 ms |
| real (10 resp., 1 "cruzamento") | BFS (atual) | 100% | 10/10 | 100% (1/1) | 2076.5 | 14.1 ms |
| real | PPR | 100% | 10/10 | 100% (1/1) | 2076.5 | 38.6 ms |

PPR não mudou o recall em nenhum corpus, nem geral nem no subconjunto COMPLEX/multi-hop — nem para
melhor nem para pior (os conjuntos de arquivos entregues saem quase idênticos; só a ordem/pontuação
interna dos candidatos de grafo muda, e ambos são cortados pelos mesmos `max_results`/seeds de BM25).
O custo é só latência: ~17x no corpus sintético (power iteration roda do zero a cada query, sem
cache) e ~3x no real. `total_tokens_spent` não muda de forma relevante.

**Recomendação:** manter `PPR_ENABLED=false`. A implementação fica pronta, testada e atrás da flag
para o caso de um grafo com estrutura diferente (mais arestas cruzadas entre notas, comunidades mais
ricas) se beneficiar dela no futuro, mas nos dois corpora disponíveis hoje ela não recupera nenhuma
pergunta multi-hop que a BFS já não recuperasse, e adiciona latência sem compensação.

## Parte 2 — Recorte enviado ao JEV, §5.5 item 2 (`scripts/check_jev_snippet.py`)

Reconstrução real (não aproximada): roda `_graphify_candidates(..., allow_ppr=False)` +
`prefilter()` de produção — o snippet inspecionado é exatamente o que `run_graphify_jev` mandaria
para o juiz, já truncado em `SNIPPET_MAX_TOKENS` (300).

| qid | fonte esperada sobrevive ao pré-filtro? | seção escolhida | tokens do snippet | contém a evidência? | onde a evidência está na nota |
|---|---|---|---|---|---|
| q05 | sim (8/25 enviados ao JEV) | "Licenças de software — o caso Redis e Valkey" (seção-título) | 15 | **não** (0/28 termos) | `... > Conteúdo > 1. Os três grupos de licença` (linha 27, 27/28 termos) |
| q07 | sim (8/25) | "Ambiente local (Windows + MSYS) — armadilhas verificadas" (seção-título) | 59 | **não** (1/25 termos) | `... > 1. "pnpm: command not found" ...` (linha 20, 24/25 termos) |
| q10 | sim (8/25) | "12 — Decisão de VPS e Custos > Decisão pendente" | 63 | **não** (1/11 termos) | `... > 🔴 Três armadilhas ... > 1. "R$ 59,99/mês" não é mensalidade` (linha 45, 8/11 termos) |

Achado consistente nas 3 perguntas: o ARQUIVO certo sempre sobrevive ao pré-filtro e chegaria ao
JEV, mas a SEÇÃO escolhida pelo candidato (a que o BM25 casou — tipicamente o título/seção de
entrada da nota) não é a seção que contém a evidência. A evidência mora numa subseção mais profunda
da mesma nota, que o candidato de texto não captura (ele é só a seção com match lexical, truncada a
300 tokens). Isso é consistente com o padrão já documentado em `app/retrieval/graphify_hybrid.py`:
candidatos de texto trazem só a seção casada, não a nota inteira; só sobreviventes do JEV recebem
`full_note_text`. Ou seja: o JEV decide com um recorte que estruturalmente não contém a resposta —
se ele aprovar a nota mesmo assim (por sinal fraco de título/caminho), a resposta final só aparece
porque `full_note_text` busca a nota inteira DEPOIS da aprovação; se o JEV reprovar por falta de
evidência no recorte, a nota correta é descartada mesmo estando no vault.

**Recomendação (fora do escopo desta tarefa, registrar para follow-up):** o recorte do pré-filtro
poderia incluir, além da seção casada pelo BM25, um resumo/cabeçalhos das demais seções da mesma
nota (ainda dentro do orçamento de 300 tokens), para o JEV não julgar "não relevante" uma nota cuja
única seção visível é um título genérico.

## Parte 2b — Correção (§5.5 item 2, TAREFA J)

`graphify_jev` continua congelado — nada em `app/retrieval/pipelines.py` ou
`app/services/dedup.py` (`preprocess`) foi tocado; a tabela "frozen" abaixo é idêntica à da Parte 2.
A pergunta era se `graphify_jev_opt` (que já roda `snippet.extract`/`fit_or_keep` atrás da flag
`OPT_SMART_SNIPPET`, ligada em `OptimizationConfig.default_cascade()`) também errava a seção.
`scripts/check_jev_snippet.py --path opt` (novo) mede isso reusando `app.retrieval.pipelines_opt`
real: extraí as etapas livres (`select_pool`, antes do estágio pago) para o script e para
`run_graphify_jev_optimized` chamarem o MESMO código — não uma reimplementação.

**Resposta: sim, errava — e por duas causas distintas em `fit_or_keep`/`extract`, não por falta de
qualidade do algoritmo de janela.** `extract()` já ancora corretamente na seção certa mesmo com
poucos tokens de orçamento (linha "seed" é escolhida em TODA a nota, não só perto do início). Os dois
bugs reais, medidos em `app/services/snippet.py`:

1. **Regra 2 (STRICT IMPROVEMENT) só perguntava "ficou mais barato?"** — nunca "ficou melhor?". Um
   candidato cujo snippet original já era minúsculo (um título) tem `effective = min(budget,
   current_cost)` também minúsculo; o recorte correto, no MESMO preço, não "economiza" tokens o
   suficiente para passar o `min_saving`, e era descartado mesmo sendo estritamente mais relevante.
   Corrigido: aceita o recorte quando ele cobre estritamente mais termos da query que o atual, ao
   MESMO custo ou menor — nunca mais caro (`effective` já garante isso; Regra 1 intocada).
2. **O prefixo de heading (redundante com o campo `section` já enviado ao juiz separadamente, ver
   `JevClient.candidate_payload`) consumia sozinho o orçamento inteiro** em candidatos pequenos
   (15–63 tokens), e a Regra 3 (não perder evidência) contava palavras genéricas do TÍTULO (ex.:
   "software" em "Licenças de software...") como "evidência", vetando a realocação. Corrigido:
   heading é descartado quando custaria mais da metade do orçamento disponível, e termos que só
   batem no heading não contam para a Regra 3 (o juiz já os vê via `section` de qualquer forma).

Efeito colateral encontrado e corrigido: o ramo de early-return de `extract()` truncava para um piso
interno de busca (`max(16, max_tokens - reserve)`), não para o `max_tokens` do chamador — violava o
próprio contrato da função em orçamentos pequenos (`<~20` tokens). `SNIPPET_POLICY_VERSION` subiu
para `"snip-v2"` (invalida o cache de snippet existente).

### Antes/depois por caminho, vault real, mesmas 3 perguntas

| qid | caminho | estratégia | tokens do snippet | termos de evidência no snippet |
|---|---|---|---|---|
| q05 | frozen (congelado, sem mudança) | — | 15 | 0/28 |
| q05 | opt — antes da correção | kept (idêntico ao frozen) | 15 | 0/28 |
| q05 | opt — depois | **relocated** | 15 | 0/28 |
| q07 | frozen | — | 59 | 1/25 |
| q07 | opt — antes | kept (idêntico ao frozen) | 59 | 1/25 |
| q07 | opt — depois | kept (`kept_evidence_loss` evitado, mas sem ganho — ver limitação) | 59 | 1/25 |
| q10 | frozen | — | 63 | 1/11 |
| q10 | opt — antes | kept (idêntico ao frozen) | 63 | 1/11 |
| q10 | opt — depois | **relocated** | 60 | **2/11** |

Honestidade sobre o resultado: q05 agora ancora corretamente na subseção certa (`## Conteúdo ### 1.
Os três grupos de licença`, confirmado inspecionando o texto do snippet), mas o orçamento efetivo
(`min(budget, current_cost)` = 15 tokens, porque o candidato original já era só o título) é pequeno
demais para caber qualquer linha da tabela de evidência — a seção está certa, o ORÇAMENTO do
candidato não é suficiente para carregar a resposta, e nenhuma mudança dentro de `fit_or_keep` pode
resolver isso sem violar a Regra 1 (ceiling), que é testada e intencional
(`test_fit_or_keep_is_never_worse_than_the_baseline_at_any_budget`). Na produção, o estágio pago de
`progressive_context` (`expand`, até 600 tokens) pode recuperar esse caso quando o primeiro veredito
do juiz cai na banda ambígua — mas isso é pago e este script nunca chama o juiz, então não é medido
aqui. q10 melhora de verdade (conteúdo relevante sobre o preço promocional agora visível). q07
permanece bloqueado: a palavra "corrigido" da query também aparece no parágrafo de abertura genérico
da nota ("Cada item aqui foi **reproduzido e corrigido**"), fora do heading, então a Regra 3 (que
não foi enfraquecida além da exclusão de heading, de propósito, para não reabrir a regressão sq070)
ainda veta a realocação — um falso positivo da mesma proteção que intencionalmente barra perdas de
evidência reais.

### Corpus sintético, antes/depois (120 perguntas, 110 respondíveis com `expected_sources`)

Medido com `select_pool(..., opt=OptimizationConfig.default_cascade())` sobre todas as perguntas
respondíveis, comparando a implementação anterior de `fit_or_keep`/`extract` (reconstruída à parte,
sem tocar o módulo real) contra o código atual:

| | perguntas que chegam ao JEV (recall) | termos de evidência cobertos (soma) | tokens de snippet (soma) |
|---|---|---|---|
| antes | 104/110 | 797/1186 (0.672) | 9618 |
| depois | 104/110 (**sem queda**) | 806/1186 (0.680, **+9**) | 9534 (**-84, -0.9%**) |

Recall (quantas perguntas têm a fonte esperada sobrevivendo ao pré-filtro) não mudou — a correção
atua só DEPOIS do candidato já estar no pool, nunca na decisão de quem entra. O ganho é pequeno no
agregado porque só uma minoria dos 110 candidatos tem a patologia "snippet original = só o título";
nos que têm, o ganho de evidência é real (q10 acima) e nunca aumenta o custo em tokens.

## Parte 3 — Sweep de PREFILTER_TOP_K / PREFILTER_LEXICAL_WEIGHT (`scripts/sweep_prefilter.py`)

"Recall do pré-filtro" = a fonte esperada sobrevive ao corte determinístico (chegaria ao JEV),
medido com os candidatos reais (BM25 + grafo, `allow_ppr=False`) e o `prefilter()` de produção —
zero chamadas ao juiz.

### Synthetic (110 perguntas respondíveis com `expected_sources`)

| K \ W | 0.0 | 0.15 | 0.3 (default) | 0.5 | 0.7 |
|---|---|---|---|---|---|
| 4  | 90.00% (94/110) | 90.00% | 90.00% | 90.00% | 89.09% (93/110) |
| 6  | 90.45% (95/110) | 90.45% | 90.45% | 90.45% | 90.45% |
| **8 (default)** | **90.45%** | **90.45%** | **90.45%** | **90.45%** | **90.45%** |
| 10 | 90.45% | 90.45% | 90.45% | 90.45% | 90.45% |
| 12 | 93.18% (101/110) | 93.18% | 93.18% | 93.18% | 93.18% |
| 16 | 94.09% (103/110) | 94.09% | 94.09% | 94.09% | 94.09% |
| 20 | 94.55% (104/110) | 94.55% | 94.55% | 94.55% | 94.55% |

### Real (10 perguntas respondíveis com `expected_sources`)

| K \ W | 0.0 | 0.15 | 0.3 (default) | 0.5 | 0.7 |
|---|---|---|---|---|---|
| 4  | 96.67% (9/10) | 96.67% | 96.67% | 96.67% | 70.00% (7/10) |
| 6  | 96.67% | 96.67% | 96.67% | 100% (10/10) | 80.00% (8/10) |
| **8 (default)** | **100%** | **100%** | **100%** | **100%** | **100%** |
| 10 | 100% | 100% | 100% | 100% | 100% |
| 12 | 100% | 100% | 100% | 100% | 100% |
| 16 | 100% | 100% | 100% | 100% | 100% |
| 20 | 100% | 100% | 100% | 100% | 100% |

Observações:
- O peso lexical (`W`) não muda o recall do pré-filtro em NENHUM `K >= 6` em nenhum dos dois
  corpora — os empates são resolvidos de forma diferente, mas o conjunto de arquivos que sobrevive
  é o mesmo. Em `K=4`, `W=0.7` (peso lexical dominante) piora o recall nos dois corpora (89.09% e
  70.00% respectivamente): com poucos slots, dar peso demais ao match lexical bruto desloca a fonte
  certa por notas com match de caminho/título mas sem o conteúdo.
- No corpus real, o default (K=8, W=0.3) já está no teto (100%) — não há o que ganhar subindo K.
- No corpus sintético, subir K de 8 para 20 recupera 9 perguntas a mais (90.45% → 94.55%), um ganho
  real e mensurável. Mas subir K não é de graça: o pré-filtro existe justamente para limitar quantos
  candidatos custam tokens de juiz (`app/services/prefilter.py`) — K=20 manda 2.5x mais candidatos
  para o JEV que K=8.

**Recomendação:** manter os defaults (`PREFILTER_TOP_K=8`, `PREFILTER_LEXICAL_WEIGHT=0.3`). O
corpus real (o que importa em produção) já está no teto no default; o ganho medido no corpus
sintético é real mas vem com custo de tokens de juiz proporcional, e a tarefa pede para só mudar
default com "ganho claro sem perda" — aqui há ganho num corpus e custo real (não testado em tokens
de JEV de verdade, só em volume de candidatos), então a troca não é claramente livre de perda. Se a
prioridade mudar para recall sobre custo, K=12 é o primeiro ponto de ganho visível (93.18% no
sintético, sem perda no real).

## Parte 4 — CI, §5.8

`.github/workflows/ci.yml`: ubuntu-latest, Python 3.11 (`pip install -r requirements.txt -r
requirements-dev.txt`, `pytest tests -q`) + Node 20 (`node scripts/check_frontend_imports.mjs`,
`node scripts/check_frontend_resilience.mjs`). `tests/conftest.py` já declara que a suíte não toca
rede, API da TypeSafe, binário do graphify nem o vault real (tudo mockado) — confirmado rodando
`pytest tests -q` localmente (480 passed, nenhum marcador `@pytest.mark.integration` no repo, nada
para pular condicionalmente). `scripts/check_frontend_charts.mjs` e
`scripts/check_flow_dimming.mjs` também não precisam de navegador, mas ficaram fora do escopo desta
tarefa (só os dois nomeados foram pedidos); nenhum script atual do projeto precisa de servidor vivo
ou Chrome — `scripts/mcp_smoke.py` é o único candidato a isso e não foi incluído.
