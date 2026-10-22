// The chat's environment (plan 34, after Claude's): a chip in the thread header ("⌂ Grants · 2 folders")
// whose menu picks the set of workspace folders this chat works in, lists the folders the user allowed
// in this chat only (each can be taken back), and links to the Workspace page to manage environments.
// Also the folder card's choices: "Allow for this chat" (a folder grant in the hub) and "Add to
// <environment>" (the folder is added to the environment through the workspace mod, then the call runs
// once). The choice is saved in the chat's settings (`settings.environment`); a new chat starts with the
// last one picked in this browser. Pure helpers first (tested in utils/tests/web/environments.test.mjs).
// Written by us (web/PATCHES.md).

import { h, T, MONO, Icon, Popover, label11, getPref, setPref } from './chat-ui.js';

const R = () => globalThis.React;
export const DEFAULT_ENV = 'default';
export const NONE_ENV = 'none';      // built in: no folders (plan 42.5); a new chat's environment until you pick one
export const LAST_ENV = 'aihub.chat.environment';
export const LEVEL_WORD = { read: 'Read', edit: 'Edit', run: 'Run', run_net: 'Run + network' };
const enc = encodeURIComponent;

/** The environment with this id, else Default (a chat without one, or whose one was deleted, uses it). */
export function envOf(envs, id) {
  const list = Array.isArray(envs) ? envs : [];
  return list.find(e => e.id === id) || list.find(e => e.default || e.id === DEFAULT_ENV) || null;
}

/** The chip's words: "Grants · 2 folders", and "+1" for folders allowed in this chat only. */
export function chipText(env, allowed = 0) {
  if (!env) return 'No environment';
  const n = (env.folders || []).length;
  return `${env.name} · ${n} folder${n === 1 ? '' : 's'}${allowed ? ` +${allowed}` : ''}`;
}

/** The folders allowed in this chat (folder grants: kind "folder", key "folder:<path>"), oldest first. */
export function allowedFolders(grants, thread) {
  return (Array.isArray(grants) ? grants : [])
    .filter(g => g && g.kind === 'folder' && String(g.key || '').startsWith('folder:/') && (!thread || g.thread === thread))
    .sort((a, b) => (a.created_ts || 0) - (b.created_ts || 0))
    .map(g => ({ grant: g.id, path: String(g.key).slice(7) }));
}

/** /home/<you>/x → ~/x (for reading only; the mod gets full paths). */
export const shortPath = p => String(p || '').replace(/^\/home\/[^/]+(?=\/|$)/, '~');

/** A new chat's settings: its own environment, else the last one picked in this browser, else None (plan 42.5). */
export function newChatSettings(settings = {}, last = null) {
  return settings.environment ? settings : { ...settings, environment: last || NONE_ENV };
}
export const lastEnv = () => getPref(LAST_ENV, null);
export const rememberEnv = id => setPref(LAST_ENV, id);

/** The folder card's buttons (plan 34): allow for this chat; add to the environment the card names. */
export function folderChoices(ask) {
  const env = ask?.environment;
  return [{ remember: 'thread', label: 'Allow for this chat', primary: true },
    ...(env?.id && env.id !== NONE_ENV ? [{ remember: 'environment', label: `Add to “${env.name || env.id}”` }] : [])];   // None takes no folders
}

/** What the card's choice sends: "environment" adds the folder there first (Read), then allows this call once. */
export async function decideFolder(api, ask, o = {}) {
  if (o.remember !== 'environment') return o;
  if (!api?.callService || !ask?.environment?.id) throw Object.assign(new Error('The workspace mod is needed to add a folder'), { code: 'unavailable' });
  try {
    await api.callService('workspace', 'POST', `/v1/environments/${enc(ask.environment.id)}/folders`, { json: { path: ask.path, level: ask.level || 'read' } });
  } catch (e) { if (e?.code !== 'exists' && e?.status !== 409) throw e; }   // already there: fine
  return { ...o, remember: 'once' };
}

// ---------- the chip and its menu ----------
const rowSt = on => ({ display: 'flex', flexDirection: 'column', gap: 2, width: '100%', textAlign: 'left', padding: '7px 9px', borderRadius: 7, cursor: 'pointer',
  font: 'inherit', color: T.tx, border: '1px solid ' + (on ? T.cy : 'transparent'), background: on ? T.tcy : 'transparent' });

export function EnvChip({ api, thread, value, onChange, stamp = 0, narrow = false }) {
  const React = R(), [open, setOpen] = React.useState(false);
  const [envs, setEnvs] = React.useState(null), [grants, setGrants] = React.useState([]);
  const tid = thread?.id || null;
  const load = () => api?.callService?.('workspace', 'GET', '/v1/environments')
    .then(r => setEnvs(r.json?.environments || []), () => setEnvs(null));
  React.useEffect(() => { load(); }, [open]);
  React.useEffect(() => {
    if (!tid || !api?.listGrants) { setGrants([]); return; }
    api.listGrants({ thread: tid }).then(g => setGrants(allowedFolders(g, tid)), () => setGrants([]));
  }, [tid, stamp, open]);
  if (!envs) return null;                                     // no workspace mod (or it's stopped): no chip
  const env = envOf(envs, value);
  const pick = id => { setOpen(false); if (id !== env?.id) onChange?.(id); };
  const revoke = async g => { try { await api.revokeGrant(g.grant); setGrants(l => l.filter(x => x.grant !== g.grant)); } catch { /* shown as still there */ } };
  return h('span', { style: { position: 'relative', flex: 'none' } },
    h('button', { type: 'button', onClick: () => setOpen(!open), 'aria-haspopup': 'menu', 'aria-expanded': open ? 'true' : 'false',
      title: 'Environment: the workspace folders this chat can use', 'aria-label': 'Environment: ' + chipText(env, grants.length),
      style: { display: 'inline-flex', alignItems: 'center', gap: 6, height: 28, padding: '0 9px', borderRadius: 6, border: '1px solid ' + T.bd, background: T.card,
        color: T.tx, cursor: 'pointer', font: 'inherit', fontSize: 12, maxWidth: narrow ? 150 : 230, minWidth: 0 } },
      h('span', { style: { color: T.mut, display: 'flex', flex: 'none' } }, h(Icon, { d: 'home', size: 13 })),
      h('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, narrow ? env?.name || '—' : chipText(env, grants.length))),
    h(Popover, { open, onClose: () => setOpen(false), width: 320, label: 'Environment' },
      h('span', { style: label11 }, 'Environment'),
      h('div', { role: 'menu', 'aria-label': 'Environments', style: { display: 'flex', flexDirection: 'column', gap: 2 } },
        envs.map(e => h('button', { key: e.id, type: 'button', role: 'menuitemradio', 'aria-checked': e.id === env?.id ? 'true' : 'false', onClick: () => pick(e.id), style: rowSt(e.id === env?.id) },
          h('span', { style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, fontWeight: 500 } }, h(Icon, { d: 'home', size: 12 }), e.name,
            h('span', { style: { marginLeft: 'auto', fontSize: 11.5, color: T.mut, fontWeight: 400 } }, `${(e.folders || []).length} folder${(e.folders || []).length === 1 ? '' : 's'}`)),
          (e.folders || []).slice(0, 4).map(f => h('span', { key: f.id, style: { fontFamily: MONO, fontSize: 11, color: T.mut, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
            `${shortPath(f.path)} · ${LEVEL_WORD[f.level] || f.level}`)),
          (e.folders || []).length > 4 ? h('span', { style: { fontSize: 11, color: T.dim } }, `and ${(e.folders || []).length - 4} more`) : null))),
      grants.length ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4, borderTop: '1px solid ' + T.bd, paddingTop: 8 } },
        h('span', { style: label11 }, 'Allowed in this chat'),
        grants.map(g => h('div', { key: g.grant, style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, minWidth: 0 } },
          h(Icon, { d: 'folder', size: 12 }),
          h('span', { title: g.path, style: { fontFamily: MONO, fontSize: 11.5, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, shortPath(g.path)),
          h('span', { style: { fontSize: 11, color: T.mut } }, 'Read'),
          h('button', { type: 'button', onClick: () => revoke(g), title: 'Take it back: this chat asks again', 'aria-label': `Stop allowing ${g.path} in this chat`,
            style: { border: 0, background: 'none', color: T.mut, cursor: 'pointer', padding: 2, display: 'flex' } }, h(Icon, { d: 'x', size: 12 }))))) : null,
      h('div', { style: { fontSize: 11.5, color: T.mut } }, 'The agent can ask to read another folder you name; you choose this chat only, or the environment.'),
      h('a', { href: '#/s/workspace/environments', onClick: () => setOpen(false), style: { fontSize: 12.5 } }, 'Manage environments…')));
}
