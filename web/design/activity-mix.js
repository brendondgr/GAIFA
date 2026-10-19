// Design study (not wired into the app): the user's mix of the options (2026-10-19) —
// A's fold, closed to start · 2b sentence details · 3a+3c thinking (spinner, live seconds, peek) ·
// 4c strip + one capped preview · 5b plain words · 6c approval docked on the composer.

import { h, T, MONO, Icon, Btn, Badge, cardSt, R, Frame, Mark, Shim, Time, Chev, ToolRow, Md, ellip, UserMsg, Answer, Approval, useOpen } from './activity-kit.js';
import { Card } from '../chat/chat-cards.js';
import { fmtDur } from './activity-model.js';

const col = (gap, ...kids) => h('div', { style: { display: 'flex', flexDirection: 'column', gap, minWidth: 0 } }, ...kids);
const rowBtn = { display: 'flex', alignItems: 'center', gap: 8, width: '100%', minWidth: 0, padding: '4px 6px', margin: '0 -6px', border: 0, borderRadius: 6, background: 'none', color: T.mut, font: 'inherit', fontSize: 12.5, textAlign: 'left', cursor: 'pointer' };

/** Seconds since this stage was shown, while the turn runs (so the timers count up). */
function useTick(running) {
  const React = R(), [n, setN] = React.useState(0);
  React.useEffect(() => { if (!running) return undefined; const t = setInterval(() => setN(x => x + 1), 1000); return () => clearInterval(t); }, [running]);
  return running ? n : 0;
}

const Peek = ({ text }) => h('div', { className: 'dz-peek', style: { margin: '0 0 2px 21px', maxHeight: 40, overflow: 'hidden', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', color: T.dim, fontSize: 12, lineHeight: 1.6 } }, text + '…');

/** Thinking: a spinner, "Thinking…" and live seconds, with the last lines peeking under it; afterwards "Thought for 4s ›". */
export function MixThink({ thinking, open, onToggle, tick = 0 }) {
  if (!thinking) return null;
  const live = thinking.streaming;
  return col(2,
    h('button', { type: 'button', className: 'dz-row', onClick: onToggle, 'aria-expanded': open ? 'true' : 'false', style: rowBtn },
      live ? h('span', { className: 'dz-spin' }) : h('span', { style: { color: T.dim, display: 'flex', flex: 'none' } }, h(Icon, { d: 'check', size: 13, sw: 2 })),
      live ? h(Shim, null, 'Thinking…') : h('span', null, 'Thought for ' + fmtDur(thinking.seconds)),
      live ? h(Time, { s: thinking.seconds + tick }) : null, h('span', { style: { flex: 1 } }), h(Chev, { open })),
    open ? h('div', { style: { margin: '0 0 4px 21px', padding: '2px 10px', borderLeft: '2px solid ' + T.bds } }, h(Md, { text: thinking.text, muted: true, size: 12.5, caret: live }))
      : live ? h(Peek, { text: thinking.text }) : null);
}

/** Outputs: a strip of thumbnails, the picked one as the real result card with its preview capped. */
export function MixStrip({ outputs, ctx, cap = 300 }) {
  const React = R(), [sel, setSel] = React.useState(null);
  if (!outputs.length) return null;
  const big = outputs.find(o => o.n === sel) || outputs[outputs.length - 1];
  return col(8,
    outputs.length > 1 ? h('div', { style: { display: 'flex', gap: 6 } }, outputs.map(o => h('button', { key: o.n, type: 'button', onClick: () => setSel(o.n), title: `#${o.n} ${o.title}`,
      style: { position: 'relative', padding: 0, borderRadius: 7, border: '2px solid ' + (o.n === big.n ? T.cy : 'transparent'), background: 'none', cursor: 'pointer' } },
    h('img', { src: o.preview, alt: o.title, style: { display: 'block', width: 56, height: 56, objectFit: 'cover', borderRadius: 5, background: T.inset } }),
    h('span', { style: { position: 'absolute', left: 3, bottom: 3, fontFamily: MONO, fontSize: 10, fontWeight: 600, padding: '0 4px', borderRadius: 3, background: T.card, color: T.pu } }, '#' + o.n)))) : null,
    h('div', { className: 'dz-cap', style: { '--dz-cap': cap + 'px' } }, h(Card, { item: { key: 'r' + big.n, kind: 'result', result: { outputs: [big] }, call: {} }, ctx })));
}

/** The composer, with a pending approval docked on top of it. */
export function MixDock({ turn, ctx }) {
  return h('div', { style: { borderTop: '1px solid ' + T.bd, margin: '4px -16px -18px', padding: '10px 16px 14px', display: 'flex', flexDirection: 'column', gap: 8, background: T.sb, borderRadius: '0 0 10px 10px' } },
    turn.pending.map(t => h(Approval, { key: t.id, tool: t, ctx })),
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, height: 42, padding: '0 6px 0 12px', borderRadius: 10, border: '1px solid ' + T.bds, background: T.card, color: T.dim, fontSize: 13 } },
      h('span', { style: { flex: 1 } }, turn.pending.length ? 'Reply, or answer the card above…' : 'Message the agent…'),
      turn.running ? h(Btn, { sm: true, icon: 'stop', label: 'Stop' }) : h(Btn, { sm: true, kind: 'pri', icon: 'send', title: 'Send' })));
}

function Header({ turn, open, tick }) {
  const last = turn.steps[turn.steps.length - 1], thinking = turn.running && last?.thinking?.streaming && !turn.answer?.streaming ? last.thinking : null;
  if (!turn.running) {
    return h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: T.mut } },
      h('span', { style: { display: 'flex', color: T.dim } }, h(Icon, { d: 'tool', size: 13 })), h('span', null, turn.summary.text),
      h('span', { style: { color: T.dim } }, '·'), h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.dim } }, turn.summary.time), h(Chev, { open }));
  }
  const st = turn.status, waiting = st?.tone === 'purple', pct = st?.pct != null ? Math.round(st.pct * 100) + '%' : null;
  return col(2,
    h('div', { role: 'status', style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, minWidth: 0 } },
      waiting ? h(Mark, { status: 'waiting', size: 13 }) : h('span', { className: 'dz-spin' }),
      waiting ? h('span', { style: { color: T.pu, fontWeight: 500 } }, 'Waiting for you to approve below') : h(Shim, null, (thinking ? 'Thinking' : st.text) + '…'),
      pct ? h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.acct } }, pct) : null,
      h('span', { style: { flex: 1 } }), h(Time, { s: turn.elapsed + tick }), h(Chev, { open })),
    thinking && !open ? h(Peek, { text: thinking.text }) : null);
}

export function OptMix({ turn, ctx }) {
  const React = R(), [open, setOpen] = React.useState(false), [isOpen, toggle] = useOpen(), tick = useTick(turn.running);
  const last = turn.steps[turn.steps.length - 1];
  const list = col(2, turn.steps.map(s => col(2,
    h(MixThink, { key: 't', thinking: s.thinking, tick: s === last ? tick : 0, open: isOpen('t' + s.id), onToggle: () => toggle('t' + s.id) }),
    s.narration ? h('div', { style: { padding: '3px 0 3px 21px' } }, h(Md, { text: s.narration.text, size: 12.5, caret: s.narration.streaming })) : null,
    s.tools.map(t => h(ToolRow, { key: t.id, tool: t, turn, ctx, variant: 'sentence', open: isOpen(t.id), onToggle: () => toggle(t.id) })))));
  return h(Frame, null, h(UserMsg, { turn, ctx }),
    col(6,
      h('button', { type: 'button', className: 'dz-row', onClick: () => setOpen(!open), 'aria-expanded': open ? 'true' : 'false',
        style: { display: 'block', width: turn.running ? '100%' : 'auto', alignSelf: 'flex-start', padding: '4px 6px', margin: '0 -6px', border: 0, borderRadius: 6, background: 'none', color: 'inherit', font: 'inherit', textAlign: 'left', cursor: 'pointer' } },
      h(Header, { turn, open, tick })),
      open ? h('div', { style: { marginLeft: 6, paddingLeft: 12, borderLeft: '1px solid ' + T.bds } }, list) : null),
    h(MixStrip, { outputs: turn.outputs, ctx }), h(Answer, { turn, ctx }), h(MixDock, { turn, ctx }));
}
