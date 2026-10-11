/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAMNÉSIA TERMINAL FRAME COMPONENT
 * Moldura visual nativa para hospedar xterm.js dentro do contêiner [data-terminal-mount].
 * Zero menções a host, porta, WebSocket ou rede. Estados: "Iniciando...", "Ativo", "Encerrado".
 */

import { icon } from '../icons.js';

/**
 * 16 Cores ANSI estritas compatíveis com o xterm.js e a paleta do sistema
 */
export const ANSI_THEME = {
  background: '#06090D',
  foreground: '#E1E7EF',
  cursor: '#4F9CF9',
  cursorAccent: '#06090D',
  selectionBackground: 'rgba(79, 156, 249, 0.3)',
  black: '#121924',
  red: '#F4666B',
  green: '#2DD4A7',
  yellow: '#F5A524',
  blue: '#4F9CF9',
  magenta: '#C084FC',
  cyan: '#38BDF8',
  white: '#E1E7EF',
  brightBlack: '#4B5565',
  brightRed: '#FB7185',
  brightGreen: '#34D399',
  brightYellow: '#FBBF24',
  brightBlue: '#60A5FA',
  brightMagenta: '#D8B4FE',
  brightCyan: '#67E8F9',
  brightWhite: '#FFFFFF'
};

const TOKEN_MAP = {
  background: '--term-bg', foreground: '--term-fg', cursor: '--term-cursor', cursorAccent: '--term-bg',
  selectionBackground: '--term-selection',
  black: '--term-black', red: '--term-red', green: '--term-green', yellow: '--term-yellow',
  blue: '--term-blue', magenta: '--term-magenta', cyan: '--term-cyan', white: '--term-white',
  brightBlack: '--term-bright-black', brightRed: '--term-bright-red', brightGreen: '--term-bright-green',
  brightYellow: '--term-bright-yellow', brightBlue: '--term-bright-blue', brightMagenta: '--term-bright-magenta',
  brightCyan: '--term-bright-cyan', brightWhite: '--term-bright-white',
};

/**
 * Lê os tokens CSS --term-* do tema ativo (claro/escuro) e devolve um objeto `theme` do xterm.
 * Tokens ausentes caem em ANSI_THEME. Chamar de novo após trocar data-theme.
 * @param {Element} [el] elemento de onde ler os estilos computados (padrão: <html>)
 */
export function readTerminalTheme(el) {
  const root = el || (typeof document !== 'undefined' ? document.documentElement : null);
  if (!root || typeof getComputedStyle === 'undefined') return { ...ANSI_THEME };
  const cs = getComputedStyle(root);
  const theme = {};
  for (const [key, token] of Object.entries(TOKEN_MAP)) {
    const v = cs.getPropertyValue(token).trim();
    theme[key] = v || ANSI_THEME[key];
  }
  return theme;
}

/**
 * Renderiza a moldura visual do terminal para uma sessão
 * @param {object} session
 * @param {object} [options]
 * @returns {string}
 */
export function renderTerminalFrame(session, options = {}) {
  const isSplit = options.isSplit || false;
  const bufferLines = session?.buffer || [
    'anamnesia-local-runtime initialized',
    '➜ Sessão pronta para comandos locais.',
    '➜ '
  ];

  const bufferHtml = bufferLines
    .map(line => {
      // Formatação sutil de prompt sem emojis
      if (line.startsWith('➜')) {
        return `<span style="color: var(--term-cyan); font-weight: 600;">${line}</span>`;
      }
      if (line.includes('[?]') || line.includes('✔')) {
        return `<span style="color: var(--term-green);">${line}</span>`;
      }
      if (line.includes('>')) {
        return `<span style="color: var(--term-fg);">${line}</span>`;
      }
      return `<span>${line}</span>`;
    })
    .join('\n');

  return `
    <div class="terminal-pane" data-session-id="${session.id}">
      <!-- Ponto de encaixe 100% fluido para xterm.js (sem padding para não quebrar dimensões) -->
      <div class="terminal-mount-container" data-terminal-mount data-session-id="${session.id}">
        <div class="terminal-visual-frame" data-terminal-mock-view>
          <div class="terminal-screen" tabindex="0" role="textbox" aria-label="Terminal interativo">
            ${bufferHtml}<span class="terminal-cursor-block" aria-hidden="true"></span>
          </div>
        </div>
      </div>

      <!-- Barra de rodapé da sessão nativa: projeto · perfil · tamanho cols×rows · estado -->
      <div class="terminal-pane-footer">
        <div class="statusbar-item">
          <span>${session.projectName}</span>
          <span aria-hidden="true">/</span>
          <span style="color: var(--text-primary); font-weight: 500;">${session.profileId}</span>
        </div>
        <div class="statusbar-item tabular">
          <span>${session.cols}×${session.rows}</span>
          <span aria-hidden="true">·</span>
          <span style="color: var(--success);">${session.statusText || 'Ativo'}</span>
        </div>
      </div>
    </div>
  `;
}
