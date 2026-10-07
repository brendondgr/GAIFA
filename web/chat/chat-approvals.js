// The header's Approvals popover (Wire — Phase 13): every pending approval, from the chat or from an
// outside client (MCP, the API), as a compact parameter card (the same ParamCard the chat uses):
// the `ask` fields editable, Approve / Deny. Hub.dc.html keeps the list and refreshes it on
// `approval` events.

import { h, T, Icon, label11, fmtAgo } from './chat-ui.js';
import { ParamCard } from './chat-forms.js';

export function originText(o = {}) {
  if (o.service === 'agent') return 'from a chat';
  if (o.client) return `from ${o.client}${o.via ? ` (${String(o.via).toUpperCase()})` : ''}`;
  if (o.via) return `from ${String(o.via).toUpperCase()}`;
  return 'from the API';
}

export function ApprovalsPanel({ api, approvals, loading, onDecided, toast = () => {} }) {
  const decide = async (a, approve, args) => {
    await api.decideApproval(a.id, approve ? { approve: true, args } : { approve: false, reason: 'Denied in the Approvals popover' });
    toast(approve ? `Approved ${a.tool}` : `Denied ${a.tool}`, approve ? 'success' : 'info');
    onDecided?.(a.id);
  };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } }, h('h2', { style: { ...label11, margin: 0 } }, 'Approvals'),
      h('span', { style: { flex: 1 } }), h('span', { style: { fontSize: 11.5, color: T.mut } }, approvals.length ? `${approvals.length} waiting` : '')),
    !approvals.length ? h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '18px 4px', color: T.mut } }, h(Icon, { d: 'shield', size: 16 }),
      loading ? 'Loading…' : 'Nothing is waiting. Tools that generate, write or delete ask here (and in the chat) before they run.') : null,
    approvals.map(a => h('div', { key: a.id, style: { display: 'flex', flexDirection: 'column', gap: 4 } },
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: T.mut } },
        h('span', null, originText(a.origin)), h('span', null, '·'), h('span', null, fmtAgo(a.created_ts) === 'now' ? 'just now' : fmtAgo(a.created_ts) + ' ago'), h('span', { style: { flex: 1 } }),
        a.origin?.service === 'agent' && a.origin?.thread ? h('a', { href: '#/chat/' + encodeURIComponent(a.origin.thread), style: { fontSize: 11.5 } }, 'Open chat →') : null),
      h(ParamCard, { spec: { tool: a.tool, arguments: a.arguments, ask_fields: a.ask_fields, schema: a.schema, risk: a.risk, description: a.description }, compact: true, api, outputs: [], mods: [String(a.tool).split('_')[0]],
        runLabel: 'Approve', cancelLabel: 'Deny', onRun: args => decide(a, true, args), onCancel: () => decide(a, false) }))));
}
