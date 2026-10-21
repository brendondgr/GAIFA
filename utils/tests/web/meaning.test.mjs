// Plan 28.4: the Outputs page's "By meaning" search: when the toggle shows, and how the embed mod's
// hits become rows (one per output, their snippets without the agent's untrusted wrapper).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const m = await import(pathToFileURL(path.join(root, 'web/outputs/meaning.js')).href);

test('the toggle shows only while the embed mod runs', () => {
  assert.equal(m.canSearch([{ id: 'tts', state: 'ready' }, { id: 'embed', state: 'ready' }]), true);
  assert.equal(m.canSearch([{ id: 'embed', state: 'stopped' }]), false);
  assert.equal(m.canSearch([{ id: 'tts', state: 'ready' }]), false);      // deleting the mod hides it
  assert.equal(m.canSearch(undefined), false);
});

test('snippets lose the untrusted wrapper', () => {
  assert.equal(m.plainSnippet('<untrusted source="output:ab Notes">\nthe keeper\'s cat\n</untrusted>'), "the keeper's cat");
  assert.equal(m.plainSnippet(undefined), '');
});

test('where a hit matched', () => {
  assert.equal(m.matchLabel({ page: 3, line: 120 }), 'p.3 · line 120');
  assert.equal(m.matchLabel({ line: 88 }), 'line 88');
  assert.equal(m.matchLabel({ start_s: 30, end_s: 60, kind: 'audio', match: 'audio' }), '30–60 s');
  assert.equal(m.matchLabel({ match: 'image', kind: 'image' }), 'the image');
  assert.equal(m.matchLabel({ match: 'meta', kind: 'image' }), 'title and prompt');
});

test('one row per output, in the order of its best hit, filtered by the kind chips', () => {
  const hits = [{ output: 'output:a', kind: 'document', title: 'Report', score: 0.8, page: 2, line: 40, snippet: 'x' },
    { output: 'output:b', kind: 'image', title: 'IMG_1.png', score: 0.7, match: 'image' },
    { output: 'output:a', kind: 'document', title: 'Report', score: 0.6, page: 5, line: 90 }];
  const r = m.rows(hits);
  assert.deepEqual(r.map(x => [x.id, x.matches.length]), [['a', 2], ['b', 1]]);
  assert.equal(r[0].score, 0.8);
  assert.deepEqual(r[0].matches.map(x => x.where), ['p.2 · line 40', 'p.5 · line 90']);
  assert.deepEqual(m.rows(hits, ['image']).map(x => x.id), ['b']);
});

test('the search call', async () => {
  const calls = [];
  const api = { callService: async (...a) => { calls.push(a); return { json: { results: [], note: 'n' } }; } };
  assert.deepEqual(await m.search(api, 'red car', ['image']), { results: [], note: 'n' });
  assert.deepEqual(calls[0], ['embed', 'POST', '/v1/search', { json: { query: 'red car', limit: 30, kind: 'image' } }]);
  await m.search(api, 'x', ['image', 'video']);                            // two kinds: filtered on the page
  assert.equal(calls[1][3].json.kind, undefined);
});
