// Hidden outputs on the Outputs page (plan 30.9). The web mod saves every page the agent reads as a hidden
// output (`hidden: true`): the reading tools, screening and citations open it, but Outputs holds what the
// user made. `GET /api/outputs` leaves hidden ones out unless `include_hidden=true` and counts them in
// `totals.hidden`; the page's "Saved web pages" chip shows that count and, pressed, lists them too.
// These pure parts are tested in utils/tests/web/hidden.test.mjs.

export const TITLE = 'Pages the agent read on the web, saved so it can read them again and cite them. '
  + 'They are hidden from Outputs unless this is on.';

/** The chip: null while there is nothing hidden under these filters and it is off. */
export function toggle(totals, on) {
  const n = (totals && totals.hidden) || 0;
  if (!n && !on) return null;
  return { label: 'Saved web pages', count: n, pressed: !!on, title: TITLE };
}

/** Whether a live output belongs in a list: hidden ones only where hidden ones are shown. */
export function belongs(o, on) {
  return !(o && o.hidden) || !!on;
}

/** A list (recent outputs, a mod's newest) after a live `output` event: a hidden output is never in it, a
 *  changed one keeps its place, a new one goes first; `max` cuts it. */
export function place(list, o, max) {
  const out = o.hidden ? list.filter(x => x.id !== o.id)
    : list.some(x => x.id === o.id) ? list.map(x => x.id === o.id ? o : x) : [o, ...list];
  return max ? out.slice(0, max) : out;
}

/** The page's totals after a new output arrives live. With hidden ones off, a hidden output only counts in `hidden`. */
export function addTo(t, o, on) {
  if (!t) return t;
  const hidden = (t.hidden || 0) + (o.hidden ? 1 : 0);
  if (!belongs(o, on)) return { ...t, hidden };
  return { ...t, hidden, count: t.count + 1, size_bytes: t.size_bytes + (o.size_bytes || 0),
    by_kind: { ...t.by_kind, [o.kind]: (t.by_kind[o.kind] || 0) + 1 },
    by_service: { ...t.by_service, [o.service]: (t.by_service[o.service] || 0) + 1 } };
}
