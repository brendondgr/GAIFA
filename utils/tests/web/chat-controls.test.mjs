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
  const models = all(menuOf(ctl.ModelMenu({ models: MODELS, value: 'skynet', onChange: m => got.push(m) }), 'Model'), n => n.props?.role === 'menuitemradio');   // grouped by server since llm-servers 5.1
  assert.deepEqual(models.map(r => r.props.key), ['skynet', 'gemma4-26B']);
  assert.match(text(models[0]), /skynet \(default\).*128K|skynet \(default\)/);
  models[1].props.onClick();
  const env = ctl.EnvMenu({ api: {}, thread: null, envs: ENVS, value: null, onChange: e => got.push(e) });
  const list = all(menuOf(env, 'Environment'), n => n.props?.role === 'menuitemradio');
  assert.deepEqual(list.map(r => text(r).replace(/\d+$/, '')), ['Default', 'Grants']);
  assert.equal(list[0].props['aria-checked'], 'true');                                   // none set: Default
  list[1].props.onClick();
  assert.deepEqual(got, ['gemma4-26B', 'grants']);
});

// Plans 42.4 and 43.2: environments made, changed and deleted from the chat, in a dialog (chat-envedit.js).
const ed = await load('chat/chat-envedit.js');

test('the environment calls: create, rename, delete, a folder added, its level, removed, and the chooser', async () => {
  const seen = [];
  const api = { callService: async (mod, method, p, o) => { seen.push([mod, method, p, o.json]); return { json: { id: 'grants', name: 'Grants' } }; } };
  const ops = ed.envOps(api);
  await ops.create('Grants');
  await ops.rename('grants', 'Grant work');
  await ops.addFolder('grants', '/home/u/Docs', 'edit');
  await ops.setLevel('grants', 'docs', 'run');
  await ops.removeFolder('grants', 'docs');
  await ops.remove('grants');
  await ops.pick();
  assert.deepEqual(seen, [
    ['workspace', 'POST', '/v1/environments', { name: 'Grants' }],
    ['workspace', 'PUT', '/v1/environments/grants', { name: 'Grant work' }],
    ['workspace', 'POST', '/v1/environments/grants/folders', { path: '/home/u/Docs', level: 'edit' }],
    ['workspace', 'PATCH', '/v1/environments/grants/folders/docs', { level: 'run' }],
    ['workspace', 'DELETE', '/v1/environments/grants/folders/docs', undefined],
    ['workspace', 'DELETE', '/v1/environments/grants', undefined],
    ['workspace', 'POST', '/v1/pick-folder', { start: '/', title: 'Add a folder to the environment' }]]);   // the chooser opens at /
  assert.equal(ed.errLine({ detail: '/etc is outside your home', data: { fix: 'pick a folder in your home' } }), '/etc is outside your home — pick a folder in your home');
});

test('Save and Create: the dialog\'s changes become calls, in order', async () => {
  const env = { id: 'work', name: 'Work', folders: [{ id: 'a', path: '/w/a', level: 'read' }, { id: 'b', path: '/w/b', level: 'edit' }] };
  const draft = { name: 'Work 2', folders: [{ id: 'a', path: '/w/a', level: 'run' }, { path: '/w/c', level: 'read' }] };
  assert.deepEqual(ed.planSave(env, draft), [['rename', 'Work 2'], ['removeFolder', 'b'], ['addFolder', '/w/c', 'read'], ['setLevel', 'a', 'run']]);
  assert.deepEqual(ed.planSave(env, { name: 'Work', folders: env.folders }), []);                       // nothing changed: Save does nothing
  assert.deepEqual(ed.planSave(null, { name: ' New ', folders: [{ path: '/x', level: 'edit' }] }), [['create', 'New'], ['addFolder', '/x', 'edit']]);
  const calls = [];
  const ops = new Proxy({}, { get: (_, op) => async (...args) => { calls.push([op, ...args]); return op === 'create' ? { id: 'new-id' } : {}; } });
  assert.equal(await ed.saveEnv(ops, null, { name: 'New', folders: [{ path: '/x', level: 'read' }] }), 'new-id');
  assert.deepEqual(calls, [['create', 'New'], ['addFolder', 'new-id', '/x', 'read']]);                 // folders go into the new one
});

test('deleting an environment warns that its chats go too, archived ones included, then deletes them and it', async () => {
  const w = ed.deleteWarning({ name: 'Grants' }, { open: 3, archived: 2 });
  assert.match(w.body, /deletes its 5 chats, including 2 archived/);
  assert.equal(w.danger, true);
  assert.match(ed.deleteWarning({ name: 'X' }, { open: 0, archived: 0 }).body, /no chats/);
  const chats = { false: ['t1', 't2'], true: ['t3'] }, removed = [], calls = [];
  const c = {
    threads: async ({ environment, archived }) => (environment === 'grants' ? chats[String(!!archived)].map(id => ({ id })) : []),
    remove: async id => { removed.push(id); for (const k of ['false', 'true']) chats[k] = chats[k].filter(x => x !== id); },
    threadGroups: async ({ archived } = {}) => [{ environment: 'grants', count: archived ? 1 : 2 }],
  };
  assert.deepEqual(await ed.chatCounts(c, 'grants'), { open: 2, archived: 1 });
  const api = { callService: async (mod, method, p) => { calls.push([method, p]); return { json: {} }; } };
  assert.deepEqual(await ed.deleteEnvironment({ c, api, env: { id: 'grants', name: 'Grants' } }), ['t1', 't2', 't3']);
  assert.deepEqual(removed, ['t1', 't2', 't3']);
  assert.deepEqual(calls, [['DELETE', '/v1/environments/grants']]);                       // the environment last
});

test('the dialog: Name, Folders with levels (up to their cap) and Remove, Add folder…, Cancel and Save or Create, Delete when editing', () => {
  const api = { callService: async () => ({ json: {} }) };
  const env = { id: 'work', name: 'Work', folders: [{ id: 'gaifa', path: '/home/u/Agents/GAIFA', level: 'read', max_level: 'read', capped: 'the GAIFA folder stays at Read' },
    { id: 'a', path: '/home/u/a', level: 'edit', max_level: 'run_net' }] };
  const el = expand(ed.EnvDialog({ api, env, onClose() {} }));
  assert.equal(all(el, n => n.props?.role === 'dialog')[0].props['aria-modal'], 'true');
  assert.match(text(el), /Edit environment/);
  const groups = all(el, n => n.props?.role === 'group');
  assert.deepEqual(groups[0].props.children.filter(Boolean).map(b => b.props.disabled), [false, true, true, true]);
  assert.equal(all(el, n => n.props?.['aria-label']?.startsWith('Remove ')).length, 2);
  assert.match(text(el), /Add folder…/);
  assert.equal(all(el, n => n.type === 'input' && n.props['aria-label'] === 'Folder path').length, 0);   // the chooser, not a typed path
  assert.match(text(el), /Delete….*Cancel.*Save/);
  const fresh = expand(ed.EnvDialog({ api, env: null, onClose() {} }));
  assert.match(text(fresh), /New environment/);
  assert.match(text(fresh), /Cancel.*Create/);
  assert.doesNotMatch(text(fresh), /Delete…/);
  assert.doesNotMatch(text(expand(ed.EnvDialog({ api, env: { ...env, default: true }, onClose() {} }))), /Delete…/);
});

test('the menu: compact rows that pick, Edit on each but None, New environment; None explains itself', () => {
  const envs = [{ id: 'none', name: 'None', none: true, folders: [] }, ...ENVS];
  const api = { callService: async () => ({ json: {} }) };
  const pop = all(ctl.EnvMenu({ api, thread: null, envs, value: 'none', onChange() {} }), n => n.props?.label === 'Environment')[0];
  assert.equal(pop.props.width, ctl.ENV_MENU_W);
  const kids = expand(pop.props.children.filter(Boolean));
  assert.deepEqual(all(kids, n => n.props?.role === 'menuitemradio').map(n => text(n).replace(/\d+$/, '')), ['None', 'Default', 'Grants']);
  assert.deepEqual(all(kids, n => /^Edit /.test(n.props?.['aria-label'] || '')).map(n => n.props['aria-label']), ['Edit Default', 'Edit Grants']);
  assert.match(text(kids), /New environment/);
  assert.match(text(kids), /None has no folders/);
});
