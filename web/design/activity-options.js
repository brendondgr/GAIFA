// Design study (not wired into the app): Part 1, five ways to draw one turn of agent activity,
// plus today's thread (the real buildView and cards) as the baseline. Each option is a component
// `({ turn, ctx, events, live }) → element` drawn from the same turn model (activity-model.js).

import { h, T, MONO, Icon, Btn, Badge, cardSt, R, Frame, Mark, Shim, Time, Chev, LiveLine, ToolRow, ThinkRow, ToolDetail, OutputTile, Md, ellip,
  UserMsg, Answer, Outputs, Approval, useOpen } from './activity-kit.js';
import { Card } from '../chat/chat-cards.js';
import { buildView } from '../chat/chat-thread.js';
import { fmtDur } from './activity-model.js';

const col = (gap, ...kids) => h('div', { style: { display: 'flex', flexDirection: 'column', gap, minWidth: 0 } }, ...kids);
const stepStatus = s => { const st = s.tools.map(t => t.status); return st.includes('waiting') ? 'waiting' : st.includes('running') ? 'running' : st.includes('error') ? 'error' : st.includes('queued') ? 'queued' : 'done'; };
const stepTime = s => s.tools.reduce((n, t) => n + (t.seconds || 0), 0) || null;

// ---------- Today: the real page's cards ----------
export function OptToday({ events, live, turn, ctx }) {
  const view = buildView(events, live), items = view.items;
  const busy = items.some(i => (i.kind === 'tool' || i.kind === 'approval') && !i.result && (i.progress || i.run));
  const last = items[items.length - 1], working = turn.running && !view.pending.length && !last?.streaming && !busy;
  const c = { ...ctx, outputs: view.outputs };
  return h(Frame, null, items.map(it => h(Card, { key: it.key, item: it, ctx: c })),
    working ? h('div', { className: 'aichat-dots', 'aria-label': 'Working', style: { padding: '2px 4px' } }, h('span'), h('span'), h('span')) : null);
}

// ---------- A. One fold per turn ----------
function StepList({ turn, ctx, variant, quietLookups = true, inlineApproval = false }) {
  const [isOpen, toggle] = useOpen();
  return col(2, turn.steps.map(s => col(2,
    h(ThinkRow, { key: 't', thinking: s.thinking, open: isOpen('t' + s.id), onToggle: () => toggle('t' + s.id) }),
    s.narration ? h('div', { style: { padding: '3px 0 3px 21px' } }, h(Md, { text: s.narration.text, size: 12.5, caret: s.narration.streaming })) : null,
    s.tools.map(t => (inlineApproval && t.status === 'waiting'
      ? h('div', { key: t.id, style: { padding: '4px 0 4px 0' } }, h(Approval, { tool: t, ctx }))
      : h(ToolRow, { key: t.id, tool: t, turn, ctx, variant, quietLookups, open: isOpen(t.id), onToggle: () => toggle(t.id) }))))));
}
export function FoldBlock({ turn, ctx, variant = 'list', quietLookups, inlineApproval, startOpen }) {
  const React = R(), [open, setOpen] = React.useState(startOpen ?? (turn.running || (inlineApproval && turn.pending.length > 0)));
  const head = turn.running
    ? h(LiveLine, { status: turn.status, elapsed: turn.elapsed, right: h(Chev, { open }) })
    : h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: T.mut } },
      h('span', { style: { display: 'flex', color: T.dim } }, h(Icon, { d: 'tool', size: 13 })), h('span', null, turn.summary.text),
      h('span', { style: { color: T.dim } }, '·'), h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.dim } }, turn.summary.time), h(Chev, { open }));
  return col(6,
    h('button', { type: 'button', className: 'dz-row', onClick: () => setOpen(!open), 'aria-expanded': open ? 'true' : 'false',
      style: { display: 'block', width: turn.running ? '100%' : 'auto', alignSelf: 'flex-start', padding: '4px 6px', margin: '0 -6px', border: 0, borderRadius: 6, background: 'none', color: 'inherit', font: 'inherit', textAlign: 'left', cursor: 'pointer' } }, head),
    open ? h('div', { style: { marginLeft: 6, paddingLeft: 12, borderLeft: '1px solid ' + T.bds } }, h(StepList, { turn, ctx, variant, quietLookups, inlineApproval })) : null);
}
export function OptFold({ turn, ctx }) {
  return h(Frame, null, h(UserMsg, { turn, ctx }), h(FoldBlock, { turn, ctx }),
    turn.pending.map(t => h(Approval, { key: t.id, tool: t, ctx })),
    h(Outputs, { outputs: turn.outputs, ctx }), h(Answer, { turn, ctx }));
}

// ---------- B. A timeline rail that stays open ----------
function Node({ mark, last, children }) {
  return h('div', { style: { display: 'grid', gridTemplateColumns: '18px 1fr', columnGap: 10, minWidth: 0 } },
    h('div', { style: { position: 'relative', display: 'flex', justifyContent: 'center' } },
      last ? null : h('span', { style: { position: 'absolute', top: 18, bottom: -4, width: 1, background: T.bds } }),
      h('span', { style: { position: 'relative', height: 18, display: 'flex', alignItems: 'center', background: T.bg, padding: '2px 0' } }, mark)),
    h('div', { style: { minWidth: 0, paddingBottom: last ? 0 : 8 } }, children));
}
const dot = h('span', { style: { width: 6, height: 6, borderRadius: 99, background: T.bdh } });
export function OptRail({ turn, ctx }) {
  const [isOpen, toggle] = useOpen(), nodes = [];
  turn.steps.forEach(s => {
    if (s.thinking) nodes.push({ k: 't' + s.id, mark: h('span', { style: { color: T.dim, display: 'flex' } }, h(Icon, { d: 'bulb', size: 13 })),
      body: h(ThinkRow, { thinking: s.thinking, noIcon: true, open: isOpen('t' + s.id), onToggle: () => toggle('t' + s.id) }) });
    if (s.narration) nodes.push({ k: 'n' + s.id, mark: dot, body: h('div', { style: { paddingTop: 1 } }, h(Md, { text: s.narration.text, caret: s.narration.streaming })) });
    s.tools.forEach(t => nodes.push({ k: t.id, mark: h(Mark, { status: t.status, size: 13 }),
      body: col(6,
        t.status === 'waiting' ? h(Approval, { tool: t, ctx }) : h(ToolRow, { tool: t, turn, ctx, noMark: true, open: isOpen(t.id), onToggle: () => toggle(t.id), quietLookups: true }),
        t.outputs.length ? h('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap', paddingBottom: 4 } }, t.outputs.map(o => h(OutputTile, { key: o.n, o, size: 150 }))) : null) }));
  });
  if (turn.running && turn.status && !turn.status.tool && turn.status.tone !== 'purple' && !turn.answer?.streaming)
    nodes.push({ k: 'live', mark: h('span', { className: 'dz-spin' }), body: h(Shim, { style: { fontSize: 12.5 } }, turn.status.text + '…') });
  return h(Frame, null, h(UserMsg, { turn, ctx }),
    h('div', null, nodes.map((n, i) => h(Node, { key: n.k, mark: n.mark, last: i === nodes.length - 1 }, n.body))),
    h(Answer, { turn, ctx }));
}

// ---------- C. Chapters: one card per step that did real work ----------
export function OptChapters({ turn, ctx }) {
  const [isOpen, toggle] = useOpen(), [rowOpen, rowToggle] = useOpen();
  const out = [];
  turn.steps.forEach(s => {
    const real = s.tools.filter(t => !t.lookup), looks = s.tools.filter(t => t.lookup);
    if (looks.length && !real.length) {
      const st = stepStatus(s);
      out.push(h('div', { key: s.id, style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: T.mut, padding: '0 2px' } },
        h(Mark, { status: st, size: 12 }), st === 'running' ? h(Shim, null, 'Getting the tools ready…') : 'Got the image and 3D tools ready'));
      return;
    }
    if (!real.length) return;
    const st = stepStatus(s), open = isOpen(s.id) !== (st === 'running' || st === 'waiting'), main = real[0];
    out.push(h('div', { key: s.id, style: cardSt({ pad: '8px 12px', gap: 6, accent: st === 'waiting' ? T.pu : undefined }) },
      h('button', { type: 'button', onClick: () => toggle(s.id), 'aria-expanded': open ? 'true' : 'false', style: { display: 'flex', alignItems: 'center', gap: 9, border: 0, background: 'none', padding: 0, color: T.tx, font: 'inherit', textAlign: 'left', cursor: 'pointer', minWidth: 0 } },
        h(Mark, { status: st }),
        h('div', { style: { display: 'flex', flexDirection: 'column', minWidth: 0, flex: 1 } },
          h('span', { style: { fontWeight: 600, fontSize: 13 } }, main.label, main.status === 'running' && main.progress?.progress != null ? h('span', { style: { fontFamily: MONO, fontWeight: 400, fontSize: 11.5, color: T.acct, marginLeft: 8 } }, Math.round(main.progress.progress * 100) + '%') : null),
          s.narration ? h('span', { style: { ...ellip, fontSize: 12, color: T.mut } }, s.narration.text) : null),
        h(Time, { s: stepTime(s) }), h(Chev, { open })),
      main.status === 'running' ? h(ProgressLine, { t: main }) : null,
      open ? h('div', { style: { borderTop: '1px solid ' + T.bd, paddingTop: 6, display: 'flex', flexDirection: 'column', gap: 2 } },
        h(ThinkRow, { thinking: s.thinking, open: rowOpen('t' + s.id), onToggle: () => rowToggle('t' + s.id) }),
        real.map(t => h(ToolRow, { key: t.id, tool: t, turn, ctx, showBar: false, open: rowOpen(t.id), onToggle: () => rowToggle(t.id) }))) : null));
    real.filter(t => t.status === 'waiting').forEach(t => out.push(h(Approval, { key: 'ap' + t.id, tool: t, ctx })));
    const outs = real.flatMap(t => t.outputs);
    if (outs.length) out.push(h(Outputs, { key: 'o' + s.id, outputs: outs, ctx }));
  });
  const idle = turn.running && turn.status && !turn.status.tool && turn.status.tone !== 'purple' && !turn.answer?.streaming;
  return h(Frame, null, h(UserMsg, { turn, ctx }), out, idle ? h(LiveLine, { status: turn.status, elapsed: turn.elapsed }) : null, h(Answer, { turn, ctx }));
}
function ProgressLine({ t }) {
  const v = t.progress?.progress;
  return h('div', { style: { height: 3, borderRadius: 9, background: T.row, overflow: 'hidden', position: 'relative' } },
    h('span', { style: v != null ? { display: 'block', height: '100%', width: `${v * 100}%`, background: T.acc } : { position: 'absolute', top: 0, bottom: 0, width: '40%', background: T.acc, animation: 'aichatbar 1.4s ease-in-out infinite' } }));
}

// ---------- D. One status line in the thread, the detail in a side panel ----------
export function OptPanel({ turn, ctx }) {
  const React = R(), [panel, setPanel] = React.useState(false);
  const btn = h(Btn, { sm: true, kind: panel ? 'purple' : 'ghost', icon: 'menu', label: panel ? 'Hide activity' : 'Activity', onClick: () => setPanel(!panel) });
  const line = turn.running && turn.status?.tone !== 'purple'
    ? h(LiveLine, { status: turn.status, elapsed: turn.elapsed, right: btn })
    : h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: T.mut } },
      turn.running ? h(Mark, { status: 'waiting', size: 13 }) : h(Mark, { status: 'done', size: 13 }),
      h('span', null, turn.running ? 'Waiting for you' : turn.summary.text), h('span', { style: { color: T.dim } }, '·'), h(Time, { s: turn.elapsed }), h('span', { style: { flex: 1 } }), btn);
  const thread = col(14, h(UserMsg, { turn, ctx }), line, turn.pending.map(t => h(Approval, { key: t.id, tool: t, ctx })),
    h(Outputs, { outputs: turn.outputs, ctx }), h(Answer, { turn, ctx }));
  const side = panel ? h('aside', { style: { width: 300, flex: 'none', borderLeft: '1px solid ' + T.bd, padding: '2px 0 0 14px', display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } }, h('span', { style: { fontWeight: 600, fontSize: 13 } }, 'Activity'),
      h('span', { style: { fontSize: 12, color: T.mut } }, turn.summary.text), h('span', { style: { flex: 1 } }),
      h(Btn, { sm: true, kind: 'ghost', icon: 'x', title: 'Close', onClick: () => setPanel(false) })),
    h(StepList, { turn, ctx })) : null;
  return h('div', { style: { background: T.bg, border: '1px solid ' + T.bd, borderRadius: 10, padding: '18px 16px', display: 'flex', gap: 16, minWidth: 0 } },
    h('div', { style: { flex: 1, minWidth: 0, maxWidth: 760, margin: panel ? 0 : '0 auto' } }, thread), side);
}

// ---------- E. The agent's words, with a row of tool chips under each ----------
function Chip({ t, on, onClick }) {
  const pct = t.status === 'running' ? t.progress?.progress : null, live = t.status === 'running';
  return h('button', { type: 'button', className: 'dz-chip', onClick, 'aria-pressed': on ? 'true' : 'false', style: { position: 'relative', overflow: 'hidden', display: 'inline-flex', alignItems: 'center', gap: 6, height: 26, padding: '0 10px 0 8px',
    borderRadius: 99, border: '1px solid ' + (on ? T.cy : t.status === 'waiting' ? T.pu : T.bds), background: on ? T.tcy : T.card, color: t.lookup ? T.mut : T.tx, font: 'inherit', fontSize: 12, cursor: 'pointer', flex: 'none' } },
  pct != null ? h('span', { style: { position: 'absolute', left: 0, top: 0, bottom: 0, width: `${pct * 100}%`, background: T.tacc } }) : null,
  h('span', { style: { position: 'relative', display: 'flex' } }, h(Mark, { status: t.status, size: 12 })),
  h('span', { style: { position: 'relative', fontWeight: t.lookup ? 400 : 500 } }, t.noun),
  h('span', { style: { position: 'relative', fontFamily: MONO, fontSize: 11, color: pct != null ? T.acct : T.dim } }, pct != null ? Math.round(pct * 100) + '%' : t.status === 'waiting' ? 'needs you' : live ? fmtDur(t.seconds) : fmtDur(t.seconds)));
}
export function OptChips({ turn, ctx }) {
  const React = R(), [sel, setSel] = React.useState(null), [isOpen, toggle] = useOpen();
  const out = [];
  turn.steps.forEach(s => {
    if (s.narration) out.push(h(Md, { key: 'n' + s.id, text: s.narration.text, caret: s.narration.streaming }));
    const lookups = s.tools.filter(t => t.lookup), real = s.tools.filter(t => !t.lookup);
    const chips = [];
    if (s.thinking) chips.push(h('button', { key: 't', type: 'button', className: 'dz-chip', onClick: () => toggle('t' + s.id), style: { display: 'inline-flex', alignItems: 'center', gap: 5, height: 26, padding: '0 9px', borderRadius: 99, border: '1px dashed ' + T.bds, background: 'none', color: T.mut, font: 'inherit', fontSize: 12, cursor: 'pointer' } },
      h(Icon, { d: 'bulb', size: 12, style: s.thinking.streaming ? { animation: 'aichatpulse 1.2s ease-in-out infinite' } : null }), s.thinking.streaming ? 'Thinking…' : fmtDur(s.thinking.seconds)));
    if (lookups.length) {
      const t = { ...lookups[lookups.length - 1], noun: 'Tools', status: lookups.some(x => x.status === 'running') ? 'running' : 'done', progress: null, seconds: null };
      chips.push(h(Chip, { key: 'l', t, on: sel === 'l' + s.id, onClick: () => setSel(sel === 'l' + s.id ? null : 'l' + s.id) }));
    }
    real.forEach(t => chips.push(h(Chip, { key: t.id, t, on: sel === t.id, onClick: () => setSel(sel === t.id ? null : t.id) })));
    if (chips.length) out.push(h('div', { key: 'c' + s.id, style: { display: 'flex', flexWrap: 'wrap', gap: 6 } }, chips));
    if (isOpen('t' + s.id) && s.thinking) out.push(h('div', { key: 'th' + s.id, style: { padding: '2px 10px', borderLeft: '2px solid ' + T.bds } }, h(Md, { text: s.thinking.text, muted: true, size: 12.5 })));
    const picked = sel === 'l' + s.id ? lookups : real.filter(t => t.id === sel);
    picked.forEach(t => out.push(h('div', { key: 'd' + t.id, style: cardSt({ pad: '8px 12px', gap: 6, style: { background: T.inset } }) },
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5 } }, h(Mark, { status: t.status, size: 13 }), h('span', { style: { fontWeight: 500 } }, t.label), h('span', { style: { color: T.dim } }, t.detail)),
      h(ToolDetail, { tool: t, turn, ctx }))));
    real.filter(t => t.status === 'waiting').forEach(t => out.push(h(Approval, { key: 'ap' + t.id, tool: t, ctx })));
    const outs = real.flatMap(t => t.outputs);
    if (outs.length) out.push(h(Outputs, { key: 'o' + s.id, outputs: outs, ctx }));
  });
  const idle = turn.running && turn.status && !turn.status.tool && turn.status.tone !== 'purple' && !turn.answer?.streaming && !turn.steps.at(-1)?.thinking?.streaming;
  return h(Frame, null, h(UserMsg, { turn, ctx }), out, idle ? h(LiveLine, { status: turn.status, elapsed: turn.elapsed }) : null, h(Answer, { turn, ctx }));
}
