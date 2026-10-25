// The Settings page's rows and groups (plan settings-redesign 1.2): one row anatomy (label and hint on the
// left, the control on the right, its error under it) and one component per control, drawn from a row of
// schema.js. The toggle, chip, segmented and order-list markup that Hub.dc.html had three times is here
// once. Plain ES module on the page's React; written by us (web/PATCHES.md).

import { h, T, MONO, chipSt } from '../chat/chat-ui.js';

const R = () => globalThis.React;
const CHEV_U = 'M6 15l6-6 6 6', CHEV_D = 'M6 9l6 6 6-6';
const svg = (d, size = 14) => h('svg', { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.75,
  strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true }, h('path', { d }));

// ---------- styles (the values the Hub.dc.html template used) ----------
export const cardSt = { background: T.card, border: '1px solid ' + T.bd, borderRadius: 10, padding: '4px 16px' };
export const label11 = { margin: 0, fontSize: 11, fontWeight: 600, letterSpacing: '.07em', textTransform: 'uppercase', color: T.mut };
const inputSt = bad => ({ height: 32, width: 140, padding: '0 10px', borderRadius: 6, border: '1px solid ' + (bad ? T.rd : T.bds), background: T.sb, color: T.tx, fontFamily: MONO, fontSize: 13 });
const segSt = on => ({ height: 26, padding: '0 10px', border: 0, borderRadius: 5, fontSize: 12, fontWeight: 500, cursor: 'pointer', whiteSpace: 'nowrap', font: 'inherit',
  background: on ? T.hov : 'transparent', color: on ? T.tx : T.mut, boxShadow: on ? '0 0 0 1px ' + T.bds : 'none' });
const iconBtn = { width: 28, height: 28, display: 'grid', placeItems: 'center', border: 0, borderRadius: 6, background: 'transparent', color: T.tx, cursor: 'pointer' };

// ---------- controls ----------
export function Toggle({ on, onChange, label, disabled }) {
  return h('button', { type: 'button', role: 'switch', 'aria-label': label, 'aria-checked': on ? 'true' : 'false', disabled, onClick: () => onChange(!on),
    style: { position: 'relative', width: 34, height: 20, flex: 'none', borderRadius: 99, border: 0, padding: 0, cursor: 'pointer', background: on ? T.gr : T.bds, transition: 'background .15s' } },
  h('span', { style: { position: 'absolute', top: 3, left: on ? 17 : 3, width: 14, height: 14, borderRadius: 99, background: '#fff', transition: 'left .15s' } }));
}
export function Segmented({ value, choices, onChange, label }) {
  return h('div', { role: 'group', 'aria-label': label, style: { display: 'inline-flex', flexWrap: 'wrap', maxWidth: '100%', padding: 2, borderRadius: 7, border: '1px solid ' + T.bd, background: T.sb } },
    choices.map(c => h('button', { key: String(c.value), type: 'button', 'aria-pressed': c.value === value ? 'true' : 'false', onClick: () => onChange(c.value), style: segSt(c.value === value) }, c.label)));
}
export function Chips({ value = [], choices, onChange, label }) {
  return h('div', { role: 'group', 'aria-label': label, style: { display: 'flex', flexWrap: 'wrap', gap: 6 } },
    choices.map(c => { const on = value.includes(c.value);
      return h('button', { key: c.value, type: 'button', 'aria-pressed': on ? 'true' : 'false', style: chipSt(on),
        onClick: () => onChange(on ? value.filter(x => x !== c.value) : [...value, c.value]) }, c.label); }));
}
/** Items reordered with up/down buttons; `value` is the whole list (ids not in `items` keep their place at the end). */
export function OrderList({ value = [], items, onChange }) {
  const ids = items.map(i => i.id), move = (i, d) => { const l = [...ids]; [l[i], l[i + d]] = [l[i + d], l[i]]; onChange([...l, ...value.filter(x => !ids.includes(x))]); };
  return h('ol', { style: { listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 4 } },
    items.map((it, i) => h('li', { key: it.id, style: { display: 'flex', alignItems: 'center', gap: 10, height: 38, padding: '0 6px 0 10px', borderRadius: 7, background: T.inset, border: '1px solid ' + T.bd } },
      h('span', { style: { fontFamily: MONO, fontSize: 12, color: T.mut, width: 16 } }, String(i + 1)),
      h('span', { style: { flex: 1, minWidth: 0 } }, it.label),
      it.note ? h('span', { style: { fontSize: 11.5, color: T.mut } }, it.note) : null,
      h('button', { type: 'button', disabled: i === 0, 'aria-label': `Move ${it.label} up`, onClick: () => move(i, -1), style: iconBtn }, svg(CHEV_U)),
      h('button', { type: 'button', disabled: i === items.length - 1, 'aria-label': `Move ${it.label} down`, onClick: () => move(i, 1), style: iconBtn }, svg(CHEV_D)))));
}
export function NumberInput({ id, value, onChange, bad, row }) {
  return h('input', { id, type: row.inputMode ? 'text' : 'number', inputMode: row.inputMode, min: row.min, max: row.max, step: row.step, value: value ?? '',
    'aria-invalid': bad ? 'true' : undefined, onChange: e => onChange(e.target.value), style: { ...inputSt(bad), width: row.width || 140 } });
}
export function TextInput({ id, value, onChange, bad, row }) {
  return h('input', { id, value: value ?? '', placeholder: row.placeholder, maxLength: row.maxLength, onChange: e => onChange(e.target.value),
    style: { ...inputSt(bad), width: row.width || 200 } });
}
export function TimeInput({ id, value, onChange, bad }) {
  return h('input', { id, type: 'time', value: value ?? '', onChange: e => e.target.value && onChange(e.target.value), style: { ...inputSt(bad), width: 120 } });
}
export function Select({ id, value, onChange, row, choices }) {
  const list = choices.some(c => c.value === value) || value == null ? choices : [...choices, { value, label: String(value) }];
  return h('select', { id, value: value ?? '', onChange: e => { const c = list.find(x => String(x.value) === e.target.value); onChange(c ? c.value : e.target.value); },
    style: { ...inputSt(false), width: row.width || 'auto', fontFamily: 'inherit', fontSize: 12.5, maxWidth: 260 } },
  list.map(c => h('option', { key: String(c.value), value: c.value ?? '' }, c.label)));
}
/** One entry per line, with Add; `check(text)` → {value} | {error}. */
export function ListEditor({ value = [], onChange, row }) {
  const React = R(), [text, setText] = React.useState(''), [err, setErr] = React.useState(null);
  const add = () => {
    const r = row.check ? row.check(text) : { value: text.trim() };
    if (r.error) return setErr(r.error);
    if (!r.value) return undefined;
    if (value.includes(r.value)) return setErr('Already in the list');
    onChange([...value, r.value]); setText(''); setErr(null); return undefined;
  };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 } },
    value.map(p => h('div', { key: p, style: { display: 'flex', alignItems: 'center', gap: 6, padding: '3px 4px 3px 8px', borderRadius: 6, background: T.inset } },
      h('code', { style: { fontFamily: MONO, fontSize: 12, flex: 1, minWidth: 0, overflowWrap: 'anywhere' } }, p),
      h('button', { type: 'button', 'aria-label': `Remove ${p}`, title: `Remove ${p}`, onClick: () => onChange(value.filter(x => x !== p)), style: { ...iconBtn, width: 24, height: 24, color: T.mut } }, svg('M6 6l12 12M18 6L6 18', 13)))),
    h('div', { style: { display: 'flex', gap: 6 } },
      h('input', { value: text, placeholder: row.placeholder, 'aria-label': row.label, onChange: e => { setText(e.target.value); setErr(null); },
        onKeyDown: e => { if (e.key === 'Enter') { e.preventDefault(); add(); } }, style: { ...inputSt(!!err), width: 'auto', flex: 1, fontSize: 12 } }),
      h('button', { type: 'button', disabled: !text.trim(), onClick: add, style: { height: 32, padding: '0 10px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.inset, color: T.tx, font: 'inherit', fontSize: 12, cursor: 'pointer' } }, 'Add')),
    err ? h('span', { role: 'alert', style: { fontSize: 12, color: T.rd } }, err) : null);
}

// ---------- highlighting (search) ----------
/** `text` with `query`'s matches in <mark> (Phase 3 gives the parts; until then the text as it is). */
export function Hl({ text, query, parts, cur }) {
  if (!text) return null;
  const ps = parts ? parts(String(text), query) : [{ text: String(text), hit: false }];
  if (ps.length === 1 && !ps[0].hit) return String(text);
  return h(R().Fragment, null, ps.map((p, i) => (p.hit ? h('mark', { key: i, className: cur ? 'gaifa-hit gaifa-hit-cur' : 'gaifa-hit', style: { background: cur ? T.acc : 'var(--tacc,rgba(255,178,36,.28))', color: cur ? '#1A1200' : 'inherit', borderRadius: 2, padding: 0 } }, p.text) : p.text)));
}

// ---------- the row ----------
/** One row: label, hint (and its key), the control, the error. `value` and `onChange` come from the page. */
export function Row({ row, value, onChange, error, ctx = {}, first }) {
  const id = 'st-' + row.id, bad = !!error, q = ctx.query, parts = ctx.hlParts;
  let control = null;
  const c = row.control;
  if (c === 'toggle') control = h(Toggle, { on: !!value, onChange, label: row.aria || row.label });
  else if (c === 'segmented') control = h(Segmented, { value, onChange, label: row.label, choices: row.choices });
  else if (c === 'select') control = h(Select, { id, value, onChange, row, choices: typeof row.choices === 'function' ? row.choices(ctx) : row.choices || [] });
  else if (c === 'number') control = h(NumberInput, { id, value, onChange, bad, row });
  else if (c === 'text') control = h(TextInput, { id, value, onChange, bad, row });
  else if (c === 'time') control = h(TimeInput, { id, value, onChange, bad });
  const wide = c === 'chips' || c === 'order' || c === 'list';
  if (c === 'chips') control = h(Chips, { value, onChange, label: row.label, choices: row.choices || [] });
  else if (c === 'order') control = h(OrderList, { value, items: row.items(ctx.draft || {}), onChange });
  else if (c === 'list') control = h(ListEditor, { value, onChange, row });
  const head = h(wide ? 'div' : 'label', { htmlFor: wide ? undefined : id, style: { flex: wide ? 'none' : '1 1 220px', minWidth: 0 } },
    h('div', { style: { fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' } }, h(Hl, { text: row.label, query: q, parts, cur: ctx.current }), ...(ctx.labelExtras?.(row) || [])),
    row.hint ? h('div', { style: { fontSize: 12, color: T.mut } }, h(Hl, { text: row.hint, query: q, parts, cur: ctx.current })) : null,
    ...(ctx.hintExtras?.(row) || []));
  const st = { display: 'flex', alignItems: wide ? 'stretch' : (c === 'number' || c === 'text' ? 'flex-start' : 'center'), flexDirection: wide ? 'column' : 'row', gap: wide ? 8 : 12,
    padding: '14px 0', flexWrap: wide ? 'nowrap' : 'wrap', borderTop: first ? 0 : '1px solid ' + T.bd, opacity: ctx.dim ? 0.45 : 1 };
  return h('div', { id: 'row-' + row.ref?.replace(/\//g, '-'), 'data-row': row.ref, style: st },
    head,
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4, alignItems: wide ? 'stretch' : 'flex-end', minWidth: 0 } },
      h('div', { style: wide ? { display: 'flex', flexDirection: 'column', gap: 8 } : { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' } }, ...(ctx.controlExtras?.(row) || []), control),
      error ? h('span', { role: 'alert', style: { fontSize: 12, color: T.rd, textAlign: wide ? 'left' : 'right', maxWidth: 260 } }, error) : null));
}

/** A group: a card holding its rows. Blocks with `card: true` stand as their own cards between them. */
/** Which groups are open (2.4): `saved` is {'section/group': false} for the ones you closed (everything is open by
 *  default); `forced` lists the ones that open regardless (the hash's group, a validation error, a search match). */
export function openGroups(saved, forced, refs) {
  const f = new Set(forced || []);
  return new Set((refs || []).filter(r => f.has(r) || (saved || {})[r] !== false));
}
/** `saved` after opening or closing groups (only closed ones are kept). */
export function setOpen(saved, refs, open) {
  const s = { ...(saved || {}) };
  for (const r of [].concat(refs)) { if (open) delete s[r]; else s[r] = false; }
  return s;
}

/** A group: its title (a button that opens and closes it), its one-line summary while closed, then its rows. */
export function Group({ group, children, open = true, onToggle, summary }) {
  const id = 'grp-' + String(group.ref).replace(/\//g, '-');
  return h('div', { 'data-group': group.ref, id, style: { display: 'flex', flexDirection: 'column', gap: 8 } },
    group.label ? h('button', { type: 'button', 'aria-expanded': open ? 'true' : 'false', 'aria-controls': id + '-body', onClick: () => onToggle?.(!open),
      style: { display: 'flex', alignItems: 'center', gap: 8, padding: '4px 2px 0', border: 0, background: 'transparent', color: 'inherit', font: 'inherit', cursor: 'pointer', textAlign: 'left', minWidth: 0 } },
      h('span', { style: { display: 'inline-flex', transform: open ? 'none' : 'rotate(-90deg)', transition: 'transform .12s', color: T.mut } }, svg(CHEV_D, 13)),
      h('h2', { style: { ...label11, flex: 'none' } }, h(Hl, { text: group.label, query: group.query, parts: group.hlParts, cur: group.cur })),
      !open && summary ? h('span', { style: { fontSize: 12, color: T.mut, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, summary) : null) : null,
    open ? h('div', { id: id + '-body', style: { display: 'flex', flexDirection: 'column', gap: 14 } }, children) : null);
}
/** Plain rows share one card; a `card` block is its own. `items` is [{row, el}]. */
export function cardsOf(items) {
  const out = [];
  let run = [];
  const flush = () => { if (run.length) out.push(h('section', { key: 'c' + out.length, style: cardSt }, ...run)); run = []; };
  for (const { row, el } of items) {
    if (row.card) { flush(); out.push(h(R().Fragment, { key: row.id }, el)); } else run.push(el);
  }
  flush();
  return out;
}
