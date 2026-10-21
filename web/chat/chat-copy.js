// Copy a reply (the reply bar, chat-replybar.js) in one of three ways: Text only, Including citations, or
// Including thinking and steps. The split button copies with the default; its chevron lists the three and
// copies with the one picked, which is remembered: the default is the way picked most often in the last
// 24 hours (a tie goes to the latest; nothing picked → Text only). The picks are kept in this browser
// (`aihub.chat.copyModes` through chat-ui.js's getPref/setPref; at most 50, none older than a day).
// Pure part tested in utils/tests/web/chat-copy.test.mjs.

import { h, T, Icon, Popover, getPref, setPref } from './chat-ui.js';
import { parseCitations } from './chat-md.js';
import { stepText, errorText } from './chat-steps.js';
import { SEARCH_TOOLS, FETCH_TOOLS, turnSources, placeFor } from './chat-sources.js';

const R = () => globalThis.React;
export const MODES = [
  { id: 'text', label: 'Text only', hint: 'The answer, without links, citations or sources' },
  { id: 'cites', label: 'Including citations', hint: 'The answer as written, with a list of the pages it read' },
  { id: 'steps', label: 'Including thinking and steps', hint: 'What it thought and did, then the answer and its sources' },
];
const IDS = new Set(MODES.map(m => m.id));
export const COPY_KEY = 'aihub.chat.copyModes';
export const DAY_MS = 86400000;
const KEEP = 50;

// ---------- the remembered default ----------
const fresh = (log, now) => (Array.isArray(log) ? log : []).filter(e => e && IDS.has(e.mode) && typeof e.ts === 'number' && now - e.ts < DAY_MS && e.ts <= now + 60000);
/** The mode picked most often in the last 24 hours; a tie goes to the one picked last; none → 'text'. */
export function defaultMode(log, now = Date.now()) {
  const recent = fresh(log, now), stat = new Map();
  for (const e of recent) { const s = stat.get(e.mode) || { n: 0, last: 0 }; s.n++; s.last = Math.max(s.last, e.ts); stat.set(e.mode, s); }
  let best = null;
  for (const [mode, s] of stat) if (!best || s.n > best.n || (s.n === best.n && s.last > best.last)) best = { mode, ...s };
  return best ? best.mode : 'text';
}
/** The log with this pick added: older than a day dropped, at most 50 kept. */
export function recordMode(log, mode, now = Date.now()) {
  if (!IDS.has(mode)) return fresh(log, now).slice(-KEEP);
  return [...fresh(log, now), { mode, ts: now }].slice(-KEEP);
}

// ---------- the text of each mode ----------
const SOURCES_HEAD = /^\s{0,3}(?:#{1,6}\s*)?(?:\*\*|__)?(?:sources|references)(?:\*\*|__)?\s*:?\s*(?:\*\*|__)?\s*$/i;
const LISTISH = /^\s*(?:[-*+]|\d+[.)])\s+|^\s*\[[^\]]+\]\([^)]+\)\s*$|^\s*<?https?:\/\//;
/** The reply without the Sources list the model wrote at its end (a "Sources" line followed only by list items or links). */
export function cutSources(md) {
  const lines = String(md ?? '').split('\n');
  for (let i = lines.length - 1; i >= 0; i--) {
    if (!SOURCES_HEAD.test(lines[i])) continue;
    const rest = lines.slice(i + 1).filter(l => l.trim());
    if (rest.length && rest.every(l => LISTISH.test(l))) return lines.slice(0, i).join('\n').replace(/\s+$/, '');
    break;
  }
  return String(md ?? '');
}

const isCite = s => /^\s*(#\d{1,4}|output:[0-9a-f]{12})\b/.test(s);
/** Text only: links become their words, citations (`#3 p.14`, `[#2](url)`, `(#2)`) go, and so does a Sources list. */
export function textOnly(md) {
  let s = cutSources(md);
  // keep code as it is: cut fenced blocks and code spans out first
  const keep = [];
  const stash = x => `\u0000${keep.push(x) - 1}\u0000`;
  s = s.replace(/^(\s*)(`{3,}|~{3,})[^\n]*\n[\s\S]*?\n\s*\2\s*$/gm, m => stash(m)).replace(/`[^`\n]+`/g, m => stash(m));
  s = s.replace(/!\[([^\]]*)\]\([^)\s]*\)/g, '$1');
  s = s.replace(/\[([^\]\n]+)\]\([^)\s]+\)/g, (_, text) => (isCite(text) ? '' : text));
  s = s.replace(/<(https?:\/\/[^>\s]+)>/g, '$1');
  s = s.split('\n').map(line => {
    for (const c of parseCitations(line)) line = line.replace(c.text, '');
    return line;
  }).join('\n');
  s = s.replace(/[([]\s*(?:(?:#\d{1,4}|output:[0-9a-f]{12})\s*[,;]?\s*)+[)\]]/g, '');       // (#2), [#2, #3]
  s = s.replace(/[([]\s*[,;]?\s*[)\]]/g, '');                                                // what's left empty
  s = s.replace(/[ \t]+([.,;:!?])/g, '$1').replace(/[ \t]{2,}/g, ' ').replace(/[ \t]+$/gm, '');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => keep[+i]).trim();
}

/** The pages read as a numbered list: "1. Title — https://…". */
export function sourcesList(src) {
  if (!src?.read?.length) return '';
  return 'Sources\n' + src.read.map((p, i) => `${i + 1}. ${p.title} — ${p.url}`).join('\n');
}
/** Including citations: the reply as written plus the pages it read (replacing the model's own Sources list). */
export function withCitations(md, src) {
  const list = sourcesList(src);
  if (!list) return String(md ?? '').trim();
  return cutSources(md).trim() + '\n\n' + list;
}

const indent = s => String(s).trim().replace(/\n/g, '\n  ');
/** One step of the turn in words: thinking, an update, a search, a page read, any other tool, a question, a memory. */
export function stepLine(row, ctx) {
  const it = row.item, args = (it.decision?.approve && it.decision.arguments) || it.call?.arguments || {}, r = it.result;
  const failed = r && (r.error || (r.status && r.status !== 'done'));
  if (row.type === 'thinking') return row.text?.trim() ? `- Thought${row.seconds ? ` (${Math.round(row.seconds)}s)` : ''}: ${indent(row.text)}` : null;
  if (row.type === 'update') return row.text?.trim() ? `- Said: ${indent(row.text)}` : null;
  if (row.type === 'memory') return `- Remembered: ${it.ev?.payload?.text || ''}`;
  if (row.type === 'question') return `- Asked you: ${(it.q?.questions || []).map(q => q.question).join(' / ')}`;
  if (row.type !== 'tool') return null;
  if (SEARCH_TOOLS.has(row.name)) return `- ${failed ? 'Tried searching' : 'Searched'} the web: “${args.query || ''}”${failed ? ` (${errorText(r).text})` : ''}`;
  if (FETCH_TOOLS.has(row.name) && !failed && r) {
    const page = turnSources({ steps: [{ rows: [row] }] }).read[0];
    return page ? `- Read “${page.title}” (${page.url})` : `- Read ${args.url || 'a page'}`;
  }
  if (FETCH_TOOLS.has(row.name)) return `- Couldn't read ${args.url || 'a page'}${r ? ` (${r.error?.detail || errorText(r).text})` : ''}`;
  const w = stepText(row.name, { args, done: true, ctx });
  if (failed) return `- Tried ${w.label.charAt(0).toLowerCase() + w.label.slice(1)}: ${errorText(r).text}`;
  return `- ${w.label}${w.detail ? `: ${w.detail}` : ''}`;
}
/** Including thinking and steps: the turn's thinking and steps in order, then the answer with its sources. */
export function withSteps(md, turn, src, ctx) {
  const lines = (turn?.steps || []).flatMap(s => s.rows || []).map(r => stepLine(r, ctx)).filter(Boolean);
  const answer = withCitations(md, src);
  return lines.length ? `Thinking and steps\n${lines.join('\n')}\n\nAnswer\n${answer}` : answer;
}
/** The text a mode copies. */
export function copyText(mode, { text, turn, src, ctx } = {}) {
  const s = src || turnSources(turn);
  if (mode === 'cites') return withCitations(text, s);
  if (mode === 'steps') return withSteps(text, turn, s, ctx);
  return textOnly(text);
}

/** Writes to the clipboard, falling back to a hidden textarea (as chat-md.js's installCopy); true when it worked. */
export async function toClipboard(text, doc = globalThis.document) {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* the fallback */ }
  if (!doc?.body) return false;
  const t = doc.createElement('textarea'); t.value = text; t.setAttribute('readonly', ''); t.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
  doc.body.appendChild(t); t.select();
  try { return !!doc.execCommand('copy'); } catch { return false; } finally { t.remove(); }
}

// ---------- the split button ----------
const iconBtn = { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 5, height: 24, border: 0, background: 'none', color: T.dim, font: 'inherit', fontSize: 12, cursor: 'pointer', padding: 0 };

export function CopyButton({ text, turn, src, ctx }) {
  const React = R(), [open, setOpen] = React.useState(false), [place, setPlace] = React.useState({ place: 'up-left', max: 320 }), [said, setSaid] = React.useState(null), [log, setLog] = React.useState(() => getPref(COPY_KEY, []));
  const timer = React.useRef(0), chev = React.useRef(null), menu = React.useRef(null);
  React.useEffect(() => () => clearTimeout(timer.current), []);
  React.useEffect(() => { if (open) (menu.current?.querySelector('[aria-checked="true"]') || menu.current?.querySelector('button'))?.focus(); }, [open]);
  const def = defaultMode(log), defLabel = MODES.find(m => m.id === def).label;
  const run = async mode => {
    const ok = await toClipboard(copyText(mode, { text, turn, src, ctx }));
    setSaid(ok ? 'Copied' : 'Copy failed');
    clearTimeout(timer.current); timer.current = setTimeout(() => setSaid(null), 1600);
  };
  const pick = mode => {
    const next = recordMode(getPref(COPY_KEY, []), mode);
    setPref(COPY_KEY, next); setLog(next); setOpen(false); chev.current?.focus();
    run(mode);
  };
  const onKey = e => {   // arrow keys move between the three
    const items = [...(menu.current?.querySelectorAll('button[role="menuitemradio"]') || [])], i = items.indexOf(document.activeElement);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); items[(i + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length]?.focus(); }
    if (e.key === 'Home') { e.preventDefault(); items[0]?.focus(); }
    if (e.key === 'End') { e.preventDefault(); items[items.length - 1]?.focus(); }
  };
  const ok = said === 'Copied';
  return h('span', { style: { position: 'relative', display: 'inline-flex', alignItems: 'center' } },
    h('button', { type: 'button', onClick: () => run(def), title: `Copy: ${defLabel.toLowerCase()}`, 'aria-label': `Copy the reply, ${defLabel.toLowerCase()}`,
      style: { ...iconBtn, minWidth: 24, padding: '0 3px', borderRadius: '5px 0 0 5px', color: said ? (ok ? T.gr : T.rd) : T.dim } },
    h(Icon, { d: ok ? 'check' : 'copy', size: 13 }), said ? h('span', { role: 'status' }, said) : null),
    h('button', { ref: chev, type: 'button', onClick: () => { if (!open) setPlace(placeFor(chev.current, 320)); setOpen(!open); }, 'aria-haspopup': 'menu', 'aria-expanded': open ? 'true' : 'false', title: 'Copy as…', 'aria-label': 'Copy as…',
      style: { ...iconBtn, width: 16, borderRadius: '0 5px 5px 0' } }, h(Icon, { d: 'chevD', size: 11 })),
    open ? h(Popover, { open, onClose: () => { setOpen(false); chev.current?.focus(); }, place: place.place, width: 270, label: 'Copy as', style: { padding: 6, gap: 2, maxHeight: place.max } },
      h('div', { ref: menu, role: 'menu', 'aria-label': 'Copy as', onKeyDown: onKey, style: { display: 'flex', flexDirection: 'column', gap: 2 } },
        h('div', { style: { fontSize: 11, color: T.dim, padding: '2px 8px 4px' } }, 'Copy as… (the default is your most used today)'),
        MODES.map(m => h('button', { key: m.id, type: 'button', role: 'menuitemradio', 'aria-checked': m.id === def ? 'true' : 'false', className: 'aichat-opt', onClick: () => pick(m.id),
          style: { display: 'flex', alignItems: 'flex-start', gap: 8, padding: '6px 8px', border: '1px solid transparent', borderRadius: 6, background: m.id === def ? T.hov : 'none', color: T.tx, font: 'inherit', textAlign: 'left', cursor: 'pointer' } },
        h('span', { style: { width: 13, flex: 'none', color: T.gr, display: 'flex', paddingTop: 2 } }, m.id === def ? h(Icon, { d: 'check', size: 13 }) : null),
        h('span', { style: { display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 } },
          h('span', { style: { fontSize: 12.5, fontWeight: 500 } }, m.label, m.id === def ? h('span', { style: { color: T.dim, fontWeight: 400 } }, ' · default') : null),
          h('span', { style: { fontSize: 11.5, color: T.mut } }, m.hint)))))) : null);
}
