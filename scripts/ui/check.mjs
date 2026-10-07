// Garde UI B017 (spec §9.7–§9.10).
// node scripts/ui/check.mjs [--scenes a,b] [--viewports 360,1280] [--themes dark] [--langs en]
//                           [--out DIR] [--shots] [--no-server] [--self-test]
// Codes : 0 vert ; 1 échec non excepté ou exception inutilisée (ou écart d'auto-contrôle) ; 2 erreur d'outil.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  REPO_ROOT, UI_DIR, ToolError, evaluate, expandRuns, launchChrome, loadFixtures, loadScenes,
  openRun, runActions, runLabel, runSeed, startServer,
} from './lib.mjs';

// --- Fonction d'audit, sérialisée et exécutée dans la page ------------------------

async function audit(params) {
  const { scope, nav, lang, frMsgids } = params;
  const out = {};
  const result = (id, details, skipped) => { out[id] = { ok: details.length === 0, details, ...(skipped ? { skipped } : {}) }; };
  const raf2 = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  const inScope = (el) => scope === 'page' || !!el.closest('[data-ui-shell]');
  const short = (el) => {
    const testid = el.getAttribute('data-testid');
    if (testid) return `[data-testid=${testid}]`;
    let s = el.tagName.toLowerCase();
    if (el.id) s += `#${el.id}`;
    const cls = [...el.classList].slice(0, 2).join('.');
    return cls ? `${s}.${cls}` : s;
  };
  const inClosedDialog = (el) => {
    for (let e = el; e; e = e.parentElement) if (e.tagName === 'DIALOG' && !e.open) return true;
    return false;
  };
  // « Rendu » : visible sans condition de viewport ; « visible » : rendu + intersecte le viewport.
  const rendered = (el) => {
    if (el.closest('[hidden],[inert]') || inClosedDialog(el)) return false;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    let opacity = 1;
    for (let e = el; e; e = e.parentElement) opacity *= parseFloat(getComputedStyle(e).opacity);
    if (opacity <= 0) return false;
    const r = el.getBoundingClientRect();
    return r.width * r.height > 0;
  };
  const visible = (el) => {
    if (!rendered(el)) return false;
    const r = el.getBoundingClientRect();
    return r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < innerHeight;
  };
  const disabled = (el) => el.matches(':disabled') || !!el.closest('[aria-disabled="true"]');
  const all = (sel) => [...document.querySelectorAll(sel)].filter(inScope);

  // Couleurs et contraste (WCAG 2.1)
  const parse = (c) => {
    const m = /rgba?\(([^)]+)\)/.exec(c || '');
    if (!m) return null;
    const p = m[1].split(/[\s,/]+/).filter(Boolean).map(parseFloat);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const over = (top, bottom) => ({
    r: top.r * top.a + bottom.r * (1 - top.a), g: top.g * top.a + bottom.g * (1 - top.a),
    b: top.b * top.a + bottom.b * (1 - top.a), a: 1,
  });
  const lum = (c) => {
    const ch = [c.r, c.g, c.b].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
  };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const effectiveBg = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.backgroundImage !== 'none') return { image: true };
      const c = parse(cs.backgroundColor);
      if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; }
    }
    let bg = { r: 255, g: 255, b: 255, a: 1 };
    for (const layer of layers.reverse()) bg = over(layer, bg);
    return bg;
  };

  // hscroll (toute la page)
  {
    const details = [];
    if (document.documentElement.scrollWidth > innerWidth) {
      const culprits = [...document.querySelectorAll('body *')].filter((el) => {
        if (getComputedStyle(el).position === 'fixed') return false;
        return el.getBoundingClientRect().right > innerWidth + 1;
      }).slice(0, 5).map(short);
      details.push(`scrollWidth ${document.documentElement.scrollWidth} > ${innerWidth} : ${culprits.join(', ')}`);
    }
    result('hscroll', details);
  }

  // targets
  {
    const details = [];
    const sel = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=tab], [role=switch], [tabindex]:not([tabindex="-1"])';
    for (const el of all(sel)) {
      if (!visible(el) || disabled(el)) continue;
      const cs = getComputedStyle(el);
      if (el.tagName === 'A' && cs.display === 'inline') {
        let block = el.parentElement;
        while (block && getComputedStyle(block).display === 'inline') block = block.parentElement;
        if (block && block.textContent.replace(el.textContent, '').trim()) continue;
      }
      if (el.matches('input[type=checkbox], input[type=radio]')) {
        const label = el.closest('label') || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`));
        if (label) { const lr = label.getBoundingClientRect(); if (lr.width >= 43.5 && lr.height >= 43.5) continue; }
      }
      const r = el.getBoundingClientRect();
      if (r.width < 43.5 || r.height < 43.5) details.push(`${short(el)} ${Math.round(r.width)}×${Math.round(r.height)}`);
    }
    result('targets', details);
  }

  // contrast-text
  {
    const details = [];
    const skipped = [];
    for (const el of all('body *')) {
      if (['SCRIPT', 'STYLE', 'TEMPLATE', 'NOSCRIPT'].includes(el.tagName)) continue;
      const hasText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
      if (!hasText || !visible(el) || disabled(el) || el.closest('[aria-hidden="true"]')) continue;
      const cs = getComputedStyle(el);
      const bg = effectiveBg(el);
      const fg = parse(cs.color);
      if (bg.image || !fg) { skipped.push(short(el)); continue; }
      const size = parseFloat(cs.fontSize);
      const large = size >= 24 || (size >= 18.66 && parseInt(cs.fontWeight, 10) >= 700);
      const value = ratio(over(fg, bg), bg);
      if (value < (large ? 3 : 4.5)) details.push(`${short(el)} ${value.toFixed(2)}:1`);
    }
    result('contrast-text', details, skipped.length ? skipped : undefined);
  }

  // contrast-ui
  {
    const details = [];
    const sel = 'input:not([type=hidden]):not([type=submit]):not([type=button]), select, textarea, [role=switch], .ui-check input, .ui-radio input';
    for (const el of all(sel)) {
      if (!visible(el) || disabled(el)) continue;
      const cs = getComputedStyle(el);
      const parentBg = effectiveBg(el.parentElement);
      if (parentBg.image) continue;
      const border = parseFloat(cs.borderTopWidth) >= 1 ? parse(cs.borderTopColor) : null;
      const own = parse(cs.backgroundColor);
      const color = border || (own ? over(own, parentBg) : parentBg);
      const value = ratio(over(color, parentBg), parentBg);
      if (value < 3) details.push(`${short(el)} ${value.toFixed(2)}:1`);
    }
    result('contrast-ui', details);
  }

  // labels / names / img-alt
  const textById = (ids) => (ids || '').split(/\s+/).map((id) => document.getElementById(id)?.textContent.trim() || '').join(' ').trim();
  {
    const details = [];
    const sel = 'input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=image]), select, textarea';
    for (const el of all(sel)) {
      if (!visible(el)) continue;
      const named = (el.id && [...document.querySelectorAll(`label[for="${CSS.escape(el.id)}"]`)].some((l) => l.textContent.trim()))
        || el.closest('label')?.textContent.trim() || el.getAttribute('aria-label')?.trim() || textById(el.getAttribute('aria-labelledby'));
      if (!named) details.push(short(el));
    }
    result('labels', details);
  }
  {
    const details = [];
    for (const el of all('a[href], button, [role=button]')) {
      if (!visible(el)) continue;
      const named = el.textContent.trim() || el.getAttribute('aria-label')?.trim() || textById(el.getAttribute('aria-labelledby'))
        || el.getAttribute('title')?.trim() || [...el.querySelectorAll('img[alt]')].some((i) => i.alt.trim());
      if (!named) details.push(short(el));
    }
    result('names', details);
  }
  {
    const details = [];
    for (const img of all('img')) if (!img.hasAttribute('alt')) details.push(`${short(img)} sans alt`);
    for (const svg of all('svg')) {
      if (!visible(svg) || svg.closest('[aria-hidden="true"]')) continue;
      const named = svg.getAttribute('role') === 'img'
        && (svg.getAttribute('aria-label')?.trim() || textById(svg.getAttribute('aria-labelledby')) || svg.querySelector('title')?.textContent.trim());
      if (!named) details.push(`${short(svg)} ni aria-hidden ni role=img nommé`);
    }
    result('img-alt', details);
  }

  // h1 / primary
  if (scope === 'page') {
    const h1 = [...document.querySelectorAll('h1')].filter(rendered);
    result('h1', h1.length === 1 ? [] : [`${h1.length} h1 visibles`]);
    const primaries = [...document.querySelectorAll('main .ui-btn--primary')].filter(rendered);
    result('primary', primaries.length <= 1 ? [] : [`${primaries.length} .ui-btn--primary visibles dans main`]);
  } else {
    const h1 = [...document.querySelectorAll('[data-ui-shell] h1, h1[data-ui-shell]')];
    result('h1', h1.length === 0 ? [] : [`h1 dans le shell : ${h1.map(short).join(', ')}`]);
    result('primary', []);
  }

  // lang-fr (pages EN)
  if (lang === 'en') {
    const excluded = (el) => {
      if (el.closest('[translate="no"]')) return true;
      for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
        if (e.hasAttribute('lang')) return !e.getAttribute('lang').toLowerCase().startsWith('en');
      }
      return false;
    };
    const chunks = [];
    const roots = scope === 'page' ? [document.body] : [...document.querySelectorAll('[data-ui-shell]')];
    for (const root of roots) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const parent = n.parentElement;
        if (!parent || ['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(parent.tagName) || excluded(parent)) continue;
        if (n.textContent.trim()) chunks.push(n.textContent.trim());
      }
      for (const el of [root, ...root.querySelectorAll('*')]) {
        if (excluded(el)) continue;
        for (const attr of ['aria-label', 'title', 'placeholder', 'alt']) {
          const v = el.getAttribute(attr);
          if (v && v.trim()) chunks.push(v.trim());
        }
      }
    }
    const text = chunks.join('\n');
    const details = [];
    const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    for (const m of frMsgids) {
      if (new RegExp(`(?<![\\p{L}\\p{N}_])${esc(m)}(?![\\p{L}\\p{N}_])`, 'u').test(text)) details.push(`« ${m} »`);
    }
    const accented = text.match(/[\p{L}]*[àâçéèêëîïôûùüÿœæÀÂÇÉÈÊËÎÏÔÛÙÜŸŒÆ][\p{L}]*/gu) || [];
    for (const word of new Set(accented)) details.push(`"${word}"`);
    result('lang-fr', details.slice(0, 10));
  } else {
    result('lang-fr', []);
  }

  // nav (toute la page ; défile en haut puis en bas)
  {
    const details = [];
    const q = (id) => document.querySelector(`[data-testid=${id}]`);
    const bar = q('nav-bottom');
    const desk = q('nav-desktop');
    const shown = (el) => !!el && rendered(el);
    window.scrollTo(0, 0);
    await raf2();
    if (nav === 'none') {
      if (shown(bar)) details.push('nav-bottom visible');
      if (shown(desk)) details.push('nav-desktop visible');
      const pb = getComputedStyle(document.body).paddingBottom;
      if (pb !== '0px') details.push(`body padding-bottom ${pb} (attendu 0px)`);
    } else if (innerWidth < 1024) {
      const barOk = () => {
        if (!shown(bar)) { details.push('nav-bottom absente ou masquée'); return false; }
        if (getComputedStyle(bar).position !== 'fixed') details.push('nav-bottom non fixed');
        if (bar.getAttribute('data-context') !== nav) details.push(`nav-bottom data-context=${bar.getAttribute('data-context')} (attendu ${nav})`);
        return true;
      };
      if (barOk()) {
        const gap = () => Math.abs(bar.getBoundingClientRect().bottom - innerHeight);
        if (gap() > 1) details.push(`nav-bottom décollée du bas en haut de page (${gap().toFixed(1)} px)`);
        window.scrollTo(0, document.documentElement.scrollHeight);
        await raf2();
        if (gap() > 1) details.push(`nav-bottom décollée du bas en bas de page (${gap().toFixed(1)} px)`);
        const top = bar.getBoundingClientRect().top;
        const main = q('main-content');
        if (!main) details.push('main-content absent');
        else if (main.getBoundingClientRect().bottom > top + 1) details.push('main-content recouvert par nav-bottom');
        const footer = q('site-footer');
        if (footer && footer.getBoundingClientRect().bottom > top + 1) details.push('site-footer recouvert par nav-bottom');
      }
    } else {
      if (shown(bar)) details.push('nav-bottom affichée sur bureau');
      if (!shown(desk)) details.push('nav-desktop absente ou masquée');
      else if (desk.getAttribute('data-context') !== nav) details.push(`nav-desktop data-context=${desk.getAttribute('data-context')} (attendu ${nav})`);
    }
    result('nav', details);
  }
  return out;
}

// --- Messages FR détectables (lang-fr, critère a) ----------------------------------

function frenchMsgids() {
  const po = fs.readFileSync(path.join(REPO_ROOT, 'translations/en/LC_MESSAGES/messages.po'), 'utf8');
  const unquote = (lines) => lines.map((l) => JSON.parse(l.replace(/^[a-z_[\]0-9]+\s+/, ''))).join('');
  const ids = [];
  for (const entry of po.split(/\n\s*\n/)) {
    const lines = entry.split('\n');
    if (lines.some((l) => l.startsWith('#,') && l.includes('fuzzy'))) continue;
    if (lines.some((l) => l.startsWith('msgid_plural'))) continue;
    const field = (name) => {
      const start = lines.findIndex((l) => l.startsWith(`${name} `));
      if (start < 0) return null;
      const parts = [lines[start]];
      for (let i = start + 1; i < lines.length && lines[i].startsWith('"'); i++) parts.push(lines[i]);
      return unquote(parts);
    };
    const id = field('msgid');
    const str = field('msgstr');
    if (id && str && str !== id && !/[%{]/.test(id) && id.length >= 4) ids.push(id);
  }
  return ids;
}

// --- Exécution -----------------------------------------------------------------------

function parseArgs(argv) {
  const opts = { out: null, shots: false, server: true, selfTest: false, filters: {} };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const list = () => argv[++i].split(',').filter(Boolean);
    if (a === '--scenes' || a === '--themes' || a === '--langs') opts.filters[a.slice(2)] = list();
    else if (a === '--viewports') opts.filters.viewports = list().map(Number);
    else if (a === '--out') opts.out = argv[++i];
    else if (a === '--shots') opts.shots = true;
    else if (a === '--no-server') opts.server = false;
    else if (a === '--self-test') opts.selfTest = true;
    else throw new ToolError(`option inconnue ${a}`);
  }
  opts.out ??= path.join(os.tmpdir(), 'holishared-ui', opts.selfTest ? 'selftest' : 'check');
  return opts;
}

function matchesException(ex, run, check, detail) {
  const any = (v, actual) => v === '*' || v === actual;
  return ex.scene === run.scene.id && ex.check === check && any(ex.viewport, run.viewport.width)
    && any(ex.theme, run.theme) && any(ex.lang, run.lang) && detail.includes(ex.match);
}

function loadExceptions() {
  const file = path.join(UI_DIR, 'exceptions.json');
  let list;
  try {
    list = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (err) {
    throw new ToolError(`JSON illisible ${file} : ${err.message}`);
  }
  const fields = ['scene', 'check', 'viewport', 'theme', 'lang', 'match', 'reason', 'lot'];
  if (!Array.isArray(list) || list.some((e) => fields.some((f) => e[f] === undefined || e[f] === ''))) {
    throw new ToolError(`${file} : tableau d'objets { ${fields.join(', ')} } attendu`);
  }
  return list;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const doc = loadScenes(path.join(UI_DIR, opts.selfTest ? 'selftest-scenes.json' : 'scenes.json'), { selfTest: opts.selfTest });
  const runs = expandRuns(doc, opts.filters);
  const exceptions = opts.selfTest ? [] : loadExceptions();
  const frMsgids = frenchMsgids();
  fs.mkdirSync(opts.out, { recursive: true });

  let server = null;
  let cdp = null;
  const report = { runs: [], summary: {} };
  let failures = 0;
  let excepted = 0;
  let toolErrors = 0;
  let mismatches = 0;
  const used = new Set();
  try {
    if (opts.server) {
      runSeed();
      server = await startServer();
    }
    const fixtures = loadFixtures();
    cdp = await launchChrome();
    for (const run of runs) {
      const label = runLabel(run);
      const id = label.replaceAll(' ', '__');
      const entry = { id, scene: run.scene.id, viewport: run.viewport.width, theme: run.theme, lang: run.lang, url: null, results: {} };
      report.runs.push(entry);
      let page = null;
      try {
        page = await openRun(cdp, run, fixtures);
        entry.url = page.url;
        await runActions(cdp, page, run.scene.actions ?? []);
        const params = {
          scope: run.scene.scope, nav: run.scene.expect.nav,
          lang: run.scene.forceLang ? 'en' : run.lang, frMsgids,
        };
        const r = await evaluate(cdp, page.sessionId, `(${audit.toString()})(${JSON.stringify(params)})`, 10000);
        if (!r.ok) throw new Error(`audit : ${r.error}`);
        entry.results = r.value;
        // expectStatus : la page d'erreur voulue (403/404) est journalisée par Chrome ; seule cette ligne est tolérée.
        const expectedLog = run.scene.expectStatus ? `status of ${run.scene.expectStatus} ` : null;
        const logs = page.console.filter((m) => !(expectedLog && m.startsWith('log.error: Failed to load resource') && m.includes(expectedLog)));
        entry.results.console = { ok: logs.length === 0, details: logs };
        entry.results.assert = { ok: page.failures.length === 0, details: page.failures };
        for (const skip of run.scene.skip ?? []) delete entry.results[skip];
      } catch (err) {
        if (err instanceof ToolError) throw err;
        toolErrors++;
        entry.toolError = err.message;
        console.log(`TOOL ${label} ${err.message}`);
      }
      const failed = Object.entries(entry.results).filter(([, v]) => !v.ok).map(([k]) => k).sort();
      if (opts.selfTest) {
        const expected = [...run.scene.expectFail].sort();
        const got = entry.toolError ? ['tool-error'] : failed;
        if (got.join(',') !== expected.join(',')) {
          mismatches++;
          console.log(`SELFTEST ${run.scene.id} attendu [${expected.join(', ')}] obtenu [${got.join(', ')}]`);
          for (const k of got) if (entry.results[k]) console.log(`  [${k}] ${entry.results[k].details.slice(0, 5).join(' ; ')}`);
        }
      } else {
        let runFailed = false;
        for (const check of failed) {
          const detail = entry.results[check].details.join(' ; ');
          const ex = exceptions.find((e) => matchesException(e, run, check, detail));
          if (ex) {
            used.add(ex);
            excepted++;
            console.log(`EXCEPTED ${label} [${check}] (${ex.lot} : ${ex.reason})`);
          } else {
            failures++;
            runFailed = true;
            console.log(`FAIL ${label} [${check}] ${detail.slice(0, 400)}`);
          }
        }
        if (runFailed && opts.shots && page) {
          const shot = await cdp.send('Page.captureScreenshot', { format: 'png' }, page.sessionId).catch(() => null);
          if (shot) fs.writeFileSync(path.join(opts.out, `${id}.png`), Buffer.from(shot.data, 'base64'));
        }
      }
      await page?.close();
    }
  } finally {
    await cdp?.closeBrowser();
    await server?.stop();
  }
  const unused = exceptions.filter((e) => !used.has(e));
  for (const e of unused) console.log(`UNUSED exception inutilisée ${JSON.stringify(e)}`);
  const reportPath = path.join(opts.out, 'report.json');
  report.summary = { runs: runs.length, failures, excepted, unusedExceptions: unused.length, toolErrors, mismatches };
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
  if (opts.selfTest) {
    console.log(`ui:selftest — ${runs.length} runs, ${runs.length - mismatches} conformes, ${mismatches} écart(s), ${toolErrors} erreur(s) d'outil — rapport : ${reportPath}`);
    return toolErrors ? 2 : mismatches ? 1 : 0;
  }
  console.log(`ui:check — ${runs.length} runs, ${failures} échec(s), ${excepted} exception(s), ${toolErrors} erreur(s) d'outil — rapport : ${reportPath}`);
  if (toolErrors) return 2;
  return failures || unused.length ? 1 : 0;
}

main().then((code) => process.exit(code), (err) => {
  console.error(`erreur d'outil : ${err instanceof ToolError ? err.message : err.stack}`);
  process.exit(2);
});
