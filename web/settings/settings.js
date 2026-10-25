// The Settings page (plan settings-redesign 1.4; brief §4.5): loads GET /api/settings and /api/system, keeps the
// draft, Save (one PUT for every hub-owned row) and Revert, the restart note, the mock note and the Save bar;
// draws the current section's groups from schema.js with rows.js and the blocks. Hub.dc.html mounts it and
// asks `ref.current.dirty()` before leaving with unsaved changes. Written by us (web/PATCHES.md).

import { h, T, MONO } from '../chat/chat-ui.js';
import { sections, rowsOf, validateDraft, saveBody, isDirty } from './schema.js';
import { Row, Group, cardsOf } from './rows.js';
import { parseSettingsRoute, settingsPlace } from './route.js';
import { SectionStrip } from './strip.js';
import { HUB_BLOCKS } from './blocks-hub.js';
import { AGENT_BLOCKS } from './blocks-agent.js';

const R = () => globalThis.React;
const BLOCKS = { ...HUB_BLOCKS, ...AGENT_BLOCKS };
// The flash on a row or group a hash names (2.2): a short accent ring, 1.2 s.
const FLASH_CSS = '@keyframes gaifaFlash{0%{box-shadow:0 0 0 2px var(--acc,#FFB224);background:var(--tacc,rgba(255,178,36,.13))}100%{box-shadow:0 0 0 2px transparent;background:transparent}}.gaifa-flash{animation:gaifaFlash 1.2s ease-out;border-radius:8px}';
function useFlashCss() {
  R().useEffect(() => {
    if (typeof document === 'undefined' || document.getElementById('gaifa-settings-css')) return;
    const s = document.createElement('style'); s.id = 'gaifa-settings-css'; s.textContent = FLASH_CSS; document.head.appendChild(s);
  }, []);
}
/** Scroll the element for a place into view (below the sticky header and strip) and flash it. */
export function flashPlace(section, group, row) {
  if (typeof document === 'undefined') return false;
  const id = row ? `row-${section}-${group}-${row}` : group ? `grp-${section}-${group}` : null;
  const el = id && document.getElementById(id);
  if (!el) return false;
  const strip = document.querySelector('[data-strip]'), head = document.querySelector('header');
  const top = el.getBoundingClientRect().top + window.scrollY - (head?.offsetHeight || 0) - (strip?.offsetHeight || 0) - 12;
  window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
  el.classList.remove('gaifa-flash'); void el.offsetWidth; el.classList.add('gaifa-flash');
  setTimeout(() => el.classList.remove('gaifa-flash'), 1300);
  return true;
}
/** The sections for the shell (palette rows, the header's "where you are"). */
export function settingsSections(ctx) { return sections(ctx); }
export { settingsPlace };

const clone = o => (o == null ? o : JSON.parse(JSON.stringify(o)));
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
    // what choices and columns read: the judge's status, the screening and relevance models, each mod's tool count
    api.getJudgeStatus?.().then(x => live && up({ judgeStatus: x }), () => {});
    api.getWebReading?.().then(x => live && up({ reading: x }), () => {});
    api.getToolIndex?.().then(ix => live && up({ toolCounts: ix.reduce((m, t) => ({ ...m, [t.mod]: (m[t.mod] || 0) + 1 }), {}) }), () => {});
    return () => { live = false; };
  }, []);
  useFlashCss();
  const hash = route?.hash || '';
  React.useEffect(() => {
    if (!st.draft) return undefined;
    const parts = (route?.parts || []).slice(1);
    const p = parseSettingsRoute(parts, sections({ ...props, draft: st.draft, hasSessions: !!api.listSessions }));
    if (!p.group) return undefined;
    const t = setTimeout(() => flashPlace(p.section, p.group, p.row), 120);
    return () => clearTimeout(t);
  }, [hash, !!st.draft]);
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
  const ctx = { ...props, api, services: props.services || [], system: st.sys, draft: st.draft, orig: st.orig, setDraft,
    judgeStatus: st.judgeStatus, reading: st.reading, toolCounts: st.toolCounts, hasSessions: !!api.listSessions };
  const secs = sections(ctx);
  const place = parseSettingsRoute((route?.parts || []).slice(1), secs);
  const cur = secs.find(x => x.id === place.section) || secs[0];
  const problems = validateDraft(secs, st.draft), invalid = Object.keys(problems).length > 0;
  const errField = st.err?.data?.field;
  const save = async () => {
    up({ saving: true });
    try {
      const r = await api.saveSettings(saveBody(st.draft, st.orig, secs));
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
    return h(Group, { key: g.id, group: { ...g, ref: `${cur.id}/${g.id}` }, title: cur.groups.length > 1 }, cardsOf(items));
  };
  const miss = (cur.areas || []).filter(a => !isLive(a));

  const pick = id => (props.go ? props.go('#/settings/' + id) : (location.hash = '#/settings/' + id));
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 } },
    h(SectionStrip, { sections: secs, current: cur.id, onPick: pick, density: props.density, h1St: props.h1St || h1St, counts: props.stripCounts?.(secs) || {}, search: null }),
    st.restart ? h('div', { role: 'status', style: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', padding: '12px 14px', borderRadius: 10, background: T.tacc, border: '1px solid ' + T.acc } },
      h('span', { style: { flex: 1, minWidth: 200 } }, h('strong', null, 'Saved.'), ' Restart GAIFA to apply the new port: ', h('code', { style: { fontFamily: MONO } }, 'gaifa restart')),
      h('button', { type: 'button', onClick: () => up({ restart: false }), style: { ...btnSt(false), height: 28, fontSize: 12, background: T.card } }, 'Dismiss')) : null,
    st.err && !errField ? h('div', { role: 'alert', style: { padding: '10px 12px', borderRadius: 8, background: T.trd, color: T.rd } }, st.err.detail || String(st.err.message || st.err)) : null,
    h('div', { role: 'tabpanel', 'aria-labelledby': 'stab-' + cur.id, style: { width: '100%', maxWidth: 900, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 } },
      miss.length ? h('div', { role: 'note', style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: T.mut } },
        h('span', { style: { height: 18, padding: '0 6px', borderRadius: 4, border: '1px solid ' + T.pu, background: T.tpu, color: T.pu, fontSize: 10, fontWeight: 600, letterSpacing: '.06em', display: 'inline-flex', alignItems: 'center' } }, 'MOCK'),
        h('span', null, `Mock data: the ${miss.join(' and ')} ${miss.length > 1 ? 'areas aren’t' : 'area isn’t'} live yet.`)) : null,
      cur.groups.map(groupEl),
      dirty ? h('div', { role: 'region', 'aria-label': 'Unsaved changes', style: { position: 'sticky', bottom: 12, zIndex: 20, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', padding: '10px 14px',
        borderRadius: 10, background: T.card, border: '1px solid ' + T.acc, boxShadow: '0 10px 30px rgba(0,0,0,.35)' } },
        h('span', { style: { flex: 1, minWidth: 160, fontWeight: 500 } }, 'Unsaved changes'),
        h('button', { type: 'button', onClick: revert, style: btnSt(false) }, 'Revert'),
        h('button', { type: 'button', onClick: save, disabled: invalid || st.saving, style: btnSt(true, invalid || st.saving) }, st.saving ? 'Saving…' : 'Save changes')) : null));
}

export { rowsOf };
