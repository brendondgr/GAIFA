// Select → Reply, the selection half: part of an agent's reply, selected, turned back into **markdown**.
// - `selectionQuote`: the part of the rendered reply (chat-md.js `renderMarkdown`) between the selection's two
//   ends is cut out of the DOM as a plain tree (`clipTree`, which keeps the ancestors: a selection inside a bold
//   word inside a list item stays `- **word**`), then written as markdown (`htmlToMarkdown`) for the renderer's
//   own tags: paragraphs and line breaks, bold, italic, strikethrough, inline code, fenced code with its language
//   (the header bar left out), lists (numbered from where the selection starts), quotes, headings (h3 → `#`: the
//   renderer shifts levels by 2), rules, links, citations (as written: `#3 p.14`) and pipe tables with alignment.
//   A selection across table cells quotes the rows it touches, whole, under the table's header; one inside a
//   single cell quotes just the text. Part of one line of a code block is inline code.
// - `scrollToReply`: back to the reply a quote came from, flashed.
// The floating box, the composer's quote-reply cards and the Reply popup are in chat-quote-reply.js.

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
    if (i > 0) n.attrs = { ...n.attrs, start: String((parseInt(n.attrs?.start, 10) || 1) + i) };
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
