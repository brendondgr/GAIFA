// Select → Reply, the reply half (plan 32.2): answer parts of the agent's replies one by one.
// - `QuoteReplyBox`: select text inside one reply and a small box opens next to it: the selection clipped (2 lines)
//   over a one-line "Reply to this…" input that grows. Enter (or the button) adds a quote-reply card to the
//   composer; Shift+Enter is a new line; Escape or a click elsewhere closes it and adds nothing. The selection stays
//   highlighted while you type (CSS Custom Highlight, where the browser has it); Ctrl+C in the empty input copies
//   it. After adding, the next selection opens a new box at once: replying to many parts is select, type, Enter.
// - `QuoteCards`: the cards (~112 px, like file thumbnails): the quote with a bar, the reply, a "Reply" label and
//   × on hover (draft only). Any number of them; the row wraps and scrolls past ~2 rows so the box stays on screen.
// - `QuoteReplyDialog`: a card opens it: the quote as markdown (read-only) and the reply, editable in the composer
//   (Save, Cancel, Remove) and read-only on a sent message ("Go to the quoted reply").
// - Pure helpers (tested in utils/tests/web/quote.test.mjs): the draft list (`addQuote`, `editQuote`, `removeQuote`),
//   `quotesOf` (an event's `quotes`, or an older event's single `quote` as one with no reply), `quotesPayload`,
//   `quotesProblem` (the agent's limits), `canSendQuotes`, `messageText`, `plainPreview`.
// The message carries them as `quotes: [{text, reply, seq?}]` (chat-api.js `send`); the agent puts each before the
// user's text as "About this part of your earlier answer:", a blockquote and "My reply: …" (services/agent/agent/context.py).

import { h, T, Icon, Btn, SHADOW, ON_ACC } from './chat-ui.js';
import { renderMarkdown } from './chat-md.js';
import { selectionQuote, scrollToReply, QUOTE_MAX, QUOTE_ICON } from './chat-quote.js';

const R = () => globalThis.React;
export const REPLY_MAX = 4000;         // characters of one reply (the agent refuses longer)
export const QUOTES_TOTAL = 200000;    // characters of quotes and replies in one message, in all
const fmt = n => n.toLocaleString('en-US');

// ---------- the draft's quote-replies: [{id, text, reply, seq?}] ----------
let nid = 0;
const qid = () => `q${Date.now().toString(36)}${(++nid).toString(36)}`;
const entry = q => ({ id: qid(), text: String(q.text), reply: String(q.reply ?? ''), ...(Number.isInteger(q.seq) && q.seq > 0 ? { seq: q.seq } : {}) });

/** The list with `q` ({text, reply?, seq?}) added at the end; a blank quote adds nothing. No limit on how many. */
export function addQuote(list, q) {
  return q && String(q.text ?? '').trim() ? [...(list || []), entry(q)] : list || [];
}
export const editQuote = (list, id, reply) => (list || []).map(q => (q.id === id ? { ...q, reply: String(reply ?? '') } : q));
export const removeQuote = (list, id) => (list || []).filter(q => q.id !== id);

/** A user event's quote-replies, `[{text, reply, seq?}]`: `quotes`, or an older event's `quote` as one with no reply. */
export function quotesOf(payload) {
  const p = payload || {};
  const raw = Array.isArray(p.quotes) ? p.quotes : p.quote && typeof p.quote === 'object' ? [p.quote] : [];
  return raw.filter(q => q && String(q.text ?? '').trim())
    .map(q => ({ text: String(q.text), reply: String(q.reply ?? ''), ...(Number.isInteger(q.seq) ? { seq: q.seq } : {}) }));
}
/** A sent message's quote-replies as draft cards (Branch from here). */
export const draftQuotes = payload => quotesOf(payload).map(entry);

/** What the send API takes: `[{text, reply, seq?}]`, replies trimmed. */
export const quotesPayload = list => (list || []).map(q => ({ text: q.text, reply: String(q.reply ?? '').trim(), ...(q.seq != null ? { seq: q.seq } : {}) }));

/** Why the agent would refuse these quote-replies, or null. */
export function quotesProblem(list) {
  let total = 0;
  for (const [i, q] of (list || []).entries()) {
    if (q.text.length > QUOTE_MAX) return `Quote ${i + 1} is over ${fmt(QUOTE_MAX)} characters.`;
    if (String(q.reply ?? '').length > REPLY_MAX) return `Your reply ${i + 1} is over ${fmt(REPLY_MAX)} characters.`;
    total += q.text.length + String(q.reply ?? '').length;
  }
  return total > QUOTES_TOTAL ? `These quote-replies are ${fmt(total)} characters in all; at most ${fmt(QUOTES_TOTAL)} go in one message. Send some now and the rest next.` : null;
}
const replied = list => (list || []).some(q => String(q.reply ?? '').trim());

/** A message can go when it says something: its text, a reply to a quoted part, or attachments. */
export const canSendQuotes = (text, attachments, quotes) => !!(String(text || '').trim() || (attachments || []).length || replied(quotes)) && !quotesProblem(quotes);

/** The text to send: as typed; empty with replies; "Here are the attached outputs." when only attachments say something. */
export const messageText = (text, attachments, quotes) => {
  const t = String(text || '').trim();
  return t || replied(quotes) || !(attachments || []).length ? t : 'Here are the attached outputs.';
};

/** Markdown as one line of plain text for a card or the box (markers dropped, links as their text), clipped. */
export function plainPreview(md, max = 160) {
  const s = String(md || '')
    .replace(/^[ \t]*(```|~~~)[^\n]*$/gm, '')
    .replace(/^[ \t]*([-*_])\1{2,}[ \t]*$/gm, '')                                    // a rule
    .replace(/^[ \t]*\|?([ \t]*:?-{3,}:?[ \t]*\|)+[ \t]*:?-{0,}:?[ \t]*\|?[ \t]*$/gm, '')        // a table's rule
    .replace(/^[ \t]{0,3}(#{1,6}|>[> ]*|[-*+]|\d+[.)])[ \t]*/gm, '')                  // heading, quote, list markers
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\*\*|__|~~|`/g, '').replace(/(^|[\s(])[*_](?=\S)|(?<=\S)[*_](?=[\s).,;:!?]|$)/g, '$1')
    .replace(/^[ \t]*\|(.*)\|[ \t]*$/gm, (_, r) => r.split(/(?<!\\)\|/).map(c => c.trim()).filter(Boolean).join(' · '))
    .replace(/\s+/g, ' ').trim();
  return s.length > max ? s.slice(0, max - 1).trimEnd() + '…' : s;
}

export const QREPLY_CSS = `
::highlight(aichat-quote){background-color:rgba(88,196,221,.30)}
.aichat-qcard{position:relative;flex:none}
.aichat-qcard .aichat-qx{opacity:0;transition:opacity .12s}
.aichat-qcard:hover .aichat-qx,.aichat-qcard:focus-within .aichat-qx{opacity:1}
@media (hover:none){.aichat-qcard .aichat-qx{opacity:1}}
.aichat-qcard>button:focus-visible,.aichat-qbox textarea:focus-visible{outline:2px solid var(--cy,#58C4DD);outline-offset:1px}
.aichat-qcard>button:hover{border-color:var(--bdh,#3A4A63)!important}
`;
const clamp = n => ({ display: '-webkit-box', WebkitLineClamp: n, WebkitBoxOrient: 'vertical', overflow: 'hidden', overflowWrap: 'anywhere' });

// ---------- the floating box over a selection ----------
const HL = 'aichat-quote';
function highlight(range) {
  try { const reg = globalThis.CSS?.highlights, H = globalThis.Highlight; if (!reg || !H) return; if (range) reg.set(HL, new H(range)); else reg.delete(HL); } catch { /* no Highlight API */ }
}
const BOX_W = 340, BOX_H = 130;
function place(range) {
  const W = globalThis.innerWidth || 1000, H = globalThis.innerHeight || 800, w = Math.min(BOX_W, W - 16);
  const rects = [...(range.getClientRects?.() || [])].filter(r => r.width);
  const first = rects[0] || range.getBoundingClientRect(), last = rects[rects.length - 1] || first;
  const left = Math.max(8, Math.min(W - w - 8, last.right - w / 2));
  if (last.bottom + 8 + BOX_H < H) return { top: Math.max(8, last.bottom + 8), left, width: w };       // under the selection
  if (first.top - 8 - BOX_H > 0) return { bottom: H - first.top + 8, left, width: w };                 // over it
  return { bottom: 8, left, width: w };                                                                 // it fills the window: at the bottom
}

export function QuoteReplyBox({ scrollRef, onAdd, resetKey }) {
  const React = R(), [box, setBox] = React.useState(null), [reply, setReply] = React.useState('');
  const ref = React.useRef(null), input = React.useRef(null), down = React.useRef(false), add = React.useRef(onAdd), cur = React.useRef(null);
  add.current = onAdd; cur.current = box;
  const close = () => { highlight(null); setBox(null); setReply(''); };
  React.useEffect(() => { if (cur.current) close(); }, [resetKey]);
  React.useEffect(() => {
    const doc = globalThis.document;
    if (!doc) return undefined;
    let t = 0;
    const inBox = n => { const el = n && (n.nodeType === 1 ? n : n.parentNode); return !!(ref.current && el && ref.current.contains(el)); };
    const update = delay => {
      clearTimeout(t);
      t = setTimeout(() => {
        if (down.current || inBox(doc.activeElement)) return;         // a drag still going, or typing in the box
        const sel = doc.getSelection?.(), sc = scrollRef?.current;
        if (sc && sel?.anchorNode && !sc.contains(sel.anchorNode)) return;   // another chat's pane (chat-split plan 1.1)
        const q = selectionQuote(sel, doc);
        if (!q) return;                                                // nothing quotable: a box already open stays
        const range = sel.getRangeAt(0).cloneRange();
        setReply('');
        setBox({ q, range, at: place(range), open: false });             // a Reply button first; the box opens on its click
      }, delay);
    };
    const onDown = e => { if (!inBox(e.target)) { down.current = true; if (cur.current) close(); } };
    const onUp = e => {
      if (!down.current || (e.type === 'mousemove' && e.buttons)) return;   // a drag of the selection ends in dragend
      down.current = false; update(e.detail >= 2 ? 320 : 60);              // a double click may become a triple click
    };
    const onSel = () => { if (!down.current) update(600); };             // a keyboard selection: once it settles
    const onKey = e => { if (e.key === 'Escape' && cur.current) { close(); } };
    const follow = () => { const b = cur.current; if (b) setBox({ ...b, at: place(b.range) }); };
    const sc = scrollRef?.current;
    doc.addEventListener('selectionchange', onSel);
    doc.addEventListener('mousedown', onDown, true);
    for (const k of ['mouseup', 'pointerup', 'dragend', 'mousemove']) doc.addEventListener(k, onUp, true);
    doc.addEventListener('keydown', onKey);
    sc?.addEventListener('scroll', follow, { passive: true });
    globalThis.addEventListener?.('resize', follow);
    return () => {
      clearTimeout(t); highlight(null);
      doc.removeEventListener('selectionchange', onSel); doc.removeEventListener('mousedown', onDown, true);
      for (const k of ['mouseup', 'pointerup', 'dragend', 'mousemove']) doc.removeEventListener(k, onUp, true);
      doc.removeEventListener('keydown', onKey); sc?.removeEventListener('scroll', follow); globalThis.removeEventListener?.('resize', follow);
    };
  }, []);
  (React.useLayoutEffect || React.useEffect)(() => { const el = input.current; if (!el) return; el.style.height = ''; if (el.scrollHeight > el.clientHeight) el.style.height = Math.min(el.scrollHeight + 2, 110) + 'px'; }, [reply]);
  if (!box) return null;
  if (!box.open) {
    const open = () => {
      highlight(box.range);                                            // the input takes the focus, so keep the quote lit
      setBox({ ...box, open: true });
      setTimeout(() => input.current?.focus({ preventScroll: true }), 0);
    };
    return h('button', { ref, type: 'button', className: 'aichat-qbtn', 'data-quote-box': '', onClick: open,
      onMouseDown: e => e.preventDefault(),                            // keep the selection while clicking
      title: 'Reply to this part', 'aria-label': 'Reply to the selected part',
      style: { position: 'fixed', top: box.at.top, left: box.at.left, bottom: box.at.bottom, zIndex: 60, display: 'inline-flex', alignItems: 'center', gap: 5,
        height: 28, padding: '0 10px', borderRadius: 7, border: '1px solid ' + T.bds, background: T.card, color: T.tx, boxShadow: SHADOW,
        font: 'inherit', fontSize: 12.5, cursor: 'pointer' } },
    h(Icon, { d: 'reply', size: 13 }), 'Reply');
  }
  const ok = !!reply.trim();
  const submit = () => {
    if (!ok) return;
    add.current?.({ text: box.q.text, seq: box.q.seq, reply: reply.trim() });
    globalThis.document?.getSelection?.()?.removeAllRanges();
    input.current?.blur();
    close();
  };
  const onKey = e => {
    if (e.nativeEvent?.isComposing) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); return; }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); return; }
    const el = e.target;    // Ctrl+C with nothing selected in the input copies the quoted part (the selection moved here)
    if ((e.ctrlKey || e.metaKey) && (e.key === 'c' || e.key === 'C') && el && el.selectionStart === el.selectionEnd) {
      e.preventDefault(); globalThis.navigator?.clipboard?.writeText(box.range.toString()).catch?.(() => {});
    }
  };
  return h('div', { ref, className: 'aichat-qbox', role: 'dialog', 'aria-label': 'Reply to this part', 'data-quote-box': '',
    style: { position: 'fixed', ...box.at, zIndex: 60, display: 'flex', flexDirection: 'column', gap: 6, padding: 8, borderRadius: 10,
      border: '1px solid ' + T.bds, background: T.card, boxShadow: SHADOW, boxSizing: 'border-box' } },
  h('div', { title: box.q.text, style: { ...clamp(2), fontSize: 11.5, lineHeight: 1.4, color: T.mut, paddingLeft: 7, borderLeft: '2px solid ' + T.bdh } }, plainPreview(box.q.text, 400)),
  h('div', { style: { display: 'flex', alignItems: 'flex-end', gap: 6 } },
    h('textarea', { ref: input, value: reply, rows: 1, maxLength: REPLY_MAX, onChange: e => setReply(e.target.value), onKeyDown: onKey,
      placeholder: 'Reply to this…', 'aria-label': 'Your reply to this part',
      style: { flex: 1, minWidth: 0, minHeight: 28, maxHeight: 110, resize: 'none', padding: '5px 8px', borderRadius: 6, border: '1px solid ' + T.bds,
        background: T.sb, color: T.tx, font: 'inherit', fontSize: 12.5, lineHeight: 1.4, outline: 'none', boxSizing: 'border-box' } }),
    h('button', { type: 'button', onClick: submit, disabled: !ok, title: 'Add to your message (Enter)', 'aria-label': 'Add the reply to your message',
      style: { flex: 'none', width: 28, height: 28, display: 'grid', placeItems: 'center', borderRadius: 6, border: 0, cursor: ok ? 'pointer' : 'not-allowed',
        background: ok ? T.acc : T.hov, color: ok ? ON_ACC : T.dim } }, h(Icon, { d: 'send', size: 14 }))),
  h('div', { style: { fontSize: 10.5, color: T.dim } }, 'Enter adds it to your message · Shift+Enter new line · Esc closes'));
}

// ---------- the cards ----------
export function QuoteCard({ q, onOpen, onRemove }) {
  const reply = String(q.reply ?? '').trim();
  return h('div', { className: 'aichat-qcard', 'data-quote-card': q.seq ?? '' },
    h('button', { type: 'button', onClick: onOpen, title: 'Open this reply', 'aria-label': `Reply to “${plainPreview(q.text, 60)}”${reply ? `: ${plainPreview(reply, 60)}` : ''}`,
      style: { width: 112, height: 112, display: 'flex', flexDirection: 'column', gap: 5, padding: 7, borderRadius: 8, border: '1px solid ' + T.bd, background: T.inset,
        color: T.tx, font: 'inherit', textAlign: 'left', cursor: 'pointer', boxSizing: 'border-box', overflow: 'hidden' } },
    h('span', { style: { ...clamp(3), fontSize: 10.5, lineHeight: 1.35, color: T.mut, paddingLeft: 5, borderLeft: '2px solid ' + T.bdh, flex: 'none' } }, plainPreview(q.text, 140)),
    h('span', { style: { ...clamp(3), fontSize: 11.5, lineHeight: 1.35, flex: 1, minHeight: 0, color: reply ? T.tx : T.dim, fontStyle: reply ? 'normal' : 'italic' } }, reply ? plainPreview(reply, 140) : 'No reply'),
    h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10, fontWeight: 600, color: T.mut, flex: 'none' } }, h(Icon, { d: QUOTE_ICON, size: 10 }), 'Reply')),
  onRemove ? h('button', { type: 'button', className: 'aichat-qx', onClick: onRemove, title: 'Remove this reply', 'aria-label': 'Remove this reply',
    style: { position: 'absolute', top: -6, right: -6, width: 20, height: 20, display: 'grid', placeItems: 'center', borderRadius: 99, border: '1px solid ' + T.bds,
      background: T.card, color: T.mut, cursor: 'pointer', padding: 0 } }, h(Icon, { d: 'x', size: 10 })) : null);
}

/** The row of cards: wraps, and scrolls past ~2 rows (`max`) so many of them never push the text box off screen. */
export function QuoteCards({ quotes, onOpen, onRemove, max = 'min(248px, 32vh)', label = 'Replies to parts of earlier answers' }) {
  if (!quotes?.length) return null;
  return h('div', { role: 'group', 'aria-label': `${label} (${quotes.length})`, 'data-quote-cards': quotes.length,
    style: { display: 'flex', flexWrap: 'wrap', gap: 8, padding: '6px 6px 2px 0', maxHeight: max, overflowY: 'auto', minWidth: 0 } },
  quotes.map((q, i) => h(QuoteCard, { key: q.id || i, q, onOpen: () => onOpen?.(i), onRemove: onRemove ? () => onRemove(i) : null })));
}

// ---------- the Reply popup ----------
const FOCUSABLE = 'button:not([disabled]), textarea, a[href], [tabindex]:not([tabindex="-1"])';
export function QuoteReplyDialog({ q, editable, onSave, onRemove, onClose, ctx }) {
  const React = R(), [reply, setReply] = React.useState(String(q?.reply ?? '')), panel = React.useRef(null), area = React.useRef(null);
  const html = React.useMemo(() => renderMarkdown(q?.text || ''), [q?.text]);
  React.useEffect(() => {
    const back = globalThis.document?.activeElement;
    setTimeout(() => (area.current || panel.current?.querySelector?.(FOCUSABLE))?.focus?.(), 0);
    const k = e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onClose?.(); } };
    globalThis.addEventListener?.('keydown', k, true);
    return () => { globalThis.removeEventListener?.('keydown', k, true); back?.focus?.({ preventScroll: true }); };
  }, []);
  if (!q) return null;
  const ok = !!reply.trim() && reply.length <= REPLY_MAX;
  const save = () => { if (ok) { onSave?.(reply.trim()); onClose?.(); } };
  const trap = e => {     // Tab stays inside the popup
    if (e.key !== 'Tab' || !panel.current) return;
    const f = [...panel.current.querySelectorAll(FOCUSABLE)];
    if (!f.length) return;
    const i = f.indexOf(globalThis.document?.activeElement);
    if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); } else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); }
  };
  const go = q.seq != null ? () => { onClose?.(); (ctx?.scrollToReply || scrollToReply)(q.seq); } : null;
  const el = h('div', { onMouseDown: e => { if (e.target === e.currentTarget) onClose?.(); }, 'data-quote-dialog': editable ? 'edit' : 'view',
    style: { position: 'fixed', inset: 0, zIndex: 70, background: T.ov, display: 'grid', placeItems: 'center', padding: 12 } },
  h('div', { ref: panel, role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Reply', onKeyDown: trap,
    style: { width: 'min(560px, 100%)', maxHeight: 'min(80vh, 640px)', display: 'flex', flexDirection: 'column', gap: 10, padding: 14, borderRadius: 12,
      border: '1px solid ' + T.bds, background: T.card, boxShadow: SHADOW, boxSizing: 'border-box', minWidth: 0 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
      h('span', { style: { color: T.mut, display: 'flex' } }, h(Icon, { d: QUOTE_ICON, size: 14 })),
      h('h3', { style: { margin: 0, flex: 1, fontSize: 14, fontWeight: 600 } }, 'Reply'),
      h(Btn, { kind: 'ghost', sm: true, icon: 'x', title: 'Close', onClick: onClose })),
    h('div', { className: 'aichat-quote', style: { minHeight: 0, overflowY: 'auto', flex: '0 1 auto', maxHeight: '40vh' } },
      h('div', { className: 'aichat-md', 'aria-label': 'The quoted part', onClick: e => {
        const a = e.target?.closest?.('a[data-cite]');
        if (a) { e.preventDefault(); ctx?.openCite?.({ ref: a.dataset.cite, page: a.dataset.page, line: a.dataset.line }); }
      }, style: { padding: '2px 0 2px 10px', borderLeft: '3px solid ' + T.bdh, minWidth: 0 }, dangerouslySetInnerHTML: { __html: html } })),
    editable
      ? h('textarea', { ref: area, value: reply, maxLength: REPLY_MAX, rows: 4, 'aria-label': 'Your reply',
        onChange: e => setReply(e.target.value),
        onKeyDown: e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); } },
        placeholder: 'Your reply to this part…',
        style: { width: '100%', minHeight: 84, maxHeight: '30vh', resize: 'vertical', padding: '8px 10px', borderRadius: 8, border: '1px solid ' + T.bds, background: T.sb,
          color: T.tx, font: 'inherit', fontSize: 13, lineHeight: 1.5, outline: 'none', boxSizing: 'border-box' } })
      : h('div', { style: { whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', fontSize: 13, lineHeight: 1.5, color: q.reply?.trim() ? T.tx : T.dim, fontStyle: q.reply?.trim() ? 'normal' : 'italic', overflowY: 'auto', maxHeight: '30vh' } },
        q.reply?.trim() || 'No reply: the message below answers it.'),
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
      editable && onRemove ? h(Btn, { kind: 'ghost', sm: true, icon: 'trash', label: 'Remove', title: 'Remove this reply from your message', onClick: () => { onRemove(); onClose?.(); }, style: { color: T.rd } }) : null,
      !editable && go ? h(Btn, { kind: 'ghost', sm: true, icon: 'ext', label: 'Go to the quoted reply', onClick: go }) : null,
      h('span', { style: { flex: 1 } }),
      editable ? h(Btn, { sm: true, label: 'Cancel', onClick: onClose }) : null,
      editable ? h(Btn, { kind: 'pri', sm: true, label: 'Save', title: 'Save (Ctrl+Enter)', disabled: !ok, onClick: save }) : h(Btn, { sm: true, label: 'Close', onClick: onClose }))));
  const RD = globalThis.ReactDOM, body = globalThis.document?.body;
  return RD?.createPortal && body ? RD.createPortal(el, body) : el;
}

/** A sent message's quote-replies: the cards, and the read-only popup. */
export function SentQuotes({ payload, ctx }) {
  const React = R(), [open, setOpen] = React.useState(null), qs = quotesOf(payload);
  if (!qs.length) return null;
  return h(React.Fragment, null,
    h(QuoteCards, { quotes: qs, onOpen: setOpen, max: 'none', label: 'Replies to parts of earlier answers' }),
    open != null && qs[open] ? h(QuoteReplyDialog, { q: qs[open], editable: false, ctx, onClose: () => setOpen(null) }) : null);
}
