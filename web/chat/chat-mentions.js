// @-mentions in the message box (plan 48.2): typing `@` lists what you can name: this chat's outputs (#n), its
// folders, and what the mods declare (a voice, a workflow, an engine: GET /api/mentions). `@voice:Bre` narrows to a
// kind. A picked output becomes an attachment chip; anything else goes in the text as `@kind:name` and rides with the
// message as a mention, which fills that turn's calls (utils/tools/pins.py). Deleting the text drops the mention.

import { h, T, MONO } from './chat-ui.js';

const R = () => globalThis.React;

/** The `@word` the caret is in: {start, end, kind, query}, or null. */
export function atToken(text, caret) {
  const s = String(text || ''), at = caret == null ? s.length : caret;
  const before = s.slice(0, at), m = /(^|\s)@([\w#:.\-/]*)$/.exec(before);
  if (!m) return null;
  const start = at - m[2].length - 1, word = m[2], i = word.indexOf(':');
  const after = /^[\w#:.\-/]*/.exec(s.slice(at))[0];
  return { start, end: at + after.length, kind: i > 0 ? word.slice(0, i) : null, query: i > 0 ? word.slice(i + 1) : word };
}

/** Choices that fit the token: by kind (voice:, #) and words in the label or id; outputs first for `#`. */
export function filterChoices(choices, tok, max = 12) {
  if (!tok) return [];
  let list = choices;
  if (tok.kind) list = list.filter(c => c.kind === tok.kind);
  else if (tok.query.startsWith('#')) list = list.filter(c => c.kind === 'output');
  const q = (tok.kind ? tok.query : tok.query.replace(/^#/, '')).toLowerCase();
  if (q) list = list.filter(c => c.label.toLowerCase().includes(q) || String(c.id).toLowerCase().includes(q) || (!tok.kind && c.kind.startsWith(q)) || (c.kind === 'output' && String(c.n) === q));
  return list.slice(0, max);
}

/** The text a pick writes: `@voice:Brendon ` (a space after; names with spaces keep them out). */
export function tokenOf(m) {
  return '@' + m.kind + ':' + String(m.id).replace(/\s+/g, '_');
}

/** Replace the token with the pick: {text, caret}. Outputs leave no text (they become chips). */
export function insertMention(text, tok, m) {
  const piece = m.kind === 'output' ? '' : tokenOf(m) + ' ';
  const out = text.slice(0, tok.start) + piece + text.slice(tok.end).replace(/^\s+/, piece ? '' : ' ').replace(/^ $/, '');
  return { text: out, caret: tok.start + piece.length };
}

/** The picked mentions whose text is still in the message (as sent with it). */
export function mentionsIn(text, picked) {
  const seen = new Set();
  return (picked || []).filter(m => { const t = tokenOf(m); if (seen.has(t) || !new RegExp('(^|\\s)' + t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?=\\s|$|[.,!?])').test(text)) return false; seen.add(t); return true; })
    .map(({ kind, id, label, fills }) => ({ kind, id, label, fills: fills || [] }));
}

/** This chat's outputs and folders as choices, then the mods' (from the hub). */
export function localChoices(outputs, folders) {
  return [
    ...(outputs || []).filter(o => o.n).map(o => ({ kind: 'output', id: o.output_id, n: o.n, label: `#${o.n} ${o.title || o.kind}`, sub: o.kind, output: o })),
    ...(folders || []).map(f => ({ kind: 'folder', id: f.path || f, label: f.path || f, sub: f.level || 'folder' })),
  ];
}

/** The hub's mentions for a token, fetched after a short pause; [] while the token is for outputs. */
export function useHubMentions(api, tok) {
  const React = R(), [list, setList] = React.useState([]);
  const key = tok ? `${tok.kind || ''}|${tok.query}` : null;
  React.useEffect(() => {
    if (!tok || !api?.listMentions || tok.query.startsWith('#') || tok.kind === 'output' || tok.kind === 'folder') { setList([]); return undefined; }
    let alive = true;
    const t = setTimeout(() => api.listMentions({ q: tok.query, kind: tok.kind || undefined }).then(r => alive && setList(r || []), () => alive && setList([])), 150);
    return () => { alive = false; clearTimeout(t); };
  }, [key]);
  return list;
}

export function MentionList({ items, sel, onPick }) {
  return h('div', { role: 'listbox', 'aria-label': 'Mention', style: { position: 'absolute', left: 0, right: 0, bottom: 'calc(100% + 6px)', zIndex: 30, background: T.card, border: '1px solid ' + T.bds, borderRadius: 9, boxShadow: '0 12px 30px rgba(0,0,0,.3)', padding: 4, maxHeight: 280, overflowY: 'auto' } },
    items.map((m, i) => h('button', { key: m.kind + ':' + m.id, type: 'button', role: 'option', 'aria-selected': i === sel ? 'true' : 'false', onMouseDown: e => { e.preventDefault(); onPick(m); },
      style: { display: 'flex', alignItems: 'center', gap: 10, width: '100%', padding: '6px 9px', border: 0, borderRadius: 6, background: i === sel ? T.hov : 'transparent', color: T.tx, font: 'inherit', cursor: 'pointer', textAlign: 'left' } },
      m.output?.preview ? h('img', { src: m.output.preview, alt: '', style: { width: 20, height: 20, objectFit: 'cover', borderRadius: 3, flex: 'none' } }) : null,
      h('span', { style: { fontFamily: MONO, fontSize: 11, color: T.pu, flex: 'none' } }, m.kind),
      h('span', { style: { fontSize: 12.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 } }, m.label),
      m.sub ? h('span', { style: { marginLeft: 'auto', fontSize: 11.5, color: T.dim, flex: 'none' } }, m.sub) : null)));
}
