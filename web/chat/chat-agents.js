// Sub-agents in a chat (plan agent-workflows 3.3): the `agent` tools' words in the activity fold, a live card under the
// fold for each sub-agent a turn started (its label, state and current step; Open puts it in a pane beside this one,
// Stop stops it), a strip above the composer while background sub-agents run, and small cards for what they send back
// (`agent_done`, `agent_request`, `agent_review`). A card follows its sub-agent through `ctx.workflow` ({c, bus, paneId}):
// the chat's tree once, then the page's `agent_child` events. Pure helpers first (tested in
// utils/tests/web/chat-agents.test.mjs). Written by us (web/PATCHES.md).

import { h, T, Icon, Btn, Badge, cardSt } from './chat-ui.js';
import { registerCard } from './chat-cards.js';
import { registerStep } from './chat-steps.js';
import { childLook, applyChild } from './chat-tree.js';

const R = () => globalThis.React;
const quoted = s => (s ? `“${String(s).length > 60 ? String(s).slice(0, 58) + '…' : s}”` : '');

registerStep('agent', { running: a => (a.background ? 'Starting a sub-agent' : 'Running a sub-agent'), icon: 'branch',
  done: a => (a.background ? 'Started a sub-agent' : 'Ran a sub-agent'), detail: a => a.label || '',
  sentence: a => ({ parts: [a.background ? 'Started ' : 'Asked ', { b: a.label || 'a sub-agent' }, a.write ? ' (it may change files)' : '',
    a.background ? ' in the background, with this task:' : ' to do this and report back:'], quote: a.prompt }) });
registerStep('agent_wait', { running: 'Waiting for a sub-agent', done: 'Heard back from a sub-agent', icon: 'branch' });
registerStep('agent_send', { running: 'Writing to a sub-agent', done: 'Wrote to a sub-agent', icon: 'branch', detail: a => quoted(a.text),
  sentence: a => ({ parts: ['Gave a sub-agent more to do:'], quote: a.text }) });
registerStep('agent_stop', { running: 'Stopping a sub-agent', done: 'Stopped a sub-agent', icon: 'stop' });
registerStep('agent_list', { running: 'Checking its sub-agents', done: 'Checked its sub-agents', icon: 'branch', lookup: true });
registerStep('agent_review', { running: 'Reviewing a request', icon: 'shield',
  done: a => (a.action === 'deny' ? 'Said no to a sub-agent' : 'Passed a request to you'), detail: a => a.reason ? quoted(a.reason) : '' });

/** The sub-agent a tool row is about: from its result's `data.agent`, its content, or its live progress. */
export function childOfRow(row) {
  const r = row?.item?.result || {}, live = row?.progress?.live?.agent;
  let c = {};
  try { c = JSON.parse(r.content || '{}') || {}; } catch { /* not JSON */ }
  const d = r.data?.agent || {};
  const id = d.child || c.child || live?.child;
  if (!id) return null;
  return { id, label: d.label || c.label || live?.label, background: !!(d.background || c.background), answer: c.answer, state: c.state };
}
/** The answer as the card shows it: without the <untrusted> wrapper, cut to `n` characters. */
export function answerText(s, n = 280) {
  const t = String(s || '').replace(/^<untrusted source="[^"]*">\n?/, '').replace(/\n?<\/untrusted>\s*$/, '').trim();
  return t.length > n ? t.slice(0, n - 1) + '…' : t;
}
/** This chat's sub-agents still at work (running, queued, waiting), from its tree. */
export const atWork = (tree, tid) => (tree?.children || []).filter(n => n.parent === tid && ['running', 'queued', 'waiting'].includes(n.state));

/** The chat's workflow tree, kept current from the page's events. */
export function useTree(w, tid, enabled = true) {
  const React = R(), [tree, setTree] = React.useState(null);
  React.useEffect(() => {
    if (!w?.c?.tree || !tid || !enabled) return undefined;
    let alive = true;
    w.c.tree(tid).then(t => alive && setTree(t), () => {});
    const on = e => setTree(x => applyChild(x, e.detail) || (x && e.detail?.parent === tid ? null : x));
    w.bus?.addEventListener('agent_child', on);
    return () => { alive = false; w.bus?.removeEventListener('agent_child', on); };
  }, [tid, enabled]);
  React.useEffect(() => {        // a sub-agent this tree didn't know (a new one): read it again
    if (tree === null && w?.c?.tree && tid && enabled) w.c.tree(tid).then(setTree, () => {});
  }, [tree === null]);
  return tree;
}

export const openBeside = (w, tid) => {
  if (typeof document === 'undefined') return;
  document.dispatchEvent(new CustomEvent('gaifa:open-chat-beside', { detail: { tid, pane: w?.paneId || null } }));
};

function AgentCard({ ctx }) {
  const lc = ctx.liveCard, w = ctx.workflow, kid = childOfRow(lc.row);
  const tree = useTree(w, ctx.tid, !!kid);
  if (!kid) return null;
  const node = (tree?.children || []).find(n => n.id === kid.id) || { id: kid.id, label: kid.label, state: lc.status === 'running' ? 'running' : kid.state || 'idle', seen: true };
  const look = childLook(node), live = lc.live?.agent, step = lc.status === 'running' && lc.note ? lc.note.replace(/^[^:]*:\s*/, '') : look.word;
  const answer = kid.answer && !['running', 'queued', 'waiting'].includes(node.state) ? answerText(kid.answer) : '';
  return h('div', { style: cardSt({ pad: '9px 11px', gap: 6, accent: node.state === 'waiting' ? T.pu : undefined }) },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 } },
      h('span', { style: { width: 22, height: 22, borderRadius: 6, display: 'grid', placeItems: 'center', background: T.tpu, color: T.pu, flex: 'none' } }, h(Icon, { d: 'branch', size: 12 })),
      h('span', { title: look.label, style: { flex: '1 1 auto', fontWeight: 600, fontSize: 12.5, minWidth: 48, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, look.label),
      h(Badge, { tone: { running: 'accent', queued: 'dim', waiting: 'purple', error: 'red' }[node.state] || 'green', style: { minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' } }, step),
      node.write ? h(Badge, { tone: 'dim', title: 'It may change files' }, 'writer') : null,
      live?.calls ? h('span', { style: { fontSize: 11, color: T.dim, flex: 'none' } }, `${live.calls} step${live.calls === 1 ? '' : 's'}`) : null,
      ['running', 'queued'].includes(node.state) && w?.c ? h(Btn, { sm: true, kind: 'ghost', icon: 'stop', title: `Stop ${look.label}`, onClick: () => w.c.cancel(kid.id).catch(() => {}) }) : null,
      h(Btn, { sm: true, kind: 'ghost', icon: 'ext', title: `Open ${look.label} beside this chat`, onClick: () => openBeside(w, kid.id) })),
    answer ? h('div', { style: { fontSize: 12.5, color: T.mut, lineHeight: 1.45, whiteSpace: 'pre-wrap' } }, answer) : null);
}
registerCard('live:agent', AgentCard);

/** Above the composer while this chat's background sub-agents work: each one's label and state, and Open. */
export function AgentStrip({ w, tid, count }) {
  const tree = useTree(w, tid, count > 0), busy = atWork(tree, tid);
  if (!busy.length) return null;
  return h('div', { role: 'status', 'aria-label': 'Sub-agents at work', style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '4px 2px 6px', fontSize: 12, color: T.mut } },
    h(Icon, { d: 'branch', size: 12 }), h('span', null, `${busy.length} sub-agent${busy.length === 1 ? '' : 's'} at work:`),
    busy.map(n => { const look = childLook(n);
      return h('button', { key: n.id, type: 'button', onClick: () => openBeside(w, n.id), title: `Open ${look.label} beside this chat`,
        style: { display: 'inline-flex', alignItems: 'center', gap: 5, height: 22, padding: '0 8px', borderRadius: 99, border: '1px solid ' + T.bd, background: T.card, color: T.tx, font: 'inherit', fontSize: 11.5, cursor: 'pointer' } },
        h('span', { style: { width: 6, height: 6, borderRadius: 99, background: look.dot || T.dim, animation: n.state === 'running' ? 'aichatpulse 1.2s ease-in-out infinite' : 'none' } }),
        look.label, h('span', { style: { color: T.dim } }, look.word)); }));
}

// ---- what the sub-agents send back, in the parent's thread ----
const line = (icon, color, parts, action = null) => h('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, fontSize: 12, color, flexWrap: 'wrap' } },
  h(Icon, { d: icon, size: 12 }), h('span', null, ...parts), action);

registerCard('agent_done', ({ item, ctx }) => {
  const p = item.ev.payload, ok = p.state === 'idle';
  return line('branch', ok ? T.mut : T.acct, [h('b', { key: 'l' }, p.label || 'A sub-agent'), ok ? ' finished in the background' : ` ended: ${p.state}`],
    h('button', { type: 'button', onClick: () => openBeside(ctx.workflow, p.child), style: { border: 0, background: 'none', color: T.acc, font: 'inherit', fontSize: 12, cursor: 'pointer', padding: 0 } }, 'Open'));
});
registerCard('agent_request', ({ item }) => {
  const p = item.ev.payload;
  return line('shield', T.pu, [h('b', { key: 'l' }, p.label || 'A sub-agent'), p.kind === 'question' ? ' asked a question' : ` asked to run ${p.tool}`]);
});
registerCard('agent_review', ({ item }) => {
  const p = item.ev.payload, who = p.by === 'user' ? 'You' : p.auto ? 'Not reviewed: passed' : 'Passed';
  const what = { forward: `${who} to you`, deny: p.by === 'user' ? 'You said no' : 'Said no', approve: 'You allowed it', answer: 'You answered' }[p.action] || p.action;
  return line(p.action === 'deny' ? 'x' : p.action === 'approve' ? 'check' : 'shield', T.mut, [what, p.reason ? ` · ${quoted(p.reason)}` : '']);
});
