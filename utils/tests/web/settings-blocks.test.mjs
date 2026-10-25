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

