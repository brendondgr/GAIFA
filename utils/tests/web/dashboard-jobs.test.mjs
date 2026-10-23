// web/dashboard.js (plan 44.5): a running job's words on the Overview, with live progress.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const dash = await import(pathToFileURL(path.join(root, 'web/dashboard.js')).href);

test('a job says its step when it reports one, else its percent', () => {
  assert.equal(dash.jobStatusText({ state: 'running', progress: 0.4, live: { step: 3, steps: 8, preview: { url: '/p', seq: 3 } } }), '3/8');
  assert.equal(dash.jobStatusText({ state: 'running', progress: 0.4 }), '40%');
  assert.equal(dash.jobStatusText({ state: 'running', progress: null }), 'running');
  assert.equal(dash.jobStatusText({ state: 'queued', progress: null, live: { step: 1, steps: 8 } }), 'queued');
  assert.equal(dash.jobStatusText({ state: 'running', stage: 'waiting_gpu', progress: null }), 'GPU wait');
});
