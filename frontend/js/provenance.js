// provenance.js — result provenance. Every figure the dashboard shows carries one of three labels.
//
// WHY THIS FILE EXISTS
// A previous round of this project published a headline "-3.0% total tokens" for the full
// optimization stack. That number came from an arm comparison whose optimized arm had been
// contaminated by a context leak (candidates the optimizer deliberately refused to pay for were
// still being handed to the consumer model, so judge-token savings were being paid for with
// consumer-context tokens). The figure is INVALID and must never be rendered as a result again.
// It is kept here, explicitly marked, so the mistake stays visible instead of being quietly deleted.

export const STATUS = {
  verified: {
    id: 'verified',
    label: 'Verificado',
    tone: 'ok',
    detail: 'Medição isolada, com procedimento e números registrados no repositório.',
  },
  experimental: {
    id: 'experimental',
    label: 'Experimental',
    tone: 'warn',
    detail: 'Agregado calculado ao vivo a partir de benchmark.db. Não é um resultado auditado: '
      + 'mistura sessões, configurações e braços diferentes.',
  },
  invalid: {
    id: 'invalid',
    label: 'Inválido — substituído',
    tone: 'err',
    detail: 'Resultado retirado de circulação. Nunca deve ser exibido como número válido.',
  },
};

export const statusOf = (id) => STATUS[id] || STATUS.experimental;

/**
 * Registry of KNOWN results. Values here are transcribed from measurements recorded in the
 * repository (config/optimization.py e app/services/adaptive.py), never computed at runtime.
 */
export const RESULTS = [
  {
    id: 'opt-stack-v2',
    status: 'verified',
    title: 'Stack de otimização v2 — economia real, recall intacto',
    date: '2026-09-27',
    scope: '120 perguntas · 520 notas · corpus sintético · juiz pago · isolamento por braço',
    source: 'reports/opt_stack_v2.json (auditar com scripts/audit_opt_report.py)',
    figures: [
      ['Baseline', '257.533 tokens de juiz', 'contexto 57.936 · recall 0,900'],
      ['Melhor braço (05_smart_snippet)', '237.237 (−7,9%)', 'contexto 56.672 · recall 0,900'],
      ['full_stack', '242.190 (−6,0%)', 'contexto 56.045 · recall 0,900'],
      ['Regressões de recall', '0', 'em todos os 9 braços'],
    ],
    note: 'Medição feita DEPOIS da correção do vazamento. O invariante de vazamento fecha em todos '
      + 'os braços: 194 candidatos UNSELECTED contabilizados e nenhum entregue ao consumidor. '
      + 'Mais mecanismos não é melhor — o stack piora depois de 05_smart_snippet.',
  },
  {
    id: 'cache-warm-pass',
    status: 'verified',
    title: 'O cache domina, mas só em tráfego repetido',
    date: '2026-09-27',
    scope: '120 perguntas · passe frio + passe quente no mesmo braço',
    source: 'reports/opt_stack_v2.json (warm_pass)',
    figures: [
      ['Passe frio (04)', '237.926 tokens', 'paga tudo e popula o cache'],
      ['Passe quente (04)', '71.011 tokens (−70%)', 'mesmas perguntas + paráfrases'],
      ['03_layered_cache quente', '0 tokens de juiz', 'mas custa +2,0% no frio'],
    ],
    note: 'Os dois números são reportados sempre. Mostrar só o quente seria desonesto; mostrar só '
      + 'o frio diria que cache não serve para nada. O valor real depende da sua taxa de repetição.',
  },
  {
    id: 'adaptive-k-alone',
    status: 'verified',
    title: 'adaptive_k sem regra de parada custa mais',
    date: '2026-09-27',
    scope: '120 perguntas · braços isolados',
    source: 'config/optimization.py (comentário de calibração)',
    figures: [
      ['Baseline', '257.533 tokens de juiz', '120 requisições'],
      ['adaptive_k sozinho', '308.937 tokens de juiz (+20,0%)', '240 requisições'],
    ],
    note: 'Ondas sem regra de parada escalaram em 120/120 queries; cada requisição custa ~340 tokens. '
      + 'Por isso a configuração adaptive_k=true com early_stopping=false é rejeitada por validate().',
  },
  {
    id: 'adaptive-k-early-stop',
    status: 'verified',
    title: 'adaptive_k + early_stopping reduz tokens de juiz',
    date: '2026-09-27',
    scope: '120 perguntas · braços isolados',
    source: 'reports/opt_stack_v2.json',
    figures: [
      ['Baseline', '257.533 tokens de juiz', '120 requisições'],
      ['adaptive_k + early_stopping', '237.926 tokens de juiz (−7,6%)', '154 requisições'],
    ],
    note: 'A economia vem de NÃO escalar: a parada foi aceita em 86/120 queries.',
  },
  {
    id: 'near-dedup-threshold',
    status: 'verified',
    title: 'Limiar de near-dedup calibrado em 0,88',
    date: '2026-09-27',
    scope: '60 grupos de duplicatas declaradas + 120 notas de controle',
    source: 'config/optimization.py (tabela de calibração)',
    figures: [
      ['Precisão de pares', '1,0000', 'nenhuma fusão errada em toda a varredura'],
      ['Recall', '0,9667', 'satura em 0,88; abaixo disso não muda'],
    ],
    note: 'O limiar escolhido é o joelho da curva, não a borda.',
  },
  {
    id: 'zero-evidence-shadow',
    status: 'experimental',
    title: 'Regra zero-evidence permanece em shadow (nunca promovida)',
    date: '2026-09-27',
    scope: '2.908 candidatos · validação contra ground truth',
    source: 'scripts/validate_free_stages.py::check_zero_evidence',
    figures: [
      ['Candidatos marcados', '1.419 (48,8%)', 'descarte gratuito, muito atrativo'],
      ['Notas ground-truth marcadas', '9', 'destruiria o recall dessas perguntas'],
    ],
    note: 'O benchmark mostra "o juiz concorda" (0 discordâncias), mas isso é medido apenas sobre os '
      + 'candidatos que chegaram ao juiz. A promoção é decidida pelo teste contra ground truth, que '
      + 'reprova. Implementada, medida todo run, jamais autorizada a servir.',
  },
  {
    id: 'cost-model-constants',
    status: 'experimental',
    title: 'Modelo de custo: forma confirmada, constantes não',
    date: '2026-09-27',
    scope: '9 braços · 120 perguntas',
    source: 'scripts/audit_opt_report.py',
    figures: [
      ['Modelo', '340 × requisições + 209 × perguntas', 'erro declarado antes: ~0,3%'],
      ['Erro medido agora', '+7,0% a +8,1%', 'subestima de forma consistente'],
    ],
    note: 'A forma vale (requisições e perguntas são as variáveis certas, e a razão entre elas se '
      + 'mantém), mas as constantes foram ajustadas numa amostra menor. Conclusões que dependem só '
      + 'da razão seguem válidas; os valores absolutos precisam de novo ajuste antes de serem citados.',
  },
  {
    id: 'opt-stack-final-3pct',
    status: 'invalid',
    title: 'Headline "−3,0% de tokens totais" do stack completo',
    date: '2026-09-27',
    scope: 'Comparação de braços baseline vs full_stack',
    source: 'reports/opt_stack_FINAL.json',
    figures: [
      ['Número publicado', 'RETIRADO', 'não é exibido por este dashboard'],
      ['Contexto contaminado', '117.196 tokens', 'contra 56.045 na medição correta'],
    ],
    note: 'Contaminado por vazamento de contexto: candidatos UNSELECTED (que o otimizador decidiu '
      + 'não pagar para julgar) chegavam ao contexto do consumidor — 194 candidatos, 60.534 tokens, '
      + '51,7% do contexto daquele braço. A economia de tokens de juiz estava sendo paga com tokens '
      + 'de contexto. Substituído por opt-stack-v2, medido após a correção em survives() e na rede '
      + 'de segurança do pipeline.',
  },
];

export const invalidResults = () => RESULTS.filter((r) => r.status === 'invalid');
export const verifiedResults = () => RESULTS.filter((r) => r.status === 'verified');

/** Provenance of everything computed at runtime from benchmark.db. */
export const LIVE_PROVENANCE = {
  status: 'experimental',
  why: 'Calculado ao vivo a partir das runs gravadas em benchmark.db (GET /benchmark/runs). '
    + 'Serve para observar o sistema, não como resultado publicável: as runs vêm de sessões, '
    + 'configurações e braços diferentes, e nenhuma delas foi re-medida após a correção do '
    + 'vazamento de contexto.',
};
