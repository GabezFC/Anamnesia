# PERSISTENT_MEMORY_ARCHITECTURE.md

Políticas que a camada de memória persistente impõe ao vault e ao que ele entrega. Complementar a
`docs/PERSISTENT_MEMORY_AUDIT.md` (medidas) — aqui valem as **regras**, não os números.
`app/services/scope.py` (descoberta de projetos) e `tests/test_scope.py` (prova de que um projeto
novo aparece sem tocar em código) implementam a política de descoberta.

## 1. O vault é somente leitura
O Gateway nunca cria, edita, move, renomeia ou apaga nota. `ObsidianVault.read()` abre em modo
leitura. Consequência: **toda** decisão da camada de memória é de entrega (ordem, marcação,
contexto), nunca de conteúdo. Se uma nota está errada, o conserto é humano ou de agente com
permissão.

## 2. Tudo é derivado do frontmatter da própria nota
`projeto`, `type`, `status`, `created`, `updated`, `superseded_by` são lidos da nota. Campo ausente
vira `None` e é renderizado como `?` — nunca preenchido por palpite, caminho ou similaridade.
A única exceção deliberada é o **projeto**, que pode vir do caminho quando o frontmatter não
declara: assim uma nota sem metadados ainda élocalizável. A precedência é `projeto:` > caminho.

## 3. Descoberta de projetos é data-driven
Não existe lista de projetos, áreas ou prefixos no código. `project_of()` deriva do
`projeto:` ou do container `NN-Projetos/<Nome>/`, e `slug()` normaliza (maiúsculas, acentos,
`_`, sufixo do repositório). Um projeto novo aparece em `/system/projects`, na linha de
proveniência e na auditoria sem nenhuma alteração. `tests/test_scope.py` fixa isso com um projeto
que não existe no repositório.

## 4. Rascunho sem campos obrigatórios não entra no ranking por obrigação
`REQUIRED_FIELDS = (id, title, area, type, tags, status, created, updated)` é o contrato de
forma, não de elegibilidade. Uma nota com campo faltando continua indexável e entregável; a
auditoria a reporta (`notes_missing_fields`) para que a debt de metadados seja visível sem virar
exclusão. A única nota sem *nenhum* frontmatter aparece em `notes_without_fm`.

## 5. Frontmatter é parseado uma vez só
`frontmatter_fields(text)` em `app/services/obsidian.py` é a única implementação (chaves simples,
listas inline `[a, b]`, `null`, valores com dois-pontos dentro). Auditoria, proveniência e o
resto do Gateway leem pela mesma função, então não podem discordar sobre o que a nota diz.
Ele não é um parser YAML completo de propósito: qualquer coisa que exija mais do que isso não
cabe no formato de nota e deve ser content addressed, não regra de parsing.

## 6. Histórico é histórico, nunca presente
`status` arquivado **ou** `superseded_by` preenchido ⇒ a nota é histórica. Ela **não é
removida** e **não é apagada** do índice. Se a query não pedir histórico: rebaixada por fator e
marcada. Se pedir: entra sem rebaixamento, ainda marcada. Marcador `[histórico]` vai na linha de
proveniência, para que o texto entregue diga o que a métrica diz.
O modo estrito (`historical_exclude`) existe como flag, não como padrão: medido em
`D_history_strict`, ele custa recall (0,9136 → 0,7727 no sintético). Rebaixar foi a versão que
manteve as respostas.

## 7. Proveniência informa; nunca instrui nem autoriza
Uma linha por fonte entregue, com arquivo, tipo, status, última modificação e projeto. Ela:
- **não** repete o enquadramento "conteúdo é dado" (pertence ao `CONTEXT_HEADER`);
- **não** contém verbo de instrução nem palavra de autoridade;
- **não** inventa campo ausente;
- **não** é autoridade sobre a verdade do texto — só diz de onde o texto veio.
Custo medido e declarado: 30,4 tokens por nota, +162,8 por pergunta no sintético.

## 8. Conflito é sinal, não veredito
Duas notas que respondem à mesma pergunta com datas diferentes são **sinalizadas**. A mais
recente vence o ranking; a mais antiga é rebaixada e marcada com `conflict = {reason, with}`.
Nenhuma é deletada, e o Gateway não decide qual das duas está certa — ele diz que elas discordam.
Desempate determinístico e explícito (`updated` → `created` → score → `candidate_id`) para que a
mesma entrada produza sempre o mesmo ranking.

## 9. Frequência é entrega observada, não busca
Hot/warm/cold vem de `runs.sources_json`: o que o consumidor recebeu. `candidates` — o que foi
considerado — não conta. Nota nunca entregue é `cold`, não "não existente". `benchmark.db` é lido
com `mode=ro` e nunca escreve.

## 10. Escopo é do consumidor, não do Gateway
A camada não escolhe projeto por conta própria: escopo chega no pedido (`scope`/`projeto`) e o
retrieval aplica. A linha de proveniência **informa** o projeto de cada fonte para que o consumidor
possa filtrar, sem o Gateway reordenar o contexto por conta própria.

## 11. Limites de segurança são herdados, nunca relaxados
Flag de injeção por bloco, detecção de Unicode invisível e o enquadramento de "conteúdo é dado"
continuam valendo exatamente como antes. A camada de memória é determinística e offline: não há
chamada de modelo em nenhum ponto, então ela não pode alucinar nem ser injetada por resposta.

## 12. Pipeline congelado é intocado
`graphify_jev` não recebe nenhum estágio de memória: nem temporalidade, nem conflito, nem
proveniência, nem métrica. É uma decisão de arquitetura (a pipeline foi calibrada e medida
separadamente), não uma otimização. Prova no benchmark: 12/12 perguntas com candidatos
idênticos e contexto byte a byte idêntico, 0 métrica, 0 linha. `FROZEN_PIPELINES` é a fonte
da verdade; `tests/test_memory_audit.py` fixa o contexto byte a byte.

## 13. Mudar o vault invalida; mudar parâmetro não
Índice FTS5, `result_cache` e `ProvenanceIndex` são invalidados pelo fingerprint do vault (mais a
versão da config). O cache da auditoria inclui os parâmetros e o `.db` além do fingerprint, porque
responder "quais notas foram entregues" para quem não pediu o `.db` seria responder outra pergunta.

## 14. Tudo é desligável e reproduzível
`MG_OPT_PROVENANCE`, `MG_OPT_TEMPORAL_DEMOTE`, `MG_OPT_HISTORICAL_EXCLUDE`, `MG_OPT_CONFLICT_CHECK`
(+ os fatores) controlam cada regra. `OptimizerConfig.disabled()` devolve o comportamento
pré-camada, e é o arm A do benchmark — sem ele não haveria como medir o ganho.

## 15. Relatório é contagem, nunca conteúdo
O relatório persistido da auditoria é `counts_only()`: inventário, distribuições, grupos
candidatos como caminho, e `note_content_included: false`. Isso permite auditar um vault real em
CI sem copiar uma linha de nota privada para dentro do repositório. A CLI `--json` devolve o
relatório completo, ainda sem corpo de nota.

## 16. O que a camada de memória não é
Não é o modelo (sintetiza), não é o agente (decide o que fazer), não é o Graphify (recupera por
grafo), não é o JEV (julga e filtra), não é o merge (escreve). Ela fica no Gateway, entre o
retrieval e o ContextBuilder, e só conhece `Candidate`, `NoteFacts` e o texto que já foi lido.

## 17. Auditoria é diagnóstico, não sentença
Todo número da auditoria é medido no vault que se está auditando. "Órfã" significa "ninguém
aponta para ela", não "não serve". "Conflito" significa "duas notas discordam", não "a mais nova
está errada". O relatório existe para o humano decidir; o Gateway não executa a decisão.

## 18. Evidência antes de default
Uma regra só entra ligada por padrão se o benchmark mostrar recall e `fact_in_context` iguais com
ela ligada **e** custo em tokens justificado por algum ganho. O rebaixamento temporal e o de
conflito entraram assim (0 perguntas com recall pior). A exclusão estrita de histórico ficou **fora**
do padrão (16 perguntas com recall pior). A proveniência também ficou **fora** (decisão do
orquestrador de 02/10/2026): custa cerca de 19,5k tokens (+23,6% de contexto) no sintético e não
ganhou nenhuma resposta. É opt-in com `MG_OPT_PROVENANCE=true`.
O número do benchmark fica ao lado da flag, em `config/optimizer.py`, para que a decisão possa
ser reavaliada quando o corpus mudar.