// web/chat/chat-show.js and chat-table.js (plan 47.2): the pure parts of show's card and the table.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const show = await import(pathToFileURL(path.join(root, 'web/chat/chat-show.js')).href);
const tbl = await import(pathToFileURL(path.join(root, 'web/chat/chat-table.js')).href);
const cards = await import(pathToFileURL(path.join(root, 'web/chat/chat-cards.js')).href);

test('a file table becomes chart data; long ones are sampled', () => {
  const d = show.chartFromTable(['day', 'n', 'm'], [['Mon', '4', '1'], ['Tue', '1,200', '']], 'day', ['n', 'm']);
  assert.deepEqual(d, { x: ['Mon', 'Tue'], series: [{ name: 'n', values: [4, 1200] }, { name: 'm', values: [1, null] }] });
  const many = Array.from({ length: 2000 }, (_, i) => [i]);
  const s = show.sample(many, 100);
  assert.equal(s.length, 100);
  assert.deepEqual(s.at(-1), [1999]);
});

test('chart props per view, and series labels', () => {
  const d = { x: ['a', 'b'], series: [{ name: 'n', values: [1, 2] }] };
  assert.equal(show.chartProps('bar', d).type, 'bar');
  assert.deepEqual(show.chartProps('hbar', d, 'seconds').categories, ['a', 'b']);
  assert.equal(show.seriesLabel('mem.svc.comfy', { comfy: 'Images & Video' }), 'Images & Video');
  assert.equal(show.seriesLabel('svc.comfy.stat.made_today'), 'made today');
});

test('hub sources load through the api', async () => {
  const api = {
    getMetrics: async ({ series }) => ({ t: [1, 2], series: { 'mem.svc.tts': [1e9, 2e9], 'mem.svc.idle': [0, 0], [series]: [3, 4] } }),
    listServices: async () => [{ id: 'tts', name: 'Speech' }],
    getOutputStats: async () => ({ buckets: [{ key: '2026-10-21', by_kind: { image: 2, audio: 1 } }, { key: '2026-10-22', by_kind: { image: 1 } }] }),
    getJobStats: async () => ({ by_service: [{ service: 'comfy', p50_s: 30, p90_s: 60 }] }),
  };
  const mem = await show.loadHub(api, { name: 'memory', range: '24h' });
  assert.equal(mem.kind, 'area');
  assert.ok(mem.props.series.some(s => s.label === 'Speech'));
  assert.ok(!mem.props.series.some(s => s.key === 'mem.svc.idle'));      // all zero: left out
  const out = await show.loadHub(api, { name: 'outputs_per_day', range: '7d' });
  assert.deepEqual(out.props.categories, ['10-21', '10-22']);
  assert.deepEqual(out.props.series.find(s => s.key === 'image').values, [2, 1]);
  assert.equal((await show.loadHub(api, { name: 'job_times', range: '7d' })).kind, 'hbar');
  assert.equal((await show.loadHub(api, { name: 'mod_stat', range: '24h', mod: 'comfy', stat: 'Made today' })).props.series[0].key, 'svc.comfy.stat.made_today');
});

test('the table: numbers, sorting, filtering, CSV both ways', () => {
  assert.equal(tbl.numberOf('1,204'), 1204);
  assert.equal(tbl.numberOf('12.5%'), 12.5);
  assert.equal(tbl.numberOf('fox'), null);
  const rows = [['fox', '10'], ['owl', '9'], ['ant', null]];
  assert.deepEqual(tbl.sortRows(rows, 1, 1).map(r => r[0]), ['owl', 'fox', 'ant']);
  assert.deepEqual(tbl.sortRows(rows, 0, -1).map(r => r[0]), ['owl', 'fox', 'ant']);
  assert.deepEqual(tbl.filterRows(rows, 'FO').map(r => r[0]), ['fox']);
  const csv = tbl.toCsv(['a', 'b'], [['x, y', 'say "hi"'], [1, null]]);
  assert.equal(csv, 'a,b\n"x, y","say ""hi"""\n1,\n');
  assert.deepEqual(tbl.parseCsv(csv), [['a', 'b'], [['x, y', 'say "hi"'], ['1', '']]]);
  assert.deepEqual(tbl.tableOf('[{"n": 1, "m": 2}]'), [['n', 'm'], [[1, 2]]]);
});

test("show's card is registered", () => assert.ok(cards.hasCard('live:show')));
