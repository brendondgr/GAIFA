// The API tab's tool runs (Wire — Phase 13): an operation that is an agent tool with risk other than
// `read` goes through the hub's tool call (`callTool(<mod>_<tool>, args, {mode: 'ask'})`), so it
// asks first like any other client: the parameter card (the chat's ParamCard) inline, then
// `decideApproval`, live progress, and the result with its outputs. Written by us (web/PATCHES.md).

import { h, T, MONO, Icon, Btn, Badge, cardSt, label11 } from './chat/chat-ui.js';
import { ProgressBar, ErrorBox, pre } from './chat/chat-cards.js';
import { ParamCard } from './chat/chat-forms.js';
import { approvalButtons } from './chat/chat-risk.js';

const R = () => globalThis.React;
const sleep = ms => new Promise(r => setTimeout(r, ms));

/** The operation's form values (`p.<name>`, `b.<path>`) → the tool's flat arguments. */
export function toolArgs(fields, form) {
  const out = {};
  for (const f of fields) {
    if (f.group || f.sch?.format === 'binary') continue;
    let v = form[f.key];
    if (v == null || v === '' || (Array.isArray(v) && !v.length)) continue;
    if (['number', 'integer'].includes(f.sch?.type)) v = Number(v);
    if (f.sch?.type === 'boolean' && typeof v === 'string') v = v === 'true';
    const parts = f.key.slice(2).split('.');
    let o = out;
    parts.slice(0, -1).forEach(p => { o[p] = o[p] && typeof o[p] === 'object' ? o[p] : {}; o = o[p]; });
    o[parts[parts.length - 1]] = v;
  }
  return out;
}

export function ToolRun({ api, name, args, onClose, toast = () => {} }) {
  const React = R(), [st, setSt] = React.useState({ phase: 'calling' }), alive = React.useRef(true);
  const follow = async res => {
    let r = res;
    while (alive.current && r.status === 'running' && r.call_id) {
      setSt({ phase: 'running', res: r });
      await sleep(600);
      try { r = await api.getToolCall(r.call_id, { wait: 5 }); } catch (e) { setSt({ phase: 'error', error: { code: e.code, detail: e.detail || String(e) } }); return; }
    }
    if (!alive.current) return;
    setSt({ phase: r.status === 'done' ? 'done' : r.status, res: r, error: r.error });
  };
  React.useEffect(() => {
    alive.current = true;
    api.callTool(name, args, { mode: 'ask', origin: { client: 'AIHub API tab' }, wait: 1 })
      .then(r => (r.status === 'needs_approval' ? setSt({ phase: 'approval', res: r }) : follow(r)))
      .catch(e => setSt({ phase: 'error', error: { code: e.code, detail: e.detail || String(e), fix: e.data?.problems?.map(p => p.fix).filter(Boolean).join('; ') } }));
    return () => { alive.current = false; };
  }, []);
  const decide = async (approve, a, o = {}) => {
    const r = await api.decideApproval(st.res.approval_id, approve ? { approve: true, args: a, remember: o.remember, confirm: o.confirm, wait: 1 } : { approve: false, reason: o.reason || 'Denied in the API tab' });
    if (!approve) { setSt({ phase: 'denied', res: r }); return; }
    toast(`Running ${name}…`);
    follow(r);
  };
  const r = st.res || {}, outs = r.outputs || [];
  const head = h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
    h('span', { style: { color: T.pu, display: 'flex' } }, h(Icon, { d: 'tool', size: 14 })), h('span', { style: label11 }, 'Agent tool call'),
    h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.mut } }, name), h('span', { style: { flex: 1 } }),
    st.phase !== 'approval' ? h(Badge, { tone: { done: 'green', running: 'accent', calling: 'accent', error: 'red', denied: 'red', cancelled: 'dim' }[st.phase] || 'dim' }, st.phase) : null,
    onClose && st.phase !== 'running' ? h(Btn, { kind: 'ghost', sm: true, icon: 'x', title: 'Close', onClick: onClose }) : null);
  return h('section', { 'aria-label': 'Tool call', 'aria-live': 'polite', style: cardSt({ pad: '12px 14px', gap: 10, style: { borderRadius: 10 } }) }, head,
    st.phase === 'calling' ? h('div', { style: { fontSize: 12.5, color: T.mut } }, 'Asking AIHub…') : null,
    st.phase === 'approval' ? h(R().Fragment, null,
      h('div', { style: { fontSize: 12.5, color: T.mut } }, `This is the agent tool ${name} (risk: ${r.risk}), so it asks first, like it would for the chat or an MCP client. Check the settings, then allow it.`),
      h(ParamCard, { spec: { tool: name, arguments: r.arguments || args, ask_fields: r.ask_fields || [], schema: r.schema, risk: r.risk, description: r.description, grant_key: r.grant_key }, api, outputs: [], mods: [name.split('_')[0]],
        choices: approvalButtons(r.risk), cancelLabel: 'Deny', onRun: (a, o) => decide(true, a, o), onCancel: reason => decide(false, null, { reason }) })) : null,
    st.phase === 'running' ? h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
      h('div', { style: { flex: 1 } }, h(ProgressBar, { value: r.progress, note: [r.note, r.elapsed_s != null ? `${Math.round(r.elapsed_s)} s` : null].filter(Boolean).join(' · ') || 'running' })),
      h(Btn, { sm: true, icon: 'stop', label: 'Cancel', onClick: () => api.cancelToolCall(r.call_id).catch(() => {}) })) : null,
    st.error ? h(ErrorBox, { error: st.error }) : null,
    st.phase === 'denied' ? h('div', { style: { fontSize: 12.5, color: T.mut } }, 'Denied: nothing ran.') : null,
    st.phase === 'done' && outs.length ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } }, h('span', { style: label11 }, 'Outputs'),
      outs.map(o => h('a', { key: o.output_id, href: '#/outputs/' + encodeURIComponent(o.output_id), style: { display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', borderRadius: 6, background: T.inset, color: T.tx, textDecoration: 'none', fontSize: 12.5 } },
        o.preview ? h('img', { src: o.preview, alt: '', style: { width: 36, height: 36, objectFit: 'cover', borderRadius: 4 } }) : h(Icon, { d: 'clip', size: 14 }),
        h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, o.title || o.output_id), h(Badge, null, o.kind), h(Icon, { d: 'chevR', size: 12 })))) : null,
    st.phase === 'done' && r.result !== undefined ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } }, h('span', { style: label11 }, 'Result'), pre(JSON.stringify(r.result, null, 2))) : null);
}
