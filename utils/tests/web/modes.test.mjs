// Plan 27.4: the five chat modes in the header (Bypass only where the chat's workspace folders allow
// it, old names shown as their new ones) and the workspace card: the diff, a host run's warning,
// "asks every time" with only Allow once, and what a grant covers ("in itsdangerous, pytest commands").
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const Fragment = Symbol('Fragment');
globalThis.React = {
  Fragment,
  createElement: (type, props, ...children) => ({ type, props: { ...(props || {}), children: children.flat() } }),
  useState: init => [typeof init === 'function' ? init() : init, () => {}],
  useRef: v => ({ current: v }), useEffect: () => {}, useMemo: f => f(), useCallback: f => f,
};
const risk = await load('chat/chat-risk.js');
const header = await load('chat/chat-header.js');
const forms = await load('chat/chat-forms.js');

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
const options = el => all(expand(el), n => n.type === 'option').map(o => o.props.value);

test('five modes; Bypass only when allowed; old names read as new ones', () => {
  assert.deepEqual(header.MODES.map(m => m[0]), ['plan', 'manual', 'accept_edits', 'auto', 'bypass']);
  assert.deepEqual(options(header.ModeSelect({ value: 'manual', onChange() {} })), ['plan', 'manual', 'accept_edits', 'auto']);
  assert.deepEqual(options(header.ModeSelect({ value: 'manual', onChange() {}, bypass: true })), ['plan', 'manual', 'accept_edits', 'auto', 'bypass']);
  assert.ok(options(header.ModeSelect({ value: 'bypass', onChange() {} })).includes('bypass'));   // a chat already in Bypass keeps it
  assert.equal(expand(header.ModeSelect({ value: 'ask', onChange() {} })).props.value, 'manual');
  assert.equal(expand(header.ModeSelect({ value: 'read_only', onChange() {} })).props.value, 'plan');
  assert.equal(header.modeOf('auto'), 'auto');
});

test('bypassAllowed: the folders this chat used, or any folder before it used one', () => {
  const folders = [{ id: 'a', allow_bypass: true }, { id: 'b', allow_bypass: false }];
  const call = folder => ({ type: 'tool_call', payload: { name: 'workspace_read', arguments: { folder } } });
  assert.equal(header.bypassAllowed([], []), false);
  assert.equal(header.bypassAllowed(null, []), false);
  assert.equal(header.bypassAllowed(folders, []), true);
  assert.equal(header.bypassAllowed(folders, [call('a')]), true);
  assert.equal(header.bypassAllowed(folders, [call('a'), call('b')]), false);
  assert.equal(header.bypassAllowed([{ id: 'b', allow_bypass: false }], []), false);
});

test('once-only calls get Allow once alone', () => {
  assert.deepEqual(risk.approvalButtons('execute', { thread: true, once: true }).map(b => b.remember), ['once']);
  assert.deepEqual(risk.approvalButtons('execute', { thread: true }).map(b => b.remember), ['once', 'thread', 'always']);
  assert.equal(risk.limitsCover({ key: 'itsdangerous pytest' }), 'in itsdangerous, pytest commands');
  assert.equal(risk.limitsCover({ key: 'itsdangerous' }), 'in itsdangerous');
  assert.equal(risk.limitsCover({}), null);
});

const card = spec => expand(forms.ParamCard({ spec, api: {}, outputs: [], mods: [], onRun: async () => {}, onCancel: async () => {}, cancelLabel: 'Deny',
  choices: risk.approvalButtons(spec.risk, { thread: true, once: !!spec.limits?.once }) }));

test('an edit card shows its diff, coloured', () => {
  const diff = '--- a/pkg/calc.py\n+++ b/pkg/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n';
  const t = card({ tool: 'workspace_edit', risk: 'write', arguments: { folder: 'proj', path: 'pkg/calc.py' }, schema: { properties: {} },
    why: 'Manual: edits ask first', limits: { action: 'edit', folder: 'proj', key: 'proj', preview: { summary: 'edited pkg/calc.py', diff } } });
  const pre = all(t, n => n.type === 'pre')[0];
  assert.ok(pre, 'a diff box');
  const rows = pre.props.children;
  assert.equal(text(rows[4]), '-    return a - b');
  assert.notEqual(rows[4].props.style.color, rows[5].props.style.color);
  const s = text(t);
  assert.match(s, /edits a file · proj · edited pkg\/calc\.py/);
  assert.match(s, /Manual: edits ask first/);
  assert.match(s, /in proj/);
});

test('a host run warns and asks every time', () => {
  const t = card({ tool: 'workspace_run', risk: 'execute', arguments: { folder: 'proj', command: 'make', where: 'host' },
    schema: { properties: { command: { type: 'string' }, folder: { type: 'string' }, where: { type: 'string' } } },
    limits: { action: 'host', folder: 'proj', key: 'proj make', once: true, preview: { command: 'make', where: 'host', network: true } } });
  const s = text(t);
  assert.match(s, /runs on your machine/);
  assert.match(s, /outside the sandbox: your files, your network/);
  assert.match(s, /asks every time/);
  const btns = all(t, n => n.type === 'button').map(b => text(b).trim());
  assert.ok(btns.includes('Allow once') && !btns.some(b => /in this chat|Always/.test(b)), btns.join(','));
});

test('a turn whose workspace edits carry `undo` offers Undo this turn (plan 27.7)', async () => {
  const { undoOf } = await load('chat/chat-turn.js');
  const res = (status, result) => ({ item: { result: { status, content: JSON.stringify({ status, result }) } } });
  const path = '/api/s/workspace/v1/checkpoints/t_1/5/undo';
  assert.deepEqual(undoOf([res('done', { undo: path, diff: '' }), res('done', { undo: path }), res('done', { other: 1 })]), [path]);
  assert.deepEqual(undoOf([res('error', { undo: path })]), []);
  assert.deepEqual(undoOf([{ item: { result: { status: 'done', content: 'plain text with "undo"' } } }]), []);
  assert.deepEqual(undoOf([res('done', { undo: 'http://elsewhere/undo' })]), []);
});
