// Captures PNG des scènes (spec §9.9).
// node scripts/ui/shoot.mjs [--scenes a,b] [--viewports 360,1280] [--themes dark] [--langs en]
//                           [--out DIR] [--full] [--no-server]
// Codes : 0 ; 2 erreur d'outil.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  BASE_URL, ToolError, expandRuns, launchChrome, loadFixtures, loadScenes, openRun, runActions,
  runLabel, runSeed, startServer,
} from './lib.mjs';

const MAX_FULL_HEIGHT = 6000;

function parseArgs(argv) {
  const opts = { out: path.join(os.tmpdir(), 'holishared-ui', 'shots'), full: false, server: true, filters: {} };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const list = () => argv[++i].split(',').filter(Boolean);
    if (a === '--scenes' || a === '--themes' || a === '--langs') opts.filters[a.slice(2)] = list();
    else if (a === '--viewports') opts.filters.viewports = list().map(Number);
    else if (a === '--out') opts.out = argv[++i];
    else if (a === '--full') opts.full = true;
    else if (a === '--no-server') opts.server = false;
    else throw new ToolError(`option inconnue ${a}`);
  }
  return opts;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const runs = expandRuns(loadScenes(), opts.filters);
  fs.mkdirSync(opts.out, { recursive: true });
  let server = null;
  let cdp = null;
  const index = [];
  try {
    if (opts.server) {
      runSeed();
      server = await startServer();
    }
    const fixtures = loadFixtures();
    cdp = await launchChrome();
    for (const run of runs) {
      const page = await openRun(cdp, run, fixtures);
      await runActions(cdp, page, run.scene.actions ?? []);
      const params = { format: 'png' };
      if (opts.full) {
        const { contentSize } = await cdp.send('Page.getLayoutMetrics', {}, page.sessionId);
        params.captureBeyondViewport = true;
        params.clip = { x: 0, y: 0, width: contentSize.width, height: Math.min(contentSize.height, MAX_FULL_HEIGHT), scale: 1 };
      }
      const shot = await cdp.send('Page.captureScreenshot', params, page.sessionId);
      const file = `${run.scene.id}__${run.viewport.width}__${run.theme}__${run.lang}.png`;
      fs.writeFileSync(path.join(opts.out, file), Buffer.from(shot.data, 'base64'));
      index.push({ file, url: page.url, run: runLabel(run) });
      await page.close();
    }
  } finally {
    await cdp?.closeBrowser();
    await server?.stop();
  }
  fs.writeFileSync(path.join(opts.out, 'index.json'), JSON.stringify(index, null, 2));
  console.log(`ui:shoot — ${index.length} captures dans ${opts.out} (${BASE_URL})`);
  return 0;
}

main().then((code) => process.exit(code), (err) => {
  console.error(`erreur d'outil : ${err instanceof ToolError ? err.message : err.stack}`);
  process.exit(2);
});
