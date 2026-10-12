# Spike — compressão "caveman" do texto de contexto (itens 1.5 + 5.7)

Gerado em 2026-09-29, worktree `h1-bench`. Script: `scripts/spike_caveman_context.py`
(standalone, **não integrado** a `app/gateway/context_builder.py` ou a qualquer pipeline —
é só um spike, conforme pedido).

## O que foi medido

`scripts/spike_caveman_context.py` lê `context` (texto final já montado por `ModelContextBuilder`)
direto do `benchmark.db` principal, read-only, e aplica uma compressão determinística
"estilo caveman": remove palavras-função PT/EN (artigos, preposições, conjunções, pronomes,
verbos auxiliares) do texto solto, e **nunca toca** em:

- blocos de código (```` ``` ```` e `` `inline` ``);
- as próprias tags `<note source="..." section="..." ...>...</note>` (cabeçalho intacto);
- citações literais entre aspas duplas (`"..."`, texto dentro fica verbatim);
- qualquer token com dígito ou iniciado em maiúscula (números, datas, nomes próprios) — não
  porque haja um caso especial para eles, mas porque nenhum deles bate com a lista de palavras-
  função (que é só minúscula).

Comparação pedida: contra `MG_MCP_RESPONSE=compact`, que já existe
(`app/mcp/server.py`) — **não** contra `full`. Achado importante antes dos números: `compact`
corta ~73% do envelope JSON da resposta MCP (`sources` + metade das métricas), mas **não toca no
campo `context` em si** — é o mesmo texto em `compact` e em `full`. Caveman e `compact` atuam em
eixos diferentes (corpo do contexto vs. envelope da resposta); por isso os dois números abaixo são
reportados lado a lado, não como concorrentes.

## Resultado — população completa (5.992 contextos, todo o `benchmark.db` com erro=null)

```
TOKENS SAVED (estimate_tokens, a mesma heurística que o próprio gateway usa)
  mean=16.3%  median=16.5%  min=4.0%  max=25.7%
  total: 3.364.116 -> 2.822.890 tokens (16.1% agregado)

PROCESSING TIME
  total para 5.992 contextos: 1.263,1 ms  (média 0,211 ms/contexto)

DETERMINISM (mesma entrada comprimida duas vezes, comparação byte a byte)
  falhas: 0/5.992

FACT PRESERVATION (todo número/data/nome próprio do original)
  mantidos: 198.862/198.862 (100,00%)
```

Por pipeline na amostra: `baseline`=79, `graphify`=66, `graphify_jev`=457,
`graphify_jev_opt`=5.390 contextos — cobre as quatro pipelines, não é um recorte de uma só.

## Leitura dos números

- **Economia real, mas modesta**: 16,1% agregado — bem abaixo do "~75%" que o skill `caveman` do
  Hermes atinge em linguagem natural conversacional. Esperado: o texto aqui já é denso (notas
  técnicas dentro de `<note>` blocks, não prosa solta), então a fração de palavras-função é menor
  para começar.
- **Custo de processamento é irrelevante frente à economia**: 0,211 ms/contexto é ~4 ordens de
  grandeza abaixo de qualquer latência de rede/modelo envolvida no caminho. Isso descarta
  explicitamente o padrão de regressão já registrado no cérebro do projeto ("filtro que cortou 77%
  do contexto mas custou 10× mais no total") — aqui o processamento é local, sem chamada de
  API, então não há como o custo superar a economia.
- **Determinismo intacto**: 0 falhas em 5.992 comparações byte a byte. A transformação não usa
  timestamp, aleatoriedade ou estado externo — mesma entrada sempre produz os mesmos bytes, o que
  preserva o desconto de prompt cache do lado do consumidor
  ([[memory-gateway-token-optimization-audit]] §15), que era a condição explícita do item 5.7.
- **Preservação de fatos verificáveis é 100%** — por construção, não por sorte: a lista de
  palavras-função é só minúscula, então nenhum token com dígito ou iniciado em maiúscula pode
  bater nela. O checker confirma isso sobre dados reais, não é só uma garantia teórica do código.

## O que NÃO foi medido (limite explícito deste spike)

- **Qualidade da resposta do modelo consumidor sobre o texto comprimido.** O spike verifica que
  fatos "grep-áveis" (números, datas, nomes próprios) sobrevivem, mas remover artigos/preposições/
  verbos auxiliares pode tornar o texto menos natural de interpretar para o LLM consumidor —
  isso exigiria um teste real de Q&A (como `fact_in_context` em `scripts/bench_optimizer.py`) e
  não foi rodado aqui porque o item pede um spike de custo/determinismo, não uma avaliação de
  qualidade fim-a-fim. Não estimar essa parte — é uma pendência explícita, não uma suposição.
- Lista de palavras-função é deliberadamente pequena (não exaustiva) — cobre os casos de alta
  frequência PT/EN. Uma lista maior aumentaria a economia, mas também o risco de remover por
  engano uma palavra de conteúdo que colide em minúsculas com uma função-palavra (nenhum caso
  desse tipo apareceu nos 198.862 fatos verificados, mas o risco existe para outros vocabulários
  não cobertos pela amostra).

## Veredito

**Vale a pena investigar como estágio opcional**, com os números acima como base: economia líquida
positiva (16,1%), custo de processamento desprezível (0,2 ms), determinismo comprovado, 100% de
preservação de fatos verificáveis. Isso NÃO é uma recomendação de integração imediata — falta
exatamente o item da seção anterior (impacto na qualidade da resposta do consumidor), que é
pré-requisito antes de ligar qualquer flag em produção, seguindo o mesmo padrão de calibração já
usado para `MG_OPT_CUT_RATIO`/`MG_OPT_NEAR_DEDUP_THRESHOLD` em `config/optimizer.py` (medir antes
de ligar, nunca estimar).

Próximo passo, se o Gabriel decidir seguir: implementar como estágio opcional
`MG_OPT_CAVEMAN` (mesmo padrão de flag de `config/optimizer.py`), rodar
`scripts/bench_optimizer.py` com ele ligado nos dois corpora medindo `fact_in_context` e
`recall_mean` antes/depois (não só tokens), e só então decidir o default. Este spike não faz essa
parte — o código de compressão continua isolado em `scripts/spike_caveman_context.py`, sem nenhum
import a partir de `app/`.

## Arquivos

- `scripts/spike_caveman_context.py` — implementação + medição, standalone, zero dependências
  novas (usa `app.gateway.token_budget.estimate_tokens`, já existente, só para medir tokens).
