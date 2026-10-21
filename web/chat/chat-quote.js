// Select → Reply: select part of an agent's reply, press Reply, and the next message answers that part.
// - The selection is turned back into **markdown** (`selectionQuote`): the part of the rendered reply
//   (chat-md.js `renderMarkdown`) between the selection's two ends is cut out of the DOM as a plain tree
//   (`clipTree`, which keeps the ancestors: a selection inside a bold word inside a list item stays
//   `- **word**`), then written as markdown (`htmlToMarkdown`) for the renderer's own tags: paragraphs and
//   line breaks, bold, italic, strikethrough, inline code, fenced code with its language (the header bar
//   left out), lists (numbered from where the selection starts), quotes, headings (h3 → `#`: the renderer
//   shifts levels by 2), rules, links, citations (as written: `#3 p.14`) and pipe tables with alignment.
//   A selection across table cells quotes the rows it touches, whole, under the table's header; one inside
//   a single cell quotes just the text. Part of one line of a code block is inline code.
// - `QuoteButton`: the floating "Reply" button over a selection inside one reply (a `[data-quote-seq]`
//   element around an `.aichat-md`); hidden on deselect, scroll and Escape.
// - `QuoteChip`: the quote above the composer's box (one at a time; Reply again replaces it).
// - `QuoteBlock`: the quote on the user's message (clipped to ~6 lines, "Show more"; a click scrolls to the reply).
// The message carries it as `quote: {text, seq}` (chat-api.js `send`); the agent puts it before the
// user's words as a blockquote (services/agent/agent/context.py `with_quote`).

import { h, T, Icon } from './chat-ui.js';
import { renderMarkdown } from './chat-md.js';

const R = () => globalThis.React;
export const QUOTE_MAX = 8000;         // characters (the agent refuses longer)
export const QUOTE_ICON = 'M9.5 7H6.5A1.5 1.5 0 0 0 5 8.5v3A1.5 1.5 0 0 0 6.5 13H9v1c0 1.5-1 2.5-2.5 3M18.5 7h-3A1.5 1.5 0 0 0 14 8.5v3a1.5 1.5 0 0 0 1.5 1.5H18v1c0 1.5-1 2.5-2.5 3';

// ---------- a DOM (or a stand-in) → a plain tree: {tag, attrs, children, orig} | {text, orig} ----------
const ATTRS = ['class', 'href', 'style', 'data-lang', 'data-cite', 'start'];
const attrsOf = n => {
  const a = {};
  for (const k of ATTRS) { const v = n.getAttribute?.(k); if (v != null) a[k] = v; }
  return a;
};
const kids = n => Array.from(n.childNodes || []);

/** A whole DOM node as a plain tree. */
export function toPlain(n) {
  if (!n) return null;
  if (n.tag !== undefined || n.text !== undefined) return n;                // already plain
  if (n.nodeType === 3) return { text: n.nodeValue || '', orig: n };
  if (n.nodeType !== 1 && n.nodeType !== 11) return null;
  return { tag: n.nodeType === 11 ? '#root' : n.nodeName.toLowerCase(), attrs: n.nodeType === 1 ? attrsOf(n) : {},
    children: kids(n).map(toPlain).filter(Boolean), orig: n };
}

function pathTo(root, node) {
  const p = [];
  for (let n = node; n !== root; n = n.parentNode) {
    if (!n || !n.parentNode) return null;
    p.unshift(kids(n.parentNode).indexOf(n));
  }
  return p;
}

/** The part of `root` between two boundary points ({node, offset}, as a DOM Range has them) as a plain
 *  tree that keeps every ancestor of what's selected; null when a point isn't inside `root`. */
export function clipTree(root, start, end) {
  const sp = pathTo(root, start.node), ep = pathTo(root, end.node);
  if (!sp || !ep) return null;
  const clip = (n, s, e) => {
    if (n.nodeType === 3) { const t = n.nodeValue || ''; return { text: t.slice(s ? s[0] : 0, e ? e[0] : t.length), orig: n }; }
    if (n.nodeType !== 1) return null;
    const c = kids(n);
    let lo = 0, hi = c.length - 1, loDeep = null, hiDeep = null;
    if (s) { lo = s[0]; if (s.length > 1) loDeep = s.slice(1); }
    if (e) { if (e.length > 1) { hi = e[0]; hiDeep = e.slice(1); } else hi = e[0] - 1; }
    const children = [];
    for (let i = lo; i <= hi; i++) { const x = clip(c[i], i === lo ? loDeep : null, i === hi ? hiDeep : null); if (x) children.push(x); }
    return { tag: n.nodeName.toLowerCase(), attrs: attrsOf(n), children, orig: n };
  };
  return fixClip(clip(root, [...sp, start.offset], [...ep, end.offset]));
}

const textOf = n => (n == null ? '' : n.text !== undefined ? n.text : (n.children || []).map(textOf).join(''));
const all = (n, pred, out = []) => { if (n && n.tag !== undefined) { if (pred(n)) out.push(n); n.children.forEach(c => all(c, pred, out)); } return out; };
const origKids = (n, tags) => kids(n).filter(c => c.nodeType === 1 && tags.includes(c.nodeName.toLowerCase()));

// After clipping: a numbered list starts at its first selected item; a selection across table cells becomes
// the touched rows, whole, under the header (one cell: just its text); part of a line of code is inline code.
function fixClip(n) {
  if (!n || n.tag === undefined) return n;
  n.children = n.children.map(fixClip).filter(Boolean);
  if (n.tag === 'ul' || n.tag === 'ol') n.children = n.children.filter(c => c.tag !== 'li' || textOf(c).trim());
  if (n.tag === 'ol' && n.orig && n.children[0]?.orig) {
    const i = origKids(n.orig, ['li']).indexOf(n.children[0].orig);
    if (i > 0) n.attrs = { ...n.attrs, start: String(i + 1) };
  }
  if (n.tag === 'table' && n.orig) {
    const cells = all(n, x => (x.tag === 'td' || x.tag === 'th') && textOf(x).trim());
    if (cells.length <= 1) return { tag: 'p', attrs: {}, children: cells[0] ? cells[0].children : [] };
    const rows = all(n, x => x.tag === 'tr').filter(r => textOf(r).trim()).map(r => r.orig);
    const thead = origKids(n.orig, ['thead'])[0], head = thead ? origKids(thead, ['tr'])[0] : null;
    const body = rows.filter(r => r && r !== head);
    return { tag: 'table', attrs: {}, children: [
      ...(head ? [{ tag: 'thead', attrs: {}, children: [toPlain(head)] }] : []),
      { tag: 'tbody', attrs: {}, children: body.map(toPlain) }] };
  }
  if (n.tag === 'pre' && n.orig) {
    const t = textOf(n);
    if (!t.includes('\n') && (n.orig.textContent ?? textOf(toPlain(n.orig))).replace(/\n$/, '').includes('\n'))
      return t.trim() ? { tag: 'p', attrs: {}, children: [{ tag: 'code', attrs: {}, children: [{ text: t.trim() }] }] } : null;
  }
  return n;
}

// ---------- a plain tree → markdown ----------
const BLOCK = new Set(['p', 'div', 'ul', 'ol', 'li', 'blockquote', 'pre', 'hr', 'table', 'thead', 'tbody', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', '#root', 'section']);
const cls = n => ` ${n.attrs?.class || ''} `;
const skip = n => n.tag === 'button' || cls(n).includes(' aichat-code-bar ');

function wrap(inner, mark) {
  const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(inner);
  return m[2] ? `${m[1]}${mark}${m[2]}${mark}${m[3]}` : inner;
}
function inline(n) {
  if (n.text !== undefined) return n.text;
  if (skip(n)) return '';
  const inner = () => n.children.map(inline).join('');
  switch (n.tag) {
    case 'br': return '\n';
    case 'strong': case 'b': return wrap(inner(), '**');
    case 'em': case 'i': return wrap(inner(), '*');
    case 'del': case 's': return wrap(inner(), '~~');
    case 'code': { const t = textOf(n); if (!t) return ''; const f = t.includes('`') ? '``' : '`'; return f + (f === '``' ? ` ${t} ` : t) + f; }
    case 'a': {
      const text = inner(), href = n.attrs?.href;
      if (cls(n).includes(' aichat-cite ') || !href || href === '#') return text;
      return text === href ? href : text.trim() ? `[${text}](${href})` : '';
    }
    default: return BLOCK.has(n.tag) ? blocks(n).join(' ') : inner();
  }
}
const prefix = (text, first, rest) => text.split('\n').map((l, i) => (i ? (l ? rest + l : '') : first + l)).join('\n');

function list(n, ordered) {
  let k = ordered ? Math.max(1, parseInt(n.attrs?.start, 10) || 1) : 0;
  return n.children.filter(c => c.tag === 'li').map(li => {
    const marker = ordered ? `${k++}. ` : '- ';
    const body = blocks(li).join('\n') || '';
    return prefix(body, marker, ' '.repeat(marker.length));
  }).join('\n');
}
function fence(n) {
  const code = n.children.find(c => c.tag === 'code');
  const lang = n.attrs?.['data-lang'] || (/language-([\w+#.-]+)/.exec(code?.attrs?.class || '') || [])[1] || '';
  const text = textOf(n).replace(/\n$/, '');
  const f = /```/.test(text) ? (/~~~/.test(text) ? '````' : '~~~') : '```';
  return `${f}${lang}\n${text}\n${f}`;
}
function tableMd(n) {
  const rows = all(n, x => x.tag === 'tr');
  if (!rows.length) return '';
  const cellsOf = r => r.children.filter(c => c.tag === 'td' || c.tag === 'th');
  const head = cellsOf(rows[0]), width = Math.max(...rows.map(r => cellsOf(r).length));
  const cell = c => (c ? inline(c).replace(/\s*\n\s*/g, ' ').trim().replace(/\|/g, '\\|') : '');
  const align = Array.from({ length: width }, (_, j) => {
    const a = (/text-align:\s*(\w+)/.exec(head[j]?.attrs?.style || '') || [])[1];
    return a === 'center' ? ':---:' : a === 'right' ? '---:' : a === 'left' ? ':---' : '---';
  });
  const line = cs => `| ${Array.from({ length: width }, (_, j) => cell(cs[j])).join(' | ')} |`;
  return [line(head), `| ${align.join(' | ')} |`, ...rows.slice(1).map(r => line(cellsOf(r)))].join('\n');
}

/** A node's children as markdown blocks (inline runs between blocks become paragraphs). */
function blocks(n) {
  const out = [];
  let run = '';
  const flush = () => { const t = run.replace(/[ \t]+\n/g, '\n').trim(); if (t) out.push(t); run = ''; };
  for (const c of n.children || []) {
    if (c.text !== undefined || !BLOCK.has(c.tag) || skip(c)) { run += inline(c); continue; }
    flush();
    const b = block(c);
    if (b && b.trim()) out.push(b);
  }
  flush();
  return out;
}
function block(n) {
  const hd = /^h([1-6])$/.exec(n.tag);
  if (hd) { const t = inline({ ...n, tag: 'span' }).replace(/\s*\n\s*/g, ' ').trim(); return t ? '#'.repeat(Math.max(1, +hd[1] - 2)) + ' ' + t : ''; }
  switch (n.tag) {
    case 'hr': return '---';
    case 'ul': return list(n, false);
    case 'ol': return list(n, true);
    case 'pre': return textOf(n).trim() ? fence(n) : '';
    case 'table': return tableMd(n);
    case 'blockquote': { const t = blocks(n).join('\n\n'); return t ? t.split('\n').map(l => (l ? '> ' + l : '>')).join('\n') : ''; }
    default: return blocks(n).join('\n\n');
  }
}

/** Markdown for a plain tree (or a DOM node): the inverse of renderMarkdown on its own tags. */
export function htmlToMarkdown(node) {
  const n = toPlain(node);
  if (!n) return '';
  if (n.text !== undefined) return n.text.trim();
  return (BLOCK.has(n.tag) ? block(n) : inline(n)).trim();
}

// ---------- the browser's selection → {text, seq} ----------
const elOf = n => (n && n.nodeType === 1 ? n : n?.parentElement || n?.parentNode || null);
const blank = (doc, a, b) => { try { const r = doc.createRange(); r.setStart(a.node, a.offset); r.setEnd(b.node, b.offset); return !r.toString().trim(); } catch { return false; } };

/** The selection as a quote: {text (markdown), seq (the reply's assistant event, or null)}, when both ends are in
 *  one reply's rendered markdown (an end just outside it, past nothing but blank space, counts as its edge). */
export function selectionQuote(sel, doc = globalThis.document) {
  if (!sel || !sel.rangeCount || sel.isCollapsed) return null;
  const r = sel.getRangeAt(0);
  let start = { node: r.startContainer, offset: r.startOffset }, end = { node: r.endContainer, offset: r.endOffset };
  const mdS = elOf(start.node)?.closest?.('[data-quote-seq] .aichat-md'), mdE = elOf(end.node)?.closest?.('[data-quote-seq] .aichat-md');
  const md = mdS || mdE;
  if (!md) return null;
  if (!mdS) { const s = { node: md, offset: 0 }; if (!blank(doc, start, s)) return null; start = s; }
  if (mdE !== md) { const e = { node: md, offset: md.childNodes.length }; if (mdE || !blank(doc, e, end)) return null; end = e; }
  const text = htmlToMarkdown(clipTree(md, start, end));
  if (!text) return null;
  const seq = parseInt(md.closest('[data-quote-seq]').getAttribute('data-quote-seq'), 10);
  return { text: text.length > QUOTE_MAX ? text.slice(0, QUOTE_MAX - 1) + '…' : text, seq: Number.isFinite(seq) && seq > 0 ? seq : null };
}

/** Scroll the thread to the reply a quote came from and flash it. */
export function scrollToReply(seq, doc = globalThis.document) {
  const el = seq != null && doc?.querySelector?.(`[data-quote-seq="${seq}"]`);
  if (!el) return false;
  el.scrollIntoView?.({ block: 'center' });          // instant: a smooth scroll can stall (and the flash shows where)
  el.classList.remove('aichat-flash'); void el.offsetWidth; el.classList.add('aichat-flash');
  setTimeout(() => el.classList.remove('aichat-flash'), 1600);
  return true;
}

export const QUOTE_CSS = `
.aichat-flash{animation:aichatflash 1.5s ease-out}
@keyframes aichatflash{0%,30%{background:var(--tcy,rgba(88,196,221,.13));box-shadow:0 0 0 6px var(--tcy,rgba(88,196,221,.13))}100%{background:transparent;box-shadow:0 0 0 6px transparent}}
[data-quote-seq]{border-radius:6px}
.aichat-quote .aichat-md{font-size:12px;color:var(--mut,#8A94A6)}
.aichat-quote .aichat-md pre{max-height:none}
`;

// ---------- the floating Reply button ----------
export function QuoteButton({ scrollRef, onQuote }) {
  const React = R(), [at, setAt] = React.useState(null), down = React.useRef(false);
  React.useEffect(() => {
    const doc = globalThis.document;
    if (!doc) return undefined;
    let t = 0;
    const update = () => {
      clearTimeout(t);
      t = setTimeout(() => {
        if (down.current) return;
        const sel = doc.getSelection?.(), q = selectionQuote(sel, doc);
        if (!q) { setAt(null); return; }
        // next to where the selection ends: under its last line, or over it near the bottom of the window
        const range = sel.getRangeAt(0), rects = [...(range.getClientRects?.() || [])].filter(r => r.width), W = globalThis.innerWidth || 1000, H = globalThis.innerHeight || 800;
        const last = rects[rects.length - 1] || range.getBoundingClientRect();
        const top = last.bottom + 40 < H ? last.bottom + 6 : Math.max(8, last.top - 34);
        setAt({ q, top, left: Math.max(8, Math.min(W - 92, last.right - 40)) });
      }, 60);
    };
    const onDown = e => { if (!e.target?.closest?.('[data-quote-button]')) { down.current = true; setAt(null); } };
    const onUp = e => { if (down.current && !(e.type === 'mousemove' && e.buttons)) { down.current = false; update(); } };   // a drag of the selection ends in dragend, not mouseup
    const onKey = e => { if (e.key === 'Escape') setAt(null); };
    const hide = () => setAt(null);
    const sc = scrollRef?.current;
    doc.addEventListener('selectionchange', update);
    doc.addEventListener('mousedown', onDown, true);
    for (const t of ['mouseup', 'pointerup', 'dragend', 'mousemove']) doc.addEventListener(t, onUp, true);
    doc.addEventListener('keydown', onKey);
    sc?.addEventListener('scroll', hide, { passive: true });
    return () => {
      clearTimeout(t);
      doc.removeEventListener('selectionchange', update); doc.removeEventListener('mousedown', onDown, true);
      for (const t of ['mouseup', 'pointerup', 'dragend', 'mousemove']) doc.removeEventListener(t, onUp, true);
      doc.removeEventListener('keydown', onKey); sc?.removeEventListener('scroll', hide);
    };
  }, []);
  if (!at) return null;
  return h('button', { type: 'button', 'data-quote-button': '', title: 'Reply to this part: it goes above your message as a quote',
    onMouseDown: e => e.preventDefault(),
    onClick: () => { onQuote(at.q); globalThis.document?.getSelection?.()?.removeAllRanges(); setAt(null); },
    style: { position: 'fixed', top: at.top, left: at.left, zIndex: 60, display: 'inline-flex', alignItems: 'center', gap: 6, height: 28, padding: '0 10px',
      borderRadius: 7, border: '1px solid ' + T.bdh, background: T.card, color: T.tx, font: 'inherit', fontSize: 12.5, cursor: 'pointer', boxShadow: '0 8px 24px rgba(0,0,0,.35)' } },
  h(Icon, { d: QUOTE_ICON, size: 13 }), 'Reply');
}

// ---------- the chip above the composer's box ----------
export function QuoteChip({ quote, onRemove }) {
  const React = R(), html = React.useMemo(() => renderMarkdown(quote?.text || ''), [quote?.text]);
  if (!quote) return null;
  return h('div', { 'data-quote': '', role: 'group', 'aria-label': 'Replying to this part of a reply', className: 'aichat-quote',
    style: { display: 'flex', alignItems: 'flex-start', gap: 6, padding: '4px 4px 4px 8px', borderLeft: '3px solid ' + T.bdh, borderRadius: 5, background: T.inset, minWidth: 0 } },
  h('span', { style: { color: T.mut, display: 'flex', paddingTop: 2 } }, h(Icon, { d: QUOTE_ICON, size: 12 })),
  h('div', { className: 'aichat-md', title: quote.text, onClick: e => { if (e.target?.closest?.('a[data-cite]')) e.preventDefault(); }, style: { flex: 1, minWidth: 0, maxHeight: 38, overflow: 'hidden' }, dangerouslySetInnerHTML: { __html: html } }),
  h('button', { type: 'button', 'aria-label': 'Remove the quote', title: 'Remove the quote', onClick: onRemove,
    style: { border: 0, background: 'none', padding: 2, color: T.mut, cursor: 'pointer', display: 'flex', flex: 'none' } }, h(Icon, { d: 'x', size: 11 })));
}

// ---------- the quote on a sent message ----------
const CLIP = 6 * 18;   // ~6 lines of 12px text
export function QuoteBlock({ quote, ctx }) {
  const React = R(), [open, setOpen] = React.useState(false), [long, setLong] = React.useState(false), ref = React.useRef(null);
  const html = React.useMemo(() => renderMarkdown(quote?.text || ''), [quote?.text]);
  (React.useLayoutEffect || React.useEffect)(() => { const el = ref.current; if (el) setLong(el.scrollHeight > CLIP + 4); }, [html]);
  if (!quote?.text) return null;
  const go = () => (ctx?.scrollToReply || scrollToReply)(quote.seq);
  return h('div', { 'data-quote': quote.seq ?? '', className: 'aichat-quote', style: { display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 } },
    h('div', { ref, role: quote.seq != null ? 'button' : undefined, tabIndex: quote.seq != null ? 0 : undefined,
      title: quote.seq != null ? 'Show this part of the reply' : undefined,
      onClick: e => {
        const a = e.target?.closest?.('a');
        if (a?.dataset?.cite) { e.preventDefault(); ctx?.openCite?.({ ref: a.dataset.cite, page: a.dataset.page, line: a.dataset.line }); return; }
        if (!a && quote.seq != null) go();
      },
      onKeyDown: e => { if (quote.seq != null && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); go(); } },
      className: 'aichat-md',
      style: { padding: '2px 0 2px 9px', borderLeft: '3px solid ' + T.bdh, cursor: quote.seq != null ? 'pointer' : 'default',
        maxHeight: open ? 'none' : CLIP, overflow: 'hidden', minWidth: 0,
        ...(long && !open ? { WebkitMaskImage: 'linear-gradient(#000 70%, transparent)', maskImage: 'linear-gradient(#000 70%, transparent)' } : {}) },
      dangerouslySetInnerHTML: { __html: html } }),
    long ? h('button', { type: 'button', onClick: () => setOpen(!open), 'aria-expanded': open ? 'true' : 'false',
      style: { alignSelf: 'flex-start', border: 0, background: 'none', padding: '0 0 0 9px', color: T.mut, font: 'inherit', fontSize: 11.5, cursor: 'pointer' } }, open ? 'Show less' : 'Show more') : null);
}
