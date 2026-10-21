// Plan 30.8: a paste that is one http(s) URL offers to read the page; a read page becomes a chip with its host and
// how the screening went; the API method posts to the hub's route.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const wp = await import(pathToFileURL(path.join(root, 'web/chat/chat-webpage.js')).href);
const { createHttpApi } = await import(pathToFileURL(path.join(root, 'web/api.js')).href);

test('only a paste that is one http(s) URL is offered as a page', () => {
  assert.equal(wp.loneUrl('https://example.org/a?b=1#c'), 'https://example.org/a?b=1#c');
  assert.equal(wp.loneUrl('  http://docs.python.org/3/  \n'), 'http://docs.python.org/3/');
  assert.equal(wp.loneUrl('<https://example.org/x>'), 'https://example.org/x');
  for (const t of ['see https://example.org/a', 'https://example.org/a https://example.org/b', 'example.org/a', 'ftp://example.org/f',
    'javascript:alert(1)', 'https://', 'http://intranet/', '', null, 'https://example.org/' + 'x'.repeat(2100), 'file:///etc/passwd'])
    assert.equal(wp.loneUrl(t), null, String(t).slice(0, 40));
});

test('a read page is a chip with its host and screening badge', () => {
  const r = { output: { id: 'abc123abc123', kind: 'text', title: 'Tides', subtype: 'markdown', preview: null }, url: 'https://www.example.org/t',
    final_url: 'https://www.example.org/tides', screening: { removed: 2, checked: 'patterns+model' } };
  const chip = wp.pageChip(r);
  assert.deepEqual(chip, { id: 'abc123abc123', kind: 'text', title: 'Tides', preview: null, subtype: 'markdown',
    web: { url: 'https://www.example.org/tides', host: 'example.org', removed: 2, checked: 'patterns+model' } });
  assert.deepEqual(wp.screenBadge(chip.web).slice(0, 2), ['2 removed', 'accent']);
  assert.deepEqual(wp.screenBadge({ removed: 0, checked: 'patterns+model' }).slice(0, 2), ['checked', 'green']);
  assert.deepEqual(wp.screenBadge({ removed: 0, checked: 'patterns' }).slice(0, 2), ['patterns only', 'accent']);
  assert.deepEqual(wp.pageChip({ ...r, screening: null }).web.checked, 'off');
  assert.equal(wp.screenBadge(undefined), null);
});

test('readWebPage posts the URL to the hub', async () => {
  const seen = [];
  const fetch = async (url, init) => { seen.push({ url, init }); return new Response(JSON.stringify({ output: {} }), { status: 200, headers: { 'content-type': 'application/json' } }); };
  const api = createHttpApi('http://hub', { fetch });
  await api.readWebPage('https://example.org/a', { text: true });
  assert.equal(seen[0].url, 'http://hub/api/web/read');
  assert.equal(seen[0].init.method, 'POST');
  assert.deepEqual(JSON.parse(seen[0].init.body), { url: 'https://example.org/a', text: true });
});

test('the web mod page renders the screened markdown with removals marked', async () => {
  const fs = await import('node:fs');
  const md = pathToFileURL(path.join(root, 'web/chat/chat-md.js')).href;
  const src = fs.readFileSync(path.join(root, 'services/web/ui/page.js'), 'utf8').replace("'/chat/chat-md.js'", `'${md}'`);
  const page = await import('data:text/javascript,' + encodeURIComponent(src));
  const html = page.render('# Tides\n\nText.\n\n[removed by screening: tells an AI what to reply]\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```py\nx = 1\n```');
  assert.match(html, /<p class="web-removed">Removed by screening: tells an AI what to reply<\/p>/);
  assert.match(html, /<table>/);
  assert.match(html, /aichat-code/);
  assert.deepEqual(page.screeningLabel({ removed: 1, checked: 'patterns+model' }), ['1 passage removed', 'accent']);
  assert.deepEqual(page.screeningLabel({ removed: 0, checked: 'patterns+model' })[1], 'green');
  assert.equal(page.screeningLabel(null)[1], 'dim');
  assert.deepEqual(page.default.tabs.map(t => t.id), ['read']);
});
