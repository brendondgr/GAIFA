// web/chart-kit.js, web/charts.js and web/dashboard.js: the pure parts (formatting, scales, paths,
// treemap layout, dashboard layout). The components themselves are checked in the browser.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const kit = await load('chart-kit.js');
const { squarify } = await load('charts.js');
const dash = await load('dashboard.js');

test('values are formatted like the rest of the UI', () => {
  assert.equal(kit.fmtBytes(18.6e9), '18.6 GB');
  assert.equal(kit.fmtBytes(512), '512 B');
  assert.equal(kit.fmtValue(412, 'ms'), '412 ms');
  assert.equal(kit.fmtValue(0.42, 'ratio'), '42%');
  assert.equal(kit.fmtValue(3100000, 'count'), '3.1M');
  assert.equal(kit.fmtValue(null, 'bytes'), '—');
  assert.equal(kit.fmtDur(3725), '1h 2m');
});

test('axis time is HH:mm under a day, ddd HH:mm up to 7 days, MMM d beyond', () => {
  const ts = new Date(2026, 9, 5, 9, 30).getTime() / 1000;  // Mon Oct 5 09:30 local
  assert.equal(kit.fmtTime(ts, 3600), '09:30');
  assert.equal(kit.fmtTime(ts, 3 * 86400), 'Mon 09:30');
  assert.equal(kit.fmtTime(ts, 30 * 86400), 'Oct 5');
});

test('nice ticks start at 0 and reach the max with round steps', () => {
  assert.deepEqual(kit.niceTicks(0, 87, 4), [0, 25, 50, 75, 100]);
  assert.deepEqual(kit.niceTicks(0, 9, 4), [0, 2.5, 5, 7.5, 10]);
  const gb = kit.byteTicks(121e9);
  assert.equal(gb[0], 0); assert.ok(gb.at(-1) >= 121e9); assert.ok(gb.every(v => (v / 1e9) % 1 === 0 || (v / 1e9) * 2 % 1 === 0));
});

test('time ticks fall on local clock boundaries inside the range', () => {
  const from = new Date(2026, 9, 5, 9, 7).getTime() / 1000, to = from + 6 * 3600;
  const t = kit.timeTicks(from, to, 6);
  assert.ok(t.length >= 3 && t.length <= 7, String(t.length));
  for (const x of t) { const d = new Date(x * 1000); assert.equal(d.getMinutes(), 0); assert.ok(x >= from && x <= to); }
  const days = kit.timeTicks(from, from + 14 * 86400, 7);
  for (const x of days) assert.equal(new Date(x * 1000).getHours(), 0);
});

test('a null breaks a line and an area instead of bridging the gap', () => {
  assert.equal(kit.linePath([0, 1, 2, 3], [5, null, 7, 8]), 'M0 5M2 7L3 8');
  const a = kit.areaPath([0, 1, 2], [10, 10, 10], [5, null, 4]);
  assert.equal((a.match(/Z/g) || []).length, 2);
  assert.ok(kit.allNull([[null, null], [null]]) && !kit.allNull([[null, 1]]));
});

test('stacks add up and keep gaps', () => {
  const [a, b] = kit.stackValues([[1, 2, null], [3, null, 5]]);
  assert.deepEqual(a.top, [1, 2, null]);
  assert.deepEqual(b.lo, [1, 2, 0]);
  assert.deepEqual(b.top, [4, null, 5]);
  assert.equal(kit.lastValue([1, 2, null]), 2);
});

test('the treemap fills its box with areas proportional to the values', () => {
  const r = squarify([{ key: 'a', value: 6 }, { key: 'b', value: 3 }, { key: 'c', value: 1 }, { key: 'z', value: 0 }], 0, 0, 200, 100);
  assert.equal(r.length, 3);
  const area = r.reduce((s, x) => s + x.w * x.h, 0);
  assert.ok(Math.abs(area - 20000) < 1e-6);
  assert.ok(Math.abs(r.find(x => x.key === 'a').w * r.find(x => x.key === 'a').h - 12000) < 1e-6);
  for (const x of r) assert.ok(x.x >= -1e-9 && x.y >= -1e-9 && x.x + x.w <= 200 + 1e-9 && x.y + x.h <= 100 + 1e-9);
});

test('dashboard order: saved keys first, unknown ones dropped, new widgets appended', () => {
  const d = dash.DEFAULT_KEYS;
  assert.deepEqual(dash.orderKeys(d, []), d);
  const o = dash.orderKeys(d, ['activity', 'gone', 'memory', 'activity']);
  assert.deepEqual(o.slice(0, 2), ['activity', 'memory']);
  assert.equal(o.length, d.length);
  assert.ok(!o.includes('gone'));
  assert.deepEqual(dash.moveKey(['a', 'b', 'c'], 'c', -1), ['a', 'c', 'b']);
  assert.deepEqual(dash.moveKey(['a', 'b'], 'a', -1), ['a', 'b']);
});

test('widgets span one column on phones and double up on narrow screens', () => {
  assert.equal(dash.spanAt(3, 360), 12);
  assert.equal(dash.spanAt(4, 900), 6);
  assert.equal(dash.spanAt(6, 900), 12);
  assert.equal(dash.spanAt(3, 1400), 3);
});

test('mod widgets join the list; relay traffic becomes "LLM traffic"', () => {
  assert.ok(!dash.widgetDefs([]).some(w => w.key === 'llm'));
  const defs = dash.widgetDefs([
    { service: 'relay', id: 'traffic', title: 'Traffic', kind: 'bar', ranges: ['24h', '7d'], span: 6 },
    { service: 'fake-ok', id: 'requests', title: 'Requests', kind: 'bar', ranges: ['24h', '7d'], span: 6 },
  ]);
  const llm = defs.find(w => w.key === 'llm');
  assert.equal(llm.info.id, 'traffic');
  assert.deepEqual(llm.ranges, ['24h', '7d']);
  assert.ok(defs.some(w => w.key === 'mod:fake-ok:requests' && w.span === 6));
  // every built-in has a title, a valid span and a default range when it has ranges
  for (const w of defs) {
    assert.ok(w.title && [3, 4, 6, 12].includes(w.span), w.key);
    if (w.ranges) assert.ok(w.ranges.includes(w.def), w.key);
  }
});
