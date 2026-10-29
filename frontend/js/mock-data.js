/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAMNÉSIA MOCK DATA STORE (PT-BR)
 * Dados realistas para simulação local, respeitando rigorosamente a Seção 7 do brief.
 */

export const mockProjects = [
  {
    id: 'proj-1',
    name: 'anamnesia-core',
    path: '~/dev/anamnesia/core',
    active_sessions: 2,
    git_branch: 'main',
    vault_size_mb: 42.8,
  },
  {
    id: 'proj-2',
    name: 'ecommerce-backend',
    path: '~/work/fintech/ecommerce-api',
    active_sessions: 1,
    git_branch: 'feature/payment-v2',
    vault_size_mb: 118.4,
  },
  {
    id: 'proj-3',
    name: 'hermes-plugin-graph',
    path: '~/dev/plugins/hermes-graph',
    active_sessions: 0,
    git_branch: 'develop',
    vault_size_mb: 19.1,
  },
  {
    id: 'proj-4',
    name: 'cli-orchestrator',
    path: '~/experiments/agent-orchestrator',
    active_sessions: 0,
    git_branch: 'refactor/jev-filter',
    vault_size_mb: 8.5,
  }
];

export const mockFiles = [
  { name: 'src', type: 'dir', indent: 0 },
  { name: 'gateway', type: 'dir', indent: 1 },
  { name: 'router.ts', type: 'file', indent: 2, size: '4.2 KB' },
  { name: 'cache.ts', type: 'file', indent: 2, size: '8.1 KB' },
  { name: 'filter.ts', type: 'file', indent: 2, size: '12.0 KB' },
  { name: 'evaluator.ts', type: 'file', indent: 2, size: '15.4 KB' },
  { name: 'memory', type: 'dir', indent: 1 },
  { name: 'vault.ts', type: 'file', indent: 2, size: '9.6 KB' },
  { name: 'embeddings.ts', type: 'file', indent: 2, size: '6.3 KB' },
  { name: 'graphify.ts', type: 'file', indent: 2, size: '18.7 KB' },
  { name: 'jev.ts', type: 'file', indent: 2, size: '11.2 KB' },
  { name: 'types', type: 'dir', indent: 1 },
  { name: 'index.ts', type: 'file', indent: 2, size: '3.1 KB' },
  { name: 'session.ts', type: 'file', indent: 2, size: '2.4 KB' },
  { name: 'telemetry.ts', type: 'file', indent: 2, size: '4.8 KB' },
  { name: 'docs', type: 'dir', indent: 0 },
  { name: 'architecture.md', type: 'file', indent: 1, size: '14.1 KB' },
  { name: 'jev-pipeline.md', type: 'file', indent: 1, size: '8.9 KB' },
  { name: 'benchmarks.md', type: 'file', indent: 1, size: '6.0 KB' },
  { name: 'package.json', type: 'file', indent: 0, size: '1.4 KB' },
  { name: 'tsconfig.json', type: 'file', indent: 0, size: '0.8 KB' },
  { name: 'README.md', type: 'file', indent: 0, size: '5.2 KB' },
  { name: '.env.example', type: 'file', indent: 0, size: '0.4 KB' },
  { name: 'firestore.rules', type: 'file', indent: 0, size: '1.1 KB' },
  { name: 'anamnesia.config.json', type: 'file', indent: 0, size: '0.9 KB' }
];

export const mockRecentContext = [
  {
    title: 'architecture-decision-004: Pipeline JEV com Veredito Conjunto',
    source: 'vault/decisions/adr-004.md',
    tokens: 840,
    timestamp: 'há 6 min',
    score: 0.94
  },
  {
    title: 'jev-scoring-heuristics: Penalização de Falsos Positivos em Retrieval',
    source: 'vault/evals/heuristics.md',
    tokens: 1120,
    timestamp: 'há 18 min',
    score: 0.89
  },
  {
    title: 'api-spec-v2: Contrato do Gateway Unix Socket para CLIs',
    source: 'vault/specs/gateway-socket.md',
    tokens: 610,
    timestamp: 'há 35 min',
    score: 0.82
  }
];

// Sem seeds: conexões vêm só do backend (GET /api/connections). Nenhum agente aparece conectado por padrão.
export const mockConnections = { agents: [], models: [], mcp: [] };

export const mockPresets = [
  {
    id: 'economico',
    name: 'Econômico',
    tag: 'Foco em custo',
    description: 'Roteamento com modelos compactos para o grosso do trabalho e modelo médio apenas no revisor.',
    roles: {
      orchestrator: { title: 'Orquestrador', class: 'barato', className: 'class-barato', label: 'Barato (ex: Haiku / 8B)' },
      researcher: { title: 'Pesquisador', class: 'barato', className: 'class-barato', label: 'Barato (ex: Haiku / 8B)' },
      implementer: { title: 'Implementador', class: 'barato', className: 'class-barato', label: 'Barato (ex: Qwen 14B)' },
      reviewer: { title: 'Revisor', class: 'medio', className: 'class-medio', label: 'Médio (ex: Sonnet / 4o-mini)' }
    },
    costNote: 'sem medição ainda'
  },
  {
    id: 'equilibrado',
    name: 'Equilibrado',
    tag: 'Padrão recomendado',
    description: 'Melhor relação custo-benefício. Modelos fortes para orquestração e revisão, médios para implementação.',
    roles: {
      orchestrator: { title: 'Orquestrador', class: 'forte', className: 'class-forte', label: 'Forte (ex: Sonnet 3.7)' },
      researcher: { title: 'Pesquisador', class: 'medio', className: 'class-medio', label: 'Médio (ex: 4o-mini / 14B)' },
      implementer: { title: 'Implementador', class: 'medio', className: 'class-medio', label: 'Médio (ex: Qwen 32B)' },
      reviewer: { title: 'Revisor', class: 'forte', className: 'class-forte', label: 'Forte (ex: Sonnet / o3-mini)' }
    },
    costNote: 'sem medição ainda'
  },
  {
    id: 'maximo',
    name: 'Máximo',
    tag: 'Raciocínio profundo',
    description: 'Atribui a classe mais avançada de raciocínio a todos os papéis do ciclo de desenvolvimento.',
    roles: {
      orchestrator: { title: 'Orquestrador', class: 'forte', className: 'class-forte', label: 'Forte (ex: o1 / Opus)' },
      researcher: { title: 'Pesquisador', class: 'forte', className: 'class-forte', label: 'Forte (ex: Sonnet 3.7)' },
      implementer: { title: 'Implementador', class: 'forte', className: 'class-forte', label: 'Forte (ex: Sonnet 3.7)' },
      reviewer: { title: 'Revisor', class: 'forte', className: 'class-forte', label: 'Forte (ex: o3 / Opus)' }
    },
    costNote: 'sem medição ainda'
  }
];

export const mockCostSummary = {
  total_usd: { value: 0.42, origin: 'measured', label: 'US$ 0,42' },
  calls: { value: 34, origin: 'measured', label: '34 chamadas' },
  context_tokens: { value: 182400, origin: 'measured', label: '182.4K tok' },
  saved_tokens_est: { value: 94600, origin: 'estimated', label: '94.6K tok' }
};

export const mockBudget = {
  daily: {
    spent: 0.42,
    limit: 2.00,
    currency: 'US$',
    pct: 21,
    status: 'ok',
    statusLabel: 'Normal'
  },
  monthly: {
    spent: 11.85,
    limit: 50.00,
    currency: 'US$',
    pct: 23.7,
    status: 'ok',
    statusLabel: 'Normal'
  }
};

// 30 chamadas com origem explícita
export const mockCalls = [
  { id: 'call-01', when: '11:22:10', project: 'anamnesia-core', agent: 'claude-code', pipeline: 'graphify_jev', context_tokens: 3840, cost_usd: { value: 0.0192, origin: 'measured' } },
  { id: 'call-02', when: '11:18:44', project: 'anamnesia-core', agent: 'claude-code', pipeline: 'graphify_jev', context_tokens: 4120, cost_usd: { value: 0.0206, origin: 'measured' } },
  { id: 'call-03', when: '11:15:02', project: 'ecommerce-backend', agent: 'hermes', pipeline: 'graphify', context_tokens: 6400, cost_usd: { value: 0.0128, origin: 'measured' } },
  { id: 'call-04', when: '11:08:21', project: 'anamnesia-core', agent: 'claude-code', pipeline: 'graphify_jev_opt', context_tokens: 2980, cost_usd: { value: 0.0149, origin: 'measured' } },
  { id: 'call-05', when: '10:55:12', project: 'anamnesia-core', agent: 'shell', pipeline: 'baseline', context_tokens: 8190, cost_usd: { value: 0.0409, origin: 'measured' } },
  { id: 'call-06', when: '10:48:30', project: 'ecommerce-backend', agent: 'hermes', pipeline: 'graphify_jev', context_tokens: 4500, cost_usd: { value: 0.0225, origin: 'measured' } },
  { id: 'call-07', when: '10:41:09', project: 'anamnesia-core', agent: 'claude-code', pipeline: 'graphify_jev', context_tokens: 3710, cost_usd: { value: 0.0185, origin: 'measured' } },
  { id: 'call-08', when: '10:32:55', project: 'ecommerce-backend', agent: 'hermes', pipeline: 'graphify', context_tokens: 5890, cost_usd: { value: 0.0117, origin: 'measured' } },
  { id: 'call-09', when: '10:20:14', project: 'cli-orchestrator', agent: 'opencode', pipeline: 'graphify_jev_opt', context_tokens: 3100, cost_usd: { value: null, origin: 'unavailable' } },
  { id: 'call-10', when: '10:14:02', project: 'anamnesia-core', agent: 'claude-code', pipeline: 'graphify_jev', context_tokens: 4200, cost_usd: { value: 0.0210, origin: 'measured' } },
  { id: 'call-11', when: '10:02:40', project: 'anamnesia-core', agent: 'claude-code', pipeline: 'graphify_jev', context_tokens: 3950, cost_usd: { value: 0.0197, origin: 'measured' } },
  { id: 'call-12', when: '09:54:19', project: 'ecommerce-backend', agent: 'hermes', pipeline: 'graphify_jev', context_tokens: 4400, cost_usd: { value: 0.0220, origin: 'measured' } },
  { id: 'call-13', when: '09:41:33', project: 'anamnesia-core', agent: 'claude-code', pipeline: 'graphify_jev_opt', context_tokens: 2850, cost_usd: { value: 0.0142, origin: 'measured' } },
  { id: 'call-14', when: '09:33:10', project: 'cli-orchestrator', agent: 'opencode', pipeline: 'baseline', context_tokens: 9200, cost_usd: { value: 0.0184, origin: 'estimated' } },
  { id: 'call-15', when: '09:21:45', project: 'ecommerce-backend', agent: 'hermes', pipeline: 'graphify', context_tokens: 6100, cost_usd: { value: 0.0122, origin: 'measured' } },
  { id: 'call-16', when: '09:15:00', project: 'anamnesia-core', agent: 'claude-code', pipeline: 'graphify_jev', context_tokens: 3600, cost_usd: { value: 0.0180, origin: 'measured' } },
  { id: 'call-17', when: '09:02:18', project: 'ecommerce-backend', agent: 'hermes', pipeline: 'graphify_jev', context_tokens: 4800, cost_usd: { value: 0.0240, origin: 'measured' } },
  { id: 'call-18', when: '08:50:44', project: 'anamnesia-core', agent: 'claude-code', pipeline: 'graphify_jev', context_tokens: 3920, cost_usd: { value: 0.0196, origin: 'measured' } },
  { id: 'call-19', when: '08:44:12', project: 'cli-orchestrator', agent: 'opencode', pipeline: 'graphify_jev_opt', context_tokens: 3050, cost_usd: { value: null, origin: 'unavailable' } },
  { id: 'call-20', when: '08:35:05', project: 'anamnesia-core', agent: 'claude-code', pipeline: 'graphify_jev', context_tokens: 4180, cost_usd: { value: 0.0209, origin: 'measured' } },
  { id: 'call-21', when: '08:22:30', project: 'ecommerce-backend', agent: 'hermes', pipeline: 'graphify', context_tokens: 5900, cost_usd: { value: 0.0118, origin: 'measured' } },
  { id: 'call-22', when: '08:14:15', project: 'anamnesia-core', agent: 'claude-code', pipeline: 'graphify_jev_opt', context_tokens: 2790, cost_usd: { value: 0.0139, origin: 'measured' } },
  { id: 'call-23', when: '08:05:00', project: 'ecommerce-backend', agent: 'hermes', pipeline: 'graphify_jev', context_tokens: 4320, cost_usd: { value: 0.0216, origin: 'measured' } },
  { id: 'call-24', when: '07:54:19', project: 'anamnesia-core', agent: 'claude-code', pipeline: 'graphify_jev', context_tokens: 3880, cost_usd: { value: 0.0194, origin: 'measured' } },
  { id: 'call-25', when: '07:41:02', project: 'anamnesia-core', agent: 'shell', pipeline: 'baseline', context_tokens: 8400, cost_usd: { value: 0.0420, origin: 'measured' } },
  { id: 'call-26', when: '07:29:40', project: 'ecommerce-backend', agent: 'hermes', pipeline: 'graphify', context_tokens: 6250, cost_usd: { value: 0.0125, origin: 'measured' } },
  { id: 'call-27', when: '07:18:11', project: 'anamnesia-core', agent: 'claude-code', pipeline: 'graphify_jev_opt', context_tokens: 2910, cost_usd: { value: 0.0145, origin: 'measured' } },
  { id: 'call-28', when: '07:05:54', project: 'cli-orchestrator', agent: 'opencode', pipeline: 'graphify_jev', context_tokens: 3800, cost_usd: { value: 0.0190, origin: 'estimated' } },
  { id: 'call-29', when: '06:50:20', project: 'ecommerce-backend', agent: 'hermes', pipeline: 'graphify_jev', context_tokens: 4450, cost_usd: { value: 0.0222, origin: 'measured' } },
  { id: 'call-30', when: '06:38:12', project: 'anamnesia-core', agent: 'claude-code', pipeline: 'graphify_jev', context_tokens: 3750, cost_usd: { value: 0.0187, origin: 'measured' } }
];
