// Plan 34: the chat's environment chip (its words, which environment a chat uses, the folders allowed in it, a new
// chat's default) and the folder card ("Let this chat read …?": Allow for this chat · Add to <environment> · Deny).
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
const env = await load('chat/chat-env.js');
const risk = await load('chat/chat-risk.js');
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

const ENVS = [{ id: 'default', name: 'Default', default: true, folders: [{ id: 'aihub', path: '/home/u/Agents/AIHub', level: 'read' }] },
  { id: 'grants', name: 'Grants', folders: [{ id: 'a', path: '/home/u/a', level: 'edit' }, { id: 'b', path: '/home/u/b', level: 'read' }] }];

test('which environment a chat uses, and the chip\'s words', () => {
  assert.equal(env.envOf(ENVS, 'grants').name, 'Grants');
  assert.equal(env.envOf(ENVS, null).id, 'default');
  assert.equal(env.envOf(ENVS, 'deleted').id, 'default');           // a deleted environment: Default, as the mod does
  assert.equal(env.envOf([], 'x'), null);
  assert.equal(env.chipText(ENVS[1]), 'Grants · 2 folders');
  assert.equal(env.chipText(ENVS[0], 1), 'Default · 1 folder +1');
  assert.equal(env.chipText(null), 'No environment');
});

test('the folders allowed in this chat come from its folder grants', () => {
  const grants = [
    { id: 'gr_2', kind: 'folder', key: 'folder:/home/u/Mycelium', thread: 't1', created_ts: 2 },
    { id: 'gr_1', kind: 'folder', key: 'folder:/home/u/notes', thread: 't1', created_ts: 1 },
    { id: 'gr_3', kind: 'arg:folder', key: 'proj pytest', thread: 't1' },
    { id: 'gr_4', kind: 'folder', key: 'folder:/home/u/x', thread: 't2' }];
  assert.deepEqual(env.allowedFolders(grants, 't1'), [{ grant: 'gr_1', path: '/home/u/notes' }, { grant: 'gr_2', path: '/home/u/Mycelium' }]);
  assert.deepEqual(env.allowedFolders(null, 't1'), []);
  assert.equal(env.shortPath('/home/u/Agents/Mycelium'), '~/Agents/Mycelium');
  assert.equal(env.shortPath('/srv/x'), '/srv/x');
});

test('a new chat starts in the last environment picked', () => {
  assert.deepEqual(env.newChatSettings({}, 'grants'), { environment: 'grants' });
  assert.deepEqual(env.newChatSettings({ environment: 'default' }, 'grants'), { environment: 'default' });
  assert.deepEqual(env.newChatSettings({ no_learn: true }, null), { no_learn: true });
});

const ASK = { path: '/home/u/Agents/Mycelium', level: 'read', environment: { id: 'grants', name: 'Grants' } };

test('the folder card offers this chat or the environment, never Always', () => {
  const b = risk.approvalButtons('read', { thread: true, folder: ASK });
  assert.deepEqual(b.map(x => [x.remember, x.label]), [['thread', 'Allow for this chat'], ['environment', 'Add to “Grants”']]);
  assert.deepEqual(risk.approvalButtons('read', { thread: false, folder: ASK }).map(x => x.remember), ['once', 'environment']);
  assert.deepEqual(env.folderChoices(ASK).map(x => x.remember), ['thread', 'environment']);
  assert.equal(risk.limitsCover({ key: 'folder:/home/u/Agents/Mycelium' }), 'in ~/Agents/Mycelium');
  const t = expand(forms.ParamCard({ spec: { tool: 'workspace_tree', risk: 'read', arguments: { folder: '~/Agents/Mycelium' }, schema: { properties: { folder: { type: 'string' } } },
    limits: { action: 'read', key: 'folder:' + ASK.path, ask_folder: ASK } }, api: {}, outputs: [], mods: [], onRun: async () => {}, onCancel: async () => {}, cancelLabel: 'Deny',
  choices: b }));
  const s = text(t);
  assert.match(s, /Let this chat read ~\/Agents\/Mycelium\?/);
  assert.match(s, /\/home\/u\/Agents\/Mycelium/);
  assert.match(s, /Read/);
  assert.match(s, /not in this chat's environment \(Grants\)/);
  const btns = all(t, n => n.type === 'button').map(x => text(x).trim());
  assert.deepEqual(btns.filter(x => /Allow|Add to|Deny/.test(x)), ['Allow for this chat', 'Add to “Grants”', 'Deny']);
});

test('"Add to the environment" adds the folder there, then allows the call once', async () => {
  const calls = [];
  const api = { callService: async (...a) => { calls.push(a); return { json: {} }; } };
  assert.deepEqual(await env.decideFolder(api, ASK, { remember: 'thread' }), { remember: 'thread' });
  assert.equal(calls.length, 0);
  assert.deepEqual(await env.decideFolder(api, ASK, { remember: 'environment' }), { remember: 'once' });
  assert.deepEqual(calls[0], ['workspace', 'POST', '/v1/environments/grants/folders', { json: { path: ASK.path, level: 'read' } }]);
  const there = { callService: async () => { throw Object.assign(new Error('exists'), { status: 409, code: 'exists' }); } };
  assert.deepEqual(await env.decideFolder(there, ASK, { remember: 'environment' }), { remember: 'once' });   // already in it
  const broken = { callService: async () => { throw Object.assign(new Error('capped'), { status: 422, code: 'capped' }); } };
  await assert.rejects(env.decideFolder(broken, ASK, { remember: 'environment' }), /capped/);
});

test('the chip shows nothing without the workspace mod', () => {
  assert.equal(env.EnvChip({ api: {}, thread: null, value: null }), null);
});
