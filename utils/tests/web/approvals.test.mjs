// Plan 25.3: the approval card. The buttons per risk (Allow once · Allow in this chat · Always
// allow, the last behind a second confirm for execute and destructive), the risk's word and colour,
// the grant key in words, and the code of an execute tool shown whole and editable. ParamCard is
// rendered with a minimal stand-in for React (hooks keep their first value; nothing mounts).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const risk = await load('chat/chat-risk.js');

// ---- a tiny React: elements as objects, function components expanded, hooks with fixed state ----
const Fragment = Symbol('Fragment');
const states = [];
globalThis.React = {
  Fragment,
  createElement: (type, props, ...children) => ({ type, props: { ...(props || {}), children: children.flat() } }),
  useState: init => { const s = [typeof init === 'function' ? init() : init, v => states.push(v)]; return s; },
  useRef: v => ({ current: v }), useEffect: () => {}, useMemo: f => f(), useCallback: f => f,
};
const forms = await load('chat/chat-forms.js');

function expand(n) {
  if (n == null || n === false || typeof n !== 'object') return n;
  if (Array.isArray(n)) return n.map(expand);
  if (typeof n.type === 'function') return expand(n.type(n.props));
  return { ...n, props: { ...n.props, children: (n.props.children || []).map(expand) } };
}
function all(n, pred, out = []) {
  if (Array.isArray(n)) { n.forEach(x => all(x, pred, out)); return out; }
  if (!n || typeof n !== 'object') return out;
  if (pred(n)) out.push(n);
  all(n.props?.children, pred, out);
  return out;
}
const text = n => (n == null || n === false ? '' : typeof n !== 'object' ? String(n) : Array.isArray(n) ? n.map(text).join('') : text(n.props?.children));
const card = (spec, props = {}) => expand(forms.ParamCard({ spec, api: {}, outputs: [], mods: [], onRun: async () => {}, onCancel: async () => {}, cancelLabel: 'Deny', ...props }));
const buttons = tree => all(tree, n => n.type === 'button').map(b => text(b).trim());
const SPECS = {
  read: ['fake_get', {}], write: ['fake_save', {}], generate: ['fake_make_image', {}],
  network: ['web_fetch', { url: { type: 'string' } }, 'url:host', { url: 'https://GitHub.com/a/b' }],
  execute: ['workspace_python', { code: { type: 'string' }, folder: { type: 'string' } }, 'arg:folder', { code: 'print(1)\nprint(2)', folder: '~/Projects/foo' }],
  destructive: ['tts_delete_voice', { name: { type: 'string' } }, null, { name: 'Hope' }],
};
const specOf = r => { const [tool, properties, grant_key, args] = SPECS[r]; return { tool, risk: r, grant_key, arguments: args || {}, ask_fields: [], schema: { type: 'object', properties } }; };

test('the buttons per risk, in a chat and outside one', () => {
  for (const r of Object.keys(SPECS)) {
    const inChat = risk.approvalButtons(r, { thread: true }), outside = risk.approvalButtons(r);
    assert.deepEqual(inChat.map(b => b.remember), ['once', 'thread', 'always'], r);
    assert.deepEqual(outside.map(b => b.remember), ['once', 'always'], r);      // MCP and the API tab: no chat to allow it in
    const second = ['execute', 'destructive'].includes(r);
    assert.equal(!!inChat.at(-1).confirm, second, r);
    assert.ok(inChat.slice(0, -1).every(b => !b.confirm));
    const shown = buttons(card(specOf(r), { choices: inChat }));
    assert.deepEqual(shown, ['Allow once', 'Allow in this chat', second ? 'Always allow…' : 'Always allow', 'Deny'], r);
    assert.deepEqual(buttons(card(specOf(r), { choices: outside })), ['Allow once', second ? 'Always allow…' : 'Always allow', 'Deny'], r);
  }
  // a tool form (no choices) keeps its one Run button
  assert.deepEqual(buttons(card(specOf('generate'), { cancelLabel: 'Cancel' })), ['Run', 'Cancel']);
});

test('the risk badge has its word and colour; the grant key reads as words', () => {
  assert.deepEqual(risk.RISK_TONE, { read: 'green', write: 'purple', generate: 'purple', network: 'cyan', execute: 'accent', destructive: 'red' });
  for (const r of Object.keys(SPECS)) {
    const t = card(specOf(r), { choices: risk.approvalButtons(r, { thread: true }) });
    const badge = all(t, n => n.type === 'span' && n.props.title === risk.RISK_WORD[r]);
    assert.equal(text(badge[0]), r, r);
  }
  assert.ok(text(card(specOf('network'), { choices: [] })).includes('on github.com'));
  assert.ok(text(card(specOf('execute'), { choices: [] })).includes('in ~/Projects/foo'));
  assert.equal(risk.grantKeyOf('url:host', { url: 'https://api.github.com:8443/x' }), 'api.github.com');
  assert.equal(risk.grantKeyOf('url:host', { url: 'nope' }), null);
  assert.equal(risk.grantKeyOf('arg:folder', { folder: '' }), null);
  assert.equal(risk.grantKeyOf('const:search', {}), 'search');
  assert.equal(risk.grantText('const:search', 'search'), 'every search call');
  assert.equal(risk.grantText('arg:lang', 'py'), 'lang py');
  assert.equal(risk.grantText(null, 'x'), null);
});

test('execute shows the code whole, monospaced and editable', () => {
  assert.deepEqual(risk.codeFields({ properties: { code: { type: 'string' }, folder: { type: 'string' }, n: { type: 'integer' }, script: { type: 'string', format: 'code' } } }, 'execute'), ['code', 'script']);
  assert.deepEqual(risk.codeFields({ properties: { code: { type: 'string' } } }, 'generate'), []);
  const t = card(specOf('execute'), { choices: risk.approvalButtons('execute', { thread: true }) });
  const areas = all(t, n => n.type === 'textarea');
  assert.equal(areas.length, 1);
  assert.equal(areas[0].props.value, 'print(1)\nprint(2)');                     // the whole code, not a one-line summary
  assert.match(areas[0].props.style.fontFamily, /mono/i);
  assert.equal(typeof areas[0].props.onChange, 'function');
  assert.equal(areas[0].props.style.maxHeight, 360);
});

test('choosing a button hands the card its remember; always on execute asks a second time', async () => {
  const got = [];
  const spec = specOf('network');
  const t = card(spec, { choices: risk.approvalButtons("network", { thread: true }), onRun: async (args, o) => got.push(o) });
  const click = label => all(t, n => n.type === 'button' && text(n).trim() === label)[0].props.onClick();
  await click('Allow in this chat');
  await click('Always allow');
  assert.deepEqual(got, [{ remember: 'thread' }, { remember: 'always' }]);
  states.length = 0;
  const ex = card(specOf('execute'), { choices: risk.approvalButtons('execute', { thread: true }), onRun: async (a, o) => got.push(o) });
  all(ex, n => n.type === 'button' && text(n).trim() === 'Always allow…')[0].props.onClick();
  assert.equal(got.length, 2);                                                    // nothing decided yet…
  assert.deepEqual(states.at(-1), { remember: 'always', label: 'Always allow', confirm: true });   // …the confirm opens
  assert.match(risk.confirmText('workspace_python', 'execute', 'in ~/x'), /Always let the agent run code with workspace_python \(in ~\/x\)/);
  assert.equal(risk.rememberText('thread'), 'Allowed in this chat');
  assert.equal(risk.rememberText('once'), null);
});

test('the popover says how many memories wait for review (memory-auto-learning 4.1)', async () => {
  const { memoriesText } = await load('chat/chat-approvals.js');
  assert.equal(memoriesText(0), null);
  assert.equal(memoriesText(1), '1 memory waits for your review');
  assert.equal(memoriesText(12), '12 memories wait for your review');
});

test('web-approvals 2.2: a web page card in a chat offers "Allow every site in this chat"', async () => {
  const got = [];
  const inChat = risk.approvalButtons('network', { thread: true, grantKey: 'url:host' });
  assert.deepEqual(inChat.map(b => b.remember), ['once', 'thread', 'sites', 'always']);
  assert.deepEqual(risk.approvalButtons('network', { grantKey: 'url:host' }).map(b => b.remember), ['once', 'always']);   // no chat: no sites
  assert.deepEqual(risk.approvalButtons('execute', { thread: true, grantKey: 'arg:folder' }).map(b => b.remember), ['once', 'thread', 'always']);
  const t = card(specOf('network'), { choices: inChat, onRun: async (args, o) => got.push(o) });
  assert.deepEqual(buttons(t), ['Allow once', 'Allow in this chat', 'Allow every site in this chat', 'Always allow', 'Deny']);
  const btn = all(t, n => n.type === 'button' && text(n).trim() === 'Allow every site in this chat')[0];
  assert.equal(btn.props.title, risk.SITES_HINT);
  await btn.props.onClick();
  assert.deepEqual(got, [{ remember: 'sites' }]);
  assert.equal(risk.rememberText('sites'), 'Every site allowed in this chat');
  assert.equal(risk.grantText('url:any', '*'), 'on every site');                 // Settings → Permissions → Grants
});

test('capability-enablement 3.6: a tool group whose mod cannot run says so; an empty catalog is not "Loading"', async () => {
  const comp = await import(pathToFileURL(path.join(root, 'web/chat/chat-composer.js')).href);
  assert.equal(comp.groupState([{ state: 'not_set_up' }, { state: 'not_set_up' }]), 'not set up');
  assert.equal(comp.groupState([{ state: 'off' }]), 'turned off');
  assert.equal(comp.groupState([{ state: 'off_by_mod' }, { state: 'on' }]), '', 'one tool off: the group still works');
  assert.equal(comp.groupState([{ state: 'on' }]), '');
  const fix = await import(pathToFileURL(path.join(root, 'web/chat/chat-fix.js')).href);
  assert.deepEqual(fix.fixAction({ label: 'Set up Web', setup: 'web', command: 'gaifa setup web' }, {}), { kind: 'setup', ids: ['web'] });
});
