// The activity fold (plan 19.4): one per turn, closed by default. Its header says what's happening
// now (a spinner, the words, percent, the time counting up; the thinking peeking under it), then
// "Ran 2 tools · 2m 58s". Opened, it lists the steps: thinking, the agent's updates, tool calls,
// notes. A tool row opens to its sentence (chat-steps.js), and "Raw call" shows the JSON.
//
// One tool's opened detail can be replaced: registerCard('step:<tool name>', ({ row, item, ctx }) => …).

import { h, T, MONO, Icon, Badge } from './chat-ui.js';
import { Card, ProgressBar, hasCard, cardFor } from './chat-cards.js';
import { renderMarkdown } from './chat-md.js';
import { stepText, stepSentence, errorText } from './chat-steps.js';
import { OutputStrip } from './chat-results.js';

const R = () => globalThis.React;

export const ACTIVITY_CSS = `
@keyframes aichatspin{to{transform:rotate(360deg)}}
.aichat-spin{display:inline-block;width:12px;height:12px;border-radius:99px;border:1.7px solid var(--bds,#2A3547);border-top-color:var(--acc,#FFB224);animation:aichatspin .8s linear infinite;flex:none;box-sizing:border-box}
.aichat-shim{background:linear-gradient(90deg,var(--mut,#8A94A6) 0%,var(--mut,#8A94A6) 38%,var(--tx,#E6EAF2) 50%,var(--mut,#8A94A6) 62%,var(--mut,#8A94A6) 100%);background-size:250% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;animation:aichatshim 2.4s linear infinite}
@keyframes aichatshim{from{background-position:100% 0}to{background-position:-150% 0}}
.aichat-row{transition:background .1s}.aichat-row:hover{background:var(--hov,#161C28)}
.aichat-peek{-webkit-mask-image:linear-gradient(to bottom,transparent 0,#000 60%);mask-image:linear-gradient(to bottom,transparent 0,#000 60%)}
@media (prefers-reduced-motion:reduce){.aichat-spin,.aichat-shim{animation:none}.aichat-shim{color:var(--mut,#8A94A6);background:none}}
`;

const ellip = { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 };
const rowBtn = { display: 'flex', alignItems: 'center', gap: 8, width: '100%', minWidth: 0, padding: '4px 6px', margin: '0 -6px', border: 0, borderRadius: 6, background: 'none',
  color: T.tx, font: 'inherit', fontSize: 12.5, textAlign: 'left', cursor: 'pointer' };
export const fmtDur = s => { if (s == null) return ''; s = Math.max(0, Math.round(s)); return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`; };
const Time = ({ s }) => (s == null ? null : h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.dim, flex: 'none' } }, fmtDur(s)));
const Chev = ({ open }) => h('span', { style: { color: T.dim, display: 'flex', flex: 'none' } }, h(Icon, { d: open ? 'chevD' : 'chevR', size: 12 }));
export const Spinner = () => h('span', { className: 'aichat-spin', 'aria-hidden': true });
const Md = ({ text, muted, size = 12.5, caret }) => h('div', { className: 'aichat-md' + (caret ? ' aichat-caret' : ''), style: { fontSize: size, color: muted ? T.mut : T.tx },
  dangerouslySetInnerHTML: { __html: renderMarkdown(text || '') } });

/** A step's status mark: a spinner while it runs, a check, a cross, a shield while it waits for you. */
export function Mark({ status, size = 13 }) {
  if (status === 'running') return h(Spinner);
  const m = { done: ['check', T.gr], error: ['x', T.rd], denied: ['x', T.rd], waiting: ['shield', T.pu], cancelled: ['stop', T.dim], stopped: ['stop', T.dim], skipped: ['stop', T.dim] }[status];
  if (m) return h('span', { style: { color: m[1], display: 'flex', flex: 'none' } }, h(Icon, { d: m[0], size, sw: 2.1 }));
  return h('span', { title: 'Next', style: { width: size - 4, height: size - 4, margin: 2, borderRadius: 99, border: '1.5px solid ' + T.bdh, flex: 'none', boxSizing: 'border-box' } });
}

const stepCtx = ctx => ({ tools: ctx.tools, outputs: ctx.outputs, mods: ctx.mods });
// The arguments that ran: the ones approved on the card (you may have changed them), else the model's.
export const argsOf = it => (it.decision?.approve && it.decision.arguments) || it.call?.arguments || {};
const toolWords = (row, ctx) => stepText(row.name, { args: argsOf(row.item), done: row.status === 'done', ctx: stepCtx(ctx) });

/** The live header's words for a turn's status. */
export function statusText(st, ctx) {
  if (!st) return null;
  if (st.kind === 'waiting') return { text: st.question ? 'Waiting for your answer below' : 'Waiting for you to approve below', tone: 'purple' };
  if (st.kind === 'tool' || st.kind === 'lookup') return { text: toolWords(st.row, ctx).label + '…', pct: st.pct, note: st.note };
  if (st.kind === 'writing') return { text: 'Writing…' };
  if (st.kind === 'thinking') return { text: 'Thinking…', seconds: st.row.seconds };
  return { text: 'Working…' };
}

function Peek({ text }) {
  return h('div', { className: 'aichat-peek', 'aria-hidden': true, style: { margin: '0 0 2px 21px', maxHeight: 40, overflow: 'hidden', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end',
    color: T.dim, fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } }, text);
}

function Header({ turn, ctx, open }) {
  if (!turn.running) {
    return h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, color: T.mut } },
      h('span', { style: { display: 'flex', color: T.dim } }, h(Icon, { d: turn.summary.work ? 'tool' : 'check', size: 13 })), h('span', null, turn.summary.text),
      turn.elapsed >= 1 ? h('span', { style: { color: T.dim } }, '·') : null, turn.elapsed >= 1 ? h(Time, { s: turn.elapsed }) : null, h(Chev, { open }));
  }
  const s = statusText(turn.status, ctx), waiting = s.tone === 'purple', pct = s.pct != null ? Math.round(s.pct * 100) + '%' : null;
  const thinking = turn.status.kind === 'thinking' ? turn.status.row : null;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 } },
    h('div', { role: 'status', 'aria-live': 'polite', style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, minWidth: 0 } },
      waiting ? h(Mark, { status: 'waiting' }) : h(Spinner),
      waiting ? h('span', { style: { color: T.pu, fontWeight: 500 } }, s.text) : h('span', { className: 'aichat-shim', style: { fontWeight: 500, ...ellip } }, s.text),
      pct ? h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.acct, flex: 'none' } }, pct) : null,
      s.note && !thinking ? h('span', { style: { fontSize: 11.5, color: T.dim, ...ellip } }, s.note) : null,
      h('span', { style: { flex: 1 } }), h(Time, { s: turn.elapsed }), h(Chev, { open })),
    thinking && !open ? h(Peek, { text: thinking.text }) : null);
}

// ---------- rows ----------
function ThinkRow({ row, open, onToggle }) {
  const live = row.streaming;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 } },
    h('button', { type: 'button', className: 'aichat-row', onClick: onToggle, 'aria-expanded': open ? 'true' : 'false', style: { ...rowBtn, color: T.mut } },
      live ? h(Spinner) : h('span', { style: { color: T.dim, display: 'flex', flex: 'none' } }, h(Icon, { d: 'check', size: 13, sw: 2 })),
      live ? h('span', { className: 'aichat-shim', style: { fontWeight: 500 } }, 'Thinking…') : h('span', null, 'Thought for ' + (row.seconds >= 1 ? fmtDur(row.seconds) : 'a moment')),
      live ? h(Time, { s: row.seconds }) : null, h('span', { style: { flex: 1 } }), h(Chev, { open })),
    open ? h('div', { style: { margin: '0 0 4px 21px', padding: '2px 10px', borderLeft: '2px solid ' + T.bds } }, h(Md, { text: row.text, muted: true, caret: live }))
      : live ? h(Peek, { text: row.text }) : null);
}

function OutChip({ o }) {
  return h('span', { title: o.title, style: { display: 'inline-flex', alignItems: 'center', gap: 6, height: 22, padding: '0 7px 0 3px', borderRadius: 5, background: T.inset, border: '1px solid ' + T.bd,
    fontSize: 12, maxWidth: '100%', verticalAlign: 'middle' } },
  o.preview ? h('img', { src: o.preview, alt: '', style: { width: 16, height: 16, objectFit: 'cover', borderRadius: 3 } }) : null,
  h('span', { style: { fontFamily: MONO, fontSize: 11, color: T.pu, fontWeight: 600 } }, o.n ? '#' + o.n : 'output'), o.title ? h('span', { style: ellip }, o.title) : null);
}
const part = (p, i) => (typeof p === 'string' ? p : p?.b ? h('strong', { key: i, style: { fontWeight: 600 } }, p.b) : p?.ref ? h(OutChip, { key: i, o: p.ref }) : p?.code ? h('code', { key: i }, p.code) : null);
const json = v => { try { return JSON.stringify(typeof v === 'string' ? JSON.parse(v) : v, null, 2); } catch { return String(v); } };
const pre = t => h('pre', { style: { margin: 0, padding: '8px 10px', borderRadius: 6, background: T.inset, border: '1px solid ' + T.bd, fontFamily: MONO, fontSize: 11.5, lineHeight: 1.5,
  whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 240, overflow: 'auto', color: T.tx } }, t);

/** What a tool row opens to: its sentence, the prompt quoted, the result, then "Raw call". */
export function StepDetail({ row, ctx }) {
  const React = R(), [raw, setRaw] = React.useState(false), it = row.item, args = argsOf(it), r = it.result, sc = stepCtx(ctx);
  const s = stepSentence(row.name, { args, ctx: sc, done: row.status === 'done' });
  const outs = (r?.outputs || []).map(o => (ctx.outputs || []).find(x => x.output_id === o.output_id) || o);
  const failed = r && (r.error || (r.status && r.status !== 'done'));
  const e = failed ? errorText(r) : null;
  const decided = it.decision ? (it.decision.approve ? 'Approved by you' + ({ thread: ', and allowed in this chat', always: ', and always allowed' }[it.decision.remember] || '')   // plan 25.3
    : 'Denied by you') + (it.decision.reason && !it.decision.approve ? `: ${it.decision.reason}` : '') : null;
  const result = e ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 2 } }, h('span', { style: { color: r.status === 'error' || r.error ? T.rd : T.mut } }, e.text), e.fix ? h('span', { style: { color: T.mut, fontSize: 12 } }, e.fix) : null)
    : outs.length ? h('span', { style: { display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' } }, 'Made ', outs.map(o => h(OutChip, { key: o.output_id + o.n, o })), row.seconds != null ? h('span', { style: { color: T.dim, fontSize: 12 } }, 'in ' + fmtDur(row.seconds)) : null)
      : r ? h('span', { style: { color: T.mut } }, 'Done' + (row.seconds ? ' in ' + fmtDur(row.seconds) : '') + '.')
        : row.status === 'waiting' ? h('span', { style: { color: T.pu } }, 'Waiting for you to approve.') : row.status === 'queued' ? h('span', { style: { color: T.mut } }, 'Next.')
          : row.status === 'running' ? h('span', { style: { color: T.mut } }, 'Running…') : h('span', { style: { color: T.mut } }, 'Stopped before it finished.');
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12.5, minWidth: 0 } },
    failed ? h('div', { style: { color: T.dim, fontSize: 11.5 } }, 'What it tried:') : null,
    h('div', { style: { lineHeight: 1.7 } }, s.parts.map(part)),
    s.quote ? h('div', { style: { padding: '2px 10px', borderLeft: '2px solid ' + T.bds, color: T.mut, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } }, s.quote) : null,
    s.fields?.length ? h('div', { style: { display: 'grid', gridTemplateColumns: 'minmax(60px, max-content) 1fr', gap: '4px 12px', alignItems: 'baseline' } },
      s.fields.flatMap(([k, v], i) => [h('span', { key: 'k' + i, style: { color: T.mut, fontSize: 12 } }, k), h('span', { key: 'v' + i, style: { minWidth: 0, overflowWrap: 'anywhere' } }, typeof v === 'object' && v?.ref ? h(OutChip, { o: v.ref }) : String(v))])) : null,
    decided ? h('div', { style: { color: T.mut, fontSize: 12 } }, decided) : null,
    result,
    h('button', { type: 'button', onClick: () => setRaw(!raw), style: { alignSelf: 'flex-start', display: 'inline-flex', alignItems: 'center', gap: 4, border: 0, background: 'none', padding: 0, color: T.dim, font: 'inherit', fontSize: 11.5, cursor: 'pointer' } },
      h(Icon, { d: raw ? 'chevD' : 'chevR', size: 11 }), raw ? 'Hide raw call' : 'Raw call'),
    raw ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
      h('span', { style: { fontFamily: MONO, fontSize: 11, color: T.dim } }, it.call?.name, e?.code ? ' · ' + e.code : ''), pre(json(args)), r ? pre(json(r.content ?? r)) : null) : null);
}

function ToolRow({ row, ctx, open, onToggle }) {
  const w = toolWords(row, ctx), pct = row.progress?.progress, grey = row.lookup;
  const failed = ['error', 'denied'].includes(row.status), r0 = stepText(row.name, { args: argsOf(row.item), ctx: stepCtx(ctx) }).label;
  const label = failed ? 'Tried ' + r0.charAt(0).toLowerCase() + r0.slice(1) : w.label;
  const detail = failed ? errorText(row.item.result).text : w.detail;
  const Detail = hasCard('step:' + row.name) ? cardFor({ kind: 'step', call: row.item.call }) : StepDetail;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 } },
    h('button', { type: 'button', className: 'aichat-row', onClick: onToggle, 'aria-expanded': open ? 'true' : 'false', style: rowBtn },
      h(Mark, { status: row.status }),
      h('span', { style: { ...ellip, flex: 'none', maxWidth: '60%', fontWeight: grey ? 400 : 500, color: grey ? T.mut : T.tx } }, label),
      detail ? h('span', { title: detail, style: { ...ellip, color: T.dim, fontSize: 12 } }, detail) : null,
      h('span', { style: { flex: 1 } }),
      row.status === 'running' && pct != null ? h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.acct, flex: 'none' } }, Math.round(pct * 100) + '%') : null,
      row.status === 'waiting' ? h(Badge, { tone: 'purple' }, 'needs you') : row.status === 'queued' ? h('span', { style: { fontSize: 11.5, color: T.dim } }, 'next') : h(Time, { s: row.seconds }),
      it_by(row) ? h(Badge, { tone: 'cyan', title: 'Started by a button, not by the model' }, 'you') : null,
      h(Chev, { open })),
    row.status === 'running' && !row.lookup ? h('div', { style: { padding: '0 0 2px 21px' } }, h(ProgressBar, { value: pct, note: row.progress?.note })) : null,
    open ? h('div', { style: { padding: '2px 0 6px 21px' } }, h(Detail, { row, item: row.item, ctx })) : null);
}
const it_by = row => row.item.call?.by === 'user';

function QuietRow({ icon, color, children }) {
  return h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 8, padding: '3px 0', fontSize: 12.5, color: T.mut, minWidth: 0 } },
    h('span', { style: { display: 'flex', color: color || T.dim, flex: 'none', alignSelf: 'center' } }, h(Icon, { d: icon, size: 13 })), h('span', { style: { minWidth: 0, overflowWrap: 'anywhere' } }, children));
}
function QuestionRow({ row }) {
  const it = row.item, qs = it.q?.questions || [], a = it.answer?.answers || {};
  if (!it.answer && !it.result) return h(QuietRow, { icon: 'chat', color: T.pu }, h('span', { style: { color: T.pu } }, `Asked you ${qs.length === 1 ? 'a question' : qs.length + ' questions'}`));
  if (!it.answer) return h(QuietRow, { icon: 'chat' }, 'Asked you a question; you wrote back instead');
  const said = qs.map(q => [q, [].concat(a[q.question] ?? []).filter(x => x !== '' && x != null)]).filter(([, v]) => v.length).map(([q, v]) => `${q.header || q.question}: ${v.join(', ')}`).join(' · ') || 'the defaults';
  return h(QuietRow, { icon: 'chat' }, 'You chose ', h('span', { style: { color: T.tx } }, said));
}

/** The rows of a turn's steps, with their open state. */
function StepList({ turn, ctx }) {
  const React = R(), [open, setOpen] = React.useState(() => new Set());
  const toggle = k => setOpen(s => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const rows = turn.steps.flatMap(s => s.rows);
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 } }, rows.map(row => {
    const k = row.key, p = row.item.ev?.payload || {};
    if (row.type === 'thinking') return h(ThinkRow, { key: k, row, open: open.has(k), onToggle: () => toggle(k) });
    if (row.type === 'update') return h('div', { key: k, style: { padding: '3px 0 3px 21px' } }, h(Md, { text: row.text, caret: row.streaming }));
    if (row.type === 'tool') return h(ToolRow, { key: k, row, ctx, open: open.has(k), onToggle: () => toggle(k) });
    if (row.type === 'question') return h(QuestionRow, { key: k, row });
    if (row.type === 'note') return h(QuietRow, { key: k, icon: p.level === 'warn' || p.level === 'warning' ? 'alert' : 'info', color: p.level === 'warn' || p.level === 'warning' ? T.acct : null }, String(p.text || '').replace(/^./, c => c.toUpperCase()));
    if (row.type === 'memory') return h(QuietRow, { key: k, icon: 'bookmark', color: T.pu }, 'Remembered: ', h('span', { style: { color: T.tx } }, p.text));
    if (row.type === 'todos') return h(QuietRow, { key: k, icon: 'check' }, `Made a plan of ${(row.item.items || []).length} steps`);
    return h('div', { key: k }, h(Card, { item: row.item, ctx }));
  }));
}

/** One turn's fold: closed to start; the header is the live status, then the summary. */
export function ActivityFold({ turn, ctx }) {
  const React = R(), [open, setOpen] = React.useState(false);
  if (!turn.running && !turn.steps.length) return null;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 } },
    h('button', { type: 'button', className: 'aichat-row', onClick: () => setOpen(!open), 'aria-expanded': open ? 'true' : 'false', 'aria-label': open ? 'Hide the steps' : 'Show the steps',
      style: { display: 'block', width: turn.running ? 'calc(100% + 12px)' : 'auto', alignSelf: 'flex-start', padding: '4px 6px', margin: '0 -6px', border: 0, borderRadius: 6, background: 'none', color: 'inherit', font: 'inherit', textAlign: 'left', cursor: 'pointer', minWidth: 0 } },
    h(Header, { turn, ctx, open })),
    open ? h('div', { style: { marginLeft: 6, paddingLeft: 12, borderLeft: '1px solid ' + T.bds } },
      turn.steps.length ? h(StepList, { turn, ctx }) : h('div', { style: { fontSize: 12.5, color: T.mut, padding: '3px 0' } }, 'Nothing yet.')) : null);
}

/** "You ran Upscale image": the head of a turn a result button or quick action started. */
export function ActionHead({ turn, ctx }) {
  const w = stepText(turn.action.call?.name, { args: argsOf(turn.action), ctx: stepCtx(ctx) });
  return h('div', { style: { display: 'flex', justifyContent: 'flex-end' } },
    h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px', borderRadius: 10, background: T.hov, border: '1px solid ' + T.bd, fontSize: 12.5, color: T.mut } },
      h(Icon, { d: w.icon || 'tool', size: 13 }), 'You ran ', h('span', { style: { color: T.tx } }, w.label.replace(/^(\w)/, c => c.toLowerCase()))));
}

/** "Undo this turn" (plan 27.7): every file this turn changed in a workspace folder, back as it was. */
function UndoTurn({ paths, ctx }) {
  const React = R(), [state, setState] = React.useState(null);
  const go = async () => {
    setState('busy');
    try { setState(await ctx.undo(paths)); } catch { setState(null); }
  };
  return h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: T.mut } },
    state === 'undone' ? h('span', null, 'Undone: the files are back as they were before this turn.')
      : h('button', { type: 'button', className: 'aichat-row', disabled: state === 'busy', onClick: go, title: 'Put every file this turn changed back as it was (refused if you changed one since)',
        style: { display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 8px', border: '1px solid ' + T.bds, borderRadius: 6, background: 'none', color: T.mut, font: 'inherit', cursor: 'pointer' } },
        h(Icon, { d: 'undo', size: 12 }), state === 'busy' ? 'Undoing…' : 'Undo this turn'));
}

/** One turn: your message (or "You ran …"), the fold, errors, cards waiting for you, the outputs, the answer. */
export function TurnView({ turn, ctx }) {
  const kids = [
    turn.user ? h(Card, { key: 'u', item: turn.user, ctx }) : h(ActionHead, { key: 'u', turn, ctx }),
    h(ActivityFold, { key: 'f', turn, ctx }),
    ...turn.errors.map(it => h(Card, { key: it.key, item: it, ctx })),
    ...(ctx.dock ? [] : turn.pending.map(it => h(Card, { key: it.key, item: it, ctx }))),
    turn.outputs.length ? h(OutputStrip, { key: 'o', outputs: turn.outputs, ctx }) : null,
    turn.answer ? h(Card, { key: 'a', item: turn.answer.item, ctx }) : null,
    turn.undo?.length && !turn.running && ctx.undo ? h(UndoTurn, { key: 'undo', paths: turn.undo, ctx }) : null,
  ];
  return h(R().Fragment, null, ...kids.filter(Boolean));
}
