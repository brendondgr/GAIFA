// Plan settings-redesign: the Settings page's rows (web/settings/rows.js) and blocks (blocks-*.js), rendered
// with a minimal React stand-in (tinyreact.mjs) and fixed data. The page itself is checked in the browser.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { render, all, text, find } from './tinyreact.mjs';
const h = (...a) => globalThis.React.createElement(...a);

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const rows = await load('settings/rows.js');
const S = await load('settings/schema.js');

const services = [{ id: 'relay', name: 'LLM Relay', manifest_errors: [] }, { id: 'lcpp', name: 'LLM Launcher', manifest_errors: [] }];
const draft = { hub: { port: 7000 }, memory: { reserve_gb: 12, auto_make_room: true, never_unload: ['lcpp'], priority: ['relay', 'lcpp'] } };
const secs = S.sections({ services });
const rowOf = p => S.rowFor(secs, p);
const draw = (p, o = {}) => render(rows.Row({ row: rowOf(p), value: rowOf(p).get(draft), onChange: () => {}, ctx: { draft }, ...o }));

test('a toggle is a switch with aria-checked', () => {
  const t = draw('memory.auto_make_room');
  const sw = find(t, n => n.props.role === 'switch');
  assert.equal(sw.props['aria-checked'], 'true');
  assert.equal(sw.props['aria-label'], 'Automatically make room');
  assert.match(text(t), /Automatically make room when a service needs memory/);
});

test('number, chips and order rows', () => {
  const n = draw('memory.reserve_gb', { error: 'Between 0 and 64 GB' });
  const inp = find(n, x => x.type === 'input');
  assert.equal(inp.props.value, 12); assert.equal(inp.props.max, 64); assert.equal(inp.props['aria-invalid'], 'true');
  assert.equal(text(find(n, x => x.props.role === 'alert')), 'Between 0 and 64 GB');
  const c = draw('memory.never_unload');
  assert.deepEqual(all(c, x => x.type === 'button').map(b => [text(b), b.props['aria-pressed']]), [['LLM Relay', 'false'], ['LLM Launcher', 'true']]);
  const o = draw('memory.priority');
  assert.deepEqual(all(o, x => x.type === 'li').map(li => text(li)), ['1LLM Relay', '2LLM Launchernever unloaded']);
  const btns = all(o, x => x.type === 'button');
  assert.equal(btns[0].props.disabled, true); assert.equal(btns.at(-1).props.disabled, true);
  assert.equal(btns[1].props['aria-label'], 'Move LLM Relay down');
});

test('segmented and the order list’s moves', () => {
  const theme = S.rowsOf(secs).find(r => r.key === 'ui.theme');
  const t = render(rows.Row({ row: theme, value: 'dark', onChange: () => {}, ctx: {} }));
  assert.deepEqual(all(t, x => x.type === 'button').map(b => b.props['aria-pressed']), ['false', 'false', 'true']);
  let got = null;
  const ol = render(rows.OrderList({ value: ['a', 'b', 'gone'], items: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }], onChange: v => { got = v; } }));
  all(ol, x => x.type === 'button')[1].props.onClick();
  assert.deepEqual(got, ['b', 'a', 'gone']);
});

// ---------- the blocks (1.3) ----------
const B = await load('settings/blocks-hub.js');
const A = await load('settings/blocks-agent.js');   // imports cleanly: the agent's cards, placed one by one
const sys = { hub: { version: '0.1.0', pid: 31337, uptime_s: 7260, rss_bytes: 92e6 },
  paths: { root: '/gaifa', models: '/gaifa/data/models', databases: '/gaifa/data/databases', outputs: '/gaifa/outputs', logs: '/gaifa/data/logs' },
  usage: { models_bytes: 190e9, databases_bytes: 12e6, outputs_bytes: 3.4e9, logs_bytes: 5e6 }, disk: { free_bytes: 500e9, total_bytes: 2000e9 } };

test('the pure views: process, paths, Doctor', () => {
  assert.deepEqual(B.processInfo(sys), [{ k: 'Version', v: 'v0.1.0' }, { k: 'PID', v: '31337' }, { k: 'Uptime', v: '2h 1m' }, { k: 'Memory (RSS)', v: '92.0 MB' }]);
  assert.deepEqual(B.pathRows(sys).map(p => [p.k, p.sz]), [['Project root', ''], ['Models', '190 GB'], ['Databases', '12.0 MB'], ['Outputs', '3.4 GB'], ['Logs', '5.0 MB']]);
  const rep = { ts: 1, counts: { fail: 1, warn: 0, note: 1, ok: 2 }, checks: [{ level: 'fail', title: 'a' }, { level: 'ok', title: 'b' }, { level: 'note', title: 'c' }, { level: 'ok', title: 'd' }] };
  const v = B.doctorView(rep, false);
  assert.equal(v.summary, '1 problem · 2 ok, 0 warnings, 1 note'); assert.equal(v.tone, 'fail');
  assert.deepEqual(v.rows.map(r => r.title), ['a', 'c']); assert.equal(B.doctorView(rep, true).rows.length, 4);
  assert.equal(B.doctorView(null), null);
});

test('the hub blocks render with fixed data', () => {
  const copied = [], ctx = { system: sys, services, copy: (t, w) => copied.push([t, w]), api: {} };
  assert.match(text(render(h(B.ProcessCard, { ctx }))), /GAIFA process.*v0\.1\.0.*31337/);
  const paths = render(h(B.PathsList, { ctx }));
  assert.match(text(paths), /Disk500 GB free of 2.0 TB/);
  all(paths, n => n.props['aria-label'] === 'Copy path')[1].props.onClick();
  assert.deepEqual(copied, [['/gaifa/data/models', 'Path copied']]);
  assert.match(text(render(h(B.Versions, { ctx }))), /GAIFA.*v0\.1\.0.*LLM Relay—/);
  assert.equal(all(render(h(B.CliList, { ctx })), n => n.props['aria-label'] === 'Copy command').length, B.CLI.length);
  assert.match(text(render(h(B.AddModCard, { ctx }))), /gaifa new <id>/);
  const doc = render(h(B.DoctorPanel, { ctx, initial: { ts: 1, counts: { fail: 0, warn: 0, note: 0, ok: 1 }, checks: [{ level: 'ok', title: 'x', area: 'disk' }] } }));
  assert.match(text(doc), /All good · 1 ok/); assert.match(text(doc), /Nothing needs attention\./);
  // the services table edits the draft
  let d = { services: { order: ['relay', 'lcpp'], enabled: { relay: true, lcpp: true }, autostart: { relay: false, lcpp: true } } };
  const t = render(h(B.ServicesTable, { ctx: { ...ctx, draft: d, setDraft: fn => { d = JSON.parse(JSON.stringify(d)); fn(d); } } }));
  const sw = all(t, n => n.props.role === 'switch');
  assert.deepEqual(sw.map(s => s.props['aria-checked']), ['true', 'false', 'true', 'true']);
  sw[1].props.onClick(); assert.equal(d.services.autostart.relay, true);
  all(t, n => n.props['aria-label'] === 'Move LLM Relay down')[0].props.onClick(); assert.deepEqual(d.services.order, ['lcpp', 'relay']);
});

test('every block the schema names exists', () => {
  const names = { ...B.HUB_BLOCKS, ...A.AGENT_BLOCKS };
  for (const r of S.rowsOf(S.sections({ services })).filter(r => r.control === 'block')) assert.ok(names[r.block], r.block);
});
