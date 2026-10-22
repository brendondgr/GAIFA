// Plan 42.3: the row under the message box: the environment, the mode and the model as plain buttons that open small
// menus, with the mode rules the header's select had (Bypass only where folders allow it, Auto disabled while the
// judge doesn't answer).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
globalThis.React = {
  Fragment: Symbol('Fragment'),
  createElement: (type, props, ...children) => ({ type, props: { ...(props || {}), children: children.flat() } }),
  useState: init => [typeof init === 'function' ? init() : init, () => {}],
  useRef: v => ({ current: v }), useEffect: () => {}, useLayoutEffect: () => {}, useMemo: f => f(), useCallback: f => f,
};
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const ctl = await load('chat/chat-controls.js');
const header = await load('chat/chat-header.js');

function expand(n) {
  if (n == null || n === false || typeof n !== 'object') return n;
  if (Array.isArray(n)) return n.map(expand);
  if (typeof n.type === 'function') return expand(n.type(n.props));
  return { ...n, props: { ...n.props, children: (n.props.children || []).map(expand) } };
}
const all = (n, pred, out = []) => {
  if (Array.isArray(n)) { n.forEach(x => all(x, pred, out)); return out; }
  if (!n || typeof n !== 'object') return out;
  if (pred(n)) out.push(n);
  all(n.props?.children, pred, out);
  return out;
};
const text = n => (n == null || n === false ? '' : typeof n !== 'object' ? String(n) : Array.isArray(n) ? n.map(text).join('') : text(n.props?.children));
const menuOf = (el, label) => all(el, n => n.props?.label === label)[0].props.children.flat().filter(Boolean);   // a popover's rows, shut or not

const ENVS = [{ id: 'default', name: 'Default', default: true, folders: [{ id: 'a', path: '/home/u/a', level: 'read' }] }, { id: 'grants', name: 'Grants', folders: [] }];
const MODELS = { default: 'skynet', models: [{ id: 'skynet', meta: { context_length: 131072 } }, { id: 'gemma4-26B', meta: {} }] };

test('the three buttons say the environment, the mode and the model', () => {
  const row = expand(ctl.ControlsRow({
    env: ctl.EnvMenu({ api: {}, thread: null, envs: ENVS, value: 'grants', onChange() {} }),
    mode: ctl.ModeMenu({ value: 'accept_edits', onChange() {} }),
    model: ctl.ModelMenu({ models: MODELS, value: null, onChange() {} }) }));
  const labels = all(row, n => n.props?.className === 'aichat-ctl').map(n => n.props['aria-label']);
  assert.deepEqual(labels, ['Environment: Grants', 'Mode: Accept edits', 'Model: skynet']);
  assert.equal(all(row, n => n.type === 'select').length, 0);                         // buttons, not selects
  assert.equal(ctl.EnvMenu({ api: {}, envs: null, value: null, onChange() {} }), null);  // no workspace mod: no environment button
});

test('the mode menu keeps the rules: Bypass where folders allow it, Auto disabled while the judge is down', () => {
  const keys = el => menuOf(el, 'Mode').map(r => r.props.key);
  assert.deepEqual(keys(ctl.ModeMenu({ value: 'manual', onChange() {} })), ['plan', 'manual', 'accept_edits', 'auto']);
  assert.deepEqual(keys(ctl.ModeMenu({ value: 'manual', onChange() {}, bypass: true })), ['plan', 'manual', 'accept_edits', 'auto', 'bypass']);
  const down = { available: false, model: 'gemma4-26B', detail: "the relay doesn't list gemma4-26B" };
  const auto = menuOf(ctl.ModeMenu({ value: 'manual', onChange() {}, judge: down }), 'Mode').find(r => r.props.key === 'auto');
  assert.equal(auto.props.disabled, true);
  assert.match(auto.props.title, /doesn't list gemma4-26B/);
  assert.deepEqual(header.modeChoices('ask').map(m => m.key), ['plan', 'manual', 'accept_edits', 'auto']);   // old names map over
  const picked = [];
  const rows = menuOf(ctl.ModeMenu({ value: 'manual', onChange: m => picked.push(m) }), 'Mode');
  rows.find(r => r.props.key === 'plan').props.onClick();
  rows.find(r => r.props.key === 'manual').props.onClick();                                      // the current one: no change
  assert.deepEqual(picked, ['plan']);
});

test('the model and environment menus list their choices and call back', () => {
  const got = [];
  const models = menuOf(ctl.ModelMenu({ models: MODELS, value: 'skynet', onChange: m => got.push(m) }), 'Model').filter(r => r.type === 'button');
  assert.deepEqual(models.map(r => r.props.key), ['skynet', 'gemma4-26B']);
  assert.match(text(models[0]), /skynet \(default\).*128K|skynet \(default\)/);
  models[1].props.onClick();
  const env = ctl.EnvMenu({ api: {}, thread: null, envs: ENVS, value: null, onChange: e => got.push(e) });
  const list = all(menuOf(env, 'Environment'), n => n.props?.role === 'menuitemradio');
  assert.deepEqual(list.map(r => r.props.key), ['default', 'grants']);
  assert.equal(list[0].props['aria-checked'], 'true');                                   // none set: Default
  list[1].props.onClick();
  assert.deepEqual(got, ['gemma4-26B', 'grants']);
});
