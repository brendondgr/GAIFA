// "By meaning" on the Outputs page (plan 28.4): the search box asks the embed mod's library
// (`POST /api/s/embed/v1/search`) instead of matching titles and prompts, and the page lists what it
// finds ranked, each with its kind, score, where it matched (page and line, or seconds) and a snippet.
// The toggle shows only while the embed mod is running; deleting the mod hides it. The pure parts
// (canSearch, plainSnippet, rows, matchLabel) are tested in utils/tests/web/meaning.test.mjs.

const R = () => globalThis.React;
const h = (...a) => R().createElement(...a);
const MONO = "'JetBrains Mono',ui-monospace,Menlo,monospace";
const C = { bd: 'var(--bd,#1D2430)', inset: 'var(--inset,#131926)', mut: 'var(--mut,#8A94A6)', card: 'var(--card,#11151D)',
  hov: 'var(--hov,#161C28)', cy: 'var(--cy,#58C4DD)', rd: 'var(--rd,#F85149)' };
export const MOD = 'embed';
const LABEL = { audio: 'Audio', image: 'Image', video: 'Video', model3d: '3D', text: 'Text', document: 'Document', archive: 'Archive', other: 'Other' };
const THUMB = new Set(['image', 'video', 'model3d']);
const WAIT_MS = 400;

/** The embed mod is installed and running. */
export function canSearch(services) {
  return (services || []).some(s => s.id === MOD && s.state === 'ready');
}

/** A hit's snippet without the `<untrusted …>` wrapper the agent needs (the page shows it as plain text). */
export function plainSnippet(s) {
  return String(s || '').replace(/^<untrusted source="[^"]*">\n?/, '').replace(/\n?<\/untrusted>$/, '').trim();
}

/** Where a hit matched: "p.3 · line 120", "line 88", "30–60 s", or the match's kind. */
export function matchLabel(x) {
  const parts = [];
  if (x.page != null) parts.push(`p.${x.page}`);
  if (x.line != null) parts.push(`line ${x.line}`);
  if (x.start_s != null && x.end_s != null) parts.push(`${Math.round(x.start_s)}–${Math.round(x.end_s)} s`);
  if (!parts.length) parts.push(x.match === 'meta' ? 'title and prompt' : x.match === 'text' ? 'text' : `the ${LABEL[x.kind]?.toLowerCase() || x.match}`);
  return parts.join(' · ');
}

/** One row per output, in the order of its best hit, keeping its other hits as extra matches. `kinds`
 * (the page's kind chips) keeps only those kinds. */
export function rows(results, kinds = []) {
  const out = [], by = new Map();
  for (const x of results || []) {
    if (kinds.length && !kinds.includes(x.kind)) continue;
    const id = String(x.output || '').replace(/^output:/, '');
    let r = by.get(id);
    if (!r) { r = { id, title: x.title || id, kind: x.kind, score: x.score, matches: [] }; by.set(id, r); out.push(r); }
    r.matches.push({ where: matchLabel(x), snippet: plainSnippet(x.snippet) });
  }
  return out;
}

export async function search(api, query, kinds = []) {
  const json = { query, limit: 30, ...(kinds.length === 1 ? { kind: kinds[0] } : {}) };
  const res = await api.callService(MOD, 'POST', '/v1/search', { json });
  return res.json || { results: [] };
}

/** The ranked list shown instead of the grid while "By meaning" is on and the box has words. */
export function MeaningResults({ api, query, kinds = [], onOpen }) {
  const { useState, useEffect } = R();
  const [st, setSt] = useState({ busy: true, rows: [], note: '', err: '' });
  const key = query.trim() + '|' + kinds.join(',');
  useEffect(() => {
    let live = true;
    setSt(s => ({ ...s, busy: true, err: '' }));
    const t = setTimeout(async () => {
      try {
        const body = await search(api, query.trim(), kinds);
        if (live) setSt({ busy: false, rows: rows(body.results, kinds), note: body.note || '', err: '' });
      } catch (e) {
        if (live) setSt({ busy: false, rows: [], note: '', err: e?.detail || e?.message || String(e) });
      }
    }, WAIT_MS);
    return () => { live = false; clearTimeout(t); };
  }, [key]);
  const box = { background: C.card, border: `1px solid ${C.bd}`, borderRadius: 10, overflow: 'hidden' };
  const head = h('div', { role: 'status', style: { display: 'flex', gap: 8, alignItems: 'center', fontSize: 12.5, color: C.mut, padding: '2px 2px 8px' } },
    st.busy ? 'Searching by meaning…' : st.err ? '' : `${st.rows.length} found by meaning`, st.note && !st.busy ? h('span', null, `· ${st.note}`) : null);
  if (st.err) {
    return h('div', null, head, h('div', { role: 'alert', style: { padding: '10px 12px', borderRadius: 8, background: 'var(--trd,rgba(248,81,73,.13))', color: C.rd } }, `Search by meaning failed: ${st.err}`));
  }
  if (!st.busy && !st.rows.length) {
    return h('div', null, head, h('div', { style: { padding: '40px 20px', textAlign: 'center', border: `1px dashed var(--bds,#2A3547)`, borderRadius: 12, color: C.mut } },
      'Nothing close. Try describing it differently, or turn off By meaning to match titles and prompts.'));
  }
  return h('div', null, head, h('ol', { 'aria-label': 'Outputs found by meaning', style: { ...box, listStyle: 'none', margin: 0, padding: 0, opacity: st.busy ? 0.6 : 1 } },
    st.rows.map((r, i) => h('li', { key: r.id, style: { borderTop: i ? `1px solid ${C.bd}` : 0 } },
      h('button', { onClick: () => onOpen?.(r.id), style: { display: 'flex', gap: 12, alignItems: 'flex-start', width: '100%', textAlign: 'left', padding: '10px 12px', border: 0, background: 'transparent', color: 'inherit', cursor: 'pointer', font: 'inherit' },
        onMouseEnter: e => { e.currentTarget.style.background = C.hov; }, onMouseLeave: e => { e.currentTarget.style.background = 'transparent'; } },
        h('span', { 'aria-hidden': true, style: { flex: 'none', width: 56, height: 56, borderRadius: 6, background: THUMB.has(r.kind) ? `${C.inset} url("/api/outputs/${r.id}/preview") center / cover` : C.inset,
          display: 'grid', placeItems: 'center', fontSize: 10.5, color: C.mut } }, THUMB.has(r.kind) ? null : (LABEL[r.kind] || r.kind)),
        h('span', { style: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 3 } },
          h('span', { style: { display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' } },
            h('span', { style: { fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100%' } }, r.title),
            h('span', { style: { fontSize: 11.5, color: C.mut } }, LABEL[r.kind] || r.kind),
            h('span', { title: 'Cosine score: higher is closer; about 0.5 is unrelated', style: { marginLeft: 'auto', fontFamily: MONO, fontSize: 11.5, color: C.cy } }, (r.score ?? 0).toFixed(2))),
          r.matches.map((m, k) => h('span', { key: k, style: { fontSize: 12.5, color: C.mut, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' } },
            h('span', { style: { fontFamily: MONO, fontSize: 11 } }, m.where), m.snippet ? ` ${m.snippet}` : ''))))))));
}
