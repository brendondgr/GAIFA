// The header's Approvals popover (Wire — Phase 13): every pending approval, from the chat or from an
// outside client (MCP, the API), as a compact parameter card (the same ParamCard the chat uses):
// the `ask` fields editable, the risk and what a grant would cover, Allow once · Allow in this chat
// (a chat's cards only) · Always allow (behind a second confirm for execute and destructive), and
// Deny with a reason (plan 25.3). Hub.dc.html keeps the list and refreshes it on `approval` events.
// Under them, the memories the agent learned that wait for review, with a link to Review
// (memory-auto-learning 4.1): they don't hold up a chat, so the button's number stays the tools'.

import { h, T, Icon, label11, fmtAgo } from './chat-ui.js';
import { ParamCard } from './chat-forms.js';
import { approvalButtons } from './chat-risk.js';
import { decideFolder } from './chat-env.js';

export function originText(o = {}) {
  if (o.service === 'agent') return 'from a chat';
  if (o.client) return `from ${o.client}${o.via ? ` (${String(o.via).toUpperCase()})` : ''}`;
  if (o.via) return `from ${String(o.via).toUpperCase()}`;
  return 'from the API';
}

/** The popover's line about memories that wait (memory-auto-learning 4.1), or null. */
export function memoriesText(n) {
  return n > 0 ? `${n} ${n === 1 ? 'memory waits' : 'memories wait'} for your review` : null;
}

export function ApprovalsPanel({ api, approvals, loading, onDecided, toast = () => {}, memories = 0, onGo = () => {} }) {
  const decide = async (a, approve, args, o = {}) => {
    if (approve && a.origin?.ask_folder) o = await decideFolder(api, a.origin.ask_folder, o);   // plan 34: Add to <environment>
    await api.decideApproval(a.id, approve ? { approve: true, args, remember: o.remember, confirm: o.confirm } : { approve: false, reason: o.reason || 'Denied in the Approvals popover' });
    const how = { thread: ' in this chat', always: ' always', sites: ' for every site in this chat' }[o.remember] || '';
    toast(approve ? `Allowed ${a.tool}${how}` : `Denied ${a.tool}`, approve ? 'success' : 'info');
    onDecided?.(a.id);
  };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } }, h('h2', { style: { ...label11, margin: 0 } }, 'Approvals'),
      h('span', { style: { flex: 1 } }), h('span', { style: { fontSize: 11.5, color: T.mut } }, approvals.length ? `${approvals.length} waiting` : '')),
    !approvals.length ? h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '18px 4px', color: T.mut } }, h(Icon, { d: 'shield', size: 16 }),
      loading ? 'Loading…' : 'No tool is waiting. Tools that generate, write, use the internet, run code or delete ask here (and in the chat) before they run.') : null,
    approvals.map(a => h('div', { key: a.id, style: { display: 'flex', flexDirection: 'column', gap: 4 } },
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: T.mut } },
        h('span', null, originText(a.origin)), h('span', null, '·'), h('span', null, fmtAgo(a.created_ts) === 'now' ? 'just now' : fmtAgo(a.created_ts) + ' ago'), h('span', { style: { flex: 1 } }),
        a.origin?.service === 'agent' && a.origin?.thread ? h('a', { href: '#/chat/' + encodeURIComponent(a.origin.thread), style: { fontSize: 11.5 } }, 'Open chat →') : null),
      h(ParamCard, { spec: { tool: a.tool, arguments: a.arguments, ask_fields: a.ask_fields, schema: a.schema, risk: a.risk, description: a.description, grant_key: a.grant_key,
          ...(a.origin?.ask_folder ? { limits: { action: 'read', key: 'folder:' + a.origin.ask_folder.path, ask_folder: a.origin.ask_folder } } : {}) }, compact: true, api, outputs: [], mods: [String(a.tool).split('_')[0]],
        choices: approvalButtons(a.risk, { thread: !!a.origin?.thread, folder: a.origin?.ask_folder, grantKey: a.grant_key }), cancelLabel: 'Deny',
        onRun: (args, o) => decide(a, true, args, o), onCancel: reason => decide(a, false, null, { reason }) }))),
    memoriesText(memories) ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, paddingTop: 10, borderTop: '1px solid ' + T.bd } },
      h('h2', { style: { ...label11, margin: 0 } }, 'Memories'),
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5 } },
        h('span', { style: { flex: 1 } }, memoriesText(memories)),
        h('a', { href: '#/s/agent/review', onClick: () => onGo(), style: { color: T.acct, fontSize: 12.5 } }, 'Review →'))) : null);
}
