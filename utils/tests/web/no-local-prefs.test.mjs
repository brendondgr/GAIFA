// settings-that-stick 4.3: nothing a person chooses is written only to this browser. Every key written to
// localStorage (setItem, lsSet, setPref, usePref) must be a first-paint copy, an import mark or a draft; a new
// preference goes in config.toml (ui-prefs.js) or the UI store (ui-store.js) instead.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../web');
const ALLOWED = new Set([
  'gaifa.ui.cache', 'gaifa.prefs.imported',   // ui-prefs.js: config.toml's [ui] copy for the first paint, the import's mark
  'hub.theme', 'hub.density', 'hub.nav',      // the shell's first paint, before config.toml arrives (it wins)
]);
const files = dir => readdirSync(dir).flatMap(f => { const p = path.join(dir, f); return statSync(p).isDirectory() ? files(p) : /\.(m?js|html)$/.test(f) ? [p] : []; });
const WRITE = /(?:localStorage\.setItem|storage\??\.setItem|lsSet|setPref|usePref)\(\s*'([^']+)'/g;

test('no preference is written only to this browser', () => {
  const found = [];
  for (const f of files(web)) {
    if (f.endsWith('support.js')) continue;   // generated (Claude Design)
    for (const m of readFileSync(f, 'utf8').matchAll(WRITE)) if (!ALLOWED.has(m[1])) found.push(`${path.relative(web, f)}: ${m[1]}`);
  }
  assert.deepEqual(found, []);
});
