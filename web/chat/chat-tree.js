// Sub-agents in the sidebar (plan agent-workflows 3.2): a chat that started sub-agents gets a chevron on its row, and
// open, its sub-agents fold out under it as a tree (├ └, deeper ones indented), each with its label, a dot while it
// runs, waits for a free slot, waits on a card or failed, and an unread dot once it ended and nobody opened it. Which
// rows are open is kept on the hub (`hub.chat.tree.open`, a list of chat ids). The tree follows the page's
// `agent_child` events (`bus`, from `watchWorkflows`). Pure helpers first (tested in utils/tests/web/chat-agents.test.mjs).
// Written by us (web/PATCHES.md).

import { h, T, Icon } from './chat-ui.js';
import { store } from '../ui-store.js';

const R = () => globalThis.React;
export const OPEN_KEY = 'hub.chat.tree.open';
const enc = encodeURIComponent;

/** A sub-agent's row look: its dot (running, queued, waiting, error), whether it's unread, a word for its state. */
export function childLook(n) {
  const state = ['running', 'queued', 'waiting', 'error'].includes(n.state) ? n.state : null;
  const unread = !n.seen && ['idle', 'error', 'cancelled'].includes(n.state);
  return { label: n.label || n.title || 'Sub-agent', state, unread, write: !!n.write,
    dot: { running: T.acc, queued: T.dim, waiting: T.pu, error: T.rd }[state] || null,
    word: { running: 'running', queued: 'waiting for a free slot', waiting: 'waiting for you', error: 'failed', cancelled: 'stopped' }[n.state] || (unread ? 'finished, new' : 'finished') };
}

/** The tree's rows in order, each with its depth and whether it's the last of its parent's (└) or not (├). */
export function treeRows(tree) {
  const all = tree?.children || [], root = tree?.root?.id, out = [];
  const walk = (pid, depth) => {
    const kids = all.filter(n => n.parent === pid);
    kids.forEach((n, i) => { out.push({ node: n, depth, last: i === kids.length - 1 }); walk(n.id, depth + 1); });
  };
  if (root) walk(root, 0);
  return out;
}

/** Replace (or add) one sub-agent's row from an `agent_child` event; null when the event isn't this tree's. */
export function applyChild(tree, ev) {
  if (!tree || !ev?.child || ev.root !== tree.root?.id) return null;
  const has = tree.children.some(n => n.id === ev.child.id);
  const children = has ? tree.children.map(n => (n.id === ev.child.id ? ev.child : n)) : [...tree.children, ev.child];
  return { ...tree, children, root: { ...tree.root, children: children.filter(n => n.parent === tree.root.id).length } };
}

export const openIds = () => { const v = store.get(OPEN_KEY, []); return Array.isArray(v) ? v : []; };
export function setOpen(id, on) {
  const ids = openIds().filter(x => x !== id);
  store.set(OPEN_KEY, on ? [...ids, id].slice(-200) : ids);
}

/** The chevron on a chat's row (only when it started sub-agents). */
export function TreeToggle({ t, open, onToggle }) {
  return h('button', { type: 'button', onClick: e => { e.preventDefault(); e.stopPropagation(); onToggle(); }, 'aria-expanded': open ? 'true' : 'false',
    'aria-label': `${open ? 'Hide' : 'Show'} the sub-agents of ${t.title || 'this chat'}`, title: `${t.children} sub-agent${t.children === 1 ? '' : 's'}`,
    style: { width: 18, height: 18, display: 'grid', placeItems: 'center', border: 0, borderRadius: 4, background: 'transparent', color: T.dim, cursor: 'pointer', flex: 'none' } },
    h(Icon, { d: open ? 'chevD' : 'chevR', size: 11 }));
}

/** The sub-agents under an open row. `c`: the chat client; `bus`: the page's events; `activeId`: the open chat. */
export function SubAgents({ c, t, bus, activeId = null, onOpen = () => {} }) {
  const React = R(), [tree, setTree] = React.useState(null), [err, setErr] = React.useState(null);
  React.useEffect(() => {
    let alive = true;
    c.tree(t.id).then(x => alive && setTree(x), e => alive && setErr(e?.detail || 'The sub-agents didn’t load'));
    return () => { alive = false; };
  }, [t.id, t.children]);
  React.useEffect(() => {
    if (!bus) return undefined;
    const on = e => setTree(x => applyChild(x, e.detail) || x);
    bus.addEventListener('agent_child', on);
    return () => bus.removeEventListener('agent_child', on);
  }, [bus]);
  if (err) return h('div', { style: { padding: '2px 0 4px 26px', fontSize: 11.5, color: T.dim } }, err);
  if (!tree) return h('div', { style: { padding: '2px 0 4px 26px', fontSize: 11.5, color: T.dim } }, 'Loading…');
  const rows = treeRows(tree);
  return h('div', { role: 'list', 'aria-label': `Sub-agents of ${t.title || 'this chat'}`, style: { display: 'flex', flexDirection: 'column', padding: '0 0 3px 14px' } },
    rows.map(({ node, depth, last }) => {
      const look = childLook(node), active = node.id === activeId;
      return h('a', { key: node.id, role: 'listitem', href: '#/chat/' + enc(node.id), onClick: () => onOpen(node), className: 'aichat-item',
        'aria-current': active ? 'page' : undefined, title: `${look.label}: ${look.word}${look.write ? ' · may change files' : ''}`,
        'aria-label': `${look.label}, ${look.word}`,
        style: { display: 'flex', alignItems: 'center', gap: 6, height: 26, paddingLeft: 6 + depth * 14, paddingRight: 8, borderRadius: 6, fontSize: 12,
          color: active ? T.tx : look.unread ? T.tx : T.mut, fontWeight: active ? 500 : 400, textDecoration: 'none', background: active ? T.hov : 'transparent' } },
        h('span', { 'aria-hidden': true, style: { fontFamily: 'monospace', color: T.bds, width: 10, flex: 'none' } }, last ? '└' : '├'),
        h(Icon, { d: 'branch', size: 11 }),
        h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, look.label),
        look.dot ? h('span', { 'aria-hidden': true, style: { width: 6, height: 6, borderRadius: 99, background: look.dot, flex: 'none',
          animation: look.state === 'running' ? 'aichatpulse 1.2s ease-in-out infinite' : 'none' } }) : null,
        look.unread ? h('span', { 'aria-hidden': true, style: { width: 7, height: 7, borderRadius: 99, background: T.acc, flex: 'none' } }) : null);
    }));
}
