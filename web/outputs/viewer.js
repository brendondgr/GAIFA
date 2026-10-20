// The text and PDF viewer for outputs (plan 24.7), shown in the Outputs drawer for text and document
// outputs (on the Outputs page and over the chat). Text and code get line numbers and a small
// highlighter (keywords, strings, comments; no library), markdown can be shown rendered, PDFs page by
// page as images (plan 24.3's page route) with the page's text beside them, and a search box uses the
// hub's search. `at` ({page} or {line}) opens it at a citation from the chat. The pure parts
// (highlightLine, langOf, startAt) are tested in utils/tests/web/citations.test.mjs.

import { renderMarkdown, escapeHtml, MD_CSS } from '../chat/chat-md.js';

const R = () => globalThis.React;
const h = (...a) => R().createElement(...a);
const MONO = "'JetBrains Mono',ui-monospace,Menlo,monospace";
const C = { bd: 'var(--bd,#1D2430)', bds: 'var(--bds,#2A3547)', inset: 'var(--inset,#131926)', mut: 'var(--mut,#8A94A6)', dim: 'var(--dim,#5B6577)',
  tx: 'var(--tx,#E6EAF2)', cy: 'var(--cy,#58C4DD)', hl: 'var(--tacc,rgba(255,178,36,.16))' };
const TEXT_WINDOW = 48000, MAX_WINDOWS = 20;

// ---- the highlighter ------------------------------------------------------------------------------

const WORDS = {
  python: 'and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return self True try while with yield',
  shell: 'case do done elif else esac exit export fi for function if in local return set then until while echo',
  sql: 'select from where and or not insert into values update set delete create table index join left right inner outer on group by order having limit as null is in like distinct union',
  rust: 'as async await break const continue crate else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while',
  go: 'break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var nil true false',
  c: 'auto break case catch char class const continue default delete do double else enum extern false float for friend goto if inline int long namespace new nullptr private protected public return short signed sizeof static struct switch template this throw true try typedef typename union unsigned using virtual void volatile while bool',
  js: 'async await break case catch class const continue debugger default delete do else export extends false finally for from function if import in instanceof let new null of return static super switch this throw true try typeof undefined var void while with yield interface type enum implements',
};
const FAMILY = { python: 'python', shell: 'shell', fish: 'shell', powershell: 'shell', sql: 'sql', rust: 'rust', go: 'go',
  c: 'c', cpp: 'c', java: 'c', csharp: 'c', kotlin: 'c', swift: 'c', php: 'js', javascript: 'js', typescript: 'js', tsx: 'js', jsx: 'js', ruby: 'python', lua: 'python', r: 'python', julia: 'python',
  toml: 'conf', yaml: 'conf', ini: 'conf', env: 'conf' };
const HASH = new Set(['python', 'shell', 'conf']);
const KW = Object.fromEntries(Object.entries(WORDS).map(([k, v]) => [k, new Set(v.split(' '))]));

/** `code:python` → python; other subtypes → the language they name, or ''. */
export function langOf(subtype) {
  const m = /^(?:code|config|web|data):(.+)$/.exec(subtype || '');
  return m ? m[1] : subtype === 'notebook' ? 'python' : '';
}

/** One line of code as HTML: every character escaped, keywords, strings, numbers and comments in spans. */
export function highlightLine(line, lang) {
  const fam = FAMILY[lang] || (lang ? 'c' : ''), kw = KW[fam];
  if (!fam) return escapeHtml(line);
  const comment = HASH.has(fam) ? '#.*' : fam === 'sql' ? '--.*' : '\\/\\/.*|\\/\\*.*?(?:\\*\\/|$)';
  const rx = new RegExp(`(${comment})|("(?:[^"\\\\]|\\\\.)*"?|'(?:[^'\\\\]|\\\\.)*'?|\`[^\`]*\`?)|(\\b\\d[\\d_.xXa-fA-F]*\\b)|([A-Za-z_][\\w]*)`, 'g');
  let out = '', last = 0;
  for (const m of line.matchAll(rx)) {
    out += escapeHtml(line.slice(last, m.index));
    const t = escapeHtml(m[0]);
    out += m[1] ? `<span class="c">${t}</span>` : m[2] ? `<span class="s">${t}</span>` : m[3] ? `<span class="n">${t}</span>`
      : kw && kw.has(m[4]) ? `<span class="k">${t}</span>` : t;
    last = m.index + m[0].length;
  }
  return out + escapeHtml(line.slice(last));
}

/** Where to open: a PDF at a page, anything else at a line. */
export function startAt(output, at) {
  if (output?.subtype === 'pdf') return { page: Math.max(1, +(at?.page || 1)) };
  return { line: Math.max(1, +(at?.line || 1)) };
}

export const VIEWER_CSS = `
.aiview .c{color:var(--dim,#5B6577);font-style:italic}.aiview .s{color:#3FB950}.aiview .k{color:#BC8CFF}.aiview .n{color:#FFB224}
.aiview-line{display:flex;gap:10px;padding:0 6px;border-radius:3px}.aiview-line>b{flex:none;width:44px;text-align:right;color:var(--dim,#5B6577);font-weight:400;user-select:none}
.aiview-line.hit{background:var(--tacc,rgba(255,178,36,.16))}.aiview-line>span{white-space:pre-wrap;overflow-wrap:anywhere;min-width:0}
`;

// ---- the component ----------------------------------------------------------------------------------

const btn = { height: 26, padding: '0 9px', borderRadius: 6, border: '1px solid ' + C.bds, background: 'transparent', color: C.tx, font: 'inherit', fontSize: 12, cursor: 'pointer' };

function useCss() {
  R().useEffect(() => {
    if (typeof document === 'undefined' || document.getElementById('aiview-css')) return;
    const s = document.createElement('style');
    s.id = 'aiview-css';
    s.textContent = VIEWER_CSS + MD_CSS;
    document.head.appendChild(s);
  }, []);
}

function Search({ api, output, onHit }) {
  const React = R(), [q, setQ] = React.useState(''), [res, setRes] = React.useState(null), [err, setErr] = React.useState(null);
  const run = () => { if (!q.trim()) return; setErr(null); api.outputSearch(output.id, q, { limit: 50 }).then(setRes, e => setErr(e.detail || e.message)); };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
    h('div', { style: { display: 'flex', gap: 6 } },
      h('input', { value: q, onChange: e => setQ(e.target.value), onKeyDown: e => { if (e.key === 'Enter') run(); }, placeholder: 'Search: words, "a phrase" or /regex/', 'aria-label': 'Search in this output',
        style: { flex: 1, minWidth: 0, height: 28, padding: '0 9px', borderRadius: 6, border: '1px solid ' + C.bds, background: C.inset, color: C.tx, font: 'inherit', fontSize: 12.5 } }),
      h('button', { type: 'button', onClick: run, style: btn }, 'Find')),
    err ? h('span', { role: 'alert', style: { fontSize: 12, color: '#F78166' } }, err) : null,
    res ? h('div', { role: 'list', 'aria-label': 'Search results', style: { display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 180, overflow: 'auto' } },
      h('span', { style: { fontSize: 11.5, color: C.mut } }, res.total ? `${res.total} hit${res.total === 1 ? '' : 's'}` : 'No hits'),
      res.hits.map(x => h('button', { key: x.offset, type: 'button', role: 'listitem', onClick: () => onHit(x),
        style: { ...btn, height: 'auto', padding: '4px 8px', textAlign: 'left', border: '1px solid ' + C.bd, fontFamily: MONO, fontSize: 11.5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' } },
        h('b', { style: { color: C.cy, fontWeight: 500 } }, (x.page ? `p.${x.page} ` : '') + `line ${x.line}  `), x.text.split('\n')[Math.min(1, x.text.split('\n').length - 1)].slice(0, 200)))) : null);
}

function PdfView({ api, output, page, setPage, info }) {
  const React = R(), [w, setW] = React.useState(null), n = info.pages;
  React.useEffect(() => { setW(null); api.outputText(output.id, { page }).then(setW, () => setW({ text: '' })); }, [output.id, page]);
  const text = (w?.text || '').replace(/^\f?--- page \d+ ---\n/, '');
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' } },
      h('button', { type: 'button', style: btn, disabled: page <= 1, onClick: () => setPage(page - 1), 'aria-label': 'Previous page' }, '‹'),
      h('span', { 'data-page': page, style: { fontFamily: MONO, fontSize: 12, color: C.mut } }, `Page ${page} of ${n}`),
      h('button', { type: 'button', style: btn, disabled: page >= n, onClick: () => setPage(page + 1), 'aria-label': 'Next page' }, '›'),
      info.outline?.length ? h('select', { 'aria-label': 'Outline', value: '', onChange: e => e.target.value && setPage(+e.target.value),
        style: { ...btn, maxWidth: 220 } }, h('option', { value: '' }, 'Jump to…'),
        info.outline.filter(x => x.page).map((x, i) => h('option', { key: i, value: x.page }, `${'  '.repeat(x.level - 1)}${x.title} · p.${x.page}`))) : null,
      info.scanned?.includes(page) ? h('span', { style: { fontSize: 11.5, color: '#FFB224' } }, 'No text layer on this page (a scan?)') : null),
    h('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-start' } },
      h('img', { src: api.outputPageUrl(output.id, page, { width: 900 }), alt: `Page ${page} of ${output.title}`,
        style: { flex: '1 1 300px', maxWidth: '100%', minWidth: 0, borderRadius: 6, border: '1px solid ' + C.bd, background: '#fff' } }),
      h('pre', { 'aria-label': `Text of page ${page}`, style: { flex: '1 1 260px', minWidth: 0, margin: 0, padding: 10, borderRadius: 6, background: C.inset, border: '1px solid ' + C.bd,
        fontFamily: MONO, fontSize: 11.5, lineHeight: 1.5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: '70vh', overflow: 'auto', color: C.tx } },
        w == null ? 'Loading…' : text || '(no text on this page)')));
}

function TextView({ api, output, line, info, first }) {
  const React = R(), [text, setText] = React.useState(first.text), [next, setNext] = React.useState(first.next_offset);
  const [rendered, setRendered] = React.useState(output.subtype === 'markdown' && line <= 1), box = React.useRef(null);
  const lines = React.useMemo(() => text.replace(/\n$/, '').split('\n'), [text]), lang = langOf(output.subtype);
  const more = () => next != null && api.outputText(output.id, { offset: next, limit: TEXT_WINDOW }).then(w => { setText(t => t + w.text); setNext(w.next_offset); });
  React.useEffect(() => {   // load until the cited line is in
    let n = 0;
    const go = async () => {
      let t = text, nx = next;
      while (nx != null && t.split('\n').length < line && n++ < MAX_WINDOWS) {
        const w = await api.outputText(output.id, { offset: nx, limit: TEXT_WINDOW });
        t += w.text; nx = w.next_offset;
      }
      if (t !== text) { setText(t); setNext(nx); }
    };
    go().catch(() => {});
  }, [line]);
  React.useEffect(() => { if (line > 1) { setRendered(false); box.current?.querySelector(`[data-line="${line}"]`)?.scrollIntoView?.({ block: 'center' }); } }, [line, lines.length]);
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
    output.subtype === 'markdown' ? h('div', { style: { display: 'flex', gap: 4 } },
      h('button', { type: 'button', style: { ...btn, background: rendered ? 'var(--hov,#1A2230)' : 'transparent' }, onClick: () => setRendered(true) }, 'Rendered'),
      h('button', { type: 'button', style: { ...btn, background: rendered ? 'transparent' : 'var(--hov,#1A2230)' }, onClick: () => setRendered(false) }, 'Source')) : null,
    rendered ? h('div', { className: 'aichat-md', style: { fontSize: 13 }, dangerouslySetInnerHTML: { __html: renderMarkdown(text) } })
      : h('div', { ref: box, className: 'aiview', role: 'document', 'aria-label': output.title,
        style: { fontFamily: MONO, fontSize: 12, lineHeight: 1.55, background: C.inset, border: '1px solid ' + C.bd, borderRadius: 6, padding: '6px 0', maxHeight: '70vh', overflow: 'auto' } },
        lines.map((l, i) => h('div', { key: i, 'data-line': i + 1, className: 'aiview-line' + (i + 1 === line && line > 1 ? ' hit' : '') },
          h('b', null, i + 1), h('span', { dangerouslySetInnerHTML: { __html: highlightLine(l, lang) || ' ' } })))),
    next != null ? h('button', { type: 'button', style: { ...btn, alignSelf: 'flex-start' }, onClick: more }, `Load more (${Math.round(100 * next / info.total_chars)}% shown)`) : null);
}

/** The viewer. `output`: an Output (text or document); `at`: {page} or {line} to open at. */
export function DocViewer({ api, output, at }) {
  const React = R();
  useCss();
  const start = startAt(output, at);
  const [first, setFirst] = React.useState(null), [err, setErr] = React.useState(null);
  const [page, setPage] = React.useState(start.page || 1), [line, setLine] = React.useState(start.line || 1);
  React.useEffect(() => { setFirst(null); api.outputText(output.id, { limit: TEXT_WINDOW }).then(setFirst, e => setErr(e.detail || e.message)); }, [output.id]);
  React.useEffect(() => { if (at?.page) setPage(+at.page); if (at?.line) setLine(+at.line); }, [at?.page, at?.line]);
  if (err) return h('div', { role: 'alert', style: { fontSize: 12.5, color: C.mut } }, `Can't show its text: ${err}`);
  if (!first) return h('div', { role: 'status', style: { fontSize: 12.5, color: C.mut } }, 'Loading the text…');
  const pdf = output.subtype === 'pdf' && first.pages > 0;
  const facts = [pdf ? `${first.pages} pages` : `${first.lines.toLocaleString()} lines`, `~${first.tokens.toLocaleString()} tokens`, output.subtype || output.kind];
  return h('div', { 'data-viewer': output.id, style: { display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 } },
    h('div', { style: { fontSize: 11.5, color: C.mut, fontFamily: MONO } }, facts.join(' · ')),
    [...(first.notes || []), ...(first.truncated ? ['The text is cut at 4 M characters.'] : [])].map((n, i) => h('div', { key: i, style: { fontSize: 12, color: C.mut } }, n)),
    h(Search, { api, output, onHit: x => (pdf && x.page ? setPage(x.page) : setLine(x.line)) }),
    pdf ? h(PdfView, { api, output, page, setPage, info: first })
      : first.text ? h(TextView, { api, output, line, info: first, first }) : h('div', { style: { fontSize: 12.5, color: C.mut } }, 'No text to show.'));
}
