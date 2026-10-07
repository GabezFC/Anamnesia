// terminals.js — xterm.js bound to /api/sessions/{id}/ws.
// xterm 6.0.0 + addon-fit 0.11.0 are vendored under /static/vendor/xterm/ (UMD builds that set the
// globals `Terminal` and `FitAddon`). They are injected as same-origin <script src> (CSP script-src
// 'self'); no CDN, no inline code.
//
// Wire protocol (validated in spikes/pty_windows): client → {t:'in', d} and {t:'rs', rows, cols};
// server → raw terminal output (text or binary frames). On reconnect the server replays its buffer,
// so the terminal is reset first to avoid duplicated output.
import { openSessionSocket } from './anamnesia-api.js';

const VENDOR = '/static/vendor/xterm';
let loading = null;

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.async = false;
    s.onload = resolve;
    s.onerror = () => reject(new Error(`não foi possível carregar ${src}`));
    document.head.appendChild(s);
  });
}

/** Load xterm once. Rejects (never throws synchronously) if the vendored files are missing. */
export function loadXterm() {
  if (window.Terminal && window.FitAddon) return Promise.resolve();
  if (!loading) {
    if (!document.querySelector('link[data-xterm-css], link[href$="/xterm/xterm.css"]')) {
      const l = document.createElement('link');
      l.rel = 'stylesheet';
      l.href = `${VENDOR}/xterm.css`;
      l.dataset.xtermCss = '1';
      document.head.appendChild(l);
    }
    loading = loadScript(`${VENDOR}/xterm.js`).then(() => loadScript(`${VENDOR}/addon-fit.js`))
      .catch((e) => { loading = null; throw e; });
  }
  return loading;
}

const THEME = {
  background: '#070A0E', foreground: '#F2F6FB', cursor: '#4F9CF9', selectionBackground: '#243141',
};
const RETRY_MS = [500, 1000, 2000, 4000, 8000];
const MAX_RETRIES = 8;

/**
 * One terminal bound to one session. `hooks`: { onState(state), onPrefix(key, ev) }.
 * states: connecting | live | reconnecting | ended | error
 * `hooks.interceptKey(ev)` returns true when the key was consumed as an app shortcut (prefix chord).
 */
export class SessionTerminal {
  constructor(sessionId, hooks = {}) {
    this.sid = sessionId;
    this.hooks = hooks;
    this.state = 'connecting';
    this.el = document.createElement('div');
    this.el.className = 'ws-term';
    this.el.dataset.sid = sessionId;
    this.term = null;
    this.fit = null;
    this.ws = null;
    this.disposed = false;
    this.retries = 0;
    this.ended = false;
    this.timer = null;
    this.ro = null;
  }

  setState(s) {
    if (this.state === s) return;
    this.state = s;
    this.hooks.onState?.(s, this);
  }

  async start() {
    try {
      await loadXterm();
    } catch (e) {
      this.setState('error');
      this.el.textContent = e.message;
      return;
    }
    if (this.disposed) return;
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    this.term = new window.Terminal({
      fontFamily: 'Consolas, "Cascadia Mono", monospace', fontSize: 14, cursorBlink: !reduce,
      allowProposedApi: true, theme: THEME, scrollback: 5000,
    });
    this.fit = new window.FitAddon.FitAddon();
    this.term.loadAddon(this.fit);
    this.term.open(this.el);
    this.term.attachCustomKeyEventHandler((ev) => {
      if (ev.type !== 'keydown') return !this.hooks.interceptKey?.(ev, 'peek');
      return !this.hooks.interceptKey?.(ev, 'down');
    });
    this.term.onData((d) => this.send({ t: 'in', d }));
    this.term.onResize(({ rows, cols }) => this.send({ t: 'rs', rows, cols }));
    this.ro = new ResizeObserver(() => this.refit());
    this.ro.observe(this.el);
    if (this.pendingFocus) { this.pendingFocus = false; this.term.focus(); }
    this.connect();
  }

  send(obj) {
    if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(obj));
  }

  /** Fit to the container; skipped while hidden (0×0) so xterm never collapses to 1 column. */
  refit() {
    if (!this.fit || !this.el.isConnected || !this.el.offsetWidth || !this.el.offsetHeight) return;
    try {
      this.fit.fit();
      if (this.term) this.send({ t: 'rs', rows: this.term.rows, cols: this.term.cols });
    } catch { /* fit throws if the element is not laid out yet */ }
  }

  focus() { if (this.term) this.term.focus(); else this.pendingFocus = true; }

  async connect() {
    if (this.disposed) return;
    this.setState(this.retries ? 'reconnecting' : 'connecting');
    let ws;
    try { ws = await openSessionSocket(this.sid); } catch { return this.scheduleRetry(); }
    if (this.disposed) { ws.close(); return undefined; }
    this.ws = ws;
    ws.onopen = () => {
      this.retries = 0;
      this.setState('live');
      this.refit();
    };
    ws.onmessage = (ev) => {
      if (!this.term) return;
      if (typeof ev.data === 'string') { this.control(ev.data); return; }   // text frames are control JSON
      this.term.write(new Uint8Array(ev.data));
    };
    ws.onclose = (ev) => {
      this.ws = null;
      if (this.disposed) return;
      // 4403 forbidden / 4404 unknown session / 1000 clean end after the process exited: nothing to reconnect to.
      if ([1000, 1008, 4403, 4404].includes(ev.code) || this.ended) { this.setState('ended'); return; }
      this.scheduleRetry();
    };
    ws.onerror = () => { /* onclose follows and drives the retry */ };
    return undefined;
  }

  /** Server control frames: {t:'replay'} precedes the buffered bytes; {t:'state', v:'ended'} closes the session. */
  control(raw) {
    let m = null;
    try { m = JSON.parse(raw); } catch { return; }
    if (!m || typeof m !== 'object') return;
    if (m.t === 'replay') this.term?.reset();               // replay follows: start from a clean screen
    else if (m.t === 'state' && m.v === 'ended') { this.ended = true; this.setState('ended'); }
  }

  scheduleRetry() {
    if (this.disposed) return;
    if (this.retries >= MAX_RETRIES) { this.setState('ended'); return; }
    const wait = RETRY_MS[Math.min(this.retries, RETRY_MS.length - 1)];
    this.retries += 1;
    this.setState('reconnecting');
    this.timer = setTimeout(() => this.connect(), wait);
  }

  /** Manual reconnect (button) after the automatic retries gave up. */
  reconnectNow() {
    clearTimeout(this.timer);
    this.retries = 0;
    this.connect();
  }

  dispose() {
    this.disposed = true;
    clearTimeout(this.timer);
    this.ro?.disconnect();
    try { this.ws?.close(1000); } catch { /* already closed */ }
    try { this.term?.dispose(); } catch { /* ignore */ }
    this.el.remove();
  }
}
