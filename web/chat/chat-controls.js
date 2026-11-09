// The row under the message box (plan 42.3, after Claude Code's): the chat's environment, its mode and its model, as
// plain buttons that open small menus (not selects). They were the header's selects and environment chip. The
// environment menu's Edit and New environment open the environment dialog (plan 43.2, chat-envedit.js), which makes,
// renames, fills and deletes environments through the workspace mod. Written by us (web/PATCHES.md).

import { h, T, MONO, Icon, Popover, label11 } from './chat-ui.js';
import { EnvDialog } from './chat-envedit.js';
import { modeChoices, modeTitle, modeOf, MODES } from './chat-header.js';
import { envOf, allowedFolders, shortPath, LEVEL_WORD, projectChipText, projectFolderGroups } from './chat-env.js';

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

/** The model: server → model (plan llm-servers 5.1), in chat-model-menu.js. */
export { ModelMenu } from './chat-model-menu.js';

// ---------- environments from the chat (plan 42.4; the editor is chat-envedit.js) ----------
const envRowSt = on => ({ display: 'flex', alignItems: 'center', gap: 6, minHeight: 28, padding: '0 4px 0 8px', borderRadius: 6, background: on ? T.tcy : 'transparent',
  boxShadow: on ? 'inset 0 0 0 1px ' + T.cy : 'none' });
const quietBtn = { height: 22, padding: '0 7px', border: '1px solid transparent', borderRadius: 5, background: 'transparent', color: T.mut, font: 'inherit', fontSize: 11.5, cursor: 'pointer' };
export const ENV_MENU_W = 250;

/** The environment: the workspace folders this chat may use (plan 34). The menu (compact) lists the environments: a
 * click picks one for this chat; **Edit** on a row (not None) and **New environment** open the dialog (plan 43.2,
 * chat-envedit.js). Without the workspace mod, no button. */
export function EnvMenu({ api, c, thread, envs, value, onChange, stamp = 0, onEnvsChanged, confirm, onDeleted }) {
  const React = R(), [open, setOpen] = React.useState(false), [grants, setGrants] = React.useState([]);
  const [dialog, setDialog] = React.useState(null);               // {env} to edit, {env: null} for New environment
  const tid = thread?.id || null;
  React.useEffect(() => {
    if (!tid || !api?.listGrants) { setGrants([]); return; }
    api.listGrants({ thread: tid }).then(g => setGrants(allowedFolders(g, tid)), () => setGrants([]));
  }, [tid, stamp, open]);
  if (!envs) return null;
  const env = envOf(envs, value);
  const revoke = async g => { try { await api.revokeGrant(g.grant); setGrants(l => l.filter(x => x.grant !== g.grant)); } catch { /* shown as still there */ } };
  const openDialog = e => { setOpen(false); setDialog({ env: e }); };
  return h('span', { style: { position: 'relative', flex: 'none' } },
    h(Control, { icon: 'home', label: (env?.name || 'No environment') + (grants.length ? ` +${grants.length}` : ''), title: 'Environment: the workspace folders this chat can use',
      ariaLabel: `Environment: ${env?.name || 'none'}`, open, onClick: () => setOpen(!open) }),
    h(Popover, { open, onClose: () => setOpen(false), place: 'up-left', width: ENV_MENU_W, label: 'Environment', style: { gap: 4, padding: 6 } },
      h('span', { style: { ...label11, padding: '2px 4px' } }, 'Environment'),
      h('div', { role: 'menu', 'aria-label': 'Environments', style: { display: 'flex', flexDirection: 'column', gap: 1 } },
        envs.map(e => h('div', { key: e.id, className: 'aichat-envrow', style: envRowSt(e.id === env?.id) },
          h('button', { type: 'button', role: 'menuitemradio', 'aria-checked': e.id === env?.id ? 'true' : 'false', onClick: () => { if (e.id !== env?.id) onChange(e.id); },
            title: (e.folders || []).map(f => f.path).join('\n') || (e.none ? 'No folders' : 'No folders yet'),
            style: { flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 6, height: 28, border: 0, background: 'none', color: T.tx, font: 'inherit', fontSize: 12.5, cursor: 'pointer', textAlign: 'left', padding: 0 } },
            h(Icon, { d: 'home', size: 12 }), h('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontWeight: e.id === env?.id ? 500 : 400 } }, e.name),
            h('span', { style: { fontSize: 11, color: T.dim, flex: 'none' } }, (e.folders || []).length)),
          e.none || !api?.callService ? null : h('button', { type: 'button', className: 'aichat-quiet', 'aria-label': `Edit ${e.name}`, onClick: () => openDialog(e), style: quietBtn }, 'Edit')))),
      api?.callService ? h('button', { type: 'button', onClick: () => openDialog(null), style: { display: 'flex', alignItems: 'center', gap: 6, height: 26, padding: '0 8px', border: 0, borderRadius: 6, background: 'none', color: T.mut, font: 'inherit', fontSize: 12, cursor: 'pointer', textAlign: 'left' } },
        h(Icon, { d: 'plus', size: 12 }), 'New environment') : null,
      env?.none ? h('span', { style: { fontSize: 11, color: T.dim, padding: '0 8px', lineHeight: 1.35 } }, 'None has no folders: the agent asks before it reads one, for this chat only.') : null,
      grants.length ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 3, borderTop: '1px solid ' + T.bd, padding: '6px 4px 0' } },
        h('span', { style: label11 }, 'Allowed in this chat'),
        grants.map(g => h('div', { key: g.grant, style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, minWidth: 0 } },
          h(Icon, { d: 'folder', size: 12 }),
          h('span', { title: g.path, style: { fontFamily: MONO, fontSize: 11.5, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, shortPath(g.path)),
          h('span', { style: { fontSize: 11, color: T.mut } }, LEVEL_WORD.read),
          h('button', { type: 'button', onClick: () => revoke(g), title: 'Take it back: this chat asks again', 'aria-label': `Stop allowing ${g.path} in this chat`,
            style: { border: 0, background: 'none', color: T.mut, cursor: 'pointer', padding: 2, display: 'flex' } }, h(Icon, { d: 'x', size: 12 }))))) : null),
    dialog ? h(EnvDialog, { key: dialog.env?.id || 'new', api, c, env: dialog.env, confirm, onClose: () => setDialog(null),
      onSaved: async (id, created) => { await onEnvsChanged?.(); if (created && id) onChange(id); },
      onDeleted: (id, ids) => { onEnvsChanged?.(); onDeleted?.(id, ids); if (id === env?.id) onChange('none'); } }) : null);
}

/** A project chat's chip (plan projects 5.3), in the environment's place: the project's name; its menu opens the project's
 * page, lists the folders the chat can use (the project's environments, then its own folders) and, for a chat already
 * made, offers Remove from project. */
export function ProjectMenu({ c, settings, envs, onRemove }) {
  const React = R(), [open, setOpen] = React.useState(false), [p, setP] = React.useState(null), [own, setOwn] = React.useState([]);
  const pid = settings?.project || null;
  React.useEffect(() => {
    if (!pid || !c?.project) return;
    c.project(pid).then(setP, () => setP(null));
    c.projectFolders?.(pid).then(setOwn, () => setOwn([]));
  }, [pid, open]);
  if (!pid) return null;
  const groups = projectFolderGroups(p, envs, own);
  return h('span', { style: { position: 'relative', flex: 'none' } },
    h(Control, { icon: 'folder', label: projectChipText(p, pid), title: 'Project: its instructions, files, pages and folders apply to this chat',
      ariaLabel: `Project: ${projectChipText(p, pid)}`, open, onClick: () => setOpen(!open) }),
    h(Popover, { open, onClose: () => setOpen(false), place: 'up-left', width: ENV_MENU_W, label: 'Project', style: { gap: 4, padding: 6 } },
      h('span', { style: { ...label11, padding: '2px 4px' } }, 'Project'),
      h('a', { href: '#/chat/projects/' + encodeURIComponent(pid), onClick: () => setOpen(false), style: { display: 'flex', alignItems: 'center', gap: 6, padding: '4px 6px', fontSize: 12.5, fontWeight: 500 } },
        h(Icon, { d: 'folder', size: 12 }), p?.name || pid, h('span', { style: { marginLeft: 'auto', fontSize: 11.5, fontWeight: 400 } }, 'Open project')),
      groups.length ? groups.map(g => h('div', { key: g.id, style: { display: 'flex', flexDirection: 'column', gap: 1, padding: '2px 6px' } },
        h('span', { style: { fontSize: 11.5, color: T.mut } }, g.name),
        g.folders.length ? g.folders.slice(0, 6).map(f => h('span', { key: f.path, title: f.path, style: { fontFamily: MONO, fontSize: 11, color: T.mut, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } },
          `${shortPath(f.path)} · ${LEVEL_WORD[f.level] || f.level}`)) : h('span', { style: { fontSize: 11, color: T.dim } }, 'No folders'),
        g.folders.length > 6 ? h('span', { style: { fontSize: 11, color: T.dim } }, `and ${g.folders.length - 6} more`) : null))
        : h('span', { style: { fontSize: 11.5, color: T.dim, padding: '0 6px' } }, 'The project has no folders.'),
      onRemove ? h('button', { type: 'button', onClick: () => { setOpen(false); onRemove(); }, style: { display: 'flex', alignItems: 'center', gap: 6, height: 28, padding: '0 8px', marginTop: 2,
        border: 0, borderTop: '1px solid ' + T.bd, background: 'none', color: T.tx, font: 'inherit', fontSize: 12.5, cursor: 'pointer', textAlign: 'left' } }, h(Icon, { d: 'x', size: 12 }), 'Remove from project') : null));
}

/** The row: environment and mode on the left, the model on the right. */
export function ControlsRow({ env, mode, model }) {
  return h('div', { role: 'toolbar', 'aria-label': 'Chat settings', style: { display: 'flex', alignItems: 'center', gap: 2, padding: '5px 2px 0', minWidth: 0, flexWrap: 'wrap' } },
    env || null, mode || null, h('span', { style: { flex: 1 } }), model || null);
}
