// Sources under a reply (the reply bar, chat-replybar.js): the pages a turn read, from its own events.
// Nothing new is stored: `turnSources(turn)` reads the turn's `web_fetch` and `web_search` tool rows
// (chat-turn.js) and their results, which the hub wraps as `<untrusted …>` blocks. Pure part tested in
// utils/tests/web/chat-sources.test.mjs.
//
//   turnSources(turn, attached?) → { read: [Source], found: [Source], queries: [string], count }
//   Source: { url, site (the hostname), host (without www.), title, snippet, output_id?, n?, shared? }
//
// `read` are the pages the turn read: first the ones the user gave (`shared: true`, "you shared"): pages attached
// with "Add a web page" (the user event's `docs` carry the page's `url`; older events are resolved through
// `GET /api/outputs/{id}` by `useAttachedPages`, nothing stored) and links the user typed that the turn fetched; then
// the rest it fetched (deduplicated by URL, first read first). `found` are search results it didn't open. The icons come from the web mod (`GET /api/s/web/v1/favicon?host=`), which fetches each
// site's own icon once and caches it; a host it can't serve gets a letter on a tinted circle.

import { h, T, MONO, Icon, Popover } from './chat-ui.js';

const R = () => globalThis.React;
export const SEARCH_TOOLS = new Set(['web_search']);
export const FETCH_TOOLS = new Set(['web_fetch']);
const SNIPPET = 200;

/** Text without the hub's `<untrusted source="…">` wrapper (every block in it), trimmed. */
export function unwrap(s) {
  return String(s ?? '').replace(/<untrusted(?:\s+source="[^"\n]*")?>\n?/g, '').replace(/\n?<\/untrusted>/g, '').trim();
}
const oneLine = s => String(s ?? '').replace(/\s+/g, ' ').trim();
/** At most n characters, cut at a word, with an ellipsis. */
export function clip(s, n = SNIPPET) {
  s = oneLine(s);
  if (s.length <= n) return s;
  const cut = s.slice(0, n), sp = cut.lastIndexOf(' ');
  return (sp > n * 0.6 ? cut.slice(0, sp) : cut).replace(/[\s,;:.–-]+$/, '') + '…';
}

/** An http(s) URL that may be linked, or null. */
export function safeUrl(u) {
  if (typeof u !== 'string' || !/^https?:\/\//i.test(u.trim())) return null;
  try { const x = new URL(u.trim()); return /^https?:$/.test(x.protocol) && x.hostname ? x.href : null; } catch { return null; }
}
/** The key two URLs share when they are the same page: host without www., path without a trailing slash, query; no scheme or fragment. */
export function urlKey(u) {
  try {
    const x = new URL(u);
    return x.hostname.replace(/^www\./, '') + (x.pathname.replace(/\/+$/, '') || '') + x.search;
  } catch { return String(u); }
}

// A hostname the web mod serves icons for: a DNS name, not an IP or a local name.
const HOST = /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const LOCAL = /(^localhost|\.local|\.localhost|\.localdomain|\.internal|\.home\.arpa|\.lan)$/;
/** The web mod's icon URL for a hostname (through the hub's proxy), or null when there is none to ask for. */
export function faviconUrl(site, base = globalThis.GAIFA_API_BASE || '') {
  const s = String(site ?? '').toLowerCase().replace(/\.$/, '');
  if (!HOST.test(s) || LOCAL.test(s)) return null;
  return `${base}/api/s/web/v1/favicon?host=${encodeURIComponent(s)}`;
}

/** A tool result's content → its `result` object, or `{partial: text}` when the hub capped it (a JSON preview cut short). */
export function resultOf(content) {
  let o = content;
  if (typeof o === 'string') { try { o = JSON.parse(o); } catch { return { partial: o }; } }
  if (!o || typeof o !== 'object') return null;
  const r = o.result && typeof o.result === 'object' ? o.result : o;
  if (r.truncated && typeof r.preview === 'string') return { partial: r.preview };
  return r;
}
const STR = '"((?:[^"\\\\]|\\\\.)*)"';
const unjson = s => { try { return JSON.parse('"' + s + '"'); } catch { return s; } };
const field = (text, k) => { const m = new RegExp(`"${k}":\\s*${STR}`).exec(text); return m ? unjson(m[1]) : ''; };

/** A capped search result's preview → the results it still shows whole. */
function partialResults(text) {
  const re = new RegExp(`"title":\\s*${STR},\\s*"url":\\s*${STR},\\s*"snippet":\\s*${STR}`, 'g');
  return [...text.matchAll(re)].map(m => ({ title: unjson(m[1]), url: unjson(m[2]), snippet: unjson(m[3]) }));
}

/** The text of a web_fetch result without the hub's line numbers (`  120| …`) and excerpt lines (`── lines a–b ──`);
 * its "About this page:" line when it has one. */
export function plainPage(content) {
  const s = unwrap(content).replace(/\r\n?/g, '\n');
  const about = /^About this page: (.+)$/m.exec(s);
  if (about) return { about: about[1] };
  if (!/^\s*\d+\| /m.test(s)) return { text: s };
  return { text: s.split('\n').filter(l => !/^── lines \d/.test(l)).map(l => l.replace(/^\s*\d+\| ?/, '')).join('\n') };
}

/** The first words of a fetched page: the markdown without the web mod's header (title, Source, Fetched), as plain text. */
export function pageSnippet(content, n = SNIPPET) {
  const p = plainPage(content);
  if (p.about != null) return clip(p.about, n);
  let s = p.text;
  const head = /^# [^\n]*\n(?:[^\n]*\n){0,6}?---\n/.exec(s);       // pages.py: "# Title", Source, Fetched, Published, ---
  if (head && /\nSource: </.test(head[0])) s = s.slice(head[0].length);
  s = s.replace(/^\s*(```|~~~).*$/gm, ' ')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/<(https?:[^>\s]+)>/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '').replace(/^\s*>\s?/gm, '').replace(/^\s*(?:[-*+]|\d+[.)])\s+/gm, '')
    .replace(/^\s*\|?[\s:|-]+\|[\s:|-]*$/gm, ' ').replace(/\|/g, ' ').replace(/(\*\*|__|\*|_|`|~~)/g, '').replace(/^\s*(-{3,}|\*{3,})\s*$/gm, ' ');
  return clip(s, n);
}

const hostOf = site => site.replace(/^www\./, '');
function source(url, o = {}) {
  const u = safeUrl(url);
  if (!u) return null;
  const site = new URL(u).hostname;
  return { url: u, site, host: hostOf(site), title: oneLine(o.title) || hostOf(site), snippet: o.snippet || '', ...(o.output_id ? { output_id: o.output_id, n: o.n ?? null } : {}) };
}

/** URLs typed in a message (as the agent finds them, services/agent/agent/links.py), each as its urlKey. */
export function typedLinks(text) {
  const out = new Set();
  for (const m of String(text ?? '').matchAll(/https?:\/\/[^\s<>"'`[\]{}|\\^]+/gi)) {
    let u = m[0];
    for (;;) {
      if (/[.,;:!?*_~'"]$/.test(u)) u = u.slice(0, -1);
      else if (u.endsWith(')') && (u.match(/\)/g) || []).length > (u.match(/\(/g) || []).length) u = u.slice(0, -1);
      else break;
    }
    if (safeUrl(u)) out.add(urlKey(u));
  }
  return out;
}

/** The user's words in a message: its text and the replies to quoted parts (never the quoted parts). */
const saidOf = p => [...(Array.isArray(p?.quotes) ? p.quotes.map(q => q?.reply || '') : []), p?.text || ''].join('\n');

/** Pages the user attached to the turn's message: its `docs` with a `url` (plus `attached`, resolved ones). */
export function attachedPages(turn, attached = []) {
  const p = turn?.user?.ev?.payload || {}, out = [];
  for (const d of p.docs || []) {
    const r = d?.url ? d : attached.find(a => a.output_id === d?.id);
    const url = safeUrl(r?.url);
    if (url) out.push({ url, title: d.name || r.title, output_id: d.id, n: d.ref ? +String(d.ref).replace('#', '') : null,
      snippet: d.inline && typeof d.text === 'string' ? pageSnippet(d.text) : '' });
  }
  return out;
}

/** The turn's sources: pages the user gave, pages read (web_fetch done) and search results not opened, with the
 * searches' queries. `attached`: pages resolved by useAttachedPages for older events without `docs[].url`. */
export function turnSources(turn, attached = []) {
  const rows = (turn?.steps || []).flatMap(s => s.rows || []).filter(r => r.type === 'tool');
  const hits = new Map(), queries = [], read = [], seen = new Map();
  const typed = typedLinks(saidOf(turn?.user?.ev?.payload));
  for (const a of attachedPages(turn, attached)) {
    const s = source(a.url, { title: a.title, snippet: a.snippet, output_id: a.output_id, n: a.n });
    if (!s || seen.has(urlKey(s.url))) continue;
    s.shared = true;
    seen.set(urlKey(s.url), s);
    read.push(s);
  }
  // the search results first, so a page read later finds its snippet
  for (const r of rows) {
    if (!SEARCH_TOOLS.has(r.name)) continue;
    const q = oneLine(r.item.call?.arguments?.query);
    if (q && !queries.includes(q)) queries.push(q);
    const res = r.item.result;
    if (!res || (res.status && res.status !== 'done') || res.error) continue;
    const got = resultOf(res.content);
    const list = got?.partial != null ? partialResults(got.partial) : Array.isArray(got?.results) ? got.results : [];
    for (const it of list) {
      const s = source(it?.url, { title: unwrap(it?.title), snippet: clip(unwrap(it?.snippet), SNIPPET + 40) });
      if (s && !hits.has(urlKey(s.url))) hits.set(urlKey(s.url), s);
    }
  }
  for (const r of rows) {
    if (!FETCH_TOOLS.has(r.name)) continue;
    const res = r.item.result;
    if (!res || (res.status && res.status !== 'done') || res.error) continue;
    const got = resultOf(res.content) || {}, part = got.partial;
    const asked = part != null ? field(part, 'url') : got.url, final = part != null ? field(part, 'final_url') : got.final_url;
    const url = safeUrl(final) || safeUrl(asked) || safeUrl(r.item.call?.arguments?.url);
    if (!url) continue;
    const keys = [url, asked, r.item.call?.arguments?.url].filter(Boolean).map(urlKey);
    if (keys.some(k => seen.has(k))) continue;
    const hit = keys.map(k => hits.get(k)).find(Boolean), out = (res.outputs || [])[0];
    const title = unwrap(part != null ? field(part, 'title') : got.title) || out?.title || hit?.title;
    const snippet = hit?.snippet || pageSnippet(part != null ? field(part, 'content') : got.content);
    const s = source(url, { title, snippet, output_id: out?.output_id, n: out?.n });
    if (!s) continue;
    if (keys.some(k => typed.has(k))) s.shared = true;     // a link the user typed
    keys.forEach(k => seen.set(k, s));
    read.push(s);
  }
  read.sort((a, b) => (b.shared ? 1 : 0) - (a.shared ? 1 : 0));     // what the user gave first (a stable sort)
  const found = [...hits.entries()].filter(([k]) => !seen.has(k)).map(([, s]) => s);
  return { read, found, queries, count: read.length };
}

const resolved = new Map();      // output id → {output_id, url, title} | null, for this page's life
/** Attached outputs of the turn's message whose `docs` entry has no `url` (events from before it was stored):
 * looked up once each through `ctx.api.getOutput` (works for hidden outputs); a web mod page gives its URL. */
export function useAttachedPages(turn, ctx) {
  const React = R(), p = turn?.user?.ev?.payload;
  const ids = (p?.docs || []).filter(d => d?.id && !d.url).map(d => d.id);
  const key = ids.join(','), [, bump] = React.useState(0);
  React.useEffect(() => {
    const todo = ids.filter(id => !resolved.has(id));
    if (!todo.length || !ctx?.api?.getOutput) return;
    let live = true;
    Promise.all(todo.map(id => ctx.api.getOutput(id).then(o => {
      const m = o?.meta || {}, url = o?.service === 'web' ? safeUrl(m.final_url) || safeUrl(m.url) : null;
      resolved.set(id, url ? { output_id: id, url, title: o.title } : null);
    }, () => resolved.set(id, null)))).then(() => { if (live) bump(x => x + 1); });
    return () => { live = false; };
  }, [key]);
  return ids.map(id => resolved.get(id)).filter(Boolean);
}

/** Up to n distinct sites to show icons for: the pages read, then the results found. */
export function iconSites(src, n = 3) {
  const out = [];
  for (const s of [...src.read, ...src.found]) if (!out.includes(s.site) && out.push(s.site) >= n) break;
  return out;
}

// ---------- the icon ----------
const TINTS = [[T.cy, T.tcy], [T.pu, T.tpu], [T.gr, T.tgr], [T.acct, T.tacc], [T.rd, T.trd]];
const tint = s => TINTS[[...String(s)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7) % TINTS.length];

/** A site's icon from the web mod, or its first letter on a tinted circle when there's none. */
export function Favicon({ site, size = 16, ring }) {
  const React = R(), url = faviconUrl(site), [bad, setBad] = React.useState(!url);
  React.useEffect(() => setBad(!url), [url]);
  const box = { width: size, height: size, borderRadius: 99, flex: 'none', boxShadow: ring ? `0 0 0 1.5px ${ring}` : 'none' };
  if (bad) {
    const [fg, bg] = tint(hostOf(site || '?'));
    return h('span', { 'aria-hidden': true, style: { ...box, display: 'inline-grid', placeItems: 'center', background: bg, color: fg, fontSize: Math.round(size * 0.6), fontWeight: 700, lineHeight: 1, textTransform: 'uppercase' } },
      (hostOf(site || '?')[0] || '?'));
  }
  return h('img', { src: url, alt: '', width: size, height: size, loading: 'lazy', decoding: 'async', referrerPolicy: 'no-referrer', onError: () => setBad(true),
    style: { ...box, objectFit: 'contain', background: T.inset } });
}

// ---------- the pill and its popover ----------
/** Where a popover anchored at `el` fits: above or below (whichever has more room inside the scrolling thread), and its max height. */
export function placeFor(el, cap = 520) {
  if (!el || typeof window === 'undefined') return { place: 'up-left', max: cap };
  const r = el.getBoundingClientRect();
  let box = { top: 0, bottom: window.innerHeight };
  for (let p = el.parentElement; p; p = p.parentElement) {
    const o = getComputedStyle(p).overflowY;
    if (o === 'auto' || o === 'scroll') { const b = p.getBoundingClientRect(); box = { top: Math.max(0, b.top), bottom: Math.min(window.innerHeight, b.bottom) }; break; }
  }
  const above = r.top - box.top, below = box.bottom - r.bottom, up = above > below;
  return { place: up ? 'up-left' : 'down-left', max: Math.max(160, Math.min(cap, (up ? above : below) - 14)) };
}

const ROW_CSS = `.aichat-src{position:relative;border-radius:7px}.aichat-src:hover,.aichat-src:focus-within{background:var(--hov,#161C28)}
.aichat-src a{outline:none}.aichat-src a:focus-visible{box-shadow:0 0 0 2px var(--cy,#58C4DD);border-radius:7px}
.aichat-srcpill:hover{border-color:var(--bdh,#3A4A63)!important;color:var(--tx,#E6EAF2)!important}.aichat-srcpill:focus-visible{outline:2px solid var(--cy,#58C4DD);outline-offset:1px}
.aichat-clamp2{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.aichat-clamp3{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}`;
let cssDone = false;
function injectCss() {
  if (cssDone || typeof document === 'undefined') return;
  cssDone = true;
  const s = document.createElement('style'); s.id = 'aichat-sources-css'; s.textContent = ROW_CSS; document.head.appendChild(s);
}

function SourceRow({ s, ctx }) {
  const viewer = s.output_id && ctx?.openOutput;
  return h('li', { className: 'aichat-src', style: { listStyle: 'none' } },
    h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer', title: s.url,
      style: { display: 'flex', flexDirection: 'column', gap: 3, padding: viewer ? '8px 36px 8px 8px' : 8, color: 'inherit', textDecoration: 'none', minWidth: 0 } },
    h('span', { style: { display: 'flex', alignItems: 'center', gap: 6, minWidth: 0, fontSize: 11.5, color: T.mut } },
      h(Favicon, { site: s.site, size: 14 }),
      h('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 } }, s.host),
      s.n ? h('span', { style: { fontFamily: MONO, fontSize: 10.5, color: T.dim, flex: 'none' } }, '#' + s.n) : null,
      s.shared ? h('span', { title: 'A page you attached or a link you wrote', style: { fontSize: 10.5, color: T.cy, flex: 'none' } }, 'you shared') : null),
    h('span', { className: 'aichat-clamp2', style: { fontSize: 13, fontWeight: 600, color: T.tx, lineHeight: 1.35, overflowWrap: 'anywhere' } }, s.title),
    s.snippet ? h('span', { className: 'aichat-clamp3', style: { fontSize: 12, color: T.mut, lineHeight: 1.45, overflowWrap: 'anywhere' } }, s.snippet) : null),
    viewer ? h('button', { type: 'button', title: `Open the saved page${s.n ? ' #' + s.n : ''} in the viewer`, 'aria-label': `Open ${s.title} in the viewer`,
      onClick: () => ctx.openOutput(s.output_id),
      style: { position: 'absolute', top: 6, right: 6, display: 'grid', placeItems: 'center', width: 26, height: 26, border: '1px solid ' + T.bds, borderRadius: 6, background: T.card, color: T.mut, cursor: 'pointer' } },
    h(Icon, { d: 'doc', size: 13 })) : null);
}

function queryLine(qs) {
  if (!qs.length) return null;
  const shown = qs.slice(0, 2).map(q => `“${clip(q, 80)}”`).join(', ');
  return `Results for ${shown}${qs.length > 2 ? ` and ${qs.length - 2} more` : ''}`;
}

/** The popover's body: the query line, the pages read, then "Also found (n)" folded. */
export function SourcesList({ src, ctx, onClose }) {
  const React = R(), [more, setMore] = React.useState(!src.read.length);
  const list = items => h('ul', { style: { margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 2 } }, items.map(s => h(SourceRow, { key: s.url, s, ctx })));
  const q = queryLine(src.queries);
  return h(React.Fragment, null,
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
      h('span', { style: { fontSize: 13.5, fontWeight: 600, flex: 1 } }, 'Sources'),
      h('button', { type: 'button', onClick: onClose, 'aria-label': 'Close the sources', style: { display: 'grid', placeItems: 'center', width: 24, height: 24, border: 0, borderRadius: 5, background: 'none', color: T.mut, cursor: 'pointer' } }, h(Icon, { d: 'x', size: 13 }))),
    q ? h('div', { title: src.queries.join('\n'), style: { fontSize: 12, color: T.mut, marginTop: -4, overflowWrap: 'anywhere' } }, q) : null,
    src.read.length ? h('div', { style: { fontSize: 11.5, color: T.dim } }, `Read ${src.read.length} page${src.read.length === 1 ? '' : 's'}`) : null,
    src.read.length ? list(src.read) : null,
    src.found.length ? h('button', { type: 'button', onClick: () => setMore(!more), 'aria-expanded': more ? 'true' : 'false',
      style: { display: 'flex', alignItems: 'center', gap: 6, padding: '4px 2px', border: 0, background: 'none', color: T.mut, font: 'inherit', fontSize: 12, cursor: 'pointer', textAlign: 'left' } },
    h(Icon, { d: more ? 'chevD' : 'chevR', size: 12 }), `Also found (${src.found.length})`, h('span', { style: { color: T.dim } }, ' · not opened')) : null,
    more && src.found.length ? list(src.found) : null);
}

/** The pill: up to three site icons and "N sources" (or "N results" when the turn only searched); opens the list. */
export function SourcesPill({ src, ctx }) {
  const React = R(), [open, setOpen] = React.useState(false), [place, setPlace] = React.useState({ place: 'up-left', max: 520 });
  const btn = React.useRef(null), pop = React.useRef(null);
  React.useEffect(injectCss, []);
  React.useEffect(() => { if (open) pop.current?.querySelector('a,button')?.focus(); }, [open]);
  if (!src || (!src.read.length && !src.found.length)) return null;
  const n = src.read.length || src.found.length, word = src.read.length ? (n === 1 ? 'source' : 'sources') : (n === 1 ? 'result' : 'results');
  const toggle = () => { if (!open) setPlace(placeFor(btn.current)); setOpen(!open); };
  const close = () => { setOpen(false); btn.current?.focus(); };
  const sites = iconSites(src);
  return h('span', { style: { position: 'relative', display: 'inline-flex' } },
    h('button', { ref: btn, type: 'button', className: 'aichat-srcpill', onClick: toggle, 'aria-haspopup': 'dialog', 'aria-expanded': open ? 'true' : 'false',
      title: src.read.length ? `The ${n} page${n === 1 ? '' : 's'} this reply read` : 'Search results (no page was opened)',
      style: { display: 'inline-flex', alignItems: 'center', gap: 7, height: 26, padding: '0 10px 0 6px', borderRadius: 99, border: '1px solid ' + T.bds, background: T.inset, color: T.mut, font: 'inherit', fontSize: 12, cursor: 'pointer', whiteSpace: 'nowrap' } },
    h('span', { style: { display: 'inline-flex' } }, sites.map((s, i) => h('span', { key: s, style: { display: 'inline-flex', marginLeft: i ? -5 : 0, zIndex: 3 - i } }, h(Favicon, { site: s, size: 16, ring: T.inset })))),
    `${n} ${word}`),
    open ? h('div', { ref: pop }, h(Popover, { open, onClose: close, place: place.place, width: 400, label: 'Sources', style: { gap: 8, padding: '10px 8px 8px', maxHeight: place.max } }, h(SourcesList, { src, ctx, onClose: close }))) : null);
}
