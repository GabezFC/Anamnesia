# Gráficos de série temporal — pipeline de dados e regras (M1)

## Problema
O gráfico de Histórico agregava no navegador as 5.000 runs mais recentes carregadas no preload; com 6.014
runs, 1.014 ficavam de fora em silêncio, e o eixo X usava rótulos genéricos.

## Pipeline atual
`GET /benchmark/timeseries?metric=&agg=day|session|run&since=&until=&pipeline=&max_points=&tz=local|utc`
(`app/benchmark/timeseries.py`), calculado no servidor sobre TODAS as runs não-warmup do intervalo:

1. validar timestamp → 2. normalizar (epoch s, epoch ms > 1e12, ISO 8601 com/sem Z/offset; ingênuo = UTC)
→ 3. descartar inválidos (contados em `invalid_dropped`) → 4. ordenar ASC → 5. deduplicar `run_id`
→ 6. filtrar `since/until` → 7. extrair a métrica de `metrics_json` (mesma derivação de `format.js`;
métrica ausente = buraco, nunca 0) → 8. agregar (mediana, p25, p75, n) por dia, sessão ou run
→ 9. downsample **só depois** de ordenar (LTTB: mantém pontos reais, primeiro e último, ordem ASC).

Resposta: `series[pipeline].points` + `total_runs_in_range`, `points_returned`, `sampled`, `invalid_dropped`,
`range{first,last}`. `sampled=true` somente se os pontos agregados passam de `max_points` (padrão 600,
teto 5.000). A amostragem é só da visualização; o total de runs é sempre o real.

## Frontend
- Linha de resumo: "histórico completo: N runs · pontos desenhados: M · amostrado: sim/não".
- Período 7d / 30d / Tudo / Personalizado (since/until); zoom por arraste no gráfico (refaz a consulta no
  intervalo, com resolução maior), botões + / − e "resetar zoom".
- Eixo X: dd/MM, e HH:mm quando o intervalo < 2 dias; valores em pt-BR (1,2k tokens, US$ 0,0021, 1,2 s).
- Tooltip: data completa + valor + n runs + p25–p75. Legenda clicável (liga/desliga série). Faixa p25–p75
  opcional. Buracos quebram a linha (regra do `series.js`); nunca se ligam pontos fora de ordem.
- Escala log cai para linear (com aviso) se houver valor ≤ 0. Texto dos eixos com contraste AA.
- Revisão dos outros gráficos de linha: `grep lineChart` encontra um único uso (`pages-data.js`, Histórico);
  não há outro gráfico de linha usando índice/ordem de chegada como X.

## Medido (cópia do banco real)
`agg=run`, `max_points=600`: total_runs_in_range=6.011 (6.014 menos 3 warm-ups), invalid_dropped=0;
graphify_jev_opt 5.390 runs → 600 pontos (sampled=true); baseline 81, graphify 65, graphify_jev 475 sem
amostragem. `agg=day`: 11 pontos, sampled=false, último ponto em 01/10/2026.

## Screenshots
- Depois: `docs/img/history-depois.png` (data mais recente 01/10/2026).
- Antes: NÃO MEDIDO (sem captura do estado anterior).
