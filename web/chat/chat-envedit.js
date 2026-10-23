// The environment dialog (plan 43.2, as Claude Code's; the user's ask after 42.4): New environment and Edit open it
// over the page. It keeps its changes (the name, folders added or removed, their levels) until Create or Save; Add
// folder… opens the desktop's own folder chooser at `/` (the workspace mod's `POST /v1/pick-folder`, picker.py), or
// takes a typed path when there's none; Delete… warns that the environment's chats go too, archived ones included.
// Pure helpers first (tested in utils/tests/web/chat-controls.test.mjs). Written by us (web/PATCHES.md).

import { h, T, MONO, Icon, label11, inputSt, SHADOW, ON_ACC } from './chat-ui.js';
import { shortPath, LEVEL_WORD } from './chat-env.js';

const R = () => globalThis.React;
const enc = encodeURIComponent;
export const LEVELS = ['read', 'edit', 'run', 'run_net'];
const SHORT = { read: 'Read', edit: 'Edit', run: 'Run', run_net: 'Net' };
const LEVEL_ORDER = Object.fromEntries(LEVELS.map((l, i) => [l, i]));

/** The workspace mod's environment routes, through the hub's proxy; each resolves to its JSON or throws its error. */
export function envOps(api) {
  const call = (method, path, json) => api.callService('workspace', method, path, json ? { json } : {}).then(r => r.json);
  const E = id => `/v1/environments/${enc(id)}`;
  return {
    create: name => call('POST', '/v1/environments', { name }),
    rename: (id, name) => call('PUT', E(id), { name }),
    remove: id => call('DELETE', E(id)),
    addFolder: (id, path, level = 'read') => call('POST', `${E(id)}/folders`, { path, level }),
    setLevel: (id, fid, level) => call('PATCH', `${E(id)}/folders/${enc(fid)}`, { level }),
    removeFolder: (id, fid) => call('DELETE', `${E(id)}/folders/${enc(fid)}`),
    pick: (start = '/') => call('POST', '/v1/pick-folder', { start, title: 'Add a folder to the environment' }),
  };
}
/** An error from the mod as one line: what it says, and its fix. */
export const errLine = e => [e?.detail || e?.message || String(e || 'failed'), e?.data?.fix || e?.fix].filter(Boolean).join(' — ');

/** What Save does to `env` (null: Create) to make it `draft` ({name, folders: [{id?, path, level}]}), in order:
 * create or rename, then the folders removed, added and given another level. */
export function planSave(env, draft) {
  const name = (draft.name || '').trim(), steps = [];
  if (!env) {
    steps.push(['create', name]);
    for (const f of draft.folders) steps.push(['addFolder', f.path, f.level || 'read']);
    return steps;
  }
  if (name && name !== env.name) steps.push(['rename', name]);
  const kept = new Set(draft.folders.filter(f => f.id).map(f => f.id));
  for (const f of env.folders || []) if (!kept.has(f.id)) steps.push(['removeFolder', f.id]);
  for (const f of draft.folders) if (!f.id) steps.push(['addFolder', f.path, f.level || 'read']);
  for (const f of draft.folders) {
    const was = f.id && (env.folders || []).find(x => x.id === f.id);
    if (was && was.level !== f.level) steps.push(['setLevel', f.id, f.level]);
  }
  return steps;
}
/** Runs `planSave`'s steps; resolves to the environment's id (a new one's from Create). */
export async function saveEnv(ops, env, draft) {
  let id = env?.id;
  for (const [op, ...args] of planSave(env, draft)) {
    if (op === 'create') id = (await ops.create(args[0])).id;
    else await ops[op](id, ...args);
  }
  return id;
}

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

const segSt = (on, dis) => ({ height: 22, padding: '0 7px', border: 0, borderRadius: 4, font: 'inherit', fontSize: 11.5, cursor: dis ? 'not-allowed' : 'pointer', opacity: dis ? 0.4 : 1,
  background: on ? T.hov : 'transparent', color: on ? T.tx : T.mut, boxShadow: on ? '0 0 0 1px ' + T.bds : 'none' });
const fieldSt = { ...inputSt, height: 30, fontSize: 13, padding: '0 10px', minWidth: 0 };
const btnSt = (kind, dis) => ({ height: 30, padding: '0 14px', borderRadius: 7, font: 'inherit', fontSize: 12.5, fontWeight: 500, cursor: dis ? 'not-allowed' : 'pointer', opacity: dis ? 0.5 : 1,
  border: '1px solid ' + (kind === 'pri' ? 'transparent' : kind === 'danger' ? T.rd : T.bds), background: kind === 'pri' ? T.acc : 'transparent',
  color: kind === 'pri' ? ON_ACC : kind === 'danger' ? T.rd : T.tx });

/** The dialog. `env`: the one to edit, or null for New environment. */
export function EnvDialog({ api, c, env, confirm, onClose, onSaved, onDeleted }) {
  const React = R(), ops = envOps(api);
  const [name, setName] = React.useState(env?.name || ''), [folders, setFolders] = React.useState(() => (env?.folders || []).map(f => ({ ...f })));
  const [err, setErr] = React.useState(null), [busy, setBusy] = React.useState(false), [picking, setPicking] = React.useState(false);
  const [typed, setTyped] = React.useState(null);               // a path box, when there's no chooser
  React.useEffect(() => {
    const k = e => { if (e.key === 'Escape' && !busy) { e.stopPropagation(); onClose(); } };
    window.addEventListener('keydown', k, true);
    return () => window.removeEventListener('keydown', k, true);
  }, [busy]);
  const addPath = (path, addable = true, why = null) => {
    if (!addable) { setErr(why || `${path} can't be added`); return; }
    if (folders.some(f => f.path === path)) { setErr(`${shortPath(path)} is already here`); return; }
    setErr(null); setFolders(l => [...l, { path, level: 'read' }]);
  };
  const pick = async () => {
    setErr(null); setPicking(true);
    try { const r = await ops.pick('/'); if (!r.cancelled) addPath(r.path, r.addable, r.why); }
    catch (e) { if (e?.code === 'no_picker' || e?.status === 501) setTyped(''); else setErr(errLine(e)); }
    finally { setPicking(false); }
  };
  const save = async () => {
    setBusy(true); setErr(null);
    try { const id = await saveEnv(ops, env, { name, folders }); onSaved?.(id, !env); onClose(); }
    catch (e) { setErr(errLine(e)); onSaved?.(env?.id, false); }
    finally { setBusy(false); }
  };
  const del = async () => {
    try {
      const counts = c?.threadGroups ? await chatCounts(c, env.id) : { open: 0, archived: 0 };
      const w = deleteWarning(env, counts);
      if (!(confirm ? await confirm(w) : globalThis.confirm?.(`${w.title}\n\n${w.body}`))) return;
      setBusy(true);
      const ids = await deleteEnvironment({ c, api, env });
      onDeleted?.(env.id, ids); onClose();
    } catch (e) { setErr(errLine(e)); } finally { setBusy(false); }
  };
  const can = !busy && !picking && !!name.trim() && (!env || planSave(env, { name, folders }).length > 0);
  return h('div', { role: 'presentation', onMouseDown: e => { if (e.target === e.currentTarget && !busy) onClose(); },
    style: { position: 'fixed', inset: 0, zIndex: 70, background: 'rgba(0,0,0,.5)', display: 'grid', placeItems: 'center', padding: 16 } },
    h('div', { role: 'dialog', 'aria-modal': 'true', 'aria-label': env ? `Edit ${env.name}` : 'New environment',
      style: { width: 'min(540px, 100%)', maxHeight: 'min(80vh, 640px)', overflow: 'auto', background: T.card, border: '1px solid ' + T.bds, borderRadius: 12, boxShadow: SHADOW,
        padding: 18, display: 'flex', flexDirection: 'column', gap: 14 } },
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
        h('h2', { style: { margin: 0, fontSize: 15, fontWeight: 600, flex: 1 } }, env ? 'Edit environment' : 'New environment'),
        h('button', { type: 'button', 'aria-label': 'Close', onClick: onClose, disabled: busy, style: { border: 0, background: 'none', color: T.mut, cursor: 'pointer', padding: 4, display: 'flex' } }, h(Icon, { d: 'x', size: 14 }))),
      h('label', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
        h('span', { style: label11 }, 'Name'),
        h('input', { autoFocus: !env, value: name, onChange: e => setName(e.target.value), placeholder: 'e.g. Grants', 'aria-label': 'Environment name', style: fieldSt,
          onKeyDown: e => { if (e.key === 'Enter' && can) save(); } })),
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
        h('span', { style: label11 }, 'Folders'),
        h('span', { style: { fontSize: 12, color: T.mut } }, 'The folders a chat in this environment can use, each at its level. Anything else, the agent asks for first.'),
        folders.map((f, i) => h('div', { key: f.id || f.path, style: { display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', borderRadius: 7, background: T.inset, minWidth: 0 } },
          h(Icon, { d: 'folder', size: 13 }),
          h('span', { title: f.capped ? `${f.path} (${f.capped})` : f.path, style: { fontFamily: MONO, fontSize: 12, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, f.path),
          h('span', { role: 'group', 'aria-label': `Level of ${f.path}`, style: { display: 'inline-flex', padding: 1, borderRadius: 6, border: '1px solid ' + T.bd, flex: 'none' } },
            LEVELS.map(l => { const dis = f.max_level && LEVEL_ORDER[l] > LEVEL_ORDER[f.max_level];
              return h('button', { key: l, type: 'button', 'aria-pressed': f.level === l ? 'true' : 'false', disabled: busy || dis, title: dis ? `Up to ${LEVEL_WORD[f.max_level]} here${f.capped ? `: ${f.capped}` : ''}` : LEVEL_WORD[l],
                onClick: () => setFolders(list => list.map((x, j) => (j === i ? { ...x, level: l } : x))), style: segSt(f.level === l, dis) }, SHORT[l]); })),
          h('button', { type: 'button', 'aria-label': `Remove ${f.path}`, title: 'Remove from this environment (its files are left alone)', disabled: busy,
            onClick: () => setFolders(list => list.filter((_, j) => j !== i)), style: { border: 0, background: 'none', color: T.mut, cursor: 'pointer', padding: 2, display: 'flex' } }, h(Icon, { d: 'x', size: 13 })))),
        !folders.length ? h('span', { style: { fontSize: 12, color: T.dim } }, 'No folders yet.') : null,
        typed != null
          ? h('form', { onSubmit: e => { e.preventDefault(); if (typed.trim()) { addPath(typed.trim()); setTyped(''); } }, style: { display: 'flex', gap: 6 } },
              h('input', { autoFocus: true, value: typed, onChange: e => setTyped(e.target.value), placeholder: '/full/path/to/folder', 'aria-label': 'Folder path', style: { ...fieldSt, flex: 1, fontFamily: MONO, fontSize: 12 } }),
              h('button', { type: 'submit', disabled: !typed.trim(), style: btnSt('sec', !typed.trim()) }, 'Add'))
          : h('button', { type: 'button', onClick: pick, disabled: busy || picking, style: { ...btnSt('sec', busy || picking), alignSelf: 'flex-start', display: 'inline-flex', alignItems: 'center', gap: 6 } },
              h(Icon, { d: 'plus', size: 12 }), picking ? 'Choose a folder in the window that opened…' : 'Add folder…'),
        typed != null ? h('span', { style: { fontSize: 11.5, color: T.dim } }, 'No folder chooser on this machine (install zenity or kdialog): type the folder’s full path.') : null),
      err ? h('span', { role: 'alert', style: { fontSize: 12, color: T.rd } }, err) : null,
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, borderTop: '1px solid ' + T.bd, paddingTop: 12 } },
        env && !env.default && !env.none ? h('button', { type: 'button', onClick: del, disabled: busy, style: btnSt('danger', busy) }, 'Delete…') : null,
        h('span', { style: { flex: 1 } }),
        h('button', { type: 'button', onClick: onClose, disabled: busy, style: btnSt('sec', busy) }, 'Cancel'),
        h('button', { type: 'button', onClick: save, disabled: !can, style: btnSt('pri', !can) }, busy ? 'Saving…' : env ? 'Save' : 'Create'))));
}
