// Editing an environment from the chat (plan 42.4, reworked on the user's asks): the panel that opens to the right of
// the environment menu when a row's Edit is clicked: its name (Save), its folders with their levels and Remove, Add a
// folder by browsing this machine (the workspace mod's `GET /v1/browse`: the home folder and mounted drives, no hidden
// or secret-looking folders), and Delete, which warns that the environment's chats go too, archived ones included.
// Pure helpers first (tested in utils/tests/web/chat-controls.test.mjs). Written by us (web/PATCHES.md).

import { h, T, MONO, Icon, label11, inputSt } from './chat-ui.js';
import { shortPath, LEVEL_WORD } from './chat-env.js';

const R = () => globalThis.React;
const enc = encodeURIComponent;
export const LEVELS = ['read', 'edit', 'run', 'run_net'];
const SHORT = { read: 'Read', edit: 'Edit', run: 'Run', run_net: 'Net' };
const LEVEL_ORDER = Object.fromEntries(LEVELS.map((l, i) => [l, i]));

/** The workspace mod's environment routes, through the hub's proxy; each resolves to its JSON or throws its error. */
export function envOps(api) {
  const call = (method, path, json, query) => api.callService('workspace', method, path, { ...(json ? { json } : {}), ...(query ? { query } : {}) }).then(r => r.json);
  const E = id => `/v1/environments/${enc(id)}`;
  return {
    create: name => call('POST', '/v1/environments', { name }),
    rename: (id, name) => call('PUT', E(id), { name }),
    remove: id => call('DELETE', E(id)),
    addFolder: (id, path, level = 'read') => call('POST', `${E(id)}/folders`, { path, level }),
    setLevel: (id, fid, level) => call('PATCH', `${E(id)}/folders/${enc(fid)}`, { level }),
    removeFolder: (id, fid) => call('DELETE', `${E(id)}/folders/${enc(fid)}`),
    browse: path => call('GET', '/v1/browse', null, path ? { path } : null),
  };
}
/** An error from the mod as one line: what it says, and its fix. */
export const errLine = e => [e?.detail || e?.message || String(e || 'failed'), e?.data?.fix || e?.fix].filter(Boolean).join(' — ');

/** How many chats an environment holds, open and archived (the agent's `/v1/threads/groups`). */
export async function chatCounts(c, id) {
  const [open, archived] = await Promise.all([c.threadGroups({}), c.threadGroups({ archived: true })]);
  const n = list => (list || []).find(g => g.environment === id)?.count || 0;
  return { open: n(open), archived: n(archived) };
}
/** The warning before deleting an environment: its chats go too, archived ones included. */
export function deleteWarning(env, counts) {
  const total = counts.open + counts.archived;
  const chats = !total ? 'It has no chats.'
    : `This also deletes its ${total} chat${total === 1 ? '' : 's'}${counts.archived ? `, including ${counts.archived} archived` : ''}. Their outputs stay in Outputs.`;
  return { title: `Delete “${env.name}”?`, body: `${chats} The folders and their files are left alone.`, confirmLabel: total ? `Delete it and ${total} chat${total === 1 ? '' : 's'}` : 'Delete', danger: true };
}
/** Deletes an environment's chats (open and archived), then the environment; resolves to the deleted chat ids. */
export async function deleteEnvironment({ c, api, env }) {
  const ids = [];
  for (const archived of [false, true]) {
    for (;;) {
      const list = await c.threads({ environment: env.id, archived, limit: 200 });
      if (!list.length) break;
      for (const t of list) { await c.remove(t.id); ids.push(t.id); }
    }
  }
  await envOps(api).remove(env.id);
  return ids;
}

const segSt = (on, dis) => ({ height: 20, padding: '0 6px', border: 0, borderRadius: 4, font: 'inherit', fontSize: 11, cursor: dis ? 'not-allowed' : 'pointer', opacity: dis ? 0.4 : 1,
  background: on ? T.hov : 'transparent', color: on ? T.tx : T.mut, boxShadow: on ? '0 0 0 1px ' + T.bds : 'none' });
const fieldSt = { ...inputSt, height: 26, fontSize: 12, padding: '0 8px', minWidth: 0 };
const linkSt = { display: 'flex', alignItems: 'center', gap: 6, border: 0, background: 'none', color: T.cy, font: 'inherit', fontSize: 12, cursor: 'pointer', padding: '2px 0' };

/** Picking a folder on this machine: the place, Up, the roots (Home, mounted drives), and the folders in it; Add
 * puts the folder shown, or a listed one, in the environment at the chosen level. */
export function FolderBrowser({ api, onAdd, onClose, busy }) {
  const React = R(), ops = envOps(api);
  const [at, setAt] = React.useState(null), [err, setErr] = React.useState(null), [level, setLevel] = React.useState('read');
  const go = path => ops.browse(path).then(r => { setAt(r); setErr(null); }, e => setErr(errLine(e)));
  React.useEffect(() => { go(null); }, []);
  const row = (key, label, onOpen, add, title) => h('div', { key, className: 'aichat-brow', style: { display: 'flex', alignItems: 'center', gap: 6, minHeight: 26, padding: '0 4px', borderRadius: 5 } },
    h('button', { type: 'button', onClick: onOpen, title, style: { flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 6, border: 0, background: 'none', color: T.tx, font: 'inherit', fontSize: 12, cursor: 'pointer', textAlign: 'left', padding: 0 } },
      h(Icon, { d: 'folder', size: 12 }), h('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, label)),
    add ? h('button', { type: 'button', onClick: add, disabled: busy, style: segSt(false, busy) }, 'Add') : null);
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, borderTop: '1px solid ' + T.bd, paddingTop: 8 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 6 } },
      h('span', { style: { ...label11, flex: 1 } }, 'Add a folder'),
      h('select', { value: level, onChange: e => setLevel(e.target.value), 'aria-label': 'Level of the folder to add', style: { ...fieldSt, width: 84, height: 22, fontSize: 11.5, paddingRight: 2 } },
        LEVELS.map(l => h('option', { key: l, value: l }, LEVEL_WORD[l]))),
      h('button', { type: 'button', 'aria-label': 'Close the folder browser', onClick: onClose, style: { border: 0, background: 'none', color: T.mut, cursor: 'pointer', padding: 2, display: 'flex' } }, h(Icon, { d: 'x', size: 12 }))),
    at ? h('div', { style: { display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' } },
      (at.roots || []).map(r => h('button', { key: r.path, type: 'button', onClick: () => go(r.path), style: segSt(at.path === r.path || at.path.startsWith(r.path + '/')) }, r.name === 'Home' ? 'Home' : shortPath(r.path)))) : null,
    at ? h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, fontFamily: MONO, fontSize: 11.5, color: T.mut, minWidth: 0 } },
      at.parent ? h('button', { type: 'button', onClick: () => go(at.parent), 'aria-label': 'Up one folder', title: 'Up', style: { ...segSt(false), display: 'flex', alignItems: 'center' } }, h(Icon, { d: 'up', size: 11 })) : null,
      h('span', { title: at.path, style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
        at.parent ? shortPath(at.path) : ((at.roots || []).find(r => r.path === at.path)?.name || shortPath(at.path))),
      at.addable ? h('button', { type: 'button', disabled: busy, onClick: () => onAdd(at.path, level), style: segSt(false, busy), title: 'Add this folder' }, 'Add this') : null) : null,
    at ? h('div', { role: 'list', 'aria-label': 'Folders', style: { maxHeight: 180, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 1 } },
      !at.dirs.length ? h('span', { style: { fontSize: 11.5, color: T.dim, padding: 4 } }, 'No folders in here.') : null,
      at.dirs.map(d => row(d.path, d.name, () => go(d.path), d.addable ? () => onAdd(d.path, level) : null, d.path))) : null,
    !at && !err ? h('span', { role: 'status', style: { fontSize: 11.5, color: T.mut } }, 'Loading…') : null,
    err ? h('span', { role: 'alert', style: { fontSize: 11.5, color: T.rd } }, err) : null);
}

/** The edit panel: name and Save, folders with levels and Remove, Add a folder (browse), Delete with its warning. */
export function EnvEditor({ api, c, env, confirm, onChanged, onDeleted, onClose }) {
  const React = R(), ops = envOps(api);
  const [err, setErr] = React.useState(null), [busy, setBusy] = React.useState(false), [name, setName] = React.useState(env?.name || '');
  const [browsing, setBrowsing] = React.useState(false);
  React.useEffect(() => { setName(env?.name || ''); setBrowsing(false); setErr(null); }, [env?.id]);
  if (!env) return null;
  const run = async (f, after) => { setBusy(true); setErr(null); try { const r = await f(); after?.(r); onChanged?.(); } catch (e) { setErr(errLine(e)); } finally { setBusy(false); } };
  const del = async () => {
    try {
      const counts = c?.threadGroups ? await chatCounts(c, env.id) : { open: 0, archived: 0 };
      const w = deleteWarning(env, counts);
      if (!(confirm ? await confirm(w) : globalThis.confirm?.(`${w.title}\n\n${w.body}`))) return;
      setBusy(true);
      const ids = await deleteEnvironment({ c, api, env });
      onDeleted?.(env.id, ids);
    } catch (e) { setErr(errLine(e)); } finally { setBusy(false); }
  };
  const folders = env.folders || [];
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 6 } },
      h('span', { style: { ...label11, flex: 1 } }, 'Edit environment'),
      h('button', { type: 'button', 'aria-label': 'Close the editor', onClick: onClose, style: { border: 0, background: 'none', color: T.mut, cursor: 'pointer', padding: 2, display: 'flex' } }, h(Icon, { d: 'x', size: 12 }))),
    h('form', { onSubmit: e => { e.preventDefault(); if (name.trim() && name.trim() !== env.name) run(() => ops.rename(env.id, name.trim())); }, style: { display: 'flex', gap: 4 } },
      h('input', { value: name, onChange: e => setName(e.target.value), 'aria-label': 'Environment name', style: { ...fieldSt, flex: 1 } }),
      h('button', { type: 'submit', disabled: busy || !name.trim() || name.trim() === env.name, style: segSt(false, busy || !name.trim() || name.trim() === env.name) }, 'Save')),
    h('span', { style: label11 }, 'Folders'),
    folders.map(f => h('div', { key: f.id, style: { display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 } },
      h(Icon, { d: 'folder', size: 12 }),
      h('span', { title: f.capped ? `${f.path} (${f.capped})` : f.path, style: { fontFamily: MONO, fontSize: 11.5, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, shortPath(f.path)),
      h('span', { role: 'group', 'aria-label': `Level of ${f.path}`, style: { display: 'inline-flex', padding: 1, borderRadius: 5, border: '1px solid ' + T.bd, flex: 'none' } },
        LEVELS.map(l => { const dis = f.max_level && LEVEL_ORDER[l] > LEVEL_ORDER[f.max_level];
          return h('button', { key: l, type: 'button', 'aria-pressed': f.level === l ? 'true' : 'false', disabled: busy || dis, title: dis ? `Up to ${LEVEL_WORD[f.max_level]} here${f.capped ? `: ${f.capped}` : ''}` : LEVEL_WORD[l],
            onClick: () => f.level !== l && run(() => ops.setLevel(env.id, f.id, l)), style: segSt(f.level === l, dis) }, SHORT[l]); })),
      h('button', { type: 'button', 'aria-label': `Remove ${f.path} from ${env.name}`, title: 'Remove from this environment (its files are left alone)', disabled: busy,
        onClick: () => run(() => ops.removeFolder(env.id, f.id)), style: { border: 0, background: 'none', color: T.mut, cursor: 'pointer', padding: 2, display: 'flex' } }, h(Icon, { d: 'x', size: 12 })))),
    !folders.length ? h('span', { style: { fontSize: 11.5, color: T.dim } }, 'No folders yet; the agent asks for one when it needs it.') : null,
    browsing ? h(FolderBrowser, { api, busy, onClose: () => setBrowsing(false), onAdd: (path, level) => run(() => ops.addFolder(env.id, path, level)) })
      : h('button', { type: 'button', onClick: () => setBrowsing(true), style: linkSt }, h(Icon, { d: 'plus', size: 12 }), 'Add a folder…'),
    err ? h('span', { role: 'alert', style: { fontSize: 11.5, color: T.rd } }, err) : null,
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, borderTop: '1px solid ' + T.bd, paddingTop: 8 } },
      h('a', { href: '#/s/workspace/environments', style: { fontSize: 11.5, flex: 1 } }, 'Bypass on the Workspace page'),
      env.default ? null : h('button', { type: 'button', onClick: del, disabled: busy, style: { ...segSt(false, busy), color: T.rd } }, 'Delete…')));
}
