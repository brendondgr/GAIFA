// The CARD REGISTRY (plan 14.1): every item in a thread (chat-thread.js `buildView`) is drawn by
// the card registered for its `kind`. A new event type or a product with its own look needs only:
//
//   registerCard('my_event', ({ item, ctx }) => h('div', null, item.ev.payload.text));
//   registerCard('step:gen3d_make_3d', MyStepDetail);   // one tool's opened step in the activity fold (chat-activity.js)
//   registerCard('approval:gen3d_make_3d', MyParamCard); // one tool's parameter card
//   registerCard('result:gen3d_make_3d', MyResultCard); // one tool's result card
//
// Lookup: `<kind>:<tool name>` → `<kind>` → the generic card (a collapsed JSON view). Every card
// renders inside an error boundary, so a broken or unknown card never breaks the thread.
// Props: { item, ctx } — ctx is the page's context (see chat.js `cardCtx`).

import { h, T, MONO, Icon, Btn, Badge, cardSt, label11 } from './chat-ui.js';
import { renderMarkdown } from './chat-md.js';
import { todosOpen } from './chat-thread.js';
import { SentQuotes, quotesOf } from './chat-quote-reply.js';
import { ReplyBar } from './chat-replybar.js';

const R = () => globalThis.React;
const cards = new Map();

export function registerCard(kind, Component) {
  if (!kind || typeof Component !== 'function') throw new Error('registerCard(kind, Component)');
  cards.set(kind, Component);
  return () => cards.delete(kind);
}
export function cardFor(item) {
  const name = item.call?.name || item.result?.name;
  return (name && cards.get(`${item.kind}:${name}`)) || cards.get(item.kind) || GenericCard;
}
export const hasCard = kind => cards.has(kind);

let Boundary = null;
function boundary() {
  if (Boundary) return Boundary;
  const React = R();
  Boundary = class CardBoundary extends React.Component {
    constructor(p) { super(p); this.state = { error: null }; }
    static getDerivedStateFromError(error) { return { error }; }
    componentDidCatch(e) { console.error('[chat] card failed:', this.props.item?.kind, e); }
    render() {
      if (this.state.error) return h(GenericCard, { item: this.props.item, ctx: this.props.ctx, note: `This card failed to draw (${this.state.error.message || this.state.error}).` });
      return this.props.children;
    }
  };
  return Boundary;
}

/** One thread item, drawn by its registered card inside an error boundary. */
export function Card({ item, ctx }) {
  return h(boundary(), { item, ctx }, h(cardFor(item), { item, ctx }));
}

// ---------- the CSS the cards share (injected once by chat.js) ----------
export const CARD_CSS = `
.aichat-hov{opacity:0;transition:opacity .12s}
.aichat-user:hover .aichat-hov,.aichat-user:focus-within .aichat-hov{opacity:1}
@media (hover:none){.aichat-hov{opacity:1}}
.aichat-caret::after{content:'';display:inline-block;width:7px;height:13px;margin-left:2px;vertical-align:-2px;background:var(--mut,#8A94A6);animation:aichatblink 1s steps(2) infinite}
@keyframes aichatblink{50%{opacity:0}}
@keyframes aichatpulse{0%,100%{opacity:1}50%{opacity:.35}}
@keyframes aichatbar{0%{transform:translateX(-100%)}100%{transform:translateX(250%)}}
.aichat-opt:hover{border-color:var(--bdh,#3A4A63)!important}
.aichat-opt:focus-visible{outline:2px solid var(--cy,#58C4DD);outline-offset:1px}
`;

// ---------- small shared bits ----------
export function Collapse({ label, open, onToggle, children, right }) {
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 } },
    h('button', { type: 'button', onClick: onToggle, 'aria-expanded': open ? 'true' : 'false', style: { display: 'flex', alignItems: 'center', gap: 6, padding: 0, border: 0, background: 'none', color: T.mut, font: 'inherit', fontSize: 12, cursor: 'pointer', textAlign: 'left', minWidth: 0 } },
      h(Icon, { d: open ? 'chevD' : 'chevR', size: 12 }), h('span', { style: { minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, label), right || null),
    open ? children : null);
}
export const pre = (text, o = {}) => h('pre', { style: { margin: 0, padding: '8px 10px', borderRadius: 6, background: T.inset, border: '1px solid ' + T.bd, fontFamily: MONO, fontSize: 11.5,
  lineHeight: 1.5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: o.max || 260, overflow: 'auto', color: o.color || T.tx } }, text);
const json = v => { try { return typeof v === 'string' ? JSON.stringify(JSON.parse(v), null, 2) : JSON.stringify(v, null, 2); } catch { return String(v); } };
export const STATUS = { running: ['accent', 'running'], waiting: ['purple', 'waiting'], done: ['green', 'done'], error: ['red', 'error'], denied: ['red', 'denied'], cancelled: ['dim', 'stopped'], skipped: ['dim', 'skipped'] };

// ---------- user ----------
function UserCard({ item, ctx }) {
  const p = item.ev.payload, atts = p.attachments || [];
  return h('div', { className: 'aichat-user', style: { display: 'flex', justifyContent: 'flex-end', alignItems: 'flex-start', gap: 6, minWidth: 0 } },
    h('div', { className: 'aichat-hov', style: { display: 'flex', gap: 2, paddingTop: 3 } },
      ctx.branch ? h(Btn, { kind: 'ghost', sm: true, icon: 'branch', title: 'Branch from here: a new chat up to this message, with it in the box to edit', onClick: () => ctx.branch(item) }) : null,
      h(Btn, { kind: 'ghost', sm: true, icon: 'copy', title: 'Copy', onClick: () => ctx.copy?.(userCopy(p)) })),
    h('div', { style: { maxWidth: 'min(85%, 620px)', minWidth: 0, padding: '7px 11px', borderRadius: 10, background: T.hov, border: '1px solid ' + T.bd, display: 'flex', flexDirection: 'column', gap: 6 } },
      h(SentQuotes, { payload: p, ctx }),    // Select → Reply: the parts of replies this answers, and the user's reply to each
      p.text ? h('div', { style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } }, p.text) : null,
      atts.length ? h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 4 } }, atts.map(id => h(AttachmentChip, { key: id, id, ctx, doc: (p.docs || []).find(d => d.id === id) }))) : null,
      // plan 24.9: a document asked for whole that didn't fit says so here, where the user looks
      ...(p.docs || []).filter(d => d.fallback).map(d => h('div', { key: 'fb' + d.id, role: 'note', 'data-fallback': d.id,
        style: { display: 'flex', gap: 6, alignItems: 'flex-start', fontSize: 11.5, color: T.acct } }, h(Icon, { d: 'alert', size: 12, style: { marginTop: 2, flex: 'none' } }), h('span', null, d.fallback))),
      item.queued ? h('div', null, h(Badge, { tone: 'purple', title: 'Sent during a turn: the agent reads it after the current step' }, 'queued')) : null));
}
/** A user message as copied: each quote-reply (the part as a blockquote, then the reply), then the text. */
export function userCopy(p) {
  const qs = quotesOf(p).map(q => `${q.text.split('\n').map(l => (l ? '> ' + l : '>')).join('\n')}${q.reply.trim() ? '\n\n' + q.reply.trim() : ''}`);
  return [...qs, ...(p.text ? [p.text] : [])].join('\n\n');
}
function AttachmentChip({ id, ctx, doc }) {
  const o = ctx.outputs?.find(x => x.output_id === id);
  const how = doc ? (doc.inline ? 'whole' : 'card') : null;   // plan 24.9: how the document went to the model
  return h('span', { title: o?.title || id, style: { display: 'inline-flex', alignItems: 'center', gap: 5, height: 22, padding: '0 7px 0 3px', borderRadius: 5, background: T.inset, border: '1px solid ' + T.bd, fontSize: 11.5, color: T.mut, maxWidth: 260 } },
    o?.preview ? h('img', { src: o.preview, alt: '', style: { width: 16, height: 16, objectFit: 'cover', borderRadius: 3 } }) : h(Icon, { d: 'clip', size: 12 }),
    h('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, o ? `#${o.n} ${o.title || ''}` : id),
    how ? h('span', { title: how === 'whole' ? 'Sent whole: the model has all of it' : 'Sent as a card: the agent reads it in parts', style: { fontFamily: MONO, fontSize: 10, color: T.dim } }, how) : null);
}

// ---------- assistant ----------
// ---------- thumbs (plan 21.7): up or down on an output or a reply; the agent learns from them ----------
export function Thumbs({ ctx, target, label = 'this' }) {
  const React = R(), [got, setGot] = React.useState(null);
  if (!ctx?.feedback || (!target.output_id && target.seq == null)) return null;
  const send = value => ctx.feedback({ ...target, value }).then(() => setGot(value), () => {});
  const b = (v, title) => h('button', { type: 'button', onClick: () => send(v), title, 'aria-label': title, 'aria-pressed': got === v ? 'true' : 'false',
    style: { display: 'grid', placeItems: 'center', width: 24, height: 24, border: 0, borderRadius: 5, cursor: 'pointer', background: got === v ? T.tpu : 'none', color: got === v ? T.pu : T.dim } },
  h(Icon, { d: v, size: 13 }));
  return h('span', { style: { display: 'inline-flex', gap: 2 } }, b('up', `Good: more like ${label}`), b('down', `Not good: less like ${label}`));
}

function AssistantCard({ item, ctx }) {
  const React = R(), text = item.ev.payload.text || '';
  const html = React.useMemo(() => renderMarkdown(text), [text]);
  const onClick = e => {   // plan 24.7: citation links open the viewer
    const a = e.target?.closest?.('a[data-cite]');
    if (!a) return;
    e.preventDefault();
    ctx?.openCite?.({ ref: a.dataset.cite, page: a.dataset.page, line: a.dataset.line });
  };
  const md = h('div', { className: 'aichat-md' + (item.streaming ? ' aichat-caret' : ''), style: { fontSize: 13, padding: '0 2px' }, onClick, dangerouslySetInnerHTML: { __html: html } });
  if (item.streaming || item.ev.seq == null || !text.trim() || ctx?.turn?.running) return md;
  // the reply bar: Sources, Copy (three ways), thumbs (chat-replybar.js)
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 2 } }, md,
    h(ReplyBar, { text, ctx, thumbs: h(Thumbs, { ctx, target: { seq: item.ev.seq }, label: 'this reply' }) }));
}

// ---------- a proposal from the miner (plan 21.5, 21.7): a preference it noticed, to approve here ----------
function ProposalCard({ item, ctx }) {
  const React = R(), [done, setDone] = React.useState({});
  const prefs = item.ev.payload.prefs || [];
  const what = p => (p.tool ? `${p.tool.replace(/_/g, ' ')}: ${p.field} = ${typeof p.value === 'string' ? p.value : JSON.stringify(p.value)}` : String(p.value));
  const decide = (p, ok) => ctx.decidePref?.(p.id, ok).then(() => setDone(d => ({ ...d, [p.id]: ok ? 'active' : 'rejected' })), () => {});
  return h('div', { style: cardSt({ pad: '8px 10px', gap: 6 }) },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, color: T.mut } }, h(Icon, { d: 'bulb', size: 13 }), 'I noticed what you usually choose. Use it from now on?'),
    prefs.map(p => h('div', { key: p.id, style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 12.5 } },
      h('span', { style: { flex: 1, minWidth: 160, overflowWrap: 'anywhere' } }, what(p), p.cue ? h('span', { style: { color: T.dim } }, ` · ${p.cue}`) : null),
      done[p.id] ? h('span', { style: { color: T.mut } }, done[p.id] === 'active' ? 'Saved: it fills your cards now' : 'Not used')
        : [h(Btn, { key: 'y', sm: true, kind: 'pri', label: 'Use it', onClick: () => decide(p, true) }),
           h(Btn, { key: 'n', sm: true, kind: 'ghost', label: 'Not now', onClick: () => decide(p, false) })])));
}
registerCard('proposal', ProposalCard);
registerCard('feedback', () => null);       // thumbs show on what they rate, not as a row of their own

// ---------- thinking: one folded line per step, only with Show thinking on ----------
// ---------- tool ----------
export function ProgressBar({ value, note }) {
  const known = value != null;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 3 } },
    h('div', { role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': known ? Math.round(value * 100) : undefined, style: { height: 4, borderRadius: 9, background: T.row, overflow: 'hidden', position: 'relative' } },
      h('span', { style: known ? { display: 'block', height: '100%', width: `${Math.max(2, value * 100)}%`, background: T.acc, borderRadius: 9, transition: 'width .4s ease' }
        : { position: 'absolute', top: 0, bottom: 0, width: '40%', background: T.acc, borderRadius: 9, animation: 'aichatbar 1.4s ease-in-out infinite' } })),
    note ? h('div', { style: { fontSize: 11.5, color: T.mut, fontFamily: MONO } }, note) : null);
}
export function ErrorBox({ error }) {
  return h('div', { role: 'alert', style: { display: 'flex', flexDirection: 'column', gap: 3, padding: '7px 9px', borderRadius: 6, background: T.trd, color: T.tx, fontSize: 12.5 } },
    h('div', { style: { display: 'flex', gap: 6, alignItems: 'baseline', minWidth: 0 } }, error.code ? h(Badge, { tone: 'red', mono: true }, error.code) : null, h('span', { style: { overflowWrap: 'anywhere' } }, error.detail || String(error))),
    error.fix ? h('div', { style: { color: T.mut, fontSize: 12 } }, 'Fix: ', error.fix) : null);
}

// ---------- todos (inline where they first appeared; chat.js pins the latest list on top) ----------
export function TodoList({ items, compact }) {
  const icon = s => s === 'done' ? h('span', { style: { color: T.gr, display: 'flex' } }, h(Icon, { d: 'check', size: 13, sw: 2.2 }))
    : s === 'failed' ? h('span', { style: { color: T.rd, display: 'flex' } }, h(Icon, { d: 'x', size: 13, sw: 2.2 }))
      : h('span', { style: { width: 11, height: 11, margin: 1, borderRadius: 99, border: '1.5px solid ' + (s === 'in_progress' ? T.acc : T.bdh), background: s === 'in_progress' ? T.tacc : 'none', animation: s === 'in_progress' ? 'aichatpulse 1.4s ease-in-out infinite' : 'none', flex: 'none' } });
  return h('ul', { style: { listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: compact ? 'row' : 'column', flexWrap: 'wrap', gap: compact ? '4px 14px' : 4 } },
    (items || []).map((t, i) => h('li', { key: i, style: { display: 'flex', alignItems: 'center', gap: 7, fontSize: 12.5, color: t.state === 'done' ? T.mut : T.tx, textDecoration: t.state === 'done' && !compact ? 'line-through' : 'none' } }, icon(t.state), t.text)));
}
function TodosCard({ item }) {
  const done = (item.items || []).filter(t => t.state === 'done').length;
  return h('div', { style: cardSt({ pad: '8px 10px', gap: 6 }) },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } }, h('span', { style: label11 }, 'Plan'), h('span', { style: { fontSize: 11.5, color: T.mut, fontFamily: MONO } }, `${done}/${(item.items || []).length}`),
      todosOpen(item.items) ? null : h(Badge, { tone: 'green' }, 'done')),
    h(TodoList, { items: item.items }));
}

// ---------- memory, note, error, compact ----------
function MemoryCard({ item }) {
  const p = item.ev.payload;
  return h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: T.mut, padding: '0 2px' } },
    h('span', { style: { color: T.pu, display: 'flex' } }, h(Icon, { d: 'bookmark', size: 13 })),
    h('span', { style: { minWidth: 0, overflowWrap: 'anywhere' } }, h('span', { style: { color: T.tx } }, 'Remembered: '), p.text),
    p.topic ? h(Badge, null, p.topic) : null);
}
function NoteCard({ item }) {
  const p = item.ev.payload, warn = p.level === 'warn' || p.level === 'warning';
  return h('div', { style: { display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, fontSize: 12, color: warn ? T.acct : T.mut } },
    h(Icon, { d: warn ? 'alert' : 'info', size: 12 }), h('span', null, p.text));
}
function ErrorCard({ item }) {
  return h('div', { style: cardSt({ accent: T.rd, pad: '8px 10px', gap: 6 }) },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, color: T.rd, fontWeight: 600 } }, h(Icon, { d: 'alert', size: 14 }), 'Something went wrong'),
    h(ErrorBox, { error: item.ev.payload }));
}
function CompactCard({ item }) {
  const React = R(), [open, setOpen] = React.useState(false), p = item.ev.payload, summary = p.stage === 'summary';
  const line = h('span', { style: { flex: 1, height: 1, background: T.bd } });
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 10, color: T.mut, fontSize: 11.5 } }, line,
      h('button', { type: 'button', onClick: () => summary && setOpen(!open), style: { display: 'inline-flex', alignItems: 'center', gap: 6, border: 0, background: 'none', padding: 0, color: T.mut, font: 'inherit', fontSize: 11.5, cursor: summary ? 'pointer' : 'default' } },
        h(Icon, { d: 'compress', size: 12 }), summary ? 'Earlier messages summarized' : `Older tool results cleared${p.cleared ? ` (${p.cleared.length})` : ''}`, summary ? h(Icon, { d: open ? 'chevD' : 'chevR', size: 11 }) : null), line),
    open && p.summary ? h('div', { style: { fontSize: 12, color: T.mut, padding: '6px 10px', borderLeft: '2px solid ' + T.bds, whiteSpace: 'pre-wrap' } }, p.summary) : null);
}

// ---------- the fallback: any event type nobody registered ----------
export function GenericCard({ item, note }) {
  const React = R(), [open, setOpen] = React.useState(false), ev = item.ev || {};
  return h('div', { style: cardSt({ pad: '6px 10px', gap: 6, style: { borderStyle: 'dashed' } }) },
    note ? h('div', { style: { fontSize: 12, color: T.acct } }, note) : null,
    h(Collapse, { label: h('span', null, h('span', { style: { fontFamily: MONO } }, ev.type || item.kind), ' event'), open, onToggle: () => setOpen(!open) }, pre(json(ev.payload ?? ev))));
}

registerCard('user', UserCard);
registerCard('assistant', AssistantCard);
registerCard('todos', TodosCard);
registerCard('memory', MemoryCard);
registerCard('note', NoteCard);
registerCard('error', ErrorCard);
registerCard('compact', CompactCard);
