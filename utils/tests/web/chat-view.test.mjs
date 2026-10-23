// web/chat/chat-view.js (plan 46.1): a tool's default view turns its result into a table or a chart.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const v = await import(pathToFileURL(path.join(root, 'web/chat/chat-view.js')).href);
const live = await import(pathToFileURL(path.join(root, 'web/chat/chat-live.js')).href);

const JOBS = { jobs: [{ title: 'Fox', status: 'done', created: 1792726425, request: { engine: 'trellis2' }, files: ['a'] },
  { title: 'Owl', status: 'failed', created: 1792726000, request: { engine: 'cube3d' } }] };

test('a table view picks its rows and columns, nested keys and formats included', () => {
  const view = { kind: 'table', rows: 'jobs', columns: [{ key: 'title', label: 'Job' }, { key: 'request.engine', label: 'Engine' }, { key: 'status', label: 'State' }] };
  assert.deepEqual(v.tableFromView(view, JOBS), { columns: ['Job', 'Engine', 'State'], rows: [['Fox', 'trellis2', 'done'], ['Owl', 'cube3d', 'failed']] });
  const plain = v.tableFromView({ kind: 'table', rows: 'jobs' }, JOBS);
  assert.deepEqual(plain.columns, ['title', 'status', 'created']);          // plain keys only, objects left out
  assert.deepEqual(v.tableFromView({ kind: 'table', rows: '' }, [{ a: 1 }]).rows, [[1]]);
});

test('formats', () => {
  assert.equal(v.fmtCell(3.2e9, 'bytes'), '3.2 GB');
  assert.equal(v.fmtCell(['lcpp', { id: 'x' }], 'list'), 'lcpp, x');
  assert.equal(v.fmtCell(true, 'yesno'), 'yes');
  assert.equal(v.fmtCell(75, 'seconds'), '1m 15s');
  assert.equal(v.fmtCell(null, 'time'), '');
});

test('a chart view', () => {
  const d = v.chartFromView({ kind: 'bar', rows: 'm', x: 'name', y: ['gb'] }, { m: [{ name: 'a', gb: 2 }, { name: 'b', gb: 'x' }] });
  assert.deepEqual(d, { x: ['a', 'b'], series: [{ key: 'gb', label: 'gb', values: [2, null] }] });
});

test('a done step of a tool with a view draws it; a running one does not yet', () => {
  const tools = [{ name: 'gen3d_list_jobs', view: { kind: 'table', rows: 'jobs' } }];
  const row = (status) => ({ type: 'tool', key: 'k' + status, name: 'gen3d_list_jobs', status, item: {} });
  const rows = live.liveRows({ steps: [{ rows: [row('done'), row('running')] }] }, tools);
  assert.deepEqual(rows.map(r => [r.row.status, !!r.view]), [['done', true]]);
  assert.equal(v.viewOf(tools, 'nope'), null);
});
