// Unit tests for the mock's chart history (web/mock-history.js through createMockApi, brief §11.7/§11.9):
//   node --test utils/tests/web/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseRange, pickStep, statSlug } from '../../../web/mock-history.js';

// The mock's 1 s ticker must not keep the test process alive.
const si = globalThis.setInterval;
globalThis.setInterval = (...a) => { const t = si(...a); t.unref?.(); return t; };
const { createMockApi } = await import('../../../web/mock.js');

const now = () => Date.now() / 1000;
const RANGES = { '1h': 10, '6h': 60, '24h': 300, '7d': 1800, '14d': 3600, '30d': 7200 };

test('ranges, steps and slugs follow the hub', () => {
  assert.deepEqual(parseRange('24h'), ['24h', 86400]);
  assert.deepEqual(parseRange('90m'), ['90m', 5400]);
  assert.equal(parseRange('401d'), null);
  assert.equal(parseRange('week'), null);
  for (const [r, s] of Object.entries(RANGES)) assert.equal(pickStep(parseRange(r)[1]), s, r);
  assert.equal(pickStep(86400, 7), 60);           // rounded to the minute table
  assert.equal(pickStep(3600, 1), 10);
  assert.ok(Math.ceil(30 * 86400 / pickStep(30 * 86400, 1)) <= 2000);
  assert.equal(statSlug('Requests today'), 'requests_today');
  assert.equal(statSlug('p50 TTFT'), 'p50_ttft');
});

test('metrics: an even axis ending now, one value per bucket, for every range', async () => {
  const api = createMockApi();
  for (const [r, step] of [...Object.entries(RANGES), ['90m', null], ['3d', null]]) {
    const m = await api.getMetrics({ series: 'mem.used,mem.other,jobs.running', range: r });
    assert.equal(m.range, r);
    if (step) assert.equal(m.step_s, step);
    for (let i = 1; i < m.t.length; i++) assert.equal(m.t[i] - m.t[i - 1], m.step_s);
    const last = m.t.at(-1);
    assert.ok(last <= now() && last > now() - 2 * m.step_s, r);
    for (const [n, v] of Object.entries(m.series)) assert.equal(v.length, m.t.length, `${r} ${n}`);
    assert.notEqual(m.series['mem.used'].at(-1), null, r);
  }
  await assert.rejects(api.getMetrics({ series: 'mem.used', range: 'week' }), e => e.status === 422 && e.code === 'invalid_request');
  await assert.rejects(api.getMetrics({ series: '' }), e => e.code === 'invalid_request');
});

test('metrics: families expand, unknown names are all null, history looks real', async () => {
  const api = createMockApi();
  const ids = (await api.listServices()).map(s => s.id);
  const m = await api.getMetrics({ series: ['mem.svc.*', 'nope.x', 'svc.nope.stat.x'], range: '7d' });
  assert.deepEqual(Object.keys(m.series).filter(n => n.startsWith('mem.svc.')).sort(), ids.map(id => `mem.svc.${id}`).sort());
  assert.ok(m.series['nope.x'].every(v => v === null));
  assert.ok(m.series['svc.nope.stat.x'].every(v => v === null));
  const peak = id => Math.max(...m.series[`mem.svc.${id}`].filter(v => v != null));
  assert.ok(peak('lcpp') > 15e9, 'lcpp is loaded during the day');
  assert.ok(peak('gen3d') > 30e9, 'gen3d bursts');
  assert.ok(Math.min(...m.series['mem.svc.lcpp'].filter(v => v != null)) < 1e9, 'lcpp unloads at night');
  const h1 = await api.getMetrics({ series: 'mem.used,mem.svc.lcpp', range: '1h' });
  const live = (await api.getMemory()).used_bytes;
  assert.ok(Math.abs(h1.series['mem.used'].at(-1) - live) < 2e9, 'the last sample matches the live memory');
});

test('numeric stats name their series, and the series list has them', async () => {
  const api = createMockApi();
  const relay = (await api.listServices()).find(s => s.id === 'relay');
  assert.equal(relay.stats[0].series, 'svc.relay.stat.requests_today');
  assert.equal(relay.stats[1].series, undefined);   // '3.1' is a string
  const infos = await api.listMetricSeries();
  const by = Object.fromEntries(infos.map(i => [i.name, i]));
  assert.deepEqual(by['svc.relay.stat.p50_ttft'], { name: 'svc.relay.stat.p50_ttft', label: 'p50 TTFT', unit: 'ms', service: 'relay' });
  assert.equal(by['svc.relay.stat.requests_today'].reset, 'daily');
  assert.equal(by['mem.svc.lcpp'].unit, 'bytes');
  assert.equal(by['jobs.running'].unit, 'count');
  const m = await api.getMetrics({ series: 'svc.*', range: '24h' });
  assert.ok(m.series['svc.relay.stat.p50_ttft'].some(v => v > 0));
});

const bandsOk = (tl) => {
  for (const lane of tl.lanes) for (const key of ['states', 'loaded']) {
    const xs = lane[key];
    xs.forEach((b, i) => {
      assert.ok(b.from < b.to && b.from >= tl.from - 1e-6 && b.to <= tl.to + 1e-6, `${lane.service} ${key}`);
      if (i) assert.ok(b.from >= xs[i - 1].to - 1e-6, `${lane.service} ${key} sorted`);
    });
  }
};

test('timeline: a lane per service in sidebar order, sorted bands inside the range', async () => {
  const api = createMockApi();
  const ids = (await api.listServices()).map(s => s.id);
  const tl = await api.getTimeline({ range: '7d' });
  assert.deepEqual(tl.lanes.map(l => l.service), ids);
  bandsOk(tl);
  const lane = id => tl.lanes.find(l => l.service === id);
  assert.ok(lane('lcpp').loaded.length >= 5);
  assert.ok(lane('gen3d').jobs.length > 0 && lane('gen3d').jobs.every(j => j.to === null || j.to >= j.from));
  assert.ok(lane('comfy').states.some(b => b.state === 'stopped'));
  assert.ok(lane('tts').outputs.length > 0);
  assert.ok(lane('relay').events.every(e => e.level === 'warn' || e.level === 'error'));
  const one = await api.getTimeline({ range: '1h', services: 'tts,lcpp' });
  assert.deepEqual(one.lanes.map(l => l.service), ['tts', 'lcpp']);
  bandsOk(one);
});

test('gaps: the hub was down for 2 h ending 3 h ago', async () => {
  const api = createMockApi();
  api.mock.setHistory('gaps');
  assert.equal(api.mock.historyMode, 'gaps');
  const t0 = now(), m = await api.getMetrics({ series: 'mem.used', range: '6h' });
  m.t.forEach((t, i) => {
    const v = m.series['mem.used'][i];
    if (t >= t0 - 5 * 3600 + 60 && t + m.step_s <= t0 - 3 * 3600 - 60) assert.equal(v, null, `bucket ${i} in the gap`);
    if (t + m.step_s < t0 - 5 * 3600 - 60 || t > t0 - 3 * 3600 + 60) assert.notEqual(v, null, `bucket ${i} outside the gap`);
  });
  const tl = await api.getTimeline({ range: '24h' });
  bandsOk(tl);
  for (const lane of tl.lanes) for (const b of lane.states) assert.ok(b.to <= t0 - 5 * 3600 + 120 || b.from >= t0 - 3 * 3600 - 120, `${lane.service} band in the gap`);
});

test('empty: a fresh install has (almost) nothing', async () => {
  const api = createMockApi();
  api.mock.setHistory('empty');
  const m = await api.getMetrics({ series: 'mem.used,mem.svc.*', range: '24h' });
  for (const v of Object.values(m.series)) { assert.ok(v.slice(0, -2).every(x => x === null)); }
  assert.notEqual(m.series['mem.used'].at(-1), null);
  const tl = await api.getTimeline({ range: '24h' });
  for (const lane of tl.lanes) { assert.deepEqual([lane.loaded.length > 0 && lane.service !== 'lcpp', lane.jobs.length, lane.outputs.length, lane.events.length], [false, 0, 0, 0]); }
  assert.deepEqual((await api.getJobStats({})).by_service, []);
  assert.ok((await api.getOutputStats({})).buckets.every(b => b.count === 0));
  assert.ok((await api.getActivityStats({})).cells.reduce((a, c) => a + c.count, 0) <= 2);
  const w = await api.getWidget('relay', 'traffic', { range: '24h' });
  assert.ok(w.series.every(s => s.values.every(v => v === null)));
  api.mock.setHistory('normal');
  assert.ok((await api.getJobStats({})).by_service.length > 0);
});

test('output stats: every day for by=day, largest first otherwise, following the outputs scenario', async () => {
  const api = createMockApi();
  const days = (await api.getOutputStats({ range: '30d', by: 'day' })).buckets;
  assert.ok(days.length === 31 || days.length === 32);
  for (let i = 1; i < days.length; i++) assert.ok(days[i].key > days[i - 1].key);
  const total = days.reduce((a, b) => a + b.count, 0);
  assert.ok(total > 50);
  const svc = (await api.getOutputStats({ range: '30d', by: 'service' })).buckets;
  assert.equal(svc.reduce((a, b) => a + b.count, 0), total);
  for (let i = 1; i < svc.length; i++) assert.ok(svc[i].count <= svc[i - 1].count);
  const kinds = (await api.getOutputStats({ by: 'kind' })).buckets;
  assert.ok(kinds.every(b => b.count > 0 && b.by_kind[b.key] === b.count));
  await assert.rejects(api.getOutputStats({ by: 'week' }), e => e.code === 'invalid_request');
  api.mock.setOutputs('empty');
  assert.ok((await api.getOutputStats({ by: 'day' })).buckets.every(b => b.count === 0));
  assert.deepEqual((await api.getOutputStats({ by: 'service' })).buckets, []);
});

test('activity and job stats', async () => {
  const api = createMockApi();
  const { cells } = await api.getActivityStats({ range: '14d' });
  assert.equal(cells.length % 24, 0);
  assert.ok(cells.length >= 14 * 24);
  assert.ok(cells.reduce((a, c) => a + c.count, 0) > 50);
  assert.ok(cells.every(c => c.errors <= c.count));
  const { by_service } = await api.getJobStats({ range: '7d' });
  const g = by_service.find(x => x.service === 'gen3d');
  assert.ok(g.count > 0 && g.failed <= g.count && g.p50_s <= g.p90_s && g.p90_s <= g.max_s && g.p50_s >= 600);
});

test('widgets: the relay traffic widget, and its errors', async () => {
  const api = createMockApi();
  assert.deepEqual(await api.listWidgets(), [{ service: 'relay', id: 'traffic', title: 'LLM traffic', kind: 'bar', ranges: ['24h', '7d'], span: 6 }]);
  for (const range of ['24h', '7d', undefined]) {
    const w = await api.getWidget('relay', 'traffic', { range });
    assert.equal(w.unit, 'count');
    assert.deepEqual(w.series.map(s => [s.name, s.axis]), [['Requests', undefined], ['Tokens', 'right'], ['p50 TTFT (ms)', 'right']]);
    for (const s of w.series) assert.equal(s.values.length, w.t.length);
    assert.ok(w.t.length >= (range === '7d' ? 168 : 24));
  }
  await assert.rejects(api.getWidget('relay', 'nope'), e => e.status === 404 && e.code === 'widget_not_found');
  await assert.rejects(api.getWidget('ghost', 'traffic'), e => e.status === 404 && e.code === 'service_not_found');
  await assert.rejects(api.getWidget('relay', 'traffic', { range: '1h' }), e => e.status === 422 && e.code === 'invalid_request');
  await api.stopService('relay');
  await assert.rejects(api.getWidget('relay', 'traffic', { range: '24h' }), e => e.status === 503 && e.code === 'service_not_running');
  assert.deepEqual(await api.listWidgets(), []);
});

test('settings: compact by default, partial saves merge like the hub', async () => {
  const api = createMockApi();
  const s = await api.getSettings();
  assert.equal(s.ui.density, 'compact');
  assert.deepEqual(s.ui.dashboard, { order: [], hidden: [], ranges: {}, shown: [], sizes: {} });
  const r = await api.saveSettings({ ui: { dashboard: { order: ['memory'], hidden: [], ranges: { memory: '6h' } } }, services: { enabled: { example: false } } });
  assert.equal(r.restart_required, false);
  assert.equal(r.settings.ui.theme, 'system');
  assert.equal(r.settings.ui.density, 'compact');
  assert.equal(r.settings.services.enabled.lcpp, true);
  assert.equal(r.settings.services.enabled.example, false);
  assert.equal(r.settings.hub.port, 7000);
  assert.equal((await api.saveSettings({ hub: { port: 7001 } })).restart_required, true);
  assert.equal((await api.saveSettings({ hub: { port: 7000 } })).restart_required, false);
  await assert.rejects(api.saveSettings({ services: { enabled: { ghost: true } } }), e => e.code === 'invalid_config' && e.data.field === 'services.enabled');
});
