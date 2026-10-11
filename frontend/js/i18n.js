/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAMNÉSIA I18N DICTIONARY (PT-BR)
 * Todas as strings da aplicação centralizadas para facilitar futura internacionalização.
 */

const PT = {
  app: {
    title: 'Anamnésia',
    tagline: 'Memória Persistente & Orquestração de Agentes IA',
    localHealthOk: 'Local · ok',
    localHealthWarn: 'Local · lento',
    localHealthError: 'Local · falha',
    version: 'v0.9.4-alpha',
    themeDark: 'Tema escuro',
    themeLight: 'Tema claro',
    searchPlaceholder: 'Buscar projetos, páginas, comandos... (Ctrl+K)',
    compareModelsBtn: 'Comparar Modelos',
    backToApp: 'Voltar ao Anamnésia',
    labBadge: 'Laboratório de Comparação',
    measured: 'medido',
    estimated: 'estimado',
    unavailable: 'indisponível',
    verified: 'Verificado',
    experimental: 'Experimental',
    invalidated: 'Invalidado',
    close: 'Fechar',
    save: 'Salvar',
    cancel: 'Cancelar',
    test: 'Testar',
    copy: 'Copiar',
    copied: 'Copiado para a área de transferência',
    runNewComparison: 'Executar nova comparação',
    emptyTitle: 'Nenhum dado encontrado',
    emptyAction: 'Começar agora',
    loading: 'Carregando dados...',
    errorTitle: 'Não foi possível carregar os dados',
    errorRetry: 'Tentar novamente',
    toggleTheme: 'Alternar tema',
    switchToLight: 'Claro',
    switchToDark: 'Escuro',
    language: 'Idioma',
    languageName: 'Português',
    paletteNewTerminal: 'Abrir Novo Terminal Local',
    paletteToggleTheme: 'Alternar Tema Escuro / Claro',
    paletteToggleLang: 'Alternar idioma (PT / EN)',
    labIsolated: 'Ambiente de Teste Isolado',
    labAudit: 'Sessão de Auditoria Local',
    labTabsAria: 'Abas do Laboratório de Comparação',
    labTabLoadFail: 'Não foi possível carregar esta aba',
    noResultsTitle: 'Nenhum resultado',
    noResultsDesc: 'Ajuste os filtros ou o período para ver mais dados.',
    noCallsTitle: 'Nenhuma chamada registrada',
    noCallsDesc: 'Assim que um agente consultar o Memory Gateway, as chamadas aparecerão aqui.',
    backendUnavailableTitle: 'Servidor backend local ainda não detectado',
    backendUnavailableDesc: 'O serviço de persistência e orquestração do Anamnésia opera em localhost. O front-end está em modo de simulação com dados demonstrativos.',
  },
  nav: {
    workspace: 'Workspace',
    connections: 'Conexões',
    config: 'Configuração',
    costs: 'Custos',
  },
  workspace: {
    projectsTitle: 'Projetos',
    addProject: 'Adicionar projeto',
    activeSessions: 'Sessões ativas',
    filesTitle: 'Arquivos',
    searchFiles: 'Filtrar arquivos...',
    newTerminal: 'Novo terminal',
    splitVertical: 'Dividir verticalmente',
    splitHorizontal: 'Dividir horizontalmente',
    emptyTerminalTitle: 'Abra um terminal para começar',
    emptyTerminalDesc: 'Selecione um perfil ou adicione um projeto para orquestrar agentes com memória integrada.',
    profileShell: 'Shell nativo',
    profilePowershell: 'PowerShell',
    profileHermes: 'Hermes Agent',
    profileClaude: 'Claude Code',
    profileCodex: 'Codex CLI',
    profileOpenCode: 'OpenCode',
    profileUnavailable: 'Não instalado',
    sessionActive: 'Ativo',
    sessionStarting: 'Iniciando...',
    sessionEnded: 'Encerrado (código 0)',
    agentContextTitle: 'Contexto Recuperado',
    agentContextSubtitle: 'Últimas notas e memórias injetadas via Memory Gateway',
    retrievedTokens: 'tokens entregues',
    addProjectModalTitle: 'Registrar Novo Projeto',
    projectNameLabel: 'Nome do projeto',
    projectPathLabel: 'Caminho absoluto local (ex: /home/dev/meu-projeto)',
  },
  connections: {
    agentsTitle: 'Agentes de Programação',
    modelsTitle: 'Provedores de Modelos',
    mcpTitle: 'Servidores MCP (Model Context Protocol)',
    detected: 'Detectado',
    notDetected: 'Não detectado',
    configured: 'Chave configurada',
    notConfigured: 'Sem chave',
    online: 'Online',
    offline: 'Offline',
    apiKeyLabel: 'Chave API',
    apiKeyPlaceholder: '••••••••••••••••••••••••',
    viewSnippet: 'Snippet de configuração',
    snippetModalTitle: 'Snippet de Configuração do Agente',
    testSuccess: 'Conexão validada com sucesso',
    saveSuccess: 'Configurações de conexão salvas localmente',
  },
  config: {
    tabSubagents: 'Subagentes',
    tabGateway: 'Gateway de Memória',
    tabActive: 'Configuração Ativa',
    presetsTitle: 'Predefinições de Orquestração',
    presetEco: 'Econômico',
    presetEcoDesc: 'Roteamento focado em baixo consumo e agentes leves',
    presetBal: 'Equilibrado',
    presetBalDesc: 'Distribuição inteligente entre raciocínio e execução',
    presetMax: 'Máximo',
    presetMaxDesc: 'Maior capacidade de orquestração e contexto profundo',
    rolesTitle: 'Matriz de Papéis e Classes de Modelo',
    roleOrchestrator: 'Orquestrador',
    roleResearcher: 'Pesquisador',
    roleImplementer: 'Implementador',
    roleReviewer: 'Revisor',
    classCheap: 'barato',
    classMedium: 'médio',
    classStrong: 'forte',
    estimatedCostNoData: 'Custo estimado: sem medição ainda',
    gatewayVaultLabel: 'Caminho do Vault / Memória',
    gatewayModelKeyLabel: 'Chave do Modelo do Gateway',
    gatewayVerdictJev: 'Ativar Veredito com Avaliação Conjunta (JEV)',
    gatewayVerdictDesc: 'Filtra memórias espúrias antes da montagem do prompt',
    gatewayPreFilter: 'Pré-filtragem vetorial semântica',
    gatewayPreFilterDesc: 'Descarta chunks irrelevantes acima de corte de distância',
    advancedToggle: 'Configurações avançadas do Gateway',
  },
  costs: {
    ledgerTitle: 'Livro de Custos do Memory Gateway',
    periodToday: 'Hoje',
    period7d: '7 dias',
    period30d: '30 dias',
    periodAll: 'Tudo',
    exportCsv: 'Exportar CSV',
    kpiTotal: 'Gasto total',
    kpiCalls: 'Total de chamadas',
    kpiTokens: 'Tokens de contexto',
    kpiContextTokens: 'Tokens de contexto entregues',
    kpiSavedTokens: 'Economia estimada de contexto',
    budgetDaily: 'Orçamento diário',
    budgetMonthly: 'Orçamento mensal',
    budgetOf: 'de',
    callsTableTitle: 'Histórico de Chamadas',
    colWhen: 'Quando',
    colProject: 'Projeto',
    colAgent: 'Agente',
    colPipeline: 'Pipeline',
    colContext: 'Contexto',
    colCost: 'Custo',
    colOrigin: 'Origem',
    colActions: 'Detalhes',
    loadMore: 'Carregar mais chamadas',
    callDetailTitle: 'Detalhamento da Chamada',
  },
  lab: {
    overview: 'Visão geral',
    models: 'Comparação',
    pipeline: 'Pipeline',
    tokens: 'Tokens',
    latency: 'Latência',
    modelCost: 'Custo por modelo',
    results: 'Resultados',
    history: 'Histórico',
    datasetSelect: 'Dataset de avaliação',
    totalRuns: 'Runs executados',
    lastBenchmark: 'Último benchmark',
    diffVersusBaseline: 'vs. Baseline',
    pValue: 'p-valor',
    confidenceInterval: 'Intervalo de confiança 95%',
    statSignificant: 'Estatisticamente significativo (p < 0.05)',
  }
};


const EN = {
  app: {
    title: 'Anamnésia',
    version: 'v0.9.4-alpha',
    tagline: 'Persistent Memory & AI Agent Orchestration',
    localHealthOk: 'Local · ok',
    localHealthWarn: 'Local · slow',
    localHealthError: 'Local · failing',
    themeDark: 'Dark theme',
    themeLight: 'Light theme',
    searchPlaceholder: 'Search projects, pages, commands... (Ctrl+K)',
    compareModelsBtn: 'Compare Models',
    backToApp: 'Back to Anamnésia',
    labBadge: 'Comparison Lab',
    measured: 'measured',
    estimated: 'estimated',
    unavailable: 'unavailable',
    verified: 'Verified',
    experimental: 'Experimental',
    invalidated: 'Invalidated',
    close: 'Close',
    save: 'Save',
    cancel: 'Cancel',
    test: 'Test',
    copy: 'Copy',
    copied: 'Copied to clipboard',
    runNewComparison: 'Run new comparison',
    emptyTitle: 'No data found',
    emptyAction: 'Get started',
    loading: 'Loading data...',
    errorTitle: 'Could not load data',
    errorRetry: 'Try again',
    toggleTheme: 'Toggle theme',
    switchToLight: 'Light',
    switchToDark: 'Dark',
    language: 'Language',
    languageName: 'English',
    paletteNewTerminal: 'Open New Local Terminal',
    paletteToggleTheme: 'Toggle Dark / Light Theme',
    paletteToggleLang: 'Switch language (PT / EN)',
    labIsolated: 'Isolated Test Environment',
    labAudit: 'Local Audit Session',
    labTabsAria: 'Comparison Lab tabs',
    labTabLoadFail: 'Could not load this tab',
    noResultsTitle: 'No results',
    noResultsDesc: 'Adjust the filters or the period to see more data.',
    noCallsTitle: 'No calls recorded',
    noCallsDesc: 'As soon as an agent queries the Memory Gateway, calls will show up here.',
    backendUnavailableTitle: 'Local backend server not detected yet',
    backendUnavailableDesc: 'Anamnésia\'s persistence and orchestration service runs on localhost. The front-end is in simulation mode with demo data.',
  },
  nav: {
    workspace: 'Workspace',
    connections: 'Connections',
    config: 'Settings',
    costs: 'Costs',
  },
  workspace: {
    projectsTitle: 'Projects',
    addProject: 'Add project',
    activeSessions: 'Active sessions',
    filesTitle: 'Files',
    searchFiles: 'Filter files...',
    newTerminal: 'New terminal',
    splitVertical: 'Split vertically',
    splitHorizontal: 'Split horizontally',
    emptyTerminalTitle: 'Open a terminal to get started',
    emptyTerminalDesc: 'Pick a profile or add a project to orchestrate agents with built-in memory.',
    profileShell: 'Native shell',
    profilePowershell: 'PowerShell',
    profileHermes: 'Hermes Agent',
    profileClaude: 'Claude Code',
    profileCodex: 'Codex CLI',
    profileOpenCode: 'OpenCode',
    profileUnavailable: 'Not installed',
    sessionActive: 'Active',
    sessionStarting: 'Starting...',
    sessionEnded: 'Ended (code 0)',
    agentContextTitle: 'Retrieved Context',
    agentContextSubtitle: 'Latest notes and memories injected via Memory Gateway',
    retrievedTokens: 'tokens delivered',
    addProjectModalTitle: 'Register New Project',
    projectNameLabel: 'Project name',
    projectPathLabel: 'Absolute local path (e.g. /home/dev/my-project)',
  },
  connections: {
    agentsTitle: 'Coding Agents',
    modelsTitle: 'Model Providers',
    mcpTitle: 'MCP Servers (Model Context Protocol)',
    online: 'Online',
    offline: 'Offline',
    apiKeyPlaceholder: '••••••••••••••••••••••••',
    detected: 'Detected',
    notDetected: 'Not detected',
    configured: 'Key configured',
    notConfigured: 'No key',
    apiKeyLabel: 'API key',
    viewSnippet: 'Configuration snippet',
    snippetModalTitle: 'Agent Configuration Snippet',
    testSuccess: 'Connection validated successfully',
    saveSuccess: 'Connection settings saved locally',
  },
  config: {
    tabSubagents: 'Subagents',
    tabGateway: 'Memory Gateway',
    tabActive: 'Active Configuration',
    presetsTitle: 'Orchestration Presets',
    presetEco: 'Economy',
    presetEcoDesc: 'Routing focused on low consumption and lightweight agents',
    presetBal: 'Balanced',
    presetBalDesc: 'Smart split between reasoning and execution',
    presetMax: 'Maximum',
    presetMaxDesc: 'Highest orchestration capacity and deep context',
    rolesTitle: 'Role and Model Class Matrix',
    roleOrchestrator: 'Orchestrator',
    roleResearcher: 'Researcher',
    roleImplementer: 'Implementer',
    roleReviewer: 'Reviewer',
    classCheap: 'cheap',
    classMedium: 'medium',
    classStrong: 'strong',
    estimatedCostNoData: 'Estimated cost: no measurement yet',
    gatewayVaultLabel: 'Vault / Memory path',
    gatewayModelKeyLabel: 'Gateway Model Key',
    gatewayVerdictJev: 'Enable Joint Evaluation Verdict (JEV)',
    gatewayVerdictDesc: 'Filters spurious memories before prompt assembly',
    gatewayPreFilter: 'Semantic vector pre-filtering',
    gatewayPreFilterDesc: 'Discards irrelevant chunks beyond a distance cutoff',
    advancedToggle: 'Advanced Gateway settings',
  },
  costs: {
    ledgerTitle: 'Memory Gateway Cost Ledger',
    periodToday: 'Today',
    period7d: '7 days',
    period30d: '30 days',
    periodAll: 'All',
    exportCsv: 'Export CSV',
    kpiTotal: 'Total spend',
    kpiCalls: 'Total calls',
    kpiTokens: 'Context tokens',
    kpiContextTokens: 'Context tokens delivered',
    kpiSavedTokens: 'Estimated context savings',
    budgetDaily: 'Daily budget',
    budgetMonthly: 'Monthly budget',
    budgetOf: 'of',
    callsTableTitle: 'Call History',
    colWhen: 'When',
    colProject: 'Project',
    colAgent: 'Agent',
    colPipeline: 'Pipeline',
    colContext: 'Context',
    colCost: 'Cost',
    colOrigin: 'Origin',
    colActions: 'Details',
    loadMore: 'Load more calls',
    callDetailTitle: 'Call Details',
  },
  lab: {
    overview: 'Overview',
    models: 'Comparison',
    pipeline: 'Pipeline',
    tokens: 'Tokens',
    latency: 'Latency',
    modelCost: 'Cost per model',
    results: 'Results',
    history: 'History',
    datasetSelect: 'Evaluation dataset',
    totalRuns: 'Runs executed',
    lastBenchmark: 'Last benchmark',
    diffVersusBaseline: 'vs. Baseline',
    pValue: 'p-value',
    confidenceInterval: '95% confidence interval',
    statSignificant: 'Statistically significant (p < 0.05)',
  },
};

export const LANGS = ['pt', 'en'];
const LANG_PREF_ITEM = 'anamnesia_lang';
const PT_BASE = JSON.parse(JSON.stringify(PT));

/** Objeto vivo: páginas leem I18N.x.y no momento do render; setLang() o atualiza no lugar. */
export const I18N = JSON.parse(JSON.stringify(PT));
let currentLang = 'pt';

function apply(target, base, over) {
  for (const k of Object.keys(base)) {
    if (base[k] && typeof base[k] === 'object') {
      apply(target[k], base[k], over?.[k]);
    } else {
      // chave ausente no EN cai para PT (nunca mostra undefined)
      target[k] = over && typeof over[k] === 'string' ? over[k] : base[k];
    }
  }
}

export function getLang() { return currentLang; }

/** Chaves do dicionário PT ausentes em EN (para testes/diagnóstico). */
export function missingKeys(lang = 'en') {
  const miss = [];
  const dict = lang === 'en' ? EN : PT;
  (function walk(base, over, path) {
    for (const k of Object.keys(base)) {
      const p = path ? `${path}.${k}` : k;
      if (base[k] && typeof base[k] === 'object') walk(base[k], over?.[k], p);
      else if (typeof over?.[k] !== 'string') miss.push(p);
    }
  })(PT_BASE, dict, '');
  return miss;
}

/** Troca o idioma, persiste e avisa as páginas via evento 'anamnesia:lang'. */
export function setLang(lang, { persist = true, silent = false } = {}) {
  const next = LANGS.includes(lang) ? lang : 'pt';
  apply(I18N, PT_BASE, next === 'en' ? EN : null);
  currentLang = next;
  if (typeof document !== 'undefined') document.documentElement.setAttribute('lang', next === 'en' ? 'en' : 'pt-BR');
  if (persist) { try { localStorage.setItem(LANG_PREF_ITEM, next); } catch { /* storage bloqueado */ } }
  if (!silent && typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('anamnesia:lang', { detail: { lang: next } }));
  }
  return next;
}

export function initialLang() {
  let saved = null;
  try { saved = localStorage.getItem(LANG_PREF_ITEM); } catch { /* ignore */ }
  if (LANGS.includes(saved)) return saved;
  return 'pt';
}

setLang(initialLang(), { persist: false, silent: true });
