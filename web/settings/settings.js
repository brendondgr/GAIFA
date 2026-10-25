// The Settings page (plan settings-redesign 1.4; brief §4.5): loads GET /api/settings and /api/system, keeps the
// draft, Save (one PUT for every hub-owned row) and Revert, the restart note, the mock note and the Save bar;
// draws the current section's groups from schema.js with rows.js and the blocks. Hub.dc.html mounts it and
// asks `ref.current.dirty()` before leaving with unsaved changes. Written by us (web/PATCHES.md).

import { h, T, MONO } from '../chat/chat-ui.js';
import { sections, rowsOf, validateDraft, saveBody, isDirty } from './schema.js';
import { Row, Group, cardsOf } from './rows.js';
import { HUB_BLOCKS } from './blocks-hub.js';
import { AGENT_BLOCKS } from './blocks-agent.js';

const R = () => globalThis.React;
const BLOCKS = { ...HUB_BLOCKS, ...AGENT_BLOCKS };
const clone = o => (o == null ? o : JSON.parse(JSON.stringify(o)));
const navSt = on => ({ position: 'relative', display: 'flex', alignItems: 'center', gap: 10, height: 32, padding: '0 10px', borderRadius: 6, fontSize: 13, fontWeight: on ? 600 : 400,
  textDecoration: 'none', color: on ? T.tx : T.mut, background: on ? T.hov : 'transparent' });
const h1St = { margin: 0, fontSize: 20, fontWeight: 600, letterSpacing: '-.01em' };
const btnSt = (pri, dis) => ({ height: 32, padding: '0 12px', borderRadius: 6, font: 'inherit', fontSize: 12.5, fontWeight: pri ? 600 : 500, cursor: dis ? 'not-allowed' : 'pointer', opacity: dis ? 0.5 : 1,
  border: pri ? '1px solid transparent' : '1px solid ' + T.bds, background: pri ? T.acc : T.inset, color: pri ? '#1A1200' : T.tx });

/** A block of the schema, drawn by its component. */
function BlockRow({ row, ctx }) {
  const C = BLOCKS[row.block];
  return C ? h(C, { ctx, row }) : h('div', { role: 'alert', style: { color: T.rd, fontSize: 12 } }, `No block “${row.block}”`);
}

export function SettingsPage(props) {
  const { api, route, pageRef, isLive = () => true } = props;
  const React = R();
  const [st, setSt] = React.useState({ orig: null, draft: null, sys: null, err: null, loadErr: null, saving: false, restart: false });
  const up = p => setSt(s => ({ ...s, ...(typeof p === 'function' ? p(s) : p) }));
  React.useEffect(() => {
    let live = true;
    Promise.all([api.getSettings(), api.getSystem()]).then(([s, sys]) => live && up({ orig: s, draft: clone(s), sys }), e => live && up({ loadErr: e }));
    return () => { live = false; };
  }, []);
  const dirty = isDirty(st.orig, st.draft);
  if (pageRef) pageRef.current = { dirty: () => dirty };
  React.useEffect(() => {
    if (!dirty) return undefined;
    const f = e => { e.preventDefault(); e.returnValue = ''; };
    window.addEventListener('beforeunload', f);
    return () => window.removeEventListener('beforeunload', f);
  }, [dirty]);

  if (st.loadErr) return h('div', { role: 'alert', style: { color: T.rd } }, `Couldn’t load the settings: ${st.loadErr.detail || st.loadErr.message}`);
  if (!st.draft) return h('div', { style: { color: T.mut } }, 'Loading settings…');

  const setDraft = fn => setSt(s => { const d = clone(s.draft); fn(d); return { ...s, draft: d, err: null }; });
  const ctx = { ...props, api, services: props.services || [], system: st.sys, draft: st.draft, orig: st.orig, setDraft };
  const secs = sections(ctx);
  const cur = secs.find(x => x.id === route?.parts?.[1]) || secs[0];
  const problems = validateDraft(secs, st.draft), invalid = Object.keys(problems).length > 0;
  const errField = st.err?.data?.field;
  const save = async () => {
    up({ saving: true });
    try {
      const r = await api.saveSettings(saveBody(st.draft));
      up(s => ({ orig: r.settings, draft: { ...clone(r.settings), ui: s.draft.ui }, saving: false, restart: r.restart_required, err: null }));
      props.toast?.('Settings saved', 'success');
      props.onSaved?.(r);
    } catch (e) { up({ saving: false, err: e }); if (e.status === 0) props.goDown?.(); }
  };
  const revert = () => up(s => ({ draft: { ...clone(s.orig), ui: s.draft.ui }, err: null }));

  const rowEl = (row, first) => {
    if (row.control === 'block') return h(BlockRow, { key: row.id, row, ctx });
    const value = row.instant ? row.read(ctx) : row.get(st.draft);
    const onChange = row.instant ? v => row.apply(ctx, v) : v => setDraft(d => row.set(d, v));
    const error = problems[row.path] || (errField && errField === row.path ? st.err.detail : null);
    return h(Row, { key: row.id, row, value, onChange, error, first, ctx });
  };
  const groupEl = g => {
    const shown = g.rows.filter(r => !r.when || r.when(ctx));
    let firstPlain = true;
    const items = shown.map(r => { const row = { ...r, ref: `${cur.id}/${g.id}/${r.id}` }, first = !row.card && firstPlain; if (!row.card) firstPlain = false; return { row, el: rowEl(row, first) }; });
    return h(Group, { key: g.id, group: { ...g, ref: `${cur.id}/${g.id}` } }, cardsOf(items));
  };
  const miss = (cur.areas || []).filter(a => !isLive(a));

  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 } },
    h('h1', { style: props.h1St || h1St }, 'Settings'),
    st.restart ? h('div', { role: 'status', style: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', padding: '12px 14px', borderRadius: 10, background: T.tacc, border: '1px solid ' + T.acc } },
      h('span', { style: { flex: 1, minWidth: 200 } }, h('strong', null, 'Saved.'), ' Restart GAIFA to apply the new port: ', h('code', { style: { fontFamily: MONO } }, 'gaifa restart')),
      h('button', { type: 'button', onClick: () => up({ restart: false }), style: { ...btnSt(false), height: 28, fontSize: 12, background: T.card } }, 'Dismiss')) : null,
    st.err && !errField ? h('div', { role: 'alert', style: { padding: '10px 12px', borderRadius: 8, background: T.trd, color: T.rd } }, st.err.detail || String(st.err.message || st.err)) : null,
    h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 20, alignItems: 'flex-start' } },
      h('nav', { 'aria-label': 'Settings sections', style: { flex: '0 1 190px', display: 'flex', flexDirection: 'column', gap: 2, minWidth: 160 } },
        secs.map(x => h('a', { key: x.id, href: '#/settings/' + x.id, 'aria-current': x.id === cur.id ? 'page' : undefined, style: navSt(x.id === cur.id) }, x.label))),
      h('div', { style: { flex: '1 1 480px', minWidth: 0, maxWidth: 820, display: 'flex', flexDirection: 'column', gap: 14 } },
        miss.length ? h('div', { role: 'note', style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: T.mut } },
          h('span', { style: { height: 18, padding: '0 6px', borderRadius: 4, border: '1px solid ' + T.pu, background: T.tpu, color: T.pu, fontSize: 10, fontWeight: 600, letterSpacing: '.06em', display: 'inline-flex', alignItems: 'center' } }, 'MOCK'),
          h('span', null, `Mock data: the ${miss.join(' and ')} ${miss.length > 1 ? 'areas aren’t' : 'area isn’t'} live yet.`)) : null,
        cur.groups.map(groupEl),
        dirty ? h('div', { role: 'region', 'aria-label': 'Unsaved changes', style: { position: 'sticky', bottom: 12, zIndex: 20, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', padding: '10px 14px',
          borderRadius: 10, background: T.card, border: '1px solid ' + T.acc, boxShadow: '0 10px 30px rgba(0,0,0,.35)' } },
          h('span', { style: { flex: 1, minWidth: 160, fontWeight: 500 } }, 'Unsaved changes'),
          h('button', { type: 'button', onClick: revert, style: btnSt(false) }, 'Revert'),
          h('button', { type: 'button', onClick: save, disabled: invalid || st.saving, style: btnSt(true, invalid || st.saving) }, st.saving ? 'Saving…' : 'Save changes')) : null)));
}

export { rowsOf };
