// The row under the message box (plan 42.3, after Claude Code's): the chat's environment, its mode and its model, as
// plain buttons that open small menus (not selects). They were the header's selects and environment chip. The
// environment menu also makes, renames and fills environments through the workspace mod (plan 42.4: EnvEditor,
// envOps), so the Workspace page is needed only for Bypass and deleting. Written by us (web/PATCHES.md).

import { h, T, MONO, Icon, Popover, label11, inputSt } from './chat-ui.js';
import { modeChoices, modeTitle, modeOf, modelLabel, MODES } from './chat-header.js';
import { envOf, allowedFolders, shortPath, LEVEL_WORD } from './chat-env.js';

const R = () => globalThis.React;

/** A control: an icon and a word, a quiet button until hovered (CONTROLS_CSS). */
export function Control({ icon, label, title, open, onClick, ariaLabel }) {
  return h('button', { type: 'button', className: 'aichat-ctl', onClick, title, 'aria-label': ariaLabel || title, 'aria-haspopup': 'menu', 'aria-expanded': open ? 'true' : 'false',
    style: { display: 'inline-flex', alignItems: 'center', gap: 6, height: 26, padding: '0 8px', border: 0, borderRadius: 6, background: open ? T.hov : 'transparent',
      color: open ? T.tx : T.mut, font: 'inherit', fontSize: 12, cursor: 'pointer', maxWidth: 220, minWidth: 0 } },
    icon ? h('span', { style: { display: 'flex', flex: 'none' } }, h(Icon, { d: icon, size: 13 })) : null,
    h('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, label));
}
export const CONTROLS_CSS = `.aichat-ctl:hover{background:var(--hov,#161C28)!important;color:var(--tx,#E6EAF2)!important}`;

const rowSt = (on, dis) => ({ display: 'flex', flexDirection: 'column', gap: 2, width: '100%', textAlign: 'left', padding: '7px 9px', borderRadius: 7, cursor: dis ? 'not-allowed' : 'pointer',
  font: 'inherit', color: T.tx, border: '1px solid ' + (on ? T.cy : 'transparent'), background: on ? T.tcy : 'transparent', opacity: dis ? 0.55 : 1 });

/** The mode: Plan · Manual · Accept edits · Auto · Bypass, each with its one line (modeChoices' rules). */
export function ModeMenu({ value, onChange, bypass = false, judge = null }) {
  const React = R(), [open, setOpen] = React.useState(false), cur = modeOf(value);
  const label = MODES.find(m => m[0] === cur)?.[1] || 'Manual';
  return h('span', { style: { position: 'relative', flex: 'none' } },
    h(Control, { icon: 'shield', label, title: modeTitle(value, judge), ariaLabel: `Mode: ${label}`, open, onClick: () => setOpen(!open) }),
    h(Popover, { open, onClose: () => setOpen(false), place: 'up-left', width: 330, label: 'Mode', style: { gap: 2, padding: 6 } },
      modeChoices(value, bypass, judge).map(m => h('button', { key: m.key, type: 'button', role: 'menuitemradio', 'aria-checked': m.key === cur ? 'true' : 'false', disabled: m.disabled, title: m.why,
        onClick: () => { setOpen(false); if (m.key !== cur) onChange(m.key); }, style: rowSt(m.key === cur, m.disabled) },
        h('span', { style: { fontSize: 12.5, fontWeight: 500 } }, m.label),
        h('span', { style: { fontSize: 11.5, color: T.mut, lineHeight: 1.35 } }, m.desc)))));
}

/** The model, from the relay, each with its context window. */
export function ModelMenu({ models, value, onChange }) {
  const React = R(), [open, setOpen] = React.useState(false);
  const list = models?.models || [], cur = value || models?.default || '';
  return h('span', { style: { position: 'relative', flex: 'none' } },
    h(Control, { icon: 'chat', label: cur || 'No model', title: 'Model (from the relay) and its context window', ariaLabel: `Model: ${cur || 'none'}`, open, onClick: () => setOpen(!open) }),
    h(Popover, { open, onClose: () => setOpen(false), place: 'up-right', width: 300, label: 'Model', style: { gap: 2, padding: 6 } },
      !list.length ? h('span', { style: { fontSize: 12, color: T.mut, padding: 6 } }, 'No models from the relay yet.') : null,
      list.map(m => h('button', { key: m.id, type: 'button', role: 'menuitemradio', 'aria-checked': m.id === cur ? 'true' : 'false', onClick: () => { setOpen(false); if (m.id !== cur) onChange(m.id); }, style: rowSt(m.id === cur) },
        h('span', { style: { fontSize: 12.5, fontWeight: 500, fontFamily: MONO } }, m.id + (m.id === models.default ? ' (default)' : '')),
        h('span', { style: { fontSize: 11.5, color: T.mut } }, modelLabel(m).slice(m.id.length).replace(/^ · /, '') || ' ')))));
}

// ---------- environments from the chat (plan 42.4) ----------
const enc = encodeURIComponent;
export const LEVELS = ['read', 'edit', 'run', 'run_net'];
/** The workspace mod's environment routes, through the hub's proxy; each resolves to its JSON or throws its error. */
export function envOps(api) {
  const call = (method, path, json) => api.callService('workspace', method, path, json ? { json } : {}).then(r => r.json);
  const E = id => `/v1/environments/${enc(id)}`;
  return {
    create: name => call('POST', '/v1/environments', { name }),
    rename: (id, name) => call('PUT', E(id), { name }),
    addFolder: (id, path, level = 'read') => call('POST', `${E(id)}/folders`, { path, level }),
    setLevel: (id, fid, level) => call('PATCH', `${E(id)}/folders/${enc(fid)}`, { level }),
    removeFolder: (id, fid) => call('DELETE', `${E(id)}/folders/${enc(fid)}`),
  };
}
/** An error from the mod as one line: what it says, and its fix. */
export const errLine = e => [e?.detail || e?.message || String(e || 'failed'), e?.data?.fix || e?.fix].filter(Boolean).join(' — ');
const LEVEL_ORDER = Object.fromEntries(LEVELS.map((l, i) => [l, i]));
const segSt = (on, dis) => ({ height: 20, padding: '0 6px', border: 0, borderRadius: 4, font: 'inherit', fontSize: 11, cursor: dis ? 'not-allowed' : 'pointer', opacity: dis ? 0.4 : 1,
  background: on ? T.hov : 'transparent', color: on ? T.tx : T.mut, boxShadow: on ? '0 0 0 1px ' + T.bds : 'none' });
const fieldSt = { ...inputSt, height: 26, fontSize: 12, padding: '0 8px', minWidth: 0 };

/** The chosen environment's name and folders, and New environment: all saved in the workspace mod at once. */
export function EnvEditor({ api, env, onChanged, onCreated }) {
  const React = R(), ops = envOps(api);
  const [err, setErr] = React.useState(null), [busy, setBusy] = React.useState(false), [rename, setRename] = React.useState(null);
  const [path, setPath] = React.useState(''), [level, setLevel] = React.useState('read'), [fresh, setFresh] = React.useState(null);
  const run = async (f, after) => { setBusy(true); setErr(null); try { const r = await f(); after?.(r); onChanged?.(); } catch (e) { setErr(errLine(e)); } finally { setBusy(false); } };
  const folders = env?.folders || [], none = !!env?.none;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, borderTop: '1px solid ' + T.bd, paddingTop: 8 } },
    none ? h('span', { style: { fontSize: 11.5, color: T.mut } }, 'None: no folders. The agent asks before it reads any folder, and you allow it in this chat only.') : null,
    env && !none ? h('div', { style: { display: 'flex', alignItems: 'center', gap: 6 } },
      rename != null
        ? h('input', { autoFocus: true, value: rename, 'aria-label': 'Environment name', onChange: e => setRename(e.target.value), style: { ...fieldSt, flex: 1 },
            onKeyDown: e => { if (e.key === 'Enter' && rename.trim()) run(() => ops.rename(env.id, rename.trim()), () => setRename(null)); if (e.key === 'Escape') { e.stopPropagation(); setRename(null); } } })
        : h('span', { style: { ...label11, flex: 1 } }, `Folders in ${env.name}`),
      rename == null ? h('button', { type: 'button', onClick: () => setRename(env.name), style: segSt(false), title: 'Rename this environment' }, 'Rename') : null) : null,
    env && !none ? folders.map(f => h('div', { key: f.id, style: { display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 } },
      h(Icon, { d: 'folder', size: 12 }),
      h('span', { title: f.capped ? `${f.path} (${f.capped})` : f.path, style: { fontFamily: MONO, fontSize: 11.5, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, shortPath(f.path)),
      h('span', { role: 'group', 'aria-label': `Level of ${f.path}`, style: { display: 'inline-flex', padding: 1, borderRadius: 5, border: '1px solid ' + T.bd, flex: 'none' } },
        LEVELS.map(l => { const dis = f.max_level && LEVEL_ORDER[l] > LEVEL_ORDER[f.max_level];
          return h('button', { key: l, type: 'button', 'aria-pressed': f.level === l ? 'true' : 'false', disabled: busy || dis, title: dis ? `Up to ${LEVEL_WORD[f.max_level]} here${f.capped ? `: ${f.capped}` : ''}` : LEVEL_WORD[l],
            onClick: () => f.level !== l && run(() => ops.setLevel(env.id, f.id, l)), style: segSt(f.level === l, dis) }, { read: 'Read', edit: 'Edit', run: 'Run', run_net: 'Net' }[l]); })),
      h('button', { type: 'button', 'aria-label': `Remove ${f.path} from ${env.name}`, title: 'Remove from this environment (its files are left alone)', disabled: busy,
        onClick: () => run(() => ops.removeFolder(env.id, f.id)), style: { border: 0, background: 'none', color: T.mut, cursor: 'pointer', padding: 2, display: 'flex' } }, h(Icon, { d: 'x', size: 12 })))) : null,
    env && !none && !folders.length ? h('span', { style: { fontSize: 11.5, color: T.dim } }, 'No folders yet: add one below, or the agent asks for one when it needs it.') : null,
    env && !none ? h('form', { onSubmit: e => { e.preventDefault(); if (path.trim()) run(() => ops.addFolder(env.id, path.trim(), level), () => setPath('')); }, style: { display: 'flex', gap: 4, alignItems: 'center' } },
      h('input', { value: path, onChange: e => setPath(e.target.value), placeholder: '~/path/to/folder', 'aria-label': 'Folder to add', style: { ...fieldSt, flex: 1, fontFamily: MONO } }),
      h('select', { value: level, onChange: e => setLevel(e.target.value), 'aria-label': 'Its level', style: { ...fieldSt, width: 74, paddingRight: 2 } },
        LEVELS.map(l => h('option', { key: l, value: l }, LEVEL_WORD[l]))),
      h('button', { type: 'submit', disabled: busy || !path.trim(), style: segSt(false, busy || !path.trim()) }, 'Add')) : null,
    fresh == null
      ? h('button', { type: 'button', onClick: () => setFresh(''), style: { display: 'flex', alignItems: 'center', gap: 6, border: 0, background: 'none', color: T.cy, font: 'inherit', fontSize: 12, cursor: 'pointer', padding: '2px 0' } },
          h(Icon, { d: 'plus', size: 12 }), 'New environment')
      : h('form', { onSubmit: e => { e.preventDefault(); if (fresh.trim()) run(() => ops.create(fresh.trim()), r => { setFresh(null); onCreated?.(r.id); }); }, style: { display: 'flex', gap: 4 } },
          h('input', { autoFocus: true, value: fresh, onChange: e => setFresh(e.target.value), placeholder: 'Name, e.g. Grants', 'aria-label': 'New environment name', style: { ...fieldSt, flex: 1 },
            onKeyDown: e => { if (e.key === 'Escape') { e.stopPropagation(); setFresh(null); } } }),
          h('button', { type: 'submit', disabled: busy || !fresh.trim(), style: segSt(false, busy || !fresh.trim()) }, 'Create')),
    err ? h('span', { role: 'alert', style: { fontSize: 11.5, color: T.rd } }, err) : null);
}

/** The environment: the workspace folders this chat may use (plan 34), picked, made and changed here (plan 42.4);
 * without the workspace mod, no button. */
export function EnvMenu({ api, thread, envs, value, onChange, stamp = 0, onEnvsChanged }) {
  const React = R(), [open, setOpen] = React.useState(false), [grants, setGrants] = React.useState([]);
  const tid = thread?.id || null;
  React.useEffect(() => {
    if (!tid || !api?.listGrants) { setGrants([]); return; }
    api.listGrants({ thread: tid }).then(g => setGrants(allowedFolders(g, tid)), () => setGrants([]));
  }, [tid, stamp, open]);
  if (!envs) return null;
  const env = envOf(envs, value);
  const revoke = async g => { try { await api.revokeGrant(g.grant); setGrants(l => l.filter(x => x.grant !== g.grant)); } catch { /* shown as still there */ } };
  return h('span', { style: { position: 'relative', flex: 'none' } },
    h(Control, { icon: 'home', label: (env?.name || 'No environment') + (grants.length ? ` +${grants.length}` : ''), title: 'Environment: the workspace folders this chat can use',
      ariaLabel: `Environment: ${env?.name || 'none'}`, open, onClick: () => setOpen(!open) }),
    h(Popover, { open, onClose: () => setOpen(false), place: 'up-left', width: 400, label: 'Environment' },
      h('span', { style: label11 }, 'Environment'),
      h('div', { role: 'menu', 'aria-label': 'Environments', style: { display: 'flex', flexDirection: 'column', gap: 2 } },
        envs.map(e => h('button', { key: e.id, type: 'button', role: 'menuitemradio', 'aria-checked': e.id === env?.id ? 'true' : 'false',
          onClick: () => { if (e.id !== env?.id) onChange(e.id); }, style: rowSt(e.id === env?.id) },
          h('span', { style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, fontWeight: 500 } }, h(Icon, { d: 'home', size: 12 }), e.name,
            h('span', { style: { marginLeft: 'auto', fontSize: 11.5, color: T.mut, fontWeight: 400 } }, `${(e.folders || []).length} folder${(e.folders || []).length === 1 ? '' : 's'}`))))),
      api?.callService ? h(EnvEditor, { api, env, onChanged: () => onEnvsChanged?.(), onCreated: id => { onEnvsChanged?.(); onChange(id); } }) : null,
      grants.length ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4, borderTop: '1px solid ' + T.bd, paddingTop: 8 } },
        h('span', { style: label11 }, 'Allowed in this chat'),
        grants.map(g => h('div', { key: g.grant, style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, minWidth: 0 } },
          h(Icon, { d: 'folder', size: 12 }),
          h('span', { title: g.path, style: { fontFamily: MONO, fontSize: 11.5, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, shortPath(g.path)),
          h('span', { style: { fontSize: 11, color: T.mut } }, LEVEL_WORD.read),
          h('button', { type: 'button', onClick: () => revoke(g), title: 'Take it back: this chat asks again', 'aria-label': `Stop allowing ${g.path} in this chat`,
            style: { border: 0, background: 'none', color: T.mut, cursor: 'pointer', padding: 2, display: 'flex' } }, h(Icon, { d: 'x', size: 12 }))))) : null,
      h('a', { href: '#/s/workspace/environments', onClick: () => setOpen(false), style: { fontSize: 12 } }, 'Bypass and more on the Workspace page…')));
}

/** The row: environment and mode on the left, the model on the right. */
export function ControlsRow({ env, mode, model }) {
  return h('div', { role: 'toolbar', 'aria-label': 'Chat settings', style: { display: 'flex', alignItems: 'center', gap: 2, padding: '5px 2px 0', minWidth: 0, flexWrap: 'wrap' } },
    env || null, mode || null, h('span', { style: { flex: 1 } }), model || null);
}
