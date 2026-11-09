// A sub-agent's requests on its parent chat (plan agent-workflows 3.4): each card a sub-agent waits on is docked on the
// parent's composer like the chat's own approvals: "<label> wants to run <tool>", what the parent agent said when it
// passed it on ("the agent is reviewing it…" before it has), and the parameter card with Allow once, Allow in this
// workflow, Always allow and Deny, decided through `POST /v1/threads/{id}/requests/{rid}`. A question shows its
// questions and opens the sub-agent beside to answer. The list is the agent's `GET …/requests?waiting=true`, read
// again when the chat's events or its sub-agents change. Pure helpers first (tested in chat-agents.test.mjs).
// Written by us (web/PATCHES.md).

import { h, T, Icon, Btn, cardSt } from './chat-ui.js';
import { registerCard } from './chat-cards.js';
import { ParamCard } from './chat-forms.js';
import { approvalButtons } from './chat-risk.js';
import { openBeside } from './chat-agents.js';

const R = () => globalThis.React;

/** The card's buttons: the chat's approval buttons, "in this chat" meaning the whole workflow. */
export const requestButtons = r => approvalButtons(r.risk, { thread: true, grantKey: r.grant_key })
  .map(b => ({ ...b, label: b.label.replace('in this chat', 'in this workflow') }));
/** How far the parent agent got with it, in words. */
export function reviewWords(r) {
  if (!r.review) return 'The chat’s agent is reviewing it…';
  if (r.review.action === 'forward') return r.review.auto ? 'The chat’s agent passed it to you.' : `The chat’s agent passed it to you${r.review.reason ? `: “${r.review.reason}”` : '.'}`;
  return '';
}
/** A key that changes when the chat's requests might have: how many request, review and done events it has. */
export const requestStamp = events => (events || []).reduce((n, e) => n + (['agent_request', 'agent_review', 'agent_done'].includes(e.type) ? 1 : 0), 0);

/** The dock items for the chat's waiting requests. */
export function useRequests(c, tid, events, bus) {
  const React = R(), [list, setList] = React.useState([]), [tick, setTick] = React.useState(0);
  const stamp = requestStamp(events);
  React.useEffect(() => {
    if (!c?.requests || !tid || !stamp) { setList([]); return undefined; }
    let alive = true;
    c.requests(tid, { waiting: true }).then(l => alive && setList(l || []), () => {});
    return () => { alive = false; };
  }, [tid, stamp, tick]);
  React.useEffect(() => {
    if (!bus || !tid) return undefined;
    const on = e => { if (e.detail?.parent === tid) setTick(t => t + 1); };
    bus.addEventListener('agent_child', on);
    return () => bus.removeEventListener('agent_child', on);
  }, [bus, tid]);
  return list.map(r => ({ key: 'rq' + r.id, kind: 'agent_request_card', req: r, refresh: () => setTick(t => t + 1) }));
}

function RequestCard({ item, ctx }) {
  const r = item.req, React = R(), [busy, setBusy] = React.useState(false);
  const decide = async body => {
    setBusy(true);
    try { await ctx.decideRequest(r.id, body); ctx.toast?.(body.approve ? `Allowed ${r.tool} for ${r.label}` : `Said no to ${r.label}`, body.approve ? 'success' : 'info'); }
    catch (e) { ctx.toast?.(e?.detail || 'Not decided', 'error'); }
    finally { setBusy(false); item.refresh(); }
  };
  const head = h('div', { style: { display: 'flex', alignItems: 'center', gap: 7, fontSize: 12.5 } },
    h('span', { style: { width: 20, height: 20, borderRadius: 6, display: 'grid', placeItems: 'center', background: T.tpu, color: T.pu, flex: 'none' } }, h(Icon, { d: 'branch', size: 11 })),
    h('span', { style: { flex: 1, minWidth: 0 } }, h('b', null, r.label), r.kind === 'question' ? ' asks a question' : ` wants to run ${r.tool}`),
    h(Btn, { sm: true, kind: 'ghost', icon: 'ext', title: `Open ${r.label} beside this chat`, onClick: () => openBeside(ctx.workflow, r.child) }));
  const words = reviewWords(r);
  const note = words ? h('div', { style: { fontSize: 11.5, color: r.review ? T.mut : T.dim, fontStyle: r.review ? 'normal' : 'italic' } }, words) : null;
  if (r.kind === 'question') {
    return h('div', { style: cardSt({ accent: T.pu, gap: 6 }) }, head, note,
      (r.questions || []).map((q, i) => h('div', { key: i, style: { fontSize: 12.5 } }, q.question)),
      h('div', null, h(Btn, { sm: true, kind: 'pri', label: 'Answer in its chat', onClick: () => openBeside(ctx.workflow, r.child) })));
  }
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, opacity: busy ? 0.6 : 1 } }, head, note,
    h(ParamCard, { spec: { tool: r.tool, arguments: r.arguments, ask_fields: r.ask_fields || [], schema: r.schema, risk: r.risk, description: r.description,
        grant_key: r.grant_key, ...(r.limits ? { limits: r.limits } : {}) }, compact: true, api: ctx.api, outputs: [], mods: [String(r.tool).split('_')[0]],
      choices: requestButtons(r), cancelLabel: 'Deny',
      onRun: (args, o = {}) => decide({ approve: true, arguments: args, remember: o.remember || 'once', ...(o.confirm ? { confirm: true } : {}) }),
      onCancel: reason => decide({ approve: false, reason: reason || 'Denied in the chat that started it' }) }));
}
registerCard('agent_request_card', RequestCard);
