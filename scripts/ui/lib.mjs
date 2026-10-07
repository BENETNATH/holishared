// Outillage UI B017 (spec §9.4) : Python, démo, Chrome/CDP, scènes.
// CLI : node scripts/ui/lib.mjs seed | serve
import { spawn, spawnSync } from 'node:child_process';
import { once } from 'node:events';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const UI_DIR = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(UI_DIR, '..', '..');
export const DEMO_DIR = process.env.UI_DEMO_DIR || path.join(os.tmpdir(), 'holishared-ui', 'demo');
export const PORT = Number(process.env.UI_PORT || 8499);
export const BASE_URL = `http://127.0.0.1:${PORT}`;
const CDP_PORT = Number(process.env.UI_CDP_PORT || 9333);

export const VIEWPORTS = {
  360: { width: 360, height: 800, deviceScaleFactor: 2, mobile: true },
  390: { width: 390, height: 844, deviceScaleFactor: 2, mobile: true },
  820: { width: 820, height: 1180, deviceScaleFactor: 2, mobile: true },
  1280: { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false },
};
const CHECK_IDS = ['hscroll', 'console', 'nav', 'targets', 'contrast-text', 'contrast-ui', 'labels',
  'names', 'img-alt', 'h1', 'primary', 'lang-fr', 'assert'];

/** Erreur d'outil (code de sortie 2). */
export class ToolError extends Error {}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function pythonBin() {
  if (process.env.PYTHON) return process.env.PYTHON;
  const venv = path.join(REPO_ROOT, '.venv', 'bin', 'python');
  return fs.existsSync(venv) ? venv : 'python3';
}

export function runSeed() {
  const res = spawnSync(pythonBin(), ['scripts/ui/seed_demo.py', '--out', DEMO_DIR, '--port', String(PORT)],
    { cwd: REPO_ROOT, stdio: 'inherit' });
  if (res.status !== 0) throw new ToolError(`graine en échec (code ${res.status ?? res.error})`);
}

async function httpOk(url) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(1000) });
    return res.status === 200;
  } catch {
    return false;
  }
}

export async function startServer() {
  if (await httpOk(`${BASE_URL}/health`)) throw new ToolError(`port ${PORT} occupé`);
  const child = spawn(pythonBin(), ['scripts/ui/serve_demo.py', '--demo-dir', DEMO_DIR],
    { cwd: REPO_ROOT, stdio: ['ignore', 'ignore', 'pipe'] });
  let stderr = '';
  child.stderr.on('data', (d) => { stderr = (stderr + d).slice(-4000); });
  let exited = false;
  child.on('exit', () => { exited = true; });
  const stop = async () => {
    if (exited) return;
    child.kill('SIGTERM');
    await once(child, 'exit');
  };
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (exited) throw new ToolError(`serveur de démo arrêté : ${stderr.trim()}`);
    if (await httpOk(`${BASE_URL}/health`)) return { stop };
    await sleep(200);
  }
  await stop();
  throw new ToolError(`serveur de démo : /health sans réponse après 20 s ${stderr.trim()}`);
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (err) {
    throw new ToolError(`JSON illisible ${file} : ${err.message}`);
  }
}

export function loadFixtures() {
  return readJson(path.join(DEMO_DIR, 'fixtures.json'));
}

/** Lit et valide un fichier de scènes (format §9.5). */
export function loadScenes(file = path.join(UI_DIR, 'scenes.json'), { selfTest = false } = {}) {
  const doc = readJson(file);
  if (!doc.defaults || !Array.isArray(doc.scenes)) throw new ToolError(`${file} : defaults/scenes manquants`);
  const seen = new Set();
  for (const s of doc.scenes) {
    const where = `${file} scène ${s.id}`;
    if (!/^[a-z0-9]+(-[a-z0-9]+)*$/.test(s.id ?? '') || seen.has(s.id)) throw new ToolError(`${where} : id invalide ou dupliqué`);
    seen.add(s.id);
    if (!s.lot || !s.role || !s.path) throw new ToolError(`${where} : lot/role/path obligatoires`);
    if (!['shell', 'page'].includes(s.scope ?? doc.defaults.scope)) throw new ToolError(`${where} : scope invalide`);
    if (!['event', 'global', 'none'].includes(s.expect?.nav)) throw new ToolError(`${where} : expect.nav invalide`);
    const skip = s.skip ?? [];
    if (skip.some((c) => !CHECK_IDS.includes(c))) throw new ToolError(`${where} : contrôle inconnu dans skip`);
    if (skip.length && !s.note) throw new ToolError(`${where} : skip sans note`);
    if (selfTest && !Array.isArray(s.expectFail)) throw new ToolError(`${where} : expectFail obligatoire`);
    if (!selfTest && (s.expectFail || s.forceLang)) throw new ToolError(`${where} : expectFail/forceLang réservés à l'auto-contrôle`);
    for (const a of s.actions ?? []) {
      if (!['click', 'press', 'scroll', 'wait', 'waitFor', 'reload', 'navigate', 'offline', 'assert', 'drag'].includes(a.type)) {
        throw new ToolError(`${where} : action inconnue ${a.type}`);
      }
      if (a.type === 'wait' && !(a.ms <= 2000)) throw new ToolError(`${where} : wait > 2000 ms`);
    }
  }
  return doc;
}

/** Développe les scènes en runs { scene, viewport, theme, lang } selon les filtres. */
export function expandRuns(doc, filters = {}) {
  const runs = [];
  for (const raw of doc.scenes) {
    const scene = { scope: doc.defaults.scope, actions: [], skip: [], ...raw };
    if (filters.scenes && !filters.scenes.includes(scene.id)) continue;
    for (const width of scene.viewports ?? doc.defaults.viewports) {
      if (filters.viewports && !filters.viewports.includes(width)) continue;
      if (!VIEWPORTS[width]) throw new ToolError(`scène ${scene.id} : viewport inconnu ${width}`);
      for (const theme of scene.themes ?? doc.defaults.themes) {
        if (filters.themes && !filters.themes.includes(theme)) continue;
        for (const lang of scene.langs ?? doc.defaults.langs) {
          if (filters.langs && !filters.langs.includes(lang)) continue;
          runs.push({ scene, viewport: VIEWPORTS[width], theme, lang });
        }
      }
    }
  }
  return runs;
}

export function resolvePath(p, placeholders) {
  return p.replace(/\{([^}]+)\}/g, (_, key) => {
    if (!(key in placeholders)) throw new ToolError(`placeholder inconnu {${key}}`);
    return placeholders[key];
  });
}

export function runLabel(run) {
  return `${run.scene.id} ${run.viewport.width}x${run.viewport.height} ${run.theme} ${run.lang}`;
}

// --- CDP ---------------------------------------------------------------------

function connectCdp(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let nextId = 0;
    const pending = new Map();
    const listeners = new Set();
    ws.onerror = () => reject(new ToolError(`CDP : connexion impossible à ${wsUrl}`));
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id !== undefined) {
        const p = pending.get(msg.id);
        if (!p) return;
        pending.delete(msg.id);
        if (msg.error) p.reject(new Error(`${p.method} : ${msg.error.message}`));
        else p.resolve(msg.result);
      } else {
        for (const listener of listeners) listener(msg);
      }
    };
    ws.onclose = () => {
      for (const p of pending.values()) p.reject(new ToolError('CDP : connexion fermée'));
      pending.clear();
    };
    ws.onopen = () => resolve({
      send(method, params = {}, sessionId = undefined) {
        const id = ++nextId;
        ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
        return new Promise((res, rej) => pending.set(id, { resolve: res, reject: rej, method }));
      },
      /** Abonnement aux évènements ; retourne la fonction de désabonnement. */
      on(handler) {
        listeners.add(handler);
        return () => listeners.delete(handler);
      },
      close() { ws.close(); },
    });
  });
}

function waitEvent(cdp, sessionId, method, timeoutMs) {
  return new Promise((resolve, reject) => {
    const off = cdp.on((msg) => {
      if (msg.sessionId === sessionId && msg.method === method) {
        clearTimeout(timer);
        off();
        resolve(msg.params);
      }
    });
    const timer = setTimeout(() => { off(); reject(new Error(`${method} : délai dépassé`)); }, timeoutMs);
  });
}

export async function launchChrome() {
  if (await httpOk(`http://127.0.0.1:${CDP_PORT}/json/version`)) throw new ToolError(`port CDP ${CDP_PORT} occupé`);
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'holishared-ui-chrome-'));
  const chrome = spawn(process.env.CHROME_BIN || 'google-chrome', [
    '--headless=new', '--no-sandbox', '--disable-gpu', '--hide-scrollbars', '--mute-audio',
    '--no-first-run', '--no-default-browser-check', `--remote-debugging-port=${CDP_PORT}`,
    `--user-data-dir=${profile}`,
  ], { stdio: 'ignore', detached: true });
  let exited = false;
  chrome.on('exit', () => { exited = true; });
  chrome.on('error', () => { exited = true; });
  const close = async (cdp) => {
    cdp?.close();
    if (!exited) {
      // Groupe de processus entier : les sous-processus de Chrome écrivent dans le profil.
      try {
        process.kill(-chrome.pid, 'SIGTERM');
      } catch {
        chrome.kill('SIGTERM');
      }
      await once(chrome, 'exit');
    }
    await sleep(300);
    try {
      fs.rmSync(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
    } catch {
      // Profil temporaire hors dépôt : un reste ne doit pas masquer le résultat de la garde.
    }
  };
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline && !exited) {
    try {
      const res = await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`);
      const info = await res.json();
      const cdp = await connectCdp(info.webSocketDebuggerUrl);
      cdp.userAgent = info['User-Agent'].replace('HeadlessChrome', 'Chrome');
      cdp.closeBrowser = () => close(cdp);
      return cdp;
    } catch {
      await sleep(100);
    }
  }
  await close();
  throw new ToolError('Chrome ne répond pas (CHROME_BIN ?)');
}

/**
 * Règle unique d'évaluation (§9.4) : promesse attendue, délai explicite.
 * Retourne { ok, type, value, error }.
 */
export async function evaluate(cdp, sessionId, expression, timeoutMs) {
  const wrapped = `Promise.race([Promise.resolve().then(() => (${expression})), new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), ${timeoutMs}))])`;
  const res = await cdp.send('Runtime.evaluate', { expression: wrapped, awaitPromise: true, returnByValue: true }, sessionId);
  if (res.exceptionDetails) {
    const d = res.exceptionDetails;
    return { ok: false, error: d.exception?.description?.split('\n')[0] || d.text };
  }
  return { ok: true, type: res.result.type, value: res.result.value };
}

/** Booléen strict : seul `true` (type boolean) est un succès. */
async function evaluateStrict(cdp, sessionId, expression, timeoutMs) {
  const r = await evaluate(cdp, sessionId, expression, timeoutMs);
  if (!r.ok) return { ok: false, reason: r.error };
  if (r.type !== 'boolean') return { ok: false, reason: `valeur non booléenne : ${r.type}` };
  return r.value === true ? { ok: true } : { ok: false, reason: 'faux' };
}

const SETTLE = 'document.fonts.ready.then(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(true)))))';

async function loadAndSettle(cdp, page, navigate) {
  const loaded = waitEvent(cdp, page.sessionId, 'Page.loadEventFired', 30000);
  loaded.catch(() => {});
  await navigate();
  try {
    await loaded;
  } catch {
    page.failures.push('navigation : chargement non terminé en 30 s');
    return false;
  }
  await evaluate(cdp, page.sessionId, SETTLE, 5000);
  return true;
}

/** Ouvre un run dans un contexte de navigation isolé (§9.4). */
export async function openRun(cdp, run, fixtures) {
  const { browserContextId } = await cdp.send('Target.createBrowserContext', { disposeOnDetach: true });
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank', browserContextId });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
  const page = { sessionId, targetId, browserContextId, console: [], failures: [] };
  const s = (method, params) => cdp.send(method, params, sessionId);
  const { width, height, deviceScaleFactor, mobile } = run.viewport;
  await s('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor, mobile });
  await s('Emulation.setTouchEmulationEnabled', { enabled: width < 1024 });
  await s('Emulation.setEmulatedMedia', { features: [
    { name: 'prefers-color-scheme', value: run.theme },
    { name: 'prefers-reduced-motion', value: run.scene.reducedMotion === false ? 'no-preference' : 'reduce' },
  ] });
  await s('Network.enable');
  const acceptLanguage = run.scene.forceLang === 'fr-content' ? 'fr' : run.lang;
  await s('Network.setUserAgentOverride', { userAgent: cdp.userAgent, acceptLanguage });
  if (run.scene.role !== 'anonymous') {
    const value = fixtures.cookies?.[run.scene.role];
    if (!value) throw new ToolError(`rôle inconnu ${run.scene.role}`);
    await s('Network.setCookie', { name: 'session', value, url: BASE_URL });
  }
  await s('Runtime.enable');
  await s('Log.enable');
  await s('Page.enable');
  page.off = cdp.on((msg) => {
    if (msg.sessionId !== sessionId) return;
    const p = msg.params;
    if (msg.method === 'Runtime.consoleAPICalled' && ['error', 'warning', 'assert'].includes(p.type)) {
      page.console.push(`console.${p.type}: ${p.args.map((a) => a.value ?? a.description ?? '').join(' ')}`);
    } else if (msg.method === 'Runtime.exceptionThrown') {
      page.console.push(`exception: ${p.exceptionDetails.exception?.description?.split('\n')[0] || p.exceptionDetails.text}`);
    } else if (msg.method === 'Log.entryAdded' && ['error', 'warning'].includes(p.entry.level)) {
      page.console.push(`log.${p.entry.level}: ${p.entry.text}${p.entry.url ? ` (${p.entry.url})` : ''}`);
    }
  });
  page.navigate = (p) => loadAndSettle(cdp, page, () => s('Page.navigate', { url: BASE_URL + resolvePath(p, fixtures.placeholders) }));
  page.close = async () => {
    page.off();
    await cdp.send('Target.disposeBrowserContext', { browserContextId }).catch(() => {});
  };
  page.url = BASE_URL + resolvePath(run.scene.path, fixtures.placeholders);
  await page.navigate(run.scene.path);
  return page;
}

const KEYS = { Escape: 27, Tab: 9, Enter: 13, ArrowLeft: 37, ArrowRight: 39 };
const settleAfter = (ms) => `new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(() => r(true), ${ms}))))`;

/** Exécute les actions de la scène ; les échecs vont dans page.failures (contrôle `assert`). */
export async function runActions(cdp, page, actions) {
  const s = (method, params) => cdp.send(method, params, page.sessionId);
  for (const a of actions) {
    if (a.type === 'click') {
      const r = await evaluate(cdp, page.sessionId, `(() => { const el = document.querySelector(${JSON.stringify(a.target)}); if (!el) return null; el.scrollIntoView({ block: 'center', inline: 'center' }); const b = el.getBoundingClientRect(); return { x: b.left + b.width / 2, y: b.top + b.height / 2 }; })()`, 5000);
      if (!r.ok || !r.value) {
        page.failures.push(`click : cible introuvable ${a.target}`);
        return;
      }
      const { x, y } = r.value;
      await s('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
      await s('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
      await s('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
      await evaluate(cdp, page.sessionId, settleAfter(250), 5000);
    } else if (a.type === 'drag') {
      // Glisser réel à la souris (CDP) : de `from` (index `fromIndex`) vers `to` (index `toIndex`, négatif = depuis la fin).
      // `from`/`to` peut être `expr:<js>` (renvoie l'élément ; évalué au moment de la résolution). La cible est résolue APRÈS un premier déplacement : les zones de dépôt n'existent à l'écran qu'une fois le glisser actif.
      // Gardés dans sessionStorage pour les assertions après rechargement : __dragMealId (carte saisie), __dragFromCell et
      // __dropCell ("date|créneau"), __dropMealId (carte visée, si la cible est une carte).
      const point = (sel, index, scroll, role) => evaluate(cdp, page.sessionId, `(() => { let el; if (${JSON.stringify(sel)}.startsWith('expr:')) { el = (0, eval)(${JSON.stringify(sel)}.slice(5)); } else { const els = document.querySelectorAll(${JSON.stringify(sel)}); const i = ${index ?? 0}; el = els[i < 0 ? els.length + i : i]; } if (!el) return null; if (${scroll} && !${JSON.stringify(sel)}.startsWith('expr:')) el.scrollIntoView({ block: 'center', inline: 'center' }); const b = el.getBoundingClientRect(); const card = el.closest('[data-meal-id]'); const cell = el.closest('[data-testid=meal-cell]'); if (cell) sessionStorage.setItem(${JSON.stringify(role)} === 'from' ? '__dragFromCell' : '__dropCell', cell.dataset.date + '|' + cell.dataset.slot); if (card) sessionStorage.setItem(${JSON.stringify(role)} === 'from' ? '__dragMealId' : '__dropMealId', card.dataset.mealId); return { x: b.left + b.width / 2, y: b.top + b.height / 2, inView: b.top >= 0 && b.bottom <= innerHeight }; })()`, 5000);
      const from = await point(a.from, a.fromIndex, true, 'from');
      if (!from.ok || !from.value) {
        page.failures.push(`drag : source introuvable ${a.from}`);
        return;
      }
      await s('Input.dispatchMouseEvent', { type: 'mouseMoved', x: from.value.x, y: from.value.y });
      await s('Input.dispatchMouseEvent', { type: 'mousePressed', x: from.value.x, y: from.value.y, button: 'left', clickCount: 1 });
      await s('Input.dispatchMouseEvent', { type: 'mouseMoved', x: from.value.x + 14, y: from.value.y + 14, button: 'left', buttons: 1 });
      await sleep(60);
      const to = await point(a.to, a.toIndex, false, 'to');
      if (!to.ok || !to.value || !to.value.inView) {
        await s('Input.dispatchMouseEvent', { type: 'mouseReleased', x: from.value.x, y: from.value.y, button: 'left', clickCount: 1 });
        page.failures.push(`drag : cible introuvable ou hors écran ${a.to}`);
        return;
      }
      const steps = 10;
      for (let i = 1; i <= steps; i++) {
        const x = from.value.x + ((to.value.x - from.value.x) * i) / steps;
        const y = from.value.y + ((to.value.y - from.value.y) * i) / steps;
        await s('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, button: 'left', buttons: 1 });
        await sleep(16);
      }
      await s('Input.dispatchMouseEvent', { type: 'mouseReleased', x: to.value.x, y: to.value.y, button: 'left', clickCount: 1 });
      await evaluate(cdp, page.sessionId, settleAfter(400), 5000);
    } else if (a.type === 'press') {
      const code = KEYS[a.key];
      if (!code) throw new ToolError(`touche non prise en charge ${a.key}`);
      const base = { key: a.key, code: a.key, windowsVirtualKeyCode: code, nativeVirtualKeyCode: code };
      await s('Input.dispatchKeyEvent', { type: a.key === 'Enter' ? 'keyDown' : 'rawKeyDown', ...(a.key === 'Enter' ? { text: '\r' } : {}), ...base });
      await s('Input.dispatchKeyEvent', { type: 'keyUp', ...base });
      await evaluate(cdp, page.sessionId, settleAfter(0), 5000);
    } else if (a.type === 'scroll') {
      const y = a.to === 'top' ? '0' : 'document.documentElement.scrollHeight';
      await evaluate(cdp, page.sessionId, `(window.scrollTo(0, ${y}), ${settleAfter(0)})`, 5000);
    } else if (a.type === 'wait') {
      await sleep(a.ms);
    } else if (a.type === 'waitFor') {
      const timeout = a.timeout ?? 5000;
      const deadline = Date.now() + timeout;
      let last = { ok: false, reason: 'non évalué' };
      while (Date.now() < deadline) {
        last = await evaluateStrict(cdp, page.sessionId, a.expr, Math.max(1, deadline - Date.now()));
        if (last.ok) break;
        await sleep(100);
      }
      if (!last.ok) {
        page.failures.push(`waitFor : délai dépassé (${last.reason})${a.message ? ` — ${a.message}` : ''}`);
        return;
      }
    } else if (a.type === 'reload') {
      if (!await loadAndSettle(cdp, page, () => s('Page.reload', {}))) return;
    } else if (a.type === 'navigate') {
      if (!await page.navigate(a.path)) return;
    } else if (a.type === 'offline') {
      const conditions = { offline: true, latency: 0, downloadThroughput: -1, uploadThroughput: -1 };
      await s('Network.emulateNetworkConditions', conditions);
      const { targetInfos } = await cdp.send('Target.getTargets');
      for (const t of targetInfos.filter((i) => i.type === 'service_worker' && i.browserContextId === page.browserContextId)) {
        const { sessionId } = await cdp.send('Target.attachToTarget', { targetId: t.targetId, flatten: true });
        await cdp.send('Network.enable', {}, sessionId);
        await cdp.send('Network.emulateNetworkConditions', conditions, sessionId);
      }
    } else if (a.type === 'assert') {
      const r = await evaluateStrict(cdp, page.sessionId, a.expr, a.timeout ?? 5000);
      if (!r.ok) page.failures.push(`${a.message ?? a.expr} (${r.reason})`);
    }
  }
}

// --- CLI -----------------------------------------------------------------------

async function cli(command) {
  if (command === 'seed') {
    runSeed();
    return 0;
  }
  if (command === 'serve') {
    runSeed();
    const server = await startServer();
    console.log(`ui:serve — ${BASE_URL} (Ctrl-C pour arrêter)`);
    await new Promise((resolve) => process.once('SIGINT', resolve));
    await server.stop();
    return 0;
  }
  console.error('usage : node scripts/ui/lib.mjs seed|serve');
  return 2;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  cli(process.argv[2]).then((code) => process.exit(code), (err) => {
    console.error(`erreur d'outil : ${err.message}`);
    process.exit(2);
  });
}
