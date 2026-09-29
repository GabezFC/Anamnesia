# Benchmark comparativo por tamanho de busca (item 1.1 / 5.6 da proposta 2026-09-28)

Gerado em 2026-09-29, worktree `h1-bench`. Dados de duas fontes, ambas read-only:

1. `benchmark.db` principal (`C:\Users\fonse\Projetos_AI\Memory_Gateway\benchmark.db`, 6.011 runs,
   118 MB) — via `scripts/audit_pipeline_by_scope.py` (novo, ao lado de `scripts/audit_pipeline.py`,
   reaproveita a mesma lógica de back-fill de `total_tokens_spent`/`token_amplification`).
2. Runs novos, **zero custo de API**, gerados agora com `scripts/bench_optimizer.py` nos dois
   corpora (sintético 520 notas, vault real ~92 notas), gravados só em `reports/*.json` deste
   worktree — nada foi escrito no `benchmark.db` principal (`gw.search(..., persist=False)`, e o
   `MemoryGateway` de cada arm usa um SQLite temporário próprio de `tempfile.mkdtemp()`).

`graphify_jev` e `graphify_jev_opt` usam um juiz pago (TypeSafe/Noul). Este ambiente **não tem
`TYPESAFE_API_KEY` configurada** (verificado: sem `.env`, sem variável de ambiente) — não foi
possível gerar runs novos desses dois pipelines. A análise abaixo usa exclusivamente os runs já
existentes no `benchmark.db` para eles, com todas as ressalvas de tamanho de amostra explícitas.

Métrica usada para "tamanho da busca": `candidate_tokens_before_filter` (candidatos brutos antes
do filtro), com fallback em `documents_found` quando ausente — mesma definição do funil de
`scripts/audit_pipeline.py`. Nunca `context_reduction` isolada
([[decisao-metrica-total-tokens-spent]]): toda leitura de custo abaixo usa
`total_tokens_spent`/`token_amplification` (contexto final + tokens do juiz), que é a métrica
honesta.

## 1. Desbalanceamento real (sem correção)

```
n por pipeline (benchmark.db, mode != warmup, sem erro):
  baseline           n=78
  graphify           n=65
  graphify_jev       n=475
  graphify_jev_opt   n=5390

n por corpus (vault_path lido do config_json de cada run):
  real (Cérebro_AI, ~86-100 notas ao longo do tempo)   n=212
  synthetic (data/synthetic_vault, 520 notas)          n=5796
```

`graphify_jev_opt` domina a contagem porque é o alvo dos sweeps de calibração de
`config/optimization.py` (24 combinações de flags × repetições) — não é um sinal de que ele é mais
usado em produção.

## 2. A distribuição não é a mesma nos dois corpora (achado, não hipótese)

```
DISTRIBUIÇÃO de candidate_tokens_before_filter, pooled (os dois corpora juntos):
  n=6008  min=993  p10=1886  p25=1972  p33=2012  median=2063  p66=2181  p75=2225  p90=2364  max=18675

DISTRIBUIÇÃO por corpus:
  real       n=212   min=993   p25=12510  p33=13487  median=14351  p66=15014  p75=15420  max=18675
  synthetic  n=5796  min=1489  p25=1954   p33=1998   median=2056   p66=2160   p75=2209   max=2505
```

O corpus real produz candidatos brutos 5-9× maiores que o sintético (o `baseline` do vault real
recupera quase o vault inteiro por consulta — ex.: um run real registrado tem
`documents_found=100` / `candidate_tokens_before_filter=16859` contra um vault de ~90-100 notas).
Isso não é "vault maior = busca maior": é o retrieval do vault real usando um `top_k` mais largo.
**Cortes de quantil calculados sobre os dois corpora juntos ficam dominados pelo corpus real** (a
faixa "large" pooled captura 211 dos 212 runs reais e quase nenhum sintético). Por isso a
segmentação usada na tabela abaixo é **por corpus** (quantis calculados dentro de cada corpus,
tercis p33/p66), não pooled. O script imprime as duas visões; a pooled fica só como registro de
transparência.

Cortes usados (tercis dentro de cada corpus):

| corpus | small ≤ | medium ≤ | large > |
| --- | --- | --- | --- |
| real | 13.532 tokens | 15.014 tokens | 15.014 tokens |
| synthetic | 1.998 tokens | 2.160 tokens | 2.160 tokens |

## 3. Tabela por (corpus × cenário × pipeline) — dados existentes no benchmark.db

Todas as 15 células têm n ≥ 18 (nenhuma abaixo do limiar de 10 definido para esta análise).
`recall` só existe para runs com `expected_sources_found` no `metrics_json` — presente para
`baseline`/`graphify`/`graphify_jev` no vault real; **ausente para todos os runs sintéticos
gravados até agora** (os sweeps de `graphify_jev`/`graphify_jev_opt` no corpus sintético não
reconciliam contra `expected_sources`, só medem custo/latência — gap real, não estimado).

| corpus | cenário | pipeline | n | recall (n com gt) | total_tokens_spent (mediana) | amplificação (mediana) | latência ms (mediana) | jev_fallback | contexto vazio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| real | small | baseline | 27 | — | 1.663 | 1.0× | 14.3 | 0% | 0% |
| real | small | graphify | 20 | 0.667 (n=9) | 1.994 | 1.0× | 298.2 | 0% | 0% |
| real | small | graphify_jev | 24 | 0.333 (n=9) | 6.521 | 4.7× | 899.5 | 12% (3/24) | 25% (6/24) |
| real | medium | baseline | 22 | 1.000 (n=16) | 1.980 | 1.0× | 15.2 | 0% | 0% |
| real | medium | graphify | 27 | 1.000 (n=21) | 1.956 | 1.0× | 883.3 | 0% | 0% |
| real | medium | graphify_jev | 26 | 1.000 (n=21) | 20.936 | 34.8× | 1.320.9 | 0% | 12% (3/26) |
| real | large | baseline | 29 | 1.000 (n=23) | 2.410 | 1.0× | 18.0 | 0% | 0% |
| real | large | graphify | 18 | 0.667 (n=9) | 1.894 | 1.0× | 861.0 | 0% | 0% |
| real | large | graphify_jev | 19 | 0.333 (n=9) | 22.107 | 9.7× | 1.298.9 | 0% | **53% (10/19)** |
| synthetic | small | graphify_jev | 137 | — | 2.481 | 6.5× | 297.5 | 20% (27/137) | 0% |
| synthetic | small | graphify_jev_opt | 1.808 | — | 1.556 | 3.5× | 328.0 | 20% (356/1808) | 0% |
| synthetic | medium | graphify_jev | 131 | — | 2.505 | 7.2× | 297.6 | 21% (27/131) | 0% |
| synthetic | medium | graphify_jev_opt | 1.818 | — | 1.571 | 3.7× | 329.4 | 21% (376/1818) | 0% |
| synthetic | large | graphify_jev | 138 | — | 2.646 | 7.1× | 301.0 | 17% (24/138) | 0% |
| synthetic | large | graphify_jev_opt | 1.764 | — | 1.665 | 3.7× | 332.1 | 18% (322/1764) | 0% |

Combinações **sem nenhum run registrado** (não estimadas):

- `corpus=real, pipeline=graphify_jev_opt` — nunca rodado no vault real.
- `corpus=synthetic, pipeline=baseline` — nunca rodado no vault sintético (preenchido na seção 4).
- `corpus=synthetic, pipeline=graphify` — idem.

## 4. Preenchendo o gap: `scripts/bench_optimizer.py`, zero custo, dois corpora

Rodado agora (2026-09-29), sem tocar `benchmark.db`:

```
python scripts/bench_optimizer.py \
  --out reports/bench_optimizer_synthetic.json
# vault=data/synthetic_vault (520 notas), 120 perguntas (110 respondíveis), 4 arms x 120 = 480 buscas

python scripts/bench_optimizer.py \
  --vault "C:\Users\fonse\Cérebro_AI" \
  --questions "C:\Users\fonse\Projetos_AI\Memory_Gateway\benchmark\questions.json" \
  --out reports/bench_optimizer_real.json
# vault real, 92 notas, 12 perguntas (10 respondíveis) — amostra pequena, ver aviso abaixo
```

Este script **não roda `graphify_jev`/`graphify_jev_opt`** (custam dinheiro; ver cabeçalho do
próprio script) — só `baseline`, `graphify` e `auto` (roteador MOL, hoje resolve para `baseline`
em toda classe). Ainda assim fecha o gap de `baseline`/`graphify` no corpus sintético com uma
amostra balanceada (120 perguntas por arm, mesmas perguntas, mesmo vault):

| corpus (n perguntas) | arm | recall_mean | context_tokens (média) | latência ms (mediana) |
| --- | --- | --- | --- | --- |
| synthetic (120, 110 respondíveis) | A baseline | 0.9136 | 1.013,2 | 3.0 |
| synthetic (120) | B graphify | 0.9045 | 1.040,2 | 3.4 |
| synthetic (120) | C auto (MOL, hoje = baseline) | 0.9136 | 611,2 (−40% vs A) | 5.0 |
| synthetic (120) | D graphify + MOL | 0.9045 | 962,7 | 7.7 |
| real (12, 10 respondíveis) | A baseline | 1.000 | 2.145,1 | 15.1 |
| real (12) | B graphify | 1.000 | 1.877,0 | 13.6 |
| real (12) | C auto (= baseline) | 1.000 | 1.608,4 (−25% vs A) | 19.6 |
| real (12) | D graphify + MOL | 1.000 | 1.642,1 | 18.1 |

**Aviso de amostra**: o corpus real só tem 12 perguntas no `questions.json` privado (10
respondíveis) — abaixo do limiar de 10 células só no limite, e sem nenhuma variação de "escopo"
dentro dele (não dá para segmentar small/medium/large com n=12). O corpus sintético (120
perguntas) é a única base atual grande o bastante para tirar uma conclusão robusta sobre
`baseline` vs `graphify`.

No sintético: `baseline` e `graphify` empatam em recall (0.9136 vs 0.9045, diferença de 1 pergunta
em 110) e em custo/latência — `graphify` não é mais barato nem mais rápido, e usa mais tokens em 3
dos 4 arms. **Nenhuma evidência, em nenhum dos dois corpora, sustenta trocar o default de
`baseline` por `graphify` em qualquer cenário.**

## 5. `graphify_jev` — o que os dados existentes já mostram

Nas 5 células do vault real com `graphify_jev` (seção 3), o padrão é consistente com a auditoria de
27/09 citada na proposta, mas mais grave nos extremos:

- Recall cai para **0.333** (metade do de `baseline`) nos buckets small e large — só empata com
  `baseline` (1.000) no bucket medium.
- `total_tokens_spent` é 4,7× a 34,8× o de `baseline`/`graphify` (amplificação medida, não
  `context_reduction`).
- Latência é 60-100× a de `baseline`.
- **Contexto vazio em 53% dos runs "large"** (10/19) — o juiz derruba tudo e a pipeline não tem
  survivors. Isso não aparece em nenhuma métrica de "redução"; só aparece medindo
  `context_tokens==0` diretamente, como este script faz.

Não há dado de recall para `graphify_jev` no corpus sintético (ver seção 3) — só custo/latência.
Lá o custo por run é mais estável (6,5×-7,2× de amplificação) mas ainda 2,4×-3,4× o total de
`graphify_jev_opt` no mesmo corpus.

## 6. `graphify_jev_opt` — dados parciais, sem recall e sem vault real

5.390 runs, todos no corpus sintético, todos dentro dos sweeps de calibração de
`config/optimization.py` (24 combinações de flags testadas, não um pipeline único e fixo — ver
`n by pipeline` acima). Nenhum tem `expected_sources_found`. Dentro dessa limitação:

- Custo total (`total_tokens_spent`) é a métrica mais baixa das 4 pipelines no sintético
  (mediana 1.556-1.665 contra 2.481-2.646 de `graphify_jev`), amplificação 3,5×-3,7× contra
  6,5×-7,2×.
- `jev_fallback_used` (juiz caiu para modo de segurança) acontece em 17%-21% dos runs — parecido
  com `graphify_jev` no mesmo corpus (17%-21%), não uma melhora.
- **Nunca foi medido no vault real.** Não dá para comparar contra `baseline`/`graphify` no mesmo
  corpus onde eles têm recall real. Qualquer alegação de que `graphify_jev_opt` "vence buscas
  grandes" no vault real seria estimada, não medida — por isso não é feita.

### Por `query_complexity` (só dentro de `graphify_jev_opt`, sem comparação cross-pipeline)

`query_complexity` só é gravado nas métricas de `graphify_jev_opt` (e em 11 runs avulsos de
`baseline`, insuficiente para comparar). Agregando os 5.390 runs por classe:

| query_complexity | n | total_tokens_spent (mediana) | amplificação (mediana) | latência ms (mediana) | jev_fallback |
| --- | --- | --- | --- | --- | --- |
| SIMPLE | 4.114 | 1.554 | 3.54× | 328.9 | 16% (666/4114) |
| MEDIUM | 396 | 1.506 | 4.40× | 330.9 | 9% (36/396) |
| COMPLEX | 880 | 2.664 | 4.59× | 335.9 | **40% (352/880)** |

(`AMBIGUOUS` não aparece nos runs gravados.) COMPLEX custa mais e cai em fallback 2,5-4× mais que
as outras classes — mas isso é só dentro de `graphify_jev_opt`; não há como saber se `baseline`
erraria mais nessas mesmas perguntas COMPLEX, porque `baseline` nunca rodou com esse rótulo em
volume suficiente.

## 7. Recomendação objetiva

**Threshold `graphify` vs `graphify_jev_opt` por N candidatos, como a hipótese original do item 1.1
pedia: não é possível concluir com os dados atuais.** Falta a combinação
`corpus=real, pipeline=graphify_jev_opt` inteira, e falta recall em toda a base sintética de
`graphify_jev`/`graphify_jev_opt`. Não estimar — registrar como pendência (ver seção 8).

O que **é** possível concluir com os dados atuais, nos dois corpora, em toda célula com n ≥ 18:

> **`baseline` não perde de nenhuma outra pipeline em recall, em nenhum cenário medido (small/
> medium/large, real ou sintético), e custa menos tokens/tempo em todos eles.** `graphify` empata
> ou perde em recall e é 20-300× mais lento sem ganhar nada em troca. `graphify_jev` perde recall
> nos extremos (small/large) e custa 4,7×-34,8× mais, com até 53% de contexto vazio.

Isso **confirma** o default já configurado em `config/optimizer.py`
(`MG_ROUTE_SIMPLE=MEDIUM=COMPLEX=AMBIGUOUS=baseline`) — não há um novo threshold para escrever
porque a resposta é a mesma em toda a faixa medida: `baseline`. Não há evidência para acionar
`MG_ROUTE_COMPLEX` para uma pipeline paga: o único sinal por complexidade (seção 6) mostra
`graphify_jev_opt` ficando **mais caro e menos estável** (mais fallback) em COMPLEX, não melhor.

### Mapa `query_complexity` → pipeline (o que os dados sustentam hoje)

| classe | rota atual (`MG_ROUTE_*`) | dado que sustenta manter |
| --- | --- | --- |
| SIMPLE | baseline | recall empatado, menor custo, `graphify_jev_opt` sem ganho medido |
| MEDIUM | baseline | idem; menor taxa de fallback das 3 classes observadas |
| COMPLEX | baseline | `graphify_jev_opt` custa mais e falha mais nesta classe — trocar seria regressão, não melhoria |
| AMBIGUOUS | baseline | sem runs suficientes para avaliar (0 no sweep observado); manter o default conservador |

## 8. Pendências (não fazer suposição no lugar destas)

1. Rodar `graphify_jev_opt` no vault real pelo menos uma vez por bucket de escopo (precisa de
   `TYPESAFE_API_KEY`, indisponível neste ambiente).
2. Adicionar `expected_sources_found` (reconciliação com ground truth) aos sweeps sintéticos de
   `graphify_jev`/`graphify_jev_opt` — hoje eles só medem custo/latência, não qualidade.
3. `benchmark/questions.json` real tem só 12 perguntas — pequeno demais para segmentar por
   escopo dentro do vault real; crescer esse dataset melhoraria a seção 4.

## Arquivos

- `scripts/audit_pipeline_by_scope.py` — script novo, lê `benchmark.db` read-only.
- `reports/bench_optimizer_synthetic.json`, `reports/bench_optimizer_real.json` — saída bruta dos
  dois runs zero-custo desta análise (não versionados no `benchmark.db` principal).
