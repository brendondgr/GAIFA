// The Auto mode's judge in Settings → Agent (plan 30.5): whether its model answers, and the calls it decided,
// newest first: what ran and what asked, with the reason and a link to the chat. GET /api/judge/status and
// GET /api/judge/recent (api.getJudgeStatus, api.listJudged).

import { h, T, MONO, Badge, Btn, fmtAgo } from './chat-ui.js';

const R = () => globalThis.React;
const SOURCE = { rules: 'the fixed rules', model: 'the model', 'fail-closed': 'failed: asked' };

export function JudgedList({ api, limit = 30 }) {
  const React = R(), [rows, setRows] = React.useState(null), [st, setSt] = React.useState(null), [err, setErr] = React.useState(null);
  const load = () => {
    api.listJudged({ limit }).then(setRows, e => setErr(e));
    api.getJudgeStatus?.().then(setSt, () => setSt(null));
  };
  React.useEffect(() => { if (api?.listJudged) load(); }, []);
  if (!api?.listJudged) return null;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, borderTop: '1px solid ' + T.bd, paddingTop: 10 } },
    h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' } }, h('span', { style: { fontWeight: 500 } }, 'Judged calls'),
      h('span', { style: { fontSize: 12, color: T.mut } }, 'In Auto, the judge runs commands, fetches and deletes it’s sure you asked for, and asks you about the rest.'),
      h('span', { style: { flex: 1 } }), h(Btn, { sm: true, kind: 'ghost', icon: 'refresh', label: 'Refresh', onClick: load })),
    st ? h('div', { role: 'status', style: { fontSize: 12, color: st.available ? T.mut : T.acct } },
      st.available ? `Judge: ${st.model} (${st.backend}), answering.` : `Judge: ${st.model} (${st.backend}) doesn’t answer: ${st.detail || 'unavailable'}. Auto isn’t offered until it does.`) : null,
    err ? h('span', { role: 'alert', style: { fontSize: 12, color: T.rd } }, `Couldn’t load the judged calls: ${err.detail || err.message}`) : null,
    rows && !rows.length ? h('span', { style: { fontSize: 12.5, color: T.mut } }, 'None yet. Pick Auto in a chat’s header to let the judge decide.') : null,
    (rows || []).map(r => h('div', { key: r.id, style: { display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap', fontSize: 12.5, padding: '6px 8px', borderRadius: 6, background: T.inset } },
      h(Badge, { tone: r.verdict === 'allow' ? 'green' : 'purple' }, r.verdict === 'allow' ? 'ran' : 'asked'),
      h('span', { style: { fontFamily: MONO, fontSize: 12, minWidth: 0, overflowWrap: 'anywhere' } }, r.summary || r.tool),
      h('span', { style: { color: T.mut, minWidth: 0, overflowWrap: 'anywhere', flexBasis: '100%' } }, r.reason),
      h('span', { style: { fontSize: 11.5, color: T.dim } }, [SOURCE[r.source] || r.source, r.ms != null ? `${Math.round(r.ms)} ms` : null,
        fmtAgo(r.ts) === 'now' ? 'just now' : fmtAgo(r.ts) + ' ago'].filter(Boolean).join(' · ')),
      r.thread ? h('a', { href: '#/chat/' + encodeURIComponent(r.thread), style: { fontSize: 11.5 } }, 'the chat →') : null)));
}
