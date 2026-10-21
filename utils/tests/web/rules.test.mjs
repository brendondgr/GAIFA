// Your rules in Settings → Agent (web/chat/chat-rules.js): the Auto judge's command rules and the tool permissions,
// checked as utils/config.py checks them, the "Always allow" shortcut's list and confirm, and the editors' lists.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
globalThis.React = {
  Fragment: Symbol('Fragment'),
  createElement: (type, props, ...children) => ({ type, props: { ...(props || {}), children: children.flat() } }),
  useState: init => [typeof init === 'function' ? init() : init, () => {}],
  useRef: v => ({ current: v }), useEffect: () => {}, useMemo: f => f(), useCallback: f => f,
};
const rules = await load('chat/chat-rules.js');

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

test('command rules are checked as the hub checks them', () => {
  assert.deepEqual(rules.checkCommandRule('  pytest    * '), { value: 'pytest *' });
  assert.deepEqual(rules.checkCommandRule('make -C * test'), { value: 'make -C * test' });
  for (const bad of ['', '  ', 'pytest; curl x', 'a | sh', 'a && b', 'echo $HOME', 'x `y`', 'a > b', 'pytest\nrm', "bash -c 'x'", '* foo', 'py* -q', 'x'.repeat(201)])
    assert.ok(rules.checkCommandRule(bad).error, JSON.stringify(bad));
});

test('tool globs, the shortcut list and its confirm', () => {
  assert.deepEqual(rules.checkToolGlob(' comfy_* '), { value: 'comfy_*' });
  assert.ok(rules.checkToolGlob('hub start').error && rules.checkToolGlob('').error);
  assert.deepEqual(rules.withRule(['a *'], 'b *'), ['a *', 'b *']);
  assert.deepEqual(rules.withRule(['a *'], 'a *'), ['a *']);
  assert.deepEqual(rules.withRule(undefined, 'a *'), ['a *']);
  assert.match(rules.allowConfirm('pytest *'), /pytest \*.*internet on/s);
  assert.equal(rules.errText({ detail: 'Value error, bad' }), 'bad');
});

test('the editors list what is saved', () => {
  const cfg = { judge: { allow_commands: ['pytest *'], ask_commands: ['git checkout *'] }, permissions: { deny: [], ask: ['hub_set_preference'], allow: [] } };
  const api = { saveSettings: async () => ({ settings: cfg }), getSettings: async () => cfg };
  const tree = expand(rules.CommandRules({ api, cfg }));
  const codes = all(tree, n => n.type === 'code').map(text);
  assert.ok(codes.includes('pytest *') && codes.includes('git checkout *'));
  const inputs = all(tree, n => n.type === 'input').map(n => n.props['aria-label']);
  assert.deepEqual(inputs, ['Always allow these commands in Auto', 'Always ask before these']);
  assert.equal(rules.CommandRules({ api, cfg: null }), null);
  assert.equal(rules.CommandRules({ api: {}, cfg }), null);
});
