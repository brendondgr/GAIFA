// web/chat/chat-fix.js (plan 46.5): which failed steps get a fix-it card, and what each fix does.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const fix = await import(pathToFileURL(path.join(root, 'web/chat/chat-fix.js')).href);
const live = await import(pathToFileURL(path.join(root, 'web/chat/chat-live.js')).href);
const cards = await import(pathToFileURL(path.join(root, 'web/chat/chat-cards.js')).href);

const row = (key, status, error, args = { prompt: 'x', preset: 'quality' }) => ({ type: 'tool', key, name: 'gen3d_make_3d', status, item: { call: { arguments: args }, result: { status: 'error', error } } });

test('failed steps with fixes or log lines get a card; others do not', () => {
  const turn = { steps: [{ rows: [row('a', 'error', { code: 'job_failed', fixes: [{ label: 'Retry', retry: {} }] }), row('b', 'failed', { code: 'invalid_arguments' }),
    row('c', 'failed', { code: 'mod_error', log: ['RuntimeError: boom'] }), row('d', 'done', null)] }] };
  assert.deepEqual(fix.fixRows(turn).map(r => r.key), ['a', 'c']);
});

test('what a fix does', () => {
  const r = row('a', 'failed', {});
  assert.deepEqual(fix.fixAction({ label: 'Retry with the fast preset', retry: { preset: 'fast' } }, r), { kind: 'tool', tool: 'gen3d_make_3d', arguments: { prompt: 'x', preset: 'fast' } });
  assert.deepEqual(fix.fixAction({ label: 'Start', tool: 'hub_start_service', arguments: { id: 'gen3d' } }, r), { kind: 'tool', tool: 'hub_start_service', arguments: { id: 'gen3d' } });
  assert.deepEqual(fix.fixAction({ label: 'Restart', service: 'gen3d', action: 'restart' }, r), { kind: 'service', service: 'gen3d', action: 'restart' });
  assert.deepEqual(fix.fixAction({ label: 'Set it up', command: 'aihub setup gen3d' }, r), { kind: 'copy', text: 'aihub setup gen3d' });
});

test('a fix-it card stands in for the live card of a failed step', () => {
  const undo = cards.registerCard('live:gen3d_make_3d', () => null);
  const turn = { steps: [{ rows: [row('a', 'error', { code: 'job_failed', fixes: [{ label: 'Retry', retry: {} }] }), row('b', 'failed', { code: 'job_failed' })] }] };
  assert.deepEqual(live.liveRows(turn).map(r => r.row.key), ['b']);
  undo();
});
