// A small, safe Markdown renderer for chat messages (plan 14.1): paragraphs, headings, lists,
// quotes, bold, italic, inline code, fenced code blocks and links. Every character of the input
// is HTML-escaped first; the only tags in the output are the ones made here, and links keep
// only http(s), mailto, `#…` and `/…` targets. Citations of documents (plan 24.7: `#3 p.14`, `#3:88`,
// `output:<id> p.14`, `output:<id>:88`) become links with `data-cite`, `data-page` / `data-line` that the
// chat opens in the viewer. Pure (no DOM), tested in utils/tests/web/chat.test.mjs and citations.test.mjs.

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const escapeHtml = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);

const SAFE_URL = /^(https?:\/\/|mailto:|#|\/(?!\/))/i;

// `#n` or `output:<12 hex>`, then `:line`, ` p.N` / ` pp.N-M` / ` page N`, or ` line N` / ` lines N-M`
const CITE = /(^|[^\w&#/:])(#(\d{1,4})|output:([0-9a-f]{12}))(?::(\d{1,7})\b|,?\s+(?:pp?\.\s?|pages?\s)(\d{1,5})(?:\s?[-–]\s?\d{1,5})?\b|,?\s+(?:lines?\s|l\.\s?)(\d{1,7})(?:\s?[-–]\s?\d{1,7})?\b)/g;

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

// Inline spans on already-escaped text. Code spans are cut out first so nothing inside them changes.
function inline(src) {
  const keep = [];
  const stash = html => `\u0000${keep.push(html) - 1}\u0000`;
  let s = escapeHtml(src);
  s = s.replace(/`([^`\n]+)`/g, (_, c) => stash(`<code>${c}</code>`));
  s = s.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (m, text, url) => {
    const raw = url.replace(/&amp;/g, '&');
    if (!SAFE_URL.test(raw)) return m;
    return stash(`<a href="${url}" target="_blank" rel="noopener noreferrer">${text}</a>`);
  });
  s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:!?])/g, (_, pre, url) => pre + stash(`<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`));
  s = s.replace(CITE, (m, pre) => {
    const [c] = parseCitations(m.slice(pre.length));
    if (!c) return m;
    const at = c.line ? ` data-line="${c.line}"` : ` data-page="${c.page}"`;
    return pre + stash(`<a href="#" class="aichat-cite" data-cite="${c.ref}"${at} title="Open ${c.ref} at ${c.line ? 'line ' + c.line : 'page ' + c.page}">${c.text}</a>`);
  });
  s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>').replace(/__([^_\n]+)__/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, '$1<em>$2</em>').replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, '$1<em>$2</em>');
  s = s.replace(/~~([^~\n]+)~~/g, '<del>$1</del>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => keep[+i]);
}

/** Markdown → an HTML string that is safe to set as innerHTML. */
export function renderMarkdown(text) {
  const lines = String(text ?? '').replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let para = [], list = null, quote = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${para.map(inline).join('<br>')}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`<${list.tag}>${list.items.map(i => `<li>${inline(i)}</li>`).join('')}</${list.tag}>`); list = null; } };
  const flushQuote = () => { if (quote.length) { out.push(`<blockquote>${quote.map(inline).join('<br>')}</blockquote>`); quote = []; } };
  const flush = () => { flushPara(); flushList(); flushQuote(); };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const fence = line.match(/^\s*```\s*([\w+-]*)\s*$/);
    if (fence) {
      flush();
      const code = [];
      for (i++; i < lines.length && !/^\s*```\s*$/.test(lines[i]); i++) code.push(lines[i]);
      const lang = fence[1] ? ` data-lang="${escapeHtml(fence[1])}"` : '';
      out.push(`<pre${lang}><code>${escapeHtml(code.join('\n'))}</code></pre>`);
      continue;
    }
    if (!line.trim()) { flush(); continue; }
    const hd = line.match(/^(#{1,6})\s+(.*)$/);
    if (hd) { flush(); const n = Math.min(6, hd[1].length + 2); out.push(`<h${n}>${inline(hd[2])}</h${n}>`); continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); out.push('<hr>'); continue; }
    const ul = line.match(/^\s*[-*+]\s+(.*)$/), ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ul || ol) {
      flushPara(); flushQuote();
      const tag = ul ? 'ul' : 'ol';
      if (list && list.tag !== tag) flushList();
      if (!list) list = { tag, items: [] };
      list.items.push((ul || ol)[1]);
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
.aichat-md{line-height:1.55;overflow-wrap:anywhere;min-width:0}
.aichat-md>*:first-child{margin-top:0}.aichat-md>*:last-child{margin-bottom:0}
.aichat-md p{margin:0 0 8px}.aichat-md ul,.aichat-md ol{margin:0 0 8px;padding-left:20px}.aichat-md li{margin:2px 0}
.aichat-md h3,.aichat-md h4,.aichat-md h5,.aichat-md h6{margin:12px 0 6px;font-size:13.5px;font-weight:600}
.aichat-md code{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:.92em;padding:1px 5px;border-radius:4px;background:var(--inset,#131926);border:1px solid var(--bd,#1D2430)}
.aichat-md pre{margin:0 0 8px;padding:9px 11px;border-radius:7px;background:var(--inset,#131926);border:1px solid var(--bd,#1D2430);overflow:auto;max-height:420px}
.aichat-md pre code{padding:0;border:0;background:none;font-size:12px;white-space:pre}
.aichat-md blockquote{margin:0 0 8px;padding:2px 10px;border-left:3px solid var(--bds,#2A3547);color:var(--mut,#8A94A6)}
.aichat-md a{color:var(--cy,#58C4DD)}.aichat-md a.aichat-cite{text-decoration:none;border-bottom:1px dotted currentColor;font-family:'JetBrains Mono',ui-monospace,monospace;font-size:.92em}.aichat-md hr{border:0;border-top:1px solid var(--bd,#1D2430);margin:10px 0}
`;
