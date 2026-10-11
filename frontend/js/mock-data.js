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

export const mockProfiles = [
  {
    id: 'shell',
    name: 'Shell (Bash/Zsh)',
    description: 'Terminal padrão do sistema operacional com injeção de contexto',
    command: '/bin/bash',
    available: true,
    icon: 'terminal'
  },
  {
    id: 'powershell',
    name: 'PowerShell',
    description: 'Ambiente PowerShell com integração de variáveis de ambiente',
    command: 'pwsh',
    available: false,
    icon: 'terminal'
  },
  {
    id: 'hermes',
    name: 'Hermes Agent',
    description: 'Agente autônomo com suporte nativo a memória via Anamnésia Gateway',
    command: 'hermes',
    available: true,
    icon: 'bot'
  },
  {
    id: 'claude-code',
    name: 'Claude Code',
    description: 'CLI oficial da Anthropic configurado com MCP Anamnésia',
    command: 'claude',
    available: true,
    icon: 'bot'
  },
  {
    id: 'codex',
    name: 'Codex CLI',
    description: 'Agente de geração e refatoração de código com memória persistente',
    command: 'codex-cli',
    available: false,
    icon: 'bot'
  },
  {
    id: 'opencode',
    name: 'OpenCode',
    description: 'Orquestrador de código aberto com modelos locais Ollama/vLLM',
    command: 'opencode',
    available: true,
    icon: 'bot'
  }
];

export const mockSessions = [
  {
    id: 'sess-1',
    projectId: 'proj-1',
    projectName: 'anamnesia-core',
    profileId: 'claude-code',
    title: 'claude-code [anamnesia-core]',
    status: 'active',
    statusText: 'Ativo',
    cols: 120,
    rows: 34,
    startTime: '10:42',
    buffer: [
      'anamnesia-core on  main [?] via node v20.12.0',
      '➜ anamnesia-gateway ready on unix:///tmp/anamnesia.sock',
      '➜ Injetando contexto de memória: [architecture-decision-004.md] (840 tokens)',
      '➜ Injetando contexto de memória: [jev-scoring-heuristics.md] (1.120 tokens)',
      'claude-code > Analisando diff de pipeline e calculando p-valor de baseline...',
      'claude-code > Execução pronta: 3 arquivos modificados com sucesso.',
      'claude-code > '
    ]
  },
  {
    id: 'sess-2',
    projectId: 'proj-1',
    projectName: 'anamnesia-core',
    profileId: 'shell',
    title: 'bash [build]',
    status: 'active',
    statusText: 'Ativo',
    cols: 120,
    rows: 34,
    startTime: '11:05',
    buffer: [
      '$ git status -s',
      ' M src/memory/gateway.ts',
      ' M src/eval/evaluator.ts',
      '$ npm run lint',
      '✔ Nenhum erro de sintaxe encontrado.',
      '$ '
    ]
  },
  {
    id: 'sess-3',
    projectId: 'proj-2',
    projectName: 'ecommerce-backend',
    profileId: 'hermes',
    title: 'hermes [ecommerce]',
    status: 'active',
    statusText: 'Ativo',
    cols: 120,
    rows: 34,
    startTime: '09:18',
    buffer: [
      'hermes > Conectado ao projeto: ecommerce-backend',
      'hermes > Recuperando índice de 14.280 nós de código...',
      'hermes > 4 memórias associadas a [payment-v2] montadas.',
      'hermes > Aguardando comando...'
    ]
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

export const mockConnections = {
  agents: [
    {
      id: 'agent-claude',
      name: 'Claude Code',
      type: 'CLI Nativo',
      detected: true,
      has_key: true,
      masked_key: 'sk-ant-••••••••••••••••••••3F9A',
      status: 'online',
      snippet: 'claude config set --mcp anamnesia "npx -y @anamnesia/mcp-server"'
    },
    {
      id: 'agent-codex',
      name: 'Codex CLI',
      type: 'CLI OpenAI',
      detected: false,
      has_key: false,
      masked_key: null,
      status: 'offline',
      snippet: 'npm install -g @openai/codex-cli && codex config --memory anamnesia'
    },
    {
      id: 'agent-hermes',
      name: 'Hermes Agent',
      type: 'Agente Autônomo',
      detected: true,
      has_key: true,
      masked_key: 'sk-hermes-••••••••••••••••8B21',
      status: 'online',
      snippet: 'hermes --vault ~/dev/anamnesia/core --with-anamnesia-gateway'
    },
    {
      id: 'agent-opencode',
      name: 'OpenCode',
      type: 'Open Source Orchestrator',
      detected: true,
      has_key: false,
      masked_key: null,
      status: 'online',
      snippet: 'opencode serve --port 4100 --anamnesia-hook localhost:8492'
    }
  ],
  models: [
    {
      id: 'model-anthropic',
      name: 'Anthropic Claude',
      type: 'Provedor Cloud',
      detected: true,
      has_key: true,
      masked_key: 'sk-ant-api03-••••••••••••••4K9Q',
      status: 'online',
      snippet: 'export ANTHROPIC_API_KEY="sua_chave_aqui"'
    },
    {
      id: 'model-openai',
      name: 'OpenAI GPT-4o / o1',
      type: 'Provedor Cloud',
      detected: true,
      has_key: true,
      masked_key: 'sk-proj-••••••••••••••••••77ZA',
      status: 'online',
      snippet: 'export OPENAI_API_KEY="sua_chave_aqui"'
    },
    {
      id: 'model-openrouter',
      name: 'OpenRouter',
      type: 'Roteador Multi-Modelo',
      detected: true,
      has_key: true,
      masked_key: 'sk-or-v1-••••••••••••••••109E',
      status: 'online',
      snippet: 'export OPENROUTER_API_KEY="sua_chave_aqui"'
    },
    {
      id: 'model-ollama',
      name: 'Ollama Local',
      type: 'Servidor Local (http://localhost:11434)',
      detected: true,
      has_key: false,
      masked_key: null,
      status: 'online',
      snippet: 'ollama pull qwen2.5-coder:14b && ollama serve'
    },
    {
      id: 'model-vllm',
      name: 'vLLM Inference Engine',
      type: 'Servidor Local / GPU',
      detected: false,
      has_key: false,
      masked_key: null,
      status: 'offline',
      snippet: 'python -m vllm.entrypoints.openai.api_server --model Qwen/Qwen2.5-Coder-32B'
    },
    {
      id: 'model-compat',
      name: 'Compatível OpenAI Custom',
      type: 'Endpoint Genérico',
      detected: false,
      has_key: false,
      masked_key: null,
      status: 'offline',
      snippet: 'export OPENAI_BASE_URL="http://seu-cluster-privado/v1"'
    }
  ],
  mcp: [
    {
      id: 'mcp-anamnesia',
      name: 'Anamnésia Vault Gateway MCP',
      type: 'Servidor MCP Local',
      detected: true,
      has_key: true,
      masked_key: 'mcp-token-••••••••••••••••014D',
      status: 'online',
      snippet: '{\n  "mcpServers": {\n    "anamnesia": {\n      "command": "anamnesia-mcp",\n      "args": ["--port", "8492"]\n    }\n  }\n}'
    },
    {
      id: 'mcp-git',
      name: 'Git Context MCP',
      type: 'Servidor MCP Local',
      detected: true,
      has_key: false,
      masked_key: null,
      status: 'online',
      snippet: '{\n  "mcpServers": {\n    "git": {\n      "command": "mcp-server-git"\n    }\n  }\n}'
    }
  ]
};

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

// DADOS DE BENCHMARK (Restritos EXCLUSIVAMENTE ao Laboratório #/compare)
export const mockBenchmark = {
  meta: {
    total_runs: 34,
    last_benchmark: 'há 14 min',
    dataset_name: 'SWE-bench-lite / 50 tasks',
    evaluator_model: 'claude-3-7-sonnet-judge',
    baseline_pipeline: 'baseline'
  },
  pipelines: [
    {
      id: 'baseline',
      name: 'Baseline (Ingênuo)',
      description: 'Envio de 100% dos chunks recuperados sem pré-filtro ou veredito',
      quality_score: 54.2,
      diff_baseline: '+0.0%',
      context_tokens_avg: 8120,
      tokens_wasted_avg: 4890,
      total_latency_ms: 1820,
      stages_latency: { query: 45, retrieval: 380, graphify: 0, prefilter: 0, jev: 0, filter: 20, context: 75, model: 1300 },
      consumer_cost_per_query: 0.0406,
      judge_cost_per_query: 0.0000,
      total_cost_per_query: 0.0406,
      cost_per_1k_tokens: 0.0050,
      p_value: null,
      ci_95: '[-]',
      status: 'baseline',
      seal: 'verified',
      seal_label: 'Baseline Referência'
    },
    {
      id: 'graphify',
      name: 'Graphify puro',
      description: 'Grafo de conexões sintáticas e semânticas entre módulos e notas',
      quality_score: 68.4,
      diff_baseline: '+14.2%',
      context_tokens_avg: 6150,
      tokens_wasted_avg: 2180,
      total_latency_ms: 1980,
      stages_latency: { query: 48, retrieval: 340, graphify: 195, prefilter: 0, jev: 0, filter: 35, context: 62, model: 1300 },
      consumer_cost_per_query: 0.0307,
      judge_cost_per_query: 0.0000,
      total_cost_per_query: 0.0307,
      cost_per_1k_tokens: 0.0050,
      p_value: 0.031,
      ci_95: '[+6.1%, +22.3%]',
      status: 'significant',
      seal: 'verified',
      seal_label: 'Verificado'
    },
    {
      id: 'graphify_jev',
      name: 'Graphify + JEV',
      description: 'Grafo de conhecimento + Avaliação Conjunta de Veredito (JEV) com juiz',
      quality_score: 82.6,
      diff_baseline: '+28.4%',
      context_tokens_avg: 3950,
      tokens_wasted_avg: 420,
      total_latency_ms: 2240,
      stages_latency: { query: 52, retrieval: 320, graphify: 190, prefilter: 65, jev: 245, filter: 48, context: 40, model: 1280 },
      consumer_cost_per_query: 0.0197,
      judge_cost_per_query: 0.0042,
      total_cost_per_query: 0.0239,
      cost_per_1k_tokens: 0.0060,
      p_value: 0.004,
      ci_95: '[+18.2%, +38.6%]',
      status: 'significant',
      seal: 'verified',
      seal_label: 'Verificado'
    },
    {
      id: 'graphify_jev_opt',
      name: 'Graphify + JEV Otimizado',
      description: 'Cache semântico de veredito + poda agressiva de arestas com peso < 0.35',
      quality_score: 84.1,
      diff_baseline: '+29.9%',
      context_tokens_avg: 2980,
      tokens_wasted_avg: 280,
      total_latency_ms: 1760,
      stages_latency: { query: 40, retrieval: 280, graphify: 140, prefilter: 50, jev: 95, filter: 35, context: 30, model: 1090 },
      consumer_cost_per_query: 0.0149,
      judge_cost_per_query: 0.0018,
      total_cost_per_query: 0.0167,
      cost_per_1k_tokens: 0.0056,
      p_value: 0.002,
      ci_95: '[+20.8%, +39.0%]',
      status: 'significant',
      seal: 'experimental',
      seal_label: 'Experimental'
    }
  ],
  pipeline_flow_stages: [
    { id: 'stage-query', step: '01', name: 'Query Parser', type: 'Ingress', avg_latency_ms: 45, desc: 'Extração de intenção e símbolos alvo' },
    { id: 'stage-retrieval', step: '02', name: 'Hybrid Retrieval', type: 'Vector + BM25', avg_latency_ms: 310, desc: 'Busca semântica no vault de memória' },
    { id: 'stage-graphify', step: '03', name: 'Graphify Engine', type: 'Knowledge Graph', avg_latency_ms: 180, desc: 'Expansão de 1-hop e 2-hop no grafo de dependências' },
    { id: 'stage-prefilter', step: '04', name: 'Pré-Filtro', type: 'Heuristic prune', avg_latency_ms: 55, desc: 'Corte por limiar de similaridade de cosseno' },
    { id: 'stage-jev', step: '05', name: 'JEV (Veredito)', type: 'Joint Evaluation', avg_latency_ms: 170, desc: 'Julgamento conjunto cruzando intenção com chunks' },
    { id: 'stage-filter', step: '06', name: 'Filtro Final', type: 'Deduplication', avg_latency_ms: 38, desc: 'Remoção de trechos redundantes ou obsoletos' },
    { id: 'stage-context', step: '07', name: 'Context Assembler', type: 'Token Budgeter', avg_latency_ms: 42, desc: 'Compactação e ordenação de prioridade' },
    { id: 'stage-model', step: '08', name: 'Agent Model', type: 'Inference', avg_latency_ms: 1220, desc: 'Execução do agente (Claude Code / Hermes)' }
  ],
  history_runs: Array.from({ length: 30 }, (_, i) => {
    const runNum = i + 1;
    const baseline = 52.0 + Math.sin(i * 0.4) * 3.5;
    const graphify = 66.0 + Math.sin(i * 0.4 + 0.5) * 4.0;
    const jev = 80.0 + (i * 0.22) + Math.sin(i * 0.3) * 2.5;
    return {
      run: runNum,
      timestamp: `2026-10-${String((i % 10) + 1).padStart(2, '0')}`,
      dataset_size: 50,
      baseline_score: parseFloat(baseline.toFixed(1)),
      graphify_score: parseFloat(graphify.toFixed(1)),
      jev_score: parseFloat(jev.toFixed(1)),
      tokens_saved_pct: parseFloat((28.0 + (i * 0.7)).toFixed(1)),
      latency_p95_ms: 1850 + (i * 12)
    };
  })
};
