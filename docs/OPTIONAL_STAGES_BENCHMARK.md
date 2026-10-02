# Benchmark dos 6 estágios opcionais (M2)

Medido em 2026-10-01/02. Código: `scripts/bench_stages.py`. Dados brutos: `docs/stages_benchmark_2026-10-01.json`
(cópia versionada de `reports/stages_benchmark_2026-10-01.json`, que é gitignored) e a tabela completa em
`docs/stages_benchmark_2026-10-01.md`. Tudo que não foi medido aparece como **NÃO MEDIDO**; nada foi estimado.

## 1. Decisão (resumo)

Regra (§32): um estágio só entra no pipeline otimizado se **não perder recall nem fact_in_context** E
**reduzir `total_tokens_spent` ou melhorar a precisão** (rank-aware: P@3 / MRR, porque reranker não muda
*quais* notas entram, só a ordem). Latência, RAM/VRAM, licença, dependências e estabilidade decidem o *padrão*
(ligado ou opt-in).

| Estágio | Resultado da regra | Destino |
| --- | --- | --- |
| `sentence_dedup_mmr` | passa nos 2 corpora (−25,7% tokens sint.; −0,77% total real) | **ADOTADO, ON por padrão** em `graphify_jev_opt` (preset `free`) |
| `bge_reranker_v2_m3` | passa nos 2 (MRR 0,896→0,918 sint.; 0,80→0,90 real) | **ADOTADO, opt-in** (modelo, 2,3 GB VRAM) |
| `provence` (limiar 0,05) | passa nos 2 (−25,7% sint.; −18,2% total / −53,7% contexto real) | **ADOTADO, opt-in** (modelo + licença CC BY-NC-ND: só uso pessoal) |
| `llmlingua2` | **reprova** com o padrão (rate 0,5: 69/110 fatos vs 100/110). Variante rate 0,85 passa a regra, mas com ganho marginal | rejeitado como padrão; flag mantida |
| `mxbai_rerank_base_v2` | **reprova** (sint.: MRR 0,896→0,888, P@3 0,312→0,306) | rejeitado; flag mantida |
| `spotlight_nonce` | segurança: **+60,7%** tokens de contexto (sint.), +4,3% (real) para **0** proteção marginal medida | rejeitado como padrão; flag mantida (opt-in) |

Preset "aprovado" (`OPT_STAGES_PRESET`, ver §7): `off` = baseline `graphify_jev_opt` intacto · `free` (padrão) =
dedup · `approved` = dedup + bge + provence (os de modelo caem em *skip + métrica* se a biblioteca faltar).

Resultado do conjunto aprovado completo (explícito e via preset, números idênticos nos dois):

| | baseline | aprovado | Δ |
| --- | --- | --- | --- |
| Sintético (120 q, sem JEV): tokens de contexto | 130 553 | 83 920 | **−35,72%** |
| Sintético: recall / fact_in_context / MRR | 0,9045 / 100·110 / 0,8962 | 0,9045 / 100·110 / 0,9176 | recall e fatos iguais |
| Real (12 q, JEV): contexto | 30 856 | 14 236 | **−53,86%** |
| Real: total (judge + contexto) | 91 267 | 74 647 | **−18,21%** |
| Real: recall / hint_coverage (proxy) / MRR | 0,90 / 0,90 / 0,80 | 0,90 / 0,933 / 0,90 | recall igual |
| Latência do estágio (média/consulta) | 0 | 679 ms (sint.) · 1 559 ms (real) | custo |
| VRAM pico · carga a frio | — | 3 924 MB · 6,7 s (sint.); 5 363 MB · 6,6 s (real) | custo |

## 2. Método

**Hardware/ambiente:** RTX 3060 12 GB, Windows 11, venv **separado** (`%LOCALAPPDATA%/Temp/mg-stages-venv`,
`uv venv --python 3.11`; o `.venv` do projeto não foi tocado e segue sem torch). O projeto exige Python ≥ 3.14;
o stack opcional foi medido em 3.11 (wheels de torch/llmlingua) — **não validado em 3.14**.

**Versões instaladas e exercidas:** torch 2.6.0+cu124 · transformers **4.57.6** · sentence-transformers 6.1.0 ·
llmlingua 0.2.2 · mxbai-rerank 0.1.6 · nltk 3.10.3 · huggingface-hub 0.36.2 · tokenizers 0.22.2 · accelerate 1.15.0 ·
psutil 7.2.2 · numpy 2.4.6 · typesafe-sdk 0.7.1 (`requirements-optional.txt`).

**Corpora e pipelines**
- *Sintético* — `data/synthetic_vault` (520 notas) + `benchmark/synthetic_questions.json` (120 consultas, manifesto
  de 110 fatos enterrados e 13 notas maliciosas entregues). Pipeline `graphify` com a camada de otimização ligada,
  **sem JEV, custo zero**. Baseline = o mesmo pipeline sem estágio.
- *Vault real* — 12 perguntas (10 respondíveis + 2 sem resposta), pipeline `graphify_jev_opt` com JEV pago.
  Não há manifesto de fatos, então `fact_in_context` fica **NÃO MEDIDO** e é substituído por `hint_coverage`,
  um **proxy**: fração dos tokens distintivos do `answer_hint` (trechos entre crases, tokens com dígitos,
  identificadores com `_`) presentes no contexto entregue. Só detecta perda de fato; não prova resposta correta.
- Cada braço roda as MESMAS perguntas, isola o estado (descarrega modelos, limpa cache de scores, `empty_cache`,
  reseta o pico de VRAM) e usa o perfil `benchmark` (cache de resultado desligado).

**Braços:** baseline; cada um dos 6 estágios isolado; combinações `dedup+rerank`, `dedup+compress`,
`compress+rerank`, `dedup+compress+rerank` (melhor reranker = bge, melhor compressor = provence/llmlingua2 conforme
o corpus, escolhidos pelos braços isolados sem perder recall/fatos); varreduras de parâmetro (`provence`
limiar 0,03/0,1; `llmlingua2` rate 0,7/0,85); o conjunto aprovado (flags explícitas) e, no vault real, o
**caminho do preset** (`preset_free`, `preset_approved`) — que reproduziu os braços explícitos número a número;
e duas passadas seguidas do melhor reranker para medir o cache de scores.

**JEV e baseline do vault real.** O julgamento roda *antes* de qualquer estágio, então o gasto de JEV por pergunta
independe do braço. A primeira execução (`baseline_paid`) paga o JEV; as demais reaproveitam o cache em camadas.
Achado: um replay com cache **não** reproduz a execução paga (docs finais 2,08 → 2,33 por pergunta; contexto
26 683 → 30 856 tokens; P@3 0,683 → 0,617; MRR 0,85 → 0,80). Por isso o baseline de comparação é o **último replay
estável** (`baseline`, 2 replays até estabilizar), nas mesmas condições dos braços de estágio. As colunas `total
(equiv)` somam os tokens de judge do `baseline_paid` (60 411, medidos) + o contexto do braço — derivado e
rotulado `_equiv`, nunca misturado com o medido (`total_spent_measured`, `judge_paid` no JSON).
Observação lateral: até em replay cada braço ainda pagou ~3 488 tokens de JEV (algo não é cacheável). Não é do
escopo deste trabalho; `graphify_jev` e o cascade ficaram intocados.

**Regra, na prática (`evaluate_rule`):** `recall ≥ baseline` ∧ `fact_in_context ≥ baseline` (ou `hint_coverage ≥`)
∧ (`total_equiv <` baseline ∨ `precision`/`P@3`/`MRR >` baseline). Aplicada **por corpus**; o estágio precisa
passar nos dois.

**Limitações honestas:** (a) 12 perguntas (10 respondíveis): uma pergunta mexe 0,1 de MRR — o ganho do bge no vault
real é 1 pergunta, estatisticamente fraco; o sintético (120) é o sinal mais forte, e mesmo assim é pequeno
(+0,021). (b) o limiar do provence foi escolhido no sintético e *confirmado* no real (não é independente).
(c) `precision` por conjunto não muda com rerankers (mesmas notas entregues). (d) latência do baseline real inclui
JEV; compare a coluna *latência do estágio*. (e) RAM = RSS do processo ao fim do braço (inclui o gateway).

## 3. APIs verificadas (inspecionar → versão → doc → teste manual) e correções

| Achado | Correção |
| --- | --- |
| `PromptCompressor(model_name=...)` sem `use_llmlingua2=True` carrega o modelo como LM causal — chamada errada para o LLMLingua-2 | `use_llmlingua2=True`, `compress_prompt_llmlingua2(..., force_tokens=["\n"], force_reserve_digit=True)` |
| **mxbai-rerank 0.1.6 quebra com transformers 5.18** (`Qwen2Tokenizer.prepare_for_model` removido) | fixar `transformers<5` (4.57.6 funciona; sentence-transformers 6.1 e llmlingua 0.2.2 também) |
| Provence precisa do dado nltk `punkt_tab` (`LookupError` sem ele) e de `trust_remote_code=True`; saída = `dict(pruned_context, reranking_score, compression_rate)`; `.process(q, texto, threshold=0.1)` | `nltk.download('punkt_tab')`; limiar exposto (`OPT_STAGE_PROVENCE_THRESHOLD`, padrão do projeto 0,05) |
| Todo estágio recarregava o modelo do disco **a cada `search()`** | carga única por processo (`_get_model`), `release_models()`, métricas `*_load_ms` / `*_cold` |
| **Os rerankers eram no-op**: `ModelContextBuilder.rank()` reordena tudo por (relevância, score), descartando a ordem do estágio (MRR idêntico com e sem reranker na 1ª rodada) | o estágio grava `meta["rerank_rank"]`, chave primária do `rank()`; sem a chave a ordem é byte a byte a de antes (`graphify_jev` nunca roda estágio) |
| `spotlight_nonce`: uma nota podia conter o delimitador de fechamento e escapar do span | `SPOTLIGHT` dentro do texto é neutralizado (`SPOT-LIGHT`), métrica `stage_spotlight_nonce_forged_delimiters` |
| Licença do bge no código/catálogo estava inconsistente | HF API 2026-10-02: **Apache-2.0** |

## 4. Resultados — corpus sintético (120 consultas, `graphify`, sem JEV)

Docs: 25,3 recuperados → 9,77 pós-filtro → 9,77 no contexto (todos os braços). Malicious entregues: 13, não sinalizados: 0 em
todos os braços (a camada de otimização já marca `possible-prompt-injection`).

| braço | ctx tok | Δ | recall | MRR | P@3 | fact | lat. estágio ms | VRAM MB | carga a frio ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 130 553 | — | 0,9045 | 0,8962 | 0,3121 | 100/110 | 0 | — | — |
| llmlingua2 (rate 0,5) | 88 731 | −32,03% | 0,9045 | 0,8962 | 0,3121 | **69/110** | 617 | 2 163 | 3 004 |
| llmlingua2 rate 0,7 | 110 658 | −15,24% | 0,9045 | 0,8962 | 0,3121 | 94/110 | 677 | 2 163 | 2 633 |
| llmlingua2 rate 0,85 | 122 446 | −6,21% | 0,9045 | 0,8962 | 0,3121 | 100/110 | 686 | 2 163 | 2 641 |
| provence (thr 0,05) | 97 006 | −25,70% | 0,9045 | 0,8962 | 0,3121 | 100/110 | 598 | 1 721 | 2 618 |
| provence thr 0,1 (upstream) | 97 304 | −25,47% | 0,9045 | 0,8962 | 0,3121 | **99/110** | 614 | 1 721 | 2 775 |
| provence thr 0,03 | 100 808 | −22,78% | 0,9045 | 0,8962 | 0,3121 | 100/110 | 573 | 1 721 | 2 890 |
| bge_reranker_v2_m3 | 130 553 | 0% | 0,9045 | **0,9176** | 0,3121 | 100/110 | 145 | 2 265 | 4 474 |
| mxbai_rerank_base_v2 | 130 553 | 0% | 0,9045 | **0,8883** | 0,3061 | 100/110 | 148 | 1 825 | 2 564 |
| sentence_dedup_mmr | 96 973 | **−25,72%** | 0,9045 | 0,8962 | 0,3121 | 100/110 | 1,5 | 0 | 0 |
| spotlight_nonce | 209 812 | **+60,71%** | 0,9045 | 0,8962 | 0,3121 | 100/110 | 0,3 | 0 | 0 |
| dedup + bge | 97 976 | −24,95% | 0,9045 | 0,9176 | 0,3121 | 100/110 | 144 | 2 265 | 4 614 |
| dedup + provence | 84 361 | −35,38% | 0,9045 | 0,8962 | 0,3121 | 100/110 | 607 | 1 721 | 2 465 |
| compress + bge | 97 006 | −25,70% | 0,9045 | 0,9176 | 0,3121 | 100/110 | 731 | 3 924 | 7 181 |
| dedup + compress + bge | 83 920 | −35,72% | 0,9045 | 0,9176 | 0,3121 | 100/110 | 730 | 3 924 | 7 033 |
| **approved** (dedup+bge+provence) | 83 920 | **−35,72%** | 0,9045 | 0,9176 | 0,3121 | 100/110 | 679 | 3 924 | 6 742 |

(Combinações: reranker = bge e compressor = provence, escolhidos pelos braços isolados; o JSON registra `best_reranker`/`best_compressor`.) Latência
total/consulta sem a carga: baseline 7,4 ms; provence ~616 ms; bge ~157 ms; dedup ~10 ms.

**Cache de scores do reranker** (2 passadas idênticas, bge): passada 2 = 1 172/1 172 hits, 0 chamadas ao modelo,
latência do estágio 144 ms → 0,1 ms (total 152 → 6,2 ms). No vault real: 28/28 hits, 322 → 0,1 ms. O ganho só
existe para pergunta repetida sobre texto idêntico (chave: estágio, `query_fp`, hash do texto).

## 5. Resultados — vault real (12 perguntas, `graphify_jev_opt`, JEV)

Docs: 59,5 recuperados → 2,33 pós-filtro → 2,33 no contexto. Malicious entregues: 0 (segurança **NÃO MEDIDO** aqui).
`fact_in_context`: **NÃO MEDIDO** (sem manifesto) → `hint_coverage` (proxy). Baseline = 91 267 tokens totais
(equiv.: 60 411 judge + 30 856 contexto), amplificação 2,96.

| braço | ctx tok | Δ ctx | total equiv | Δ total | recall | hint | MRR | P@3 | lat. estágio ms | VRAM MB | cold ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline_paid (1ª execução, paga) | 26 683 | — | 87 094 | — | 0,90 | 0,90 | 0,85 | 0,683 | — | — | — |
| **baseline (replay estável)** | 30 856 | 0% | 91 267 | 0% | 0,90 | 0,90 | 0,80 | 0,617 | 0 | — | — |
| llmlingua2 | 24 796 | −19,64% | 85 207 | −6,64% | 0,90 | 0,90 | 0,80 | 0,617 | 698 | 2 370 | 2 678 |
| provence (0,05) | 14 288 | −53,69% | 74 699 | −18,15% | 0,90 | 0,933 | 0,80 | 0,617 | 1 249 | 3 197 | 2 421 |
| bge_reranker_v2_m3 | 30 856 | 0% | 91 267 | 0% | 0,90 | 0,90 | **0,90** | **0,65** | 320 | 2 366 | 4 347 |
| mxbai_rerank_base_v2 | 30 856 | 0% | 91 267 | 0% | 0,90 | 0,90 | 0,85 | 0,617 | 545 | **5 095** | 2 489 |
| sentence_dedup_mmr | 30 154 | −2,28% | 90 565 | −0,77% | 0,90 | 0,90 | 0,80 | 0,617 | 17 | 0 | 0 |
| spotlight_nonce | 32 177 | **+4,28%** | 92 588 | +1,45% | 0,90 | 0,90 | 0,80 | 0,617 | 0,5 | 0 | 0 |
| dedup + bge | 30 419 | −1,42% | 90 830 | −0,48% | 0,90 | 0,90 | 0,90 | 0,65 | 340 | 2 366 | 4 325 |
| dedup + provence | 14 246 | −53,83% | 74 657 | −18,20% | 0,90 | 0,933 | 0,80 | 0,617 | 1 286 | 3 197 | 2 497 |
| provence + bge | 14 288 | −53,69% | 74 699 | −18,15% | 0,90 | 0,933 | 0,90 | 0,65 | 1 579 | 5 363 | 6 660 |
| dedup + provence + bge | 14 236 | −53,86% | 74 647 | −18,21% | 0,90 | 0,933 | 0,90 | 0,65 | 1 568 | 5 363 | 6 747 |
| **approved** = `preset_approved` | 14 236 | −53,86% | 74 647 | −18,21% | 0,90 | 0,933 | 0,90 | 0,65 | 1 559 | 5 363 | 6 609 |
| `preset_free` (= dedup) | 30 154 | −2,28% | 90 565 | −0,77% | 0,90 | 0,90 | 0,80 | 0,617 | 17 | 0 | 0 |

Variantes: provence thr 0,03 −56,38% contexto (hint 0,933) · provence thr 0,1 −47,93% (hint 0,90) ·
llmlingua2 rate 0,7 −8,23% · rate 0,85 −2,93% contexto. Recall 0,90 em **todos** os braços (nenhum estágio mudou *quais* notas entram). Custo estimado em USD: idêntico em todos os braços do JEV
(o estágio roda depois do judge e é local: custo de modelo = US$ 0, mas custa GPU/latência). Amplificação
(`total/ctx`) sobe de 2,96 para 5,24 no aprovado só porque o contexto encolhe e o judge fica igual.

## 6. Decisão por estágio

- **sentence_dedup_mmr — ADOTADO (ON).** Sem modelo, ~1,5–17 ms, determinístico. −25,7% de contexto no sintético
  sem perder recall nem 1 fato; no vault real o ganho é pequeno (−0,77% do total) porque há ~2 notas por pergunta e
  quase nenhuma repetição, mas sem regressão.
- **bge_reranker_v2_m3 — ADOTADO (opt-in).** Passa a regra nos dois corpora pela ordenação (MRR +0,021 sint.,
  +0,10 real; P@3 +0,033 real). Não reduz tokens. Custa ~145–320 ms/consulta, 2,3 GB de VRAM, 2,2 GB de disco, carga
  a frio 4,3–4,8 s. Ganho pequeno e dentro do ruído no real — por isso opt-in, não padrão.
- **provence — ADOTADO (opt-in, uso pessoal).** A maior economia medida (−53,7% de contexto, −18,2% do total no
  vault real; −25,7% no sintético) sem perder recall nem fatos com limiar 0,05. Com o limiar upstream 0,1 perde 1 fato
  no sintético — por isso o padrão passou a 0,05. **Licença CC BY-NC-ND 4.0:** só uso pessoal/não comercial; nunca
  habilitar em deploy comercial. Custo 0,6–1,25 s/consulta, 1,7–3,2 GB de VRAM.
- **llmlingua2 — REJEITADO.** rate 0,5 (padrão upstream): −32% de tokens mas **31 dos 110 fatos perdidos** (69/110).
  rate 0,85 passa a regra formal, porém −6,2% (sint.) / −1,0% (real) por ~690 ms e 2,1 GB de VRAM: não justifica.
- **mxbai_rerank_base_v2 — REJEITADO.** Regride no sintético (MRR 0,8962→0,8883; P@3 0,3121→0,3061) e ganha
  0,05 de MRR no real; falha a regra no corpus maior. Pico de VRAM 5,1 GB no real; exige `transformers<5`.
- **spotlight_nonce — REJEITADO como padrão; opt-in mantido.** Proteção marginal medida = 0: das 13 notas
  maliciosas entregues, as 13 já saem com `possible-prompt-injection` (`malicious_unflagged` 0 antes e depois; também
  `malicious_unprotected` 0). Custo: +60,7% de contexto no sintético (cabeçalho de instrução repetido por nota) e
  +4,3% no real. Segue como defesa em profundidade para quem aceitar o custo; uma variante compacta (instrução uma vez
  por contexto) **não foi testada** (NÃO MEDIDO).

## 7. Como usar

| Quero | Faça |
| --- | --- |
| Comportamento anterior ao M2 (referência comparável) | `OPT_STAGES_PRESET=off` |
| Padrão (dedup nos resultados de `graphify_jev_opt`) | nada (`OPT_STAGES_PRESET=free`) |
| dedup + bge + provence | `OPT_STAGES_PRESET=approved` + ambiente de `requirements-optional.txt` |
| Só um estágio, em qualquer pipeline menos `graphify_jev` | `OPT_STAGE_<NOME>=true` ou a página de configuração (`config/local_settings.json` vence o preset) |

O preset só atua em `graphify_jev_opt` (`PRESET_PIPELINES`). `graphify_jev` (congelado) nunca roda estágio; `baseline` e
`graphify` só recebem estágios com flag explícita. Biblioteca ausente ⇒ *skip* + `optional_stage_skipped:<nome>` na
métrica e um aviso por processo — a busca nunca falha. Ativar os modelos: criar um venv com Python 3.11, instalar
`requirements-optional.txt` (torch cu124 via `--extra-index-url https://download.pytorch.org/whl/cu124`),
`python -c "import nltk; nltk.download('punkt_tab')"` para o provence, e iniciar o gateway **nesse** venv.

## 8. Licenças (HF API, 2026-10-02)

| Estágio | Modelo | Licença | Código |
| --- | --- | --- | --- |
| llmlingua2 | microsoft/llmlingua-2-xlm-roberta-large-meetingbank | MIT | llmlingua: MIT |
| provence | naver/provence-reranker-debertav3-v1 | **CC BY-NC-ND 4.0** (uso pessoal) | trust_remote_code |
| bge_reranker_v2_m3 | BAAI/bge-reranker-v2-m3 | Apache-2.0 | sentence-transformers: Apache-2.0 |
| mxbai_rerank_base_v2 | mixedbread-ai/mxbai-rerank-base-v2 | Apache-2.0 | mxbai-rerank: Apache-2.0 |

Tamanho em disco medido (blobs do cache HF): llmlingua2 2 149 MB · provence 1 668 MB · bge 2 187 MB · mxbai 958 MB.

## 9. Custo real gasto (JEV TypeSafe)

Somente o vault real consome JEV; o sintético fez 0 chamadas. Teto respeitado (12 perguntas, ≤ 15).

| Execução | Custo (USD) | Tokens JEV pagos |
| --- | --- | --- |
| fumaça (2 perguntas, 2 braços) | 0,000407 | 10 163 |
| 1ª rodada completa (reranker ainda no-op) — descartada | 0,003915 | 96 678 |
| 2ª rodada (baseline com replay) — descartada | 0,005183 | 127 769 |
| **rodada final (esta documentação)** | **0,005758** | 141 721 |
| **Total** | **0,015263** | **376 331** |

Dentro da rodada final: o `baseline_paid` custou US$ 0,002416 (60 411 tokens) e os 3 552 acertos de cache evitaram o resto.

## 10. Pendências

Calibrar o limiar do dedup por sentença isoladamente; ampliar o conjunto real (12 perguntas é pouco para afirmar
ganho de ordenação); testar spotlight compacto; validar o stack opcional em Python 3.14; investigar por que replays
em cache ainda pagam ~3,5 mil tokens de JEV e entregam mais notas que a execução paga (achado lateral, fora do escopo).
