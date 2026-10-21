// The similarity score of a search by meaning (web/score.js), drawn the same in the chat list, the
// header Search and the Outputs page, and the header Search's meaning results (web/palette-meaning.js).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const si = globalThis.setInterval;                 // the mock's 1 s ticker must not keep the test process alive
globalThis.setInterval = (...a) => { const t = si(...a); t.unref?.(); return t; };
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const s = await import(pathToFileURL(path.join(root, 'web/score.js')).href);
const p = await import(pathToFileURL(path.join(root, 'web/palette-meaning.js')).href);
const meaning = await import(pathToFileURL(path.join(root, 'web/outputs/meaning.js')).href);
const { createMockApi } = await import(pathToFileURL(path.join(root, 'web/mock.js')).href);
const { createMockClient } = await import(pathToFileURL(path.join(root, 'web/chat/chat-mock.js')).href);

test('the score reads as two places, nothing without one', () => {
  assert.equal(s.fmtScore(0.5834), '0.58');
  assert.equal(s.fmtScore(0.3), '0.30');
  assert.equal(s.fmtScore(1), '1.00');
  assert.equal(s.fmtScore('0.721'), '0.72');
  for (const x of [null, undefined, NaN, '', 'x', Infinity]) assert.equal(s.fmtScore(x), '', String(x));
});

test('the bar fills to the score, clamped to 0–1', () => {
  assert.equal(s.scoreWidth(0.58), 58);
  assert.equal(s.scoreWidth(-0.2), 0);
  assert.equal(s.scoreWidth(1.4), 100);
  assert.equal(s.scoreWidth(undefined), 0);
});

test('the tooltip says what the number is', () => {
  assert.equal(s.scoreTitle(0.583), 'Similarity to your search: 0.58 (higher is closer)');
  assert.equal(s.scoreTitle(null), 'Similarity to your search');
});

test('the badge draws the score with its tooltip, and nothing without one', () => {
  const calls = [];
  globalThis.React = { createElement: (t, props, ...kids) => { const el = { t, props, kids }; calls.push(el); return el; } };
  try {
    const el = s.ScoreBadge({ score: 0.612 });
    assert.equal(el.props.title, 'Similarity to your search: 0.61 (higher is closer)');
    assert.equal(el.kids.at(-1), '0.61');
    assert.equal(s.ScoreBadge({ score: null }), null);
  } finally { delete globalThis.React; }
});

test('the header Search asks by meaning only on 3+ characters while the embed mod runs', () => {
  const up = [{ id: 'embed', state: 'ready' }];
  assert.equal(p.shouldSearch('cat', up, meaning), true);
  assert.equal(p.shouldSearch(' ca ', up, meaning), false);
  assert.equal(p.shouldSearch('cats', [{ id: 'embed', state: 'stopped' }], meaning), false);
  assert.equal(p.shouldSearch('cats', up, null), false);
});

test('outputs and chats found by meaning become entries, best score first', () => {
  const items = p.meaningItems({
    outputs: [{ id: 'o1', title: 'Fox', kind: 'image', score: 0.41 }, { id: 'o 2', title: '', kind: 'audio', score: null }],
    chats: [{ thread_id: 't1', title: 'Fox talk', link: '#/chat/t1', score: 0.66 }, { thread_id: 't2', title: '', score: 0.5 }],
  }, 3);
  assert.deepEqual(items.map(x => [x.key, x.label, x.sub, x.href, x.score]), [
    ['chat:t1', 'Fox talk', 'Chat · by meaning', '#/chat/t1', 0.66],
    ['chat:t2', 'Chat', 'Chat · by meaning', '#/chat/t2', 0.5],
    ['output:o1', 'Fox', 'Output · by meaning', '#/outputs/o1', 0.41]]);
  assert.deepEqual(p.meaningItems({}), []);
});

test('a name match the meaning search also found gives way to the scored entry', () => {
  const kw = [{ label: 'Chat', sub: 'Page' }, { key: 'output:o1', label: 'Fox' }, { key: 'output:o9', label: 'Owl' }];
  const mean = [{ key: 'output:o1', label: 'Fox', score: 0.7 }];
  assert.deepEqual(p.mergePalette(kw, mean).map(x => [x.label, x.score]), [['Chat', undefined], ['Owl', undefined], ['Fox', 0.7]]);
});

test('both searches run; one failing keeps the other, both failing says why', async () => {
  const api = createMockApi();
  const chat = { searchChats: async () => [{ thread_id: 't1', title: 'Cats', score: 0.9 }] };
  const r = await p.searchMeaning({ api, chat, meaning, q: 'fox' });
  assert.equal(r.err, '');
  assert.equal(r.items[0].key, 'chat:t1');
  assert.ok(r.items.length > 1 && r.items.slice(1).every(x => x.kind === 'output' && typeof x.score === 'number'));
  const bad = { search: async () => { throw { detail: 'embed is not running' }; }, rows: meaning.rows };
  const r2 = await p.searchMeaning({ api, chat: { searchChats: async () => { throw new Error('agent down'); } }, meaning: bad, q: 'fox' });
  assert.deepEqual(r2, { items: [], err: 'embed is not running' });
});

test('the mock has the embed mod, and its searches by meaning carry scores with no minimum', async () => {
  const api = createMockApi();
  assert.equal(meaning.canSearch(await api.listServices()), true);
  const res = await api.callService('embed', 'POST', '/v1/search', { json: { query: 'zzz nothing like it', limit: 5 } });
  assert.equal(res.json.results.length, 5);
  assert.ok(res.json.results.every(x => x.score >= 0.3 && x.score <= 0.8 && x.output.startsWith('output:')));
  const chats = await createMockClient(api).searchChats('zzz nothing like it', 4);
  assert.ok(chats.length > 0 && chats.every(c => c.score >= 0.3 && c.score <= 0.8));
  assert.ok(chats.every((c, i) => !i || chats[i - 1].score >= c.score));
});
