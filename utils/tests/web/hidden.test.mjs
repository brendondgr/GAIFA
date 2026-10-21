// Plan 30.9: hidden outputs (pages the web mod saved for the agent) on the Outputs page: the "Saved web pages"
// chip, which live outputs belong in a list, and the totals after one arrives; and the mock's listOutputs.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const h = await import(pathToFileURL(path.join(root, 'web/outputs/hidden.js')).href);

const T = { count: 3, size_bytes: 30, by_kind: { text: 2, audio: 1 }, by_service: { uploads: 2, tts: 1 }, hidden: 2 };
const page = { id: 'p', service: 'web', kind: 'text', size_bytes: 5, hidden: true };
const mine = { id: 'm', service: 'uploads', kind: 'text', size_bytes: 7 };

test('the chip shows while something is hidden, or while it is on', () => {
  assert.deepEqual(h.toggle(T, false), { label: 'Saved web pages', count: 2, pressed: false, title: h.TITLE });
  assert.equal(h.toggle({ ...T, hidden: 0 }, false), null);
  assert.equal(h.toggle(null, false), null);
  assert.equal(h.toggle({ ...T, hidden: 0 }, true).pressed, true);            // on, with none under these filters: still there to turn off
});

test('a hidden output belongs only where hidden ones are shown', () => {
  assert.equal(h.belongs(page, false), false);
  assert.equal(h.belongs(page, true), true);
  assert.equal(h.belongs(mine, false), true);
});

test('recent lists never take a hidden output, and lose one that became hidden', () => {
  const list = [{ id: 'a' }, { id: 'b' }];
  assert.deepEqual(h.place(list, page, 8).map(x => x.id), ['a', 'b']);
  assert.deepEqual(h.place(list, mine, 2).map(x => x.id), ['m', 'a']);
  assert.deepEqual(h.place(list, { id: 'b', title: 'changed' }, 8), [{ id: 'a' }, { id: 'b', title: 'changed' }]);
  assert.deepEqual(h.place([{ id: 'p' }, { id: 'a' }], page, 8).map(x => x.id), ['a']);
});

test('totals after a live output: a hidden one only counts as hidden while they are off', () => {
  assert.deepEqual(h.addTo(T, page, false), { ...T, hidden: 3 });
  const on = h.addTo(T, page, true);
  assert.deepEqual([on.count, on.size_bytes, on.by_service.web, on.by_kind.text, on.hidden], [4, 35, 1, 3, 3]);
  const m = h.addTo(T, mine, false);
  assert.deepEqual([m.count, m.size_bytes, m.by_service.uploads, m.hidden], [4, 37, 3, 2]);
  assert.equal(h.addTo(null, mine, false), null);
});

test('the mock leaves hidden pages out unless include_hidden, and counts them', async () => {
  const si = globalThis.setInterval;               // the mock's 1 s ticker must not keep the test process alive
  globalThis.setInterval = (...a) => { const t = si(...a); t.unref?.(); return t; };
  const { createMockApi } = await import(pathToFileURL(path.join(root, 'web/mock.js')).href);
  const api = createMockApi();
  const off = await api.listOutputs({ limit: 500 });
  assert.ok(off.totals.hidden >= 1 && off.items.every(o => !o.hidden));
  const on = await api.listOutputs({ limit: 500, include_hidden: true });
  assert.equal(on.totals.count, off.totals.count + off.totals.hidden);
  assert.ok(on.items.some(o => o.hidden && o.service === 'web'));
  assert.ok((await api.getOverview()).recent_outputs.every(o => !o.hidden));
});
