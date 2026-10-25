// A small, safe Markdown renderer for chat messages (plan 14.1): paragraphs, headings, lists,
// quotes, bold, italic, inline code, links, GFM pipe tables, and fenced code blocks with a header
// (language, Copy) and the highlighter in highlight.js. Every character of the input
// is HTML-escaped first; the only tags in the output are the ones made here, and links keep
// only http(s), mailto, `#…` and `/…` targets. Citations of documents (plan 24.7: `#3 p.14`, `#3:88`,
// `output:<id> p.14`, `output:<id>:88`) become links with `data-cite`, `data-page` / `data-line` that the
// chat opens in the viewer. A bracketed group of them as models write it (`[eecs.berkeley.edu #1:112]`,
// `[coursera.org #6:16; BLS]`, `[resume #8 p.1]`) becomes a row of chips: the site's icon, the source's
// name and a dim place; a part without a `#n` is a plain chip. `data-src` keeps what the model wrote (for
// quoting, chat-quote.js). Pure (no DOM), tested in utils/tests/web/chat.test.mjs and citations.test.mjs.

import { highlight } from './highlight.js';
import { faviconUrl } from './chat-sources.js';

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const escapeHtml = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);

const SAFE_URL = /^(https?:\/\/|mailto:|#|\/(?!\/))/i;

// `#n` or `output:<12 hex>`, then `:line`, ` p.N` / ` pp.N-M` / ` page N`, or ` line N` / ` lines N-M`
const CITE = /(^|[^\w&#/:])(#(\d{1,4})|output:([0-9a-f]{12}))(?::(\d{1,7})(?:\s?[-–]\s?\d{1,7})?\b|,?\s+(?:pp?\.\s?|pages?\s)(\d{1,5})(?:\s?[-–]\s?\d{1,5})?\b|,?\s+(?:lines?\s|l\.\s?)(\d{1,7})(?:\s?[-–]\s?\d{1,7})?\b)/g;

/** The document citations in a text: [{text, ref ('#3' | 'output:<id>'), n?, id?, page?, line?}]. */
export function parseCitations(text) {
  const out = [];
  for (const m of String(text ?? '').matchAll(CITE)) {
    const c = { text: m[0].slice(m[1].length), ref: m[2] };
    if (m[3]) c.n = +m[3]; else c.id = m[4];
    if (m[5] || m[7]) c.line = +(m[5] || m[7]); else c.page = +m[6];
    out.push(c);
  }
  return out;
}

// One part of a bracketed group: `name #n`, `name #n:9-35`, `name #n p.1`, `#n`, or `output:<id> …`.
const PART = /^(?:(.*?)\s+)?(#(\d{1,4})|output:([0-9a-f]{12}))(?:(?::\s?|,?\s+(?:lines?\s|l\.\s?))(\d{1,7})|,?\s+(pp?\.\s?|pages?\s)(\d{1,5}))?([\d\s,–-]*)$/;
const dash = s => s.trim().replace(/\s*[-–]\s*/g, '–').replace(/\s*,\s*/g, ', ');

/** A bracketed group's text → its parts ({ref, n?, id?, name, page?, line?, at} or {name} for a part with no
 *  `#n`), or null when no part cites anything (`[x]`, `[Medium]` stay as written). */
export function citeGroup(inner) {
  const parts = String(inner ?? '').split(';').map(p => p.trim()).filter(Boolean);
  const out = parts.map(p => {
    const m = PART.exec(p);
    if (!m || (m[8].trim() && !m[5] && !m[7])) return { name: p };
    const c = { ref: m[2], name: (m[1] || '').trim() };
    if (m[3]) c.n = +m[3]; else c.id = m[4];
    if (m[5]) { c.line = +m[5]; c.at = 'L' + dash(m[5] + m[8]); }
    else if (m[7]) { c.page = +m[7]; c.at = (/^pp|^pages/.test(m[6]) || /[-–,]/.test(m[8]) ? 'pp. ' : 'p. ') + dash(m[7] + m[8]); }
    return c;
  });
  return out.some(c => c.ref) ? out : null;
}

// The titles of the chat's sources while a message renders (renderMarkdown's `cites`): '#3' → title.
let titles = null;
// Plan 47.3: the open chat's outputs, so `![caption](#3)` draws output #3 in the reply (chat.js keeps it current).
let chatOutputs = [];
export function setChatOutputs(list) { chatOutputs = Array.isArray(list) ? list : []; }
const SAFE_MEDIA = /^\/(?!\/)[\w\-./%?=&;:]*$/;   // the hub's own paths only (/api/outputs/…)
/** `![caption](#n)` or `(output:<id>)` → the output drawn inline, or null when it isn't one of this chat's. */
export function mediaHtml(ref, caption, src = '') {
  const o = ref.startsWith('#') ? chatOutputs.find(x => x.n === +ref.slice(1)) : chatOutputs.find(x => x.output_id === ref.slice(7));
  if (!o) return null;
  const url = o.url && SAFE_MEDIA.test(o.url) ? o.url : null, poster = o.preview && SAFE_MEDIA.test(o.preview) ? o.preview : null;
  const cap = escapeHtml(caption || o.title || ''), n = o.n ? `<span class="aichat-fig-n">#${o.n}</span>` : '';
  let media;
  if (o.kind === 'image' && (url || poster)) media = `<img src="${url || poster}" alt="${cap}" loading="lazy" data-open="${o.output_id}">`;
  else if (o.kind === 'video' && url) media = `<video src="${url}"${poster ? ` poster="${poster}"` : ''} controls preload="metadata"></video>`;
  else if (o.kind === 'audio' && url) media = `<audio src="${url}" controls preload="metadata"></audio>`;
  else if (poster) media = `<img src="${poster}" alt="${cap}" loading="lazy" data-open="${o.output_id}">`;
  else return null;
  // spans, not <figure>: the picture sits inside a paragraph, and a block there would end it
  return `<span class="aichat-fig" data-src="${escapeHtml(src)}">${media}<span class="aichat-fig-cap">${n}${cap}</span></span>`;
}
const clipName = (s, n = 32) => (s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s);

/** A citation chip (escaped text in, HTML out): the icon when the name is a hostname, the name, the place. */
function chip(c, src) {
  const title = titles?.(c.ref);
  const name = c.name || (title ? escapeHtml(clipName(title)) : c.ref);
  const at = c.line ? ` data-line="${c.line}"` : c.page ? ` data-page="${c.page}"` : '';
  const where = c.line ? `line ${c.line}` : c.page ? `page ${c.page}` : '';
  const tip = `Open ${title ? escapeHtml(title) + ' (' + c.ref + ')' : c.ref}${where ? ' at ' + where : ''}`;
  const icon = faviconUrl(c.name.replace(/&amp;/g, '&'));
  return `<a href="#" class="aichat-cite" data-cite="${c.ref}"${at}${src ? ` data-src="${src}"` : ''} title="${tip}">`
    + (icon ? `<img class="aichat-cite-ico" src="${icon}" alt="" loading="lazy" referrerpolicy="no-referrer">` : '')
    + `<span class="aichat-cite-name">${name}</span>${c.at ? `<span class="aichat-cite-at">${c.at}</span>` : ''}</a>`;
}

// Inline spans on already-escaped text. Code spans are cut out first so nothing inside them changes.
function inline(src) {
  const keep = [];
  const stash = html => `\u0000${keep.push(html) - 1}\u0000`;
  let s = escapeHtml(src);
  s = s.replace(/`([^`\n]+)`/g, (_, c) => stash(`<code>${c}</code>`));
  // ![caption](#n): this chat's output drawn here; any other image stays as text (no pictures from elsewhere)
  s = s.replace(/!\[([^\]\n]*)\]\(([^)\s]+)\)/g, (m, cap, ref) => {
    const raw = x => x.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
    const html = /^(#\d{1,4}|output:[0-9a-f]{12})$/.test(ref) ? mediaHtml(ref, raw(cap), raw(m)) : null;
    return stash(html || m);
  });
  s = s.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (m, text, url) => {
    const raw = url.replace(/&amp;/g, '&');
    if (!SAFE_URL.test(raw)) return m;
    return stash(`<a href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>`);
  });
  s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:!?])/g, (_, pre, url) => pre + stash(`<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`));
  s = s.replace(/\[([^\[\]\n\u0000]+)\](?!\()/g, (m, inner) => {
    const parts = citeGroup(inner);
    if (!parts) return m;
    return stash(`<span class="aichat-cites" data-src="${inner}">${parts.map(c => (c.ref ? chip(c) : `<span class="aichat-cite aichat-cite-plain">${c.name}</span>`)).join('')}</span>`);
  });
  s = s.replace(CITE, (m, pre) => {
    const [c] = parseCitations(m.slice(pre.length));
    if (!c) return m;
    const [p] = citeGroup(c.text) || [];
    return pre + stash(chip(p?.ref ? p : { ...c, name: '' }, c.text));
  });
  s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>').replace(/__([^_\n]+)__/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, '$1<em>$2</em>').replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, '$1<em>$2</em>');
  s = s.replace(/~~([^~\n]+)~~/g, '<del>$1</del>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => keep[+i]);
}

// ```lang or ~~~lang (an info string after the language is ignored); closed by the same mark, at least as long.
const FENCE = /^\s*(`{3,}|~{3,})\s*([\w+#.-]*)(?:\s+[^`]*)?\s*$/;
// A GFM table's delimiter row: |---|:--:|--:|
const DELIM = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

/** A fenced block: a header with the language and a Copy button (the page's click handler, `installCopy`), then the highlighted code. */
function codeBlock(code, lang) {
  const l = escapeHtml(lang || '');
  return `<div class="aichat-code"><div class="aichat-code-bar"><span>${l}</span><button type="button" class="aichat-copy" title="Copy code">Copy</button></div>`
    + `<pre${l ? ` data-lang="${l}"` : ''}><code>${highlight(code, lang)}</code></pre></div>`;
}

// One table row → its cells: split on `|` outside code spans; `\|` is a literal pipe.
function cells(row) {
  let r = row.trim();
  if (r.startsWith('|')) r = r.slice(1);
  if (r.endsWith('|') && !r.endsWith('\\|')) r = r.slice(0, -1);
  const out = [];
  let cur = '', code = false;
  for (let i = 0; i < r.length; i++) {
    const c = r[i];
    if (c === '\\' && r[i + 1] === '|') { cur += '|'; i++; continue; }
    if (c === '`') code = !code;
    if (c === '|' && !code) { out.push(cur.trim()); cur = ''; continue; }
    cur += c;
  }
  out.push(cur.trim());
  return out;
}

/** A GFM pipe table; rows get as many cells as the header has. */
function table(head, delim, rows) {
  const th = cells(head), n = th.length;
  const align = cells(delim).map(d => d.startsWith(':') && d.endsWith(':') ? 'center' : d.endsWith(':') ? 'right' : '');
  const td = (tag, text, j) => `<${tag}${align[j] ? ` style="text-align:${align[j]}"` : ''}>${inline(text)}</${tag}>`;
  const body = rows.map(r => { const c = cells(r); return `<tr>${Array.from({ length: n }, (_, j) => td('td', c[j] ?? '', j)).join('')}</tr>`; }).join('');
  return `<div class="aichat-table"><table><thead><tr>${th.map((t, j) => td('th', t, j)).join('')}</tr></thead>${body ? `<tbody>${body}</tbody>` : ''}</table></div>`;
}

/** Markdown → an HTML string that is safe to set as innerHTML. `cites(ref)` names a citation's source ('#3' → its title). */
export function renderMarkdown(text, { cites } = {}) {
  titles = cites || null;
  try { return blocks(text); } finally { titles = null; }
}
function blocks(text) {
  const lines = String(text ?? '').replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let para = [], list = null, quote = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${para.map(inline).join('<br>')}</p>`); para = []; } };
  // An ordered list keeps its first number, so items split by a paragraph or a sub-list count on.
  const flushList = () => { if (list) { out.push(`<${list.tag}${list.start !== 1 ?` start="${list.start}"` : ''}>${list.items.map(i => `<li>${inline(i)}</li>`).join('')}</${list.tag}>`); list = null; } };
  const flushQuote = () => { if (quote.length) { out.push(`<blockquote>${quote.map(inline).join('<br>')}</blockquote>`); quote = []; } };
  const flush = () => { flushPara(); flushList(); flushQuote(); };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const fence = line.match(FENCE);
    if (fence) {
      flush();
      const code = [], close = new RegExp(`^\\s*${fence[1][0] === '`' ? '`' : '~'}{${fence[1].length},}\\s*$`);
      for (i++; i < lines.length && !close.test(lines[i]); i++) code.push(lines[i]);
      out.push(codeBlock(code.join('\n'), fence[2]));
      continue;
    }
    if (!line.trim()) { flush(); continue; }
    if (line.includes('|') && lines[i + 1]?.includes('|') && DELIM.test(lines[i + 1])) {
      flush();
      const head = line, delim = lines[i + 1], rows = [];
      for (i += 2; i < lines.length && lines[i].trim() && lines[i].includes('|'); i++) rows.push(lines[i]);
      i--;
      out.push(table(head, delim, rows));
      continue;
    }
    const hd = line.match(/^(#{1,6})\s+(.*)$/);
    if (hd) { flush(); const n = Math.min(6, hd[1].length + 2); out.push(`<h${n}>${inline(hd[2])}</h${n}>`); continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); out.push('<hr>'); continue; }
    const ul = line.match(/^\s*[-*+]\s+(.*)$/), ol = line.match(/^\s*(\d{1,9})[.)]\s+(.*)$/);
    if (ul || ol) {
      flushPara(); flushQuote();
      const tag = ul ? 'ul' : 'ol';
      if (list && list.tag !== tag) flushList();
      if (!list) list = { tag, items: [], start: ol ? Number(ol[1]) : 1 };
      list.items.push(ul ? ul[1] : ol[2]);
      continue;
    }
    const q = line.match(/^\s*>\s?(.*)$/);
    if (q) { flushPara(); flushList(); quote.push(q[1]); continue; }
    if (list && /^\s{2,}\S/.test(line)) { list.items[list.items.length - 1] += ' ' + line.trim(); continue; }
    flushList(); flushQuote();
    para.push(line);
  }
  flush();
  return out.join('');
}

// The CSS for rendered messages, scoped to `.aichat-md` (injected once by the page).
export const MD_CSS = `
.aichat-fig{margin:8px 0;display:flex;flex-direction:column;gap:4px;max-width:100%}.aichat-fig-cap{font-size:12px;color:var(--mut,#8A94A6)}.aichat-fig img,.aichat-fig video{max-width:100%;max-height:360px;border-radius:6px;background:var(--inset,#131926);object-fit:contain;align-self:flex-start}.aichat-fig img[data-open]{cursor:zoom-in}.aichat-fig audio{width:100%;max-width:420px}.aichat-fig-n{font-family:'JetBrains Mono',ui-monospace,monospace;font-weight:600;font-size:11px;color:var(--pu,#BC8CFF);margin-right:6px}
.aichat-md{line-height:1.55;overflow-wrap:anywhere;min-width:0}
.aichat-md>*:first-child{margin-top:0}.aichat-md>*:last-child{margin-bottom:0}
.aichat-md p{margin:0 0 8px}.aichat-md ul,.aichat-md ol{margin:0 0 8px;padding-left:20px}.aichat-md li{margin:2px 0}
.aichat-md h3,.aichat-md h4,.aichat-md h5,.aichat-md h6{margin:12px 0 6px;font-size:13.5px;font-weight:600}
.aichat-md code{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:.92em;padding:1px 5px;border-radius:4px;background:var(--inset,#131926);border:1px solid var(--bd,#1D2430)}
.aichat-md pre{margin:0 0 8px;padding:9px 11px;border-radius:7px;background:var(--inset,#131926);border:1px solid var(--bd,#1D2430);overflow:auto;max-height:420px}
.aichat-md pre code{padding:0;border:0;background:none;font-size:12px;white-space:pre}
.aichat-md .aichat-code{margin:0 0 8px;border:1px solid var(--bd,#1D2430);border-radius:7px;background:var(--inset,#131926);overflow:hidden}
.aichat-md .aichat-code pre{margin:0;border:0;border-radius:0;background:none}
.aichat-md .aichat-code-bar{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:26px;padding:0 4px 0 11px;border-bottom:1px solid var(--bd,#1D2430);font:11px 'JetBrains Mono',ui-monospace,monospace;color:var(--mut,#8A94A6)}
.aichat-md .aichat-copy{height:20px;padding:0 8px;border-radius:5px;border:1px solid transparent;background:none;color:var(--mut,#8A94A6);font:inherit;font-family:inherit;cursor:pointer}
.aichat-md .aichat-copy:hover{border-color:var(--bds,#2A3547);color:var(--tx,#E6EAF2)}.aichat-md .aichat-copy.ok{color:#3FB950}
.aichat-md pre .c{color:var(--dim,#5B6577);font-style:italic}.aichat-md pre .s{color:#3FB950}.aichat-md pre .k{color:#BC8CFF}.aichat-md pre .n{color:#FFB224}.aichat-md pre .d{color:#F85149}
.aichat-md .aichat-table{margin:0 0 10px;max-width:100%;overflow-x:auto;border:1px solid var(--bd,#1D2430);border-radius:7px}
.aichat-md table{border-collapse:collapse;min-width:100%;font-size:12.5px;line-height:1.45}
.aichat-md th,.aichat-md td{padding:6px 10px;text-align:left;vertical-align:top;border-bottom:1px solid var(--bd,#1D2430);overflow-wrap:break-word;min-width:64px;max-width:360px}
.aichat-md th+th,.aichat-md td+td{border-left:1px solid var(--bd,#1D2430)}
.aichat-md th{background:var(--inset,#131926);font-weight:600}.aichat-md tbody tr:last-child td{border-bottom:0}
.aichat-md blockquote{margin:0 0 8px;padding:2px 10px;border-left:3px solid var(--bds,#2A3547);color:var(--mut,#8A94A6)}
.aichat-md a{color:var(--cy,#58C4DD)}.aichat-md hr{border:0;border-top:1px solid var(--bd,#1D2430);margin:10px 0}
.aichat-md .aichat-cites>.aichat-cite+.aichat-cite{margin-left:3px}
.aichat-md .aichat-cite{display:inline-flex;align-items:center;gap:4px;max-width:240px;height:18px;padding:0 7px;margin:0 1px;border-radius:9px;vertical-align:1px;box-sizing:border-box;border:1px solid var(--bd,#1D2430);background:var(--hov,#161C28);color:var(--mut,#8A94A6);font-size:11px;font-weight:500;line-height:1;text-decoration:none;white-space:nowrap;transition:color .12s,border-color .12s,background .12s}
.aichat-md a.aichat-cite{cursor:pointer}.aichat-md a.aichat-cite:hover,.aichat-md a.aichat-cite:focus-visible{color:var(--tx,#E6EAF2);border-color:var(--cy,#58C4DD);background:var(--tcy,rgba(88,196,221,.13));outline:none}
.aichat-md .aichat-cite-plain{color:var(--dim,#737D90);background:none}
.aichat-md .aichat-cite-ico{width:12px;height:12px;border-radius:3px;flex:none;object-fit:contain}
.aichat-md .aichat-cite-name{overflow:hidden;text-overflow:ellipsis}
.aichat-md .aichat-cite-at{flex:none;font-family:'JetBrains Mono',ui-monospace,monospace;font-size:10px;color:var(--dim,#737D90)}
`;

/** One click handler for every Copy button in rendered Markdown (chat replies, activity rows, the viewer); safe to call more than once. */
export function installCopy(doc = globalThis.document) {
  if (!doc || doc.__aichatCopy) return;
  doc.__aichatCopy = true;
  // a citation chip whose site has no icon drops it (error doesn't bubble, so listen while capturing)
  doc.addEventListener('error', e => { if (e.target?.classList?.contains('aichat-cite-ico')) e.target.remove(); }, true);
  doc.addEventListener('click', async e => {
    const fig = e.target?.closest?.('img[data-open]');   // plan 47.3: a picture in a reply opens in Outputs
    if (fig && fig.closest('.aichat-md')) { doc.dispatchEvent(new CustomEvent('gaifa:open-output', { detail: fig.dataset.open })); return; }
    const b = e.target?.closest?.('.aichat-copy');
    const code = b?.closest('.aichat-code')?.querySelector('code');
    if (!code) return;
    e.preventDefault(); e.stopPropagation();
    const text = code.textContent;
    let ok = true;
    try { await navigator.clipboard.writeText(text); } catch {   // as Hub.dc.html's copyFallback
      const t = doc.createElement('textarea'); t.value = text; t.style.cssText = 'position:fixed;opacity:0';
      doc.body.appendChild(t); t.select();
      try { ok = doc.execCommand('copy'); } catch { ok = false; } finally { t.remove(); }
    }
    b.textContent = ok ? 'Copied' : 'Copy failed'; b.classList.toggle('ok', ok);
    clearTimeout(b.__t); b.__t = setTimeout(() => { b.textContent = 'Copy'; b.classList.remove('ok'); }, 1500);
  });
}
