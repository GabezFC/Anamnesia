# ANAM-042 — Laya como decisor local: medição

Gerado por `scripts/bench_laya.py --report` (pacote `laya` 0.4.8, CPU, seed 42).
Dados: `benchmark/laya_labeled.json` (vault sintético + frases inventadas; nenhum dado real).

## Conjunto

- Relevância: **192 pares** (pos=59, neg=133); PT=149, EN=43. Tipos: positive=59, hard_negative=59, easy_negative=59, unanswerable=15.
- Privacidade: 40 textos; escrita: 30 textos.
- Split calibração/teste: 96/96 (seed fixa). Temperatura e limiar são ajustados SÓ na calibração; as tabelas de relevância são da metade de TESTE (salvo indicação).

## Relevância (metade de teste)

| braço | precisão | recall | F1 | tokens pagos |
|---|---|---|---|---|
| baseline sem filtro (tudo passa) | 0.25 | 1.0 | 0.4 | 0 |
| Laya multilingual_only, limiar padrão 0.60, sem refit | 0.333 | 0.083 | 0.133 | 0 |
| Laya multilingual_only, limiar ajustado 0.17, sem refit | 0.296 | 0.875 | 0.442 | 0 |
| Laya multilingual_only, refit T=1.4, limiar 0.23 | 0.284 | 0.875 | 0.429 | 0 |
| Laya auto_route, limiar padrão 0.60, sem refit | 0.5 | 0.083 | 0.143 | 0 |
| Laya auto_route, limiar ajustado 0.27, sem refit | 0.354 | 0.708 | 0.472 | 0 |
| Laya auto_route, refit T=1.2, limiar 0.31 | 0.364 | 0.667 | 0.471 | 0 |

### Poder de separação (AUC, conjunto inteiro; 0,5 = acaso)

| sinal | AUC |
|---|---|
| Laya multilingual_only | 0.642 |
| Laya auto_route | 0.682 |
| sobreposição lexical consulta×trecho (referência barata) | 0.975 |
| média Laya + lexical | 0.915 |

Leitura: o conjunto sintético é de **busca por entidade rara** (nomes inventados), onde o casamento lexical já é quase perfeito; Laya mede relação semântica e não ‘contém exatamente este token’. Isto NÃO prova que Laya seja fraca em relevância semântica de notas reais — prova que, neste corpus, ela não supera o prefiltro lexical que o pipeline já tem.

### Por idioma (multilingual_only, limiar 0.60, conjunto inteiro)

| idioma | n | precisão | recall | F1 |
|---|---|---|---|---|
| pt | 149 | 0.556 | 0.111 | 0.185 |
| en | 43 | 1.0 | 0.143 | 0.25 |

## Cascata Laya → JEV (JEV desligado; incertos como limites)

Escalonado ao JEV = `p` entre `drop` e `keep` OU `confidence` < mínimo. Sem JEV real reportamos dois limites: **passam** (incertos passam, como `REVIEW=keep`) e **caem**. O JEV real ficaria entre eles; **não foi medido** (sem chave/rede neste ambiente). Teste = metade de teste.

| drop | keep | conf mín. | % escalonado | P/R/F1 (incertos passam) | P/R/F1 (incertos caem) | positivos perdidos por DROP confiante |
|---|---|---|---|---|---|---|
| 0.3 | 0.6 | 0.0 | 38.5% | 0.326/0.583/0.418 | 0.333/0.083/0.133 | 10 de 24 |
| 0.2 | 0.8 | 0.0 | 65.6% | 0.297/0.792/0.432 | 1.0/0.042/0.08 | 5 de 24 |
| 0.1 | 0.9 | 0.0 | 90.6% | 0.264/0.958/0.414 | 0.0/0.0/0.0 | 1 de 24 |
| 0.3 | 0.6 | 0.3 | 88.5% | 0.264/0.958/0.414 | 0.5/0.042/0.077 | 1 de 24 |
| 0.2 | 0.8 | 0.3 | 89.6% | 0.264/0.958/0.414 | 1.0/0.042/0.08 | 1 de 24 |
| 0.1 | 0.9 | 0.3 | 93.8% | 0.256/0.958/0.404 | 0.0/0.0/0.0 | 1 de 24 |

## Latência e RAM (CPU, torch cpu, 1 processo)

| braço | p50 ms (1 cand.) | p95 ms | lote ms/cand. | RSS após carga | RSS após execução | carga |
|---|---|---|---|---|---|---|
| auto_route (auto) | 225.1 | 688.5 | 279.6 | 1631 MB | 3338 MB | 9.7 s |
| multilingual_only (multilingual) | 224.3 | 260.7 | 227.6 | 1628 MB | 1700 MB | 9.7 s |

RSS do processo (python+torch+laya) antes de carregar pesos: 24 MB. Checkpoints escolhidos no braço auto: english=19, multilingual=173.

## Privacidade (sensível → só provider local)

n=40 (pos=20), limiar 0.60, sem refit (conjunto pequeno).

| classificador | precisão | recall | F1 | FN (vazaria p/ remoto) |
|---|---|---|---|---|
| só regras (CPF/e-mail/chave...) | 1.0 | 0.15 | 0.261 | 17 |
| só Laya | 0.875 | 0.35 | 0.5 | 13 |
| regras OU Laya (implementado) | 0.875 | 0.35 | 0.5 | 13 |

Varredura de limiar (Laya, privacidade): `limiar → recall / falsos positivos` — 0.05→0.90/9; 0.10→0.90/4; 0.20→0.85/3; 0.30→0.70/3; 0.40→0.50/1; 0.60→0.35/1. AUC=0.880.

## Triagem na escrita de memória

n=30 (injeção=12, lixo=8).

| sinal | alvo | precisão | recall | F1 | FP | FN |
|---|---|---|---|---|---|---|
| injection_screen (regras) | injeção | 0.846 | 0.917 | 0.88 | 2 | 1 |
| Laya | injeção | 0.55 | 0.917 | 0.687 | 9 | 1 |
| regras OU Laya (implementado) | injeção | 0.524 | 0.917 | 0.667 | 10 | 1 |
| Laya | lixo/qualidade | 0.308 | 0.5 | 0.381 | 9 | 4 |

Varredura de limiar (Laya, injeção): 0.20→1.00/12; 0.40→0.92/9; 0.60→0.92/9; 0.80→0.92/6; 0.90→0.83/5. AUC=0.815.

## Decisão (ANAM-042)

- **Laya sozinha vale mais que o JEV/baseline para relevância? Não, neste corpus.** AUC do Laya 0,64–0,68 contra 0,975 da sobreposição lexical que o `prefilter` já aplica; F1 de teste 0,44–0,47 (limiar ajustado) contra 0,40 do baseline sem filtro e perda de recall ao usar o limiar padrão. Média Laya+lexical (0,915) é pior que o lexical sozinho.
- **Laya+JEV em cascata? Não mede economia.** Para não perder positivos (recall ≥ 0,95) a cascata escalona 65–94% dos candidatos ao JEV, ou seja, quase nada é poupado. O JEV real **não foi medido** (sem chave/rede); só os limites passam/caem.
- **Padrão escolhido:** `graphify_jev_opt` continua o padrão; `graphify_laya` e `graphify_laya_jev` ficam **registrados e opt-in** (e fora do roteamento `auto`). Laya entra como decisor local **obrigatório** onde mede algo útil: sensibilidade (AUC 0,88; recall-first com limiar 0,10 e fail-closed) e sinal extra de escrita (`MG_LAYA_WRITE_TRIAGE`, desligado por padrão: não superou as regras).
- **Limites:** conjunto pequeno e sintético (entidades inventadas), PT-BR com notas mistas PT/EN, consultas EN por gabarito; números de privacidade/escrita têm n=40/30 e limiares escolhidos nos próprios dados (otimistas). Repita com dados rotulados seus.
