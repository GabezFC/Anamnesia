# PERSISTENT_MEMORY_AUDIT.md

Auditoria da memória persistente do Memory Gateway. Todos os números abaixo são **medidos**, com o
código deste commit, nos dois corpora. Fonte primária: `reports/memory_benchmark_2026-10-01.json`
(benchmark) e `reports/memory_audit_2026-10-01.json` (auditoria do vault real).
Regra: nada aqui é projeção. Onde a medição não existe, o texto diz que não existe.

Corpora usados: sintético (`data/synthetic_vault`, 520 notas, 120 perguntas) e real
(`$MEMORY_GATEWAY_VAULT`, 135 notas indexáveis, 12 perguntas). O vault real é **somente leitura**.

## Current Memory Architecture
Vault Obsidian em markdown (fonte da verdade, somente leitura) → índice FTS5 em memória
(`BaselineIndex`, reconstruído por fingerprint) + `graphify-out/graph.json` via `graphify_hybrid` →
`MemoryGateway.search()` → Memory Optimization Layer (`app/gateway/optimizer.py`: corte adaptativo,
near-dup, flag de injeção, temporalidade, conflito, proveniência) → `ContextBuilder` → consumidor.
`benchmark.db` guarda o histórico de execuções e é lido pela auditoria em `mode=ro`.
A camada de memória é a única parte do Gateway que conhece *metadados* de nota; ela não conhece
Graphify, JEV nem modelos.

## Data Sources
- Vault real apontado por `MEMORY_GATEWAY_VAULT` (ou `--vault`). Nunca escrito.
- `data/synthetic_vault/` — 520 notas, 110 fatos com token de resposta e `MANIFEST.json`.
- `benchmark/questions.json` (12 perguntas do vault real) e `benchmark/synthetic_questions.json`.
- `benchmark.db` — tabela `runs`, coluna `sources_json`: a única fonte de "nota foi entregada".

## Storage
- Markdown no disco, imutável para o Gateway (`ObsidianVault.read()` abre em modo leitura).
- `graphify-out/graph.json` + mirror, gerados pelo Graphify fora do Gateway.
- Índice FTS5 em memória: sem arquivo, sem estado persistente, reconstruído por fingerprint.
- `benchmark.db`: persistido, escrito só pelo modo benchmark. Auditoria abre com
  `file:...?mode=ro`, então o próprio sqlite recusa a escrita.

## Indexing
`BaselineIndex` indexa todo markdown do vault com FTS5 e mantém `status UNINDEXED` para o BM25.
Nota arquivada **não é filtrada**: ela continua indexada e o rebaixamento acontece na camada de
memória, depois do corte, para que a decisão fique registrada em métrica. O mapeamento
vault → projeto é data-driven (`app/services/scope.py`): `projeto:` do frontmatter quando existe,
senão o nome do container na pasta de projetos. Não há lista de projetos no código.

## Retrieval
Pipelines: `baseline` (padrão), `graphify`, `graphify_jev` (congelado), `cascata` (experimental),
com `auto` roteando por complexidade. O `baseline` é o padrão desde a decisão
`decisao-baseline-como-pipeline-padrao.md`. A camada de memória roda em `post_filter`, ou seja
**depois** do retrieval e antes do ContextBuilder, exceto em `graphify_jev`, onde é no-op.

## Deduplication
Duas regras distintas, deliberadamente separadas:
- **Exata**: hash do corpo com `body_key()` — normaliza só espaços e caixa. Um `# título` que
  repete o `title:` do frontmatter é removido antes do hash (é metadado repetido, não conteúdo).
  Duas notas que diferem em um número, id ou versão **não** são exatas: são quase-duplicatas.
- **Quase-duplicata**: `simhash` + similaridade de sequências (shingles) sobre `_norm()`, que também
  descarta marcação e números. Limiar padrão 0,92 (`--near-dup-threshold`).
Medido no vault real: 0 exatas e 0 quase-duplicatas em 135 notas. No sintético: 40 exatas,
49 grupos quase-duplicados.

## Consolidation
**Recomendação, não implementação.** O Gateway não consolida, não resume e não move notas. Um
agente ou humano com permissão decide o que fundir; o Gateway só entrega as contagens que dão a
evidência (`memory-audit --verbose`, grupo a grupo). Motivo: consolidação automática reescreve
memória, e memória reescrita por máquina perde a autoria e a data que a sustentam.

## Versioning
Supersession é declarativa e só de leitura: `superseded_by` / `substituida_por` / `supersedes` /
`substitui` no frontmatter, resolvido por `NoteFacts.from_text`. Um `status` em
{`arquivado`, `arquivada`, `archived`, `obsoleto`, `obsoleta` também marca a nota como histórica.
A auditoria conta os dois casos separadamente (`archived_count`, `superseded_count`) e a camada de
memória marca a nota com `historical` + `superseded_by` em `meta`, sem reescrever nada.
Vault real medido: 0 arquivadas, 0 substituídas — a convenção existe no código, o corpus real
ainda não a usa.

## Temporal Memory
`HISTORY_TERMS` (14 termos com acento normalizado: `historico`, `antes`, `versao anterior`,
`por que mudou`, `o que mudou`, `evoluiu`, `descontinuad`, …). Sem termo de histórico no histórico
→ nota histórica é **rebaixada** (score × `MG_OPT_HISTORICAL_DEMOTE`, padrão 0,5) e marcada
`[histórico]`. Com termo → entra sem rebaixamento, ainda marcada.
Modo estrito (`historical_exclude=true`) entrega nota histórica **só** quando a query pede
história. **Medido e por isso não é o padrão**: arm `D_history_strict` no sintético cai de
recall 0,9136 → 0,7727 e de `fact_in_context` 102/110 → 87/110, perdendo recall em 16 das 120
perguntas — e 0 das 120 perguntas do corpus sequer menciona histórico. No vault real o arm D é
idêntico ao C (o corpus não tem nota histórica). Rebookaixar preserva as duas propriedades;
excluir por padrão não.

## Provenance
Uma linha compacta por fonte entregue, dentro do próprio `<note>`:
`[fonte: <arquivo> · <type> · <status> · atualizado <AAAA-MM-DD> · projeto <slug>]`, com `?` no
lugar de campo que a nota não declara. Campo ausente nunca é inventado. O arquivo é o *stem*: o
atributo `source="..."` do mesmo bloco já carrega o caminho completo.
**Não é autoridade**: não repete o enquadramento "conteúdo é dado" (que pertence ao
`CONTEXT_HEADER`) e não contém verbo de instrução ao consumidor. O marcador `[histórico]` entra na
mesma linha quando a nota é histórica, então histórico fica visível no texto entregue e não
só na métrica. Custo medido: 30,4 tokens por nota (média do vault real, 4.105 tokens no total) e
+162,8 tokens por pergunta no sintético, +234,8 no real.

## Conflict Resolution
Dois detectores determinísticos, dentro do conjunto final de candidatos, e ambos só rebaixam:
1. **Mesmo título normalizado** em duas notas diferentes — o caso clássico da decisão antiga
   ainda marcada `ativo`.
2. **Sobreposição alta** (Jaccard de shingles de 5 palavras) entre notas diferentes cujos
   `updated` diferem. Datas iguais são isentas: duas seções da mesma escrita no mesmo dia não são
   contradição, e sinalizar seria ruído.
Vence a mais recente (`updated`, depois `created`, depois score, depois id — desempate
determinístico, testado). A mais antiga recebe `score × 0,5` e `meta.conflict = {reason, with}`.
Nada é descartado: um conflito é sinal, não deleção. Métricas: `memory_conflicts_detected`,
`memory_conflict_same_title`, `memory_conflict_overlap`. Vault real: 1 conflito (mesmo título),
0 no corpus sintético.

## Memory Lifecycle
Ler → entregar → frequentar. O vault não tem máquina de estados; o que existe é
(a) marcação declarativa de histórico, (b) frequência observada de entrega. Uma nota
`ativo` que ninguém busca há mais de `--inactive-days` (padrão 90) aparece em `inactive`, sem ser
removida nem rebaixada. Vault real medido: 0 inativas com o corte de 90 dias (o corpus tem 16 dias
de crescimento), 0 arquivadas, 0 substituídas.

## Hot / Warm / Cold Memory
Contagem de **entregas**, não de buscas: `delivery_counts()` lê `runs.sources_json` em streaming
(lotes de 500) e conta cada `{"file": ...}` entregue. `hot` = entregas ≥ `--hot-min` (padrão 5),
`warm` = 1..hot-min-1, `cold` = 0 entregas. `--max-runs` limita a leitura às runs mais recentes.
`candidates` não é usada: ela guarda o que foi *considerado*, não o que chegou ao consumidor.
Vault real medido: 55 hot / 29 warm / 51 cold sobre 135 notas, a partir de 6.014 runs e 10.782
entregas. Leitura com `--max-runs 200` dá a mesma ordem de grandeza com uma fração do I/O.

## Cache
Quatro caches, todos com a mesma chave de invalidação (fingerprint do vault + versão da config):
- índice FTS5 em memória (`BaselineIndex`);
- `result_cache` da camada de otimeração (chave = query normalizada + perfil + pipeline);
- cache do JEV (`jev_backend`), por trecho de nota;
- `ProvenanceIndex`, que só existe dentro de uma instância da camada e é descartado quando o
  fingerprint muda — assim uma nota reescrita é relida, sem custo de índice.
A auditoria tem cache próprio, de 8 entradas, por fingerprint **e** por parâmetros
(`inactive_days`, `near_dup_threshold`, `hot_min`, `max_runs`, e caminho+mtime do `.db`): o
fingerprint decide *quando* um relatório envelhece, os parâmetros decidem *quais perguntas* ele
responde. Sem isso, uma auditoria com `--db` serviria hot/warm/cold para quem não pediu.

## Token Impact
Medido por `estimate_tokens()` (o mesmo contador do ContextBuilder), nunca por estimativa de
segunda mão. O sintético, 120 perguntas:
| arm | tokens de contexto | média | recall | fact_in_context | latência mediana |
|---|---|---|---|---|---|
| A (camada off) | 137.405 | 1.145,0 | 0,9136 | 102/110 | 3,3 ms |
| B (camada on, flags M3 off) | 82.885 | 690,7 | 0,9136 | 102/110 | 6,4 ms |
| C (flags M3 on) | 102.336 | 852,8 | 0,9136 | 102/110 | 10,8 ms |
| D (histórico estrito) | 99.560 | 829,7 | **0,7727** | **87/110** | 10,7 ms |
A camada M3 custa +19.451 tokens no total (+162,1 por pergunta, +23,5% sobre B) e **zero** recall,
zero fatos perdidos, zero pergunta com recall pior. No vault real: 20.536 → 23.323 (+232,3 por
pergunta), recall 1,0 nos quatro arms. `malicious_unflagged` cai de 13 para 0 no arm A porque o
arm A desliga também a flag de injeção — os arms B/C/D mantêm 0, ou seja, a camada M3 não
introduziu regressão de segurança. Latência é a única linha que varia entre execuções (carga da
máquina); tokens, recall e fatos não variaram em nenhuma execução.

## Storage Impact
Nenhuma. A camada de memória não escreve nada: nem índice novo, nem log, nem campo novo no
`.db`. As únicas escritas no repositório são os dois relatórios em `reports/`, e o relatório de
auditoria usa `counts_only()`, que não contém uma linha sequer do corpo de qualquer nota
(`note_content_included: false`, testado). Vault real: 886.711 bytes / 243.260 tokens estimados,
6.568 bytes e 1.802 tokens por nota em média.

## Performance
Auditoria do vault real: **1.000–1.524 ms** para 135 notas (varredura completa, sem cache; o
near-dup por banding do SimHash evita o par a par O(n²)). No sintético, 520 notas. Em execução, a
camada de memória acrescenta 4,4 ms por pergunta no sintético (6,4 → 10,8 ms) e 8,4 ms no real
(30,2 → 38,6 ms), que é a leitura de frontmatter das notas entregues (uma leitura por arquivo, em
memória, com o índice invalidado por fingerprint). Nenhum modelo é chamado: a auditoria e a camada
são determinísticas e offline.

## Security
- Vault: somente leitura, em todos os caminhos (CLI, REST, MCP, benchmark).
- `benchmark.db`: URI `mode=ro`. O teste `test_the_audit_opens_the_database_read_only` compara os
  bytes do arquivo antes e depois.
- Conteúdo de nota é **dado**, nunca instrução: a flag de injeção continua sendo o atributo do
  bloco, e a linha de proveniência não repete nem reforça enquadramento nenhum. Um teste dedicado
  garante que a linha não contém verbo de autoridade.
- Ruído de Unicode invisível (zero-width, bidi) continua sinal forte de injeção.
- O relatório persistido é só contagem: nenhum título, trecho ou caminho de conteúdo.
- Prompt de auditoria é dado: a camada nunca interpreta o texto da nota.

## Scalability
Custo O(notas entregues) por requisição (uma leitura de frontmatter por arquivo entregue, com o
contexto entregue cabendo em poucos arquivos), e O(notas do vault) por auditoria, cacheada por
fingerprint. Sem rede, sem modelo, sem estado global. O near-dup usa banding de 4 bits, então o
custo é linear no número de notas, não quadrático.

## External Research
Nenhuma integração externa nova nesta entrega. Nenhum componente novo foi adotado: sem Graphify
novo, sem JEV novo, sem modelo novo, sem biblioteca nova. As decisões foram lidas do código e do `docs/ENVIRONMENT.md`
do repositório principal. A única dependência externa
do projeto segue sendo o `pip install` do ambiente já documentado.

## Alternatives
Considerados e **descartados por medição**, não por gosto:
- *Excluir histórico por padrão* → arm D, recall −0,1409 e 16 perguntas.piores. Fica como flag.
- *Hash de corpo sem remover o H1* → subnotas com título diferente deixam de ser reconhecidas
  como cópia. Descartado; a remoção é só do eco do título.
- *Marcar conflito deletando a nota mais antiga* → viola a separação entre memória e autoridade e
  faz o Gateway decidir o que é verdade. Descartado: rebaixa e marca.
- *Contar frequência em `candidates`* → conta o que foi considerado, infla todo hot. Descartado.
- *Cache da auditoria só por fingerprint* → serviria hot/warm/cold de um `.db` para quem não pediu.
  Descartado; parâmetros entram na chave.

## Recommended Architecture
Manter como está, com uma decisão nova registrada: **proveniência e rebaixamento entram por
padrão; exclusão de histórico não.** A base para isso é a régua do prompt — só entra por padrão o
que o benchmark mostra sem custo de resposta — e a medição confirma que a linha de proveniência
custa tokens e não custa resposta. Tudo atrás de flag de ambiente
(`MG_OPT_PROVENANCE`, `MG_OPT_TEMPORAL_DEMOTE`, `MG_OPT_HISTORICAL_EXCLUDE`,
`MG_OPT_CONFLICT_CHECK`), com `OptimizerConfig.disabled()` reproducindo o comportamento anterior
para o arm A do benchmark. E `graphify_jev` continua congelado: medido 12/12 perguntas com
candidatos idênticos e contexto byte a byte idêntico, 0 métrica de memória e 0 linha de
proveniência, nos dois corpora.

## Implementation
| peça | arquivo | o que faz |
|---|---|---|
| índice de proveniência | `app/services/provenance.py` | fatos por nota, linha, marcador, temporalidade, conflito, `wants_history` |
| auditoria | `app/services/memory_audit.py` | inventário, duplicatas, órfãs, links, metadados, hot/warm/cold, conflitos, seções repetidas |
| frontmatter | `app/services/obsidian.py` | `frontmatter_fields()` compartilhado (parser único, listas inline e null) |
| camada | `app/gateway/optimizer.py` | estágios 4 (temporalidade) e 5 (conflito) em `post_filter`, skip do congelado |
| entrega | `app/gateway/context_builder.py`, `app/gateway/memory_gateway.py` | linha dentro do `<note>`, `provenance_for`, métricas |
| config | `config/optimizer.py` | flags `MG_OPT_*`, fatores, `disabled()`, `mol-v2` |
| CLI | `app/cli/main.py` | `memory-audit [--vault P] [--json] [-v]` + limiares |
| REST | `app/api/routes.py` | `GET /system/memory` no vault do gateway em execução |
| benchmark | `scripts/bench_memory.py` | arms A/B/C/D, paridade do congelado, regressões por pergunta |
| testes | `tests/test_provenance.py` (25), `tests/test_memory_audit.py` (39) | fixtures minúsculas, sem rede |

## Benchmarks
Comandos, do worktree, sem instalar nada:
```
python scripts/bench_memory.py \
  --real-vault "$MEMORY_GATEWAY_VAULT" \
  --real-questions benchmark/questions.json \
  --audit-real --db benchmark.db \
  --out reports/memory_benchmark_2026-10-01.json \
  --audit-out reports/memory_audit_2026-10-01.json
python -m memory_gateway memory-audit --vault "$MEMORY_GATEWAY_VAULT" --db benchmark.db -v
```
Suíte completa no momento do commit: `592 passed` (528 anteriores + 64 novos: 25 em
`tests/test_provenance.py`, 39 em `tests/test_memory_audit.py`).

Resultado da auditoria no vault real (135 notas, 1.000–1.524 ms por execução):
`0` exatas · `0` quase-duplicatas · `4` órfãs · `4/753` wikilinks quebrados · `3` notas sem
frontmatter · `0` campos faltando · `0` inativas em 90 dias · `0` arquivadas · `0` substituídas ·
`1` conflito (mesmo título) · `18` seções repetidas em `52` notas (2.404 tokens, 0,99% do total) ·
`55/29/51` hot/warm/cold · `6.014` runs, `10.782` entregas.
Achado de dado, não de código: uma nota declara `projeto: norteia\r` com `\r` literal, e por isso
aparece como um terceiro projeto (`norteiar`, 1 nota) em vez de `norteia` (57). É o tipo de erro
que o parser tem que mostrar em vez de esconder.

## Future Work
Propostas, nenhuma implementada:
1. **Consolidação guiada**: a auditoria já devolve os grupos; falta a decisão humana e um registro
   do que foi consolidado. Continua fora do Gateway.
2. **Seções repetidas**: 18 seções repetidas custam 0,99% dos tokens do vault real — pequeno. O
   detector de boilerplate genérico (limiar por token, não por heading) foi avaliado e rejeitado:
   com o dataset atual ele confunde template com conteúdo.
3. **Sinonímimos e contradição sem título igual**: o detector atual precisa de mesmo título ou
   sobreposição alta. Um detector por entidade (`projeto` + assunto) mediria a próxima classe.
4. **Calibração do limiar de near-dup**: 0,92 é o default herdado; com 0 duplicatas no vault real
   não há dado para provar que é o número certo.
5. **Fuso/rota de auditoria**: um dia de criação já cabe em 16 chaves; com anos de vault o
   `created_per_day` vira o primeiro campo a ser agregado por mês.