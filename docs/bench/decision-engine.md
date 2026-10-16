# Decision Engine — benchmark (ANAM-043)

> **JEV real: não medido.** O JEV (TypeSafe) não está acessível e o Colibrì local não estava rodando. As linhas com JEV usam um **JEV FAKE** (proxy lexical, `scripts/bench_decision.py::FakeJev`): contam chamadas e exercitam o código, mas P/R/F1 dessas linhas descrevem o proxy, **não o JEV**. Laya = replay das probabilidades reais gravadas em ANAM-042.

Rótulos: **MEASURED** (medido aqui/replay de medição), **ESTIMATED** (modelo/extrapolação), **UNKNOWN** (não medido).

Dados: 192 pares consulta×trecho (59 positivos) em 74 consultas — benchmark/laya_labeled.json (corpus SINTÉTICO; sem vault real). Uma requisição = uma consulta com seus candidatos. Cache desligado. Limiares = padrões (não ajustados nestes dados).

## Referências

- AUC de relevância: Laya **0.642** vs sobreposição lexical **0.975** (MEASURED; coerente com ANAM-042).
- Sem filtro (tudo passa): P=0.3073 R=1.0 F1=0.4701.

## Resultado por estratégia

| estratégia | P | R | F1 | itens ao JEV | chamadas JEV evitadas | tokens JEV (ESTIMATED) | req. JEV | itens Laya | Laya ms total (ESTIMATED) | Laya p50/p95 por req. ms (ESTIMATED) | engine p50/p95 ms (MEASURED, replay) | fallbacks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| JEV-only (padrão) | 0.8281 | 0.8983 | 0.8618 | 192 | 0 (0.0%) | 65288 | 74 | 0 | 0.0 | 0.0/0.0 | 0.094/0.114 | 0 |
| Laya-only | 0.3257 | 0.9661 | 0.4872 | 0 | 192 (100.0%) | 0 | 0 | 192 | 43699.2 | 682.8/682.8 | 0.053/0.061 | 0 |
| Laya→JEV | 0.534 | 0.9322 | 0.679 | 107 | 85 (44.3%) | 44123 | 64 | 192 | 43699.2 | 682.8/682.8 | 0.764/1.922 | 0 |
| JEV→Laya | 0.8281 | 0.8983 | 0.8618 | 192 | 0 (0.0%) | 65288 | 74 | 20 | 4552.0 | 0.0/227.6 | 0.107/0.152 | 0 |
| ensemble | 0.3277 | 0.9831 | 0.4915 | 192 | 0 (0.0%) | 65288 | 74 | 192 | 43699.2 | 682.8/682.8 | 0.142/0.162 | 0 |
| adaptive | 0.4741 | 0.9322 | 0.6286 | 89 | 103 (53.6%) | 39001 | 60 | 192 | 43699.2 | 682.8/682.8 | 0.668/1.366 | 0 |

Custo total: tokens JEV (ESTIMATED) + tempo de CPU local do Laya (ESTIMATED); **USD do JEV real = UNKNOWN**. Latência do JEV real = **UNKNOWN** (só o tempo do Laya e o overhead do engine foram quantificados). "Chamadas JEV evitadas" = itens que um JEV-only enviaria e a estratégia não enviou (contagem exata, MEASURED).

## Adaptive: varredura de `min_confidence` (exploratória)

| config | P | R | F1 | itens ao JEV | JEV evitado |
|---|---|---|---|---|---|
| adaptive min_conf=0.01 | 0.3957 | 0.9322 | 0.5556 | 57 | 70.3% |
| adaptive min_conf=0.02 | 0.4135 | 0.9322 | 0.5729 | 63 | 67.2% |
| adaptive min_conf=0.05 | 0.4741 | 0.9322 | 0.6286 | 89 | 53.6% |
| adaptive min_conf=0.1 | 0.5464 | 0.8983 | 0.6795 | 122 | 36.5% |
| adaptive min_conf=0.2 | 0.7681 | 0.8983 | 0.8281 | 163 | 15.1% |

## Divergência Laya × JEV-FAKE (ensemble avalia os dois em todos os itens)

- agreement_rate (decisão exata): **0.2917** (MEASURED)
- survival_agreement_rate (passa/não passa): **0.401**
- Cohen κ: **0.0846**; Laya passa/JEV-fake barra: 113; Laya barra/JEV-fake passa: 2
- Contra rótulos: Laya P/R/F1 = 0.3257/0.9661/0.4872; JEV-fake = 0.8281/0.8983/0.8618; Laya certa e fake errado: 6; fake certo e Laya errada: 109.
- A divergência com o JEV REAL é **UNKNOWN**: este número compara Laya com um proxy lexical.

## Fallback por tipo de operação (falha injetada: JEV fake fora do ar, Laya ausente)

| operação | decisões | ação de fallback | todos sinalizados | descartados em silêncio |
|---|---|---|---|---|
| retrieval | UNJUDGED | allow | True | 0 |
| memory | REVIEW | review | True | 0 |
| security | QUARANTINE | block | True | 0 |

## Leitura (guiada pelos dados)

- Neste corpus a Laya **não supera** o baseline lexical (AUC acima); logo nenhum arranjo com Laya é recomendado para ficar à frente do padrão. **JEV-only / `graphify_jev_opt` permanece o padrão.**
- A economia de chamadas JEV das estratégias Laya-primeiro é real e contada, mas vem com o custo de qualidade da Laya (veja recall/F1 das linhas). `JEV→Laya` e `ensemble` gastam o mesmo JEV que o JEV-only: só podem ganhar qualidade, não custo.
- Presets FAST/BALANCED/QUALITY são só configuração, **experimentais** e não validados com JEV real.
- Reproduzir: `python scripts/bench_decision.py` (determinístico; sem rede, sem torch, sem vault).
