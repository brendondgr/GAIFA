// Settings search (plan settings-redesign 3.1): an index of every row and group of schema.js, a matcher, the parts
// a renderer wraps in <mark>, and the palette's rows. Pure; tested in utils/tests/web/settings-search.test.mjs.
// Written by us (web/PATCHES.md).

import { settingsHash } from './route.js';

/** Every row and group as an entry: {id: 'section/group[/row]', section, group, row, kind, label, sub, text: [...]}. */
export function indexRows(sections, ctx = {}) {
  const out = [];
  for (const s of sections) for (const g of s.groups) {
    out.push({ id: `${s.id}/${g.id}`, kind: 'group', section: s.id, group: g.id, row: null, label: g.label, sub: `Settings › ${s.label}`, sectionLabel: s.label, groupLabel: g.label, text: [g.label] });
    for (const r of g.rows) {
      if (r.when && !r.when(ctx)) continue;
      const text = [r.label, r.hint, r.key, ...(r.keys || []), ...(r.keywords || [])].filter(Boolean).map(String);
      out.push({ id: `${s.id}/${g.id}/${r.id}`, kind: r.control === 'block' ? 'block' : 'row', section: s.id, group: g.id, row: r.id, label: r.label,
        key: r.key || null, sectionLabel: s.label, groupLabel: g.label, text });
    }
  }
  return out;
}

/** The trimmed query, or '' when it's shorter than two characters. */
export const cleanQuery = q => { const t = String(q || '').trim(); return t.length >= 2 ? t : ''; };

/** The entries whose text contains the query (any case): {rows: [{id, section, group, kind}], perSection: {id: n}, perGroup: {'s/g': n}, ids: Set}. */
export function matches(index, query) {
  const q = cleanQuery(query).toLowerCase(), out = { rows: [], perSection: {}, perGroup: {}, ids: new Set(), query: q };
  if (!q) return out;
  for (const e of index) {
    if (!e.text.some(t => t.toLowerCase().includes(q))) continue;
    out.rows.push({ id: e.id, section: e.section, group: e.group, kind: e.kind });
    out.ids.add(e.id);
    out.perSection[e.section] = (out.perSection[e.section] || 0) + 1;
    const g = `${e.section}/${e.group}`;
    out.perGroup[g] = (out.perGroup[g] || 0) + 1;
  }
  return out;
}

/** `text` split around the query's matches: [{text, hit}], case kept. */
export function highlight(text, query) {
  const s = String(text ?? ''), q = cleanQuery(query).toLowerCase();
  if (!q || !s) return [{ text: s, hit: false }];
  const low = s.toLowerCase(), out = [];
  let i = 0;
  for (;;) {
    const j = low.indexOf(q, i);
    if (j < 0) break;
    if (j > i) out.push({ text: s.slice(i, j), hit: false });
    out.push({ text: s.slice(j, j + q.length), hit: true });
    i = j + q.length;
  }
  if (i < s.length) out.push({ text: s.slice(i), hit: false });
  return out.length ? out : [{ text: s, hit: false }];
}

/** The command palette's rows: one per group ("Settings › Permissions › Auto judge") and one per row ("Reserve",
 *  sub "Settings › Machine › Memory · memory.reserve_gb"), each with its hash. */
export function paletteRows(index) {
  return index.filter(e => e.label).map(e => (e.kind === 'group'
    ? { label: `Settings › ${e.sectionLabel} › ${e.label}`, sub: 'Settings', hash: settingsHash(e.section, e.group), id: e.id }
    : { label: e.label, sub: `Settings › ${e.sectionLabel} › ${e.groupLabel}${e.key ? ' · ' + e.key : ''}`, hash: settingsHash(e.section, e.group, e.row), id: e.id }));
}
