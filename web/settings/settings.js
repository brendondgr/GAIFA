// The Settings page (plan settings-redesign 1.4; brief §4.5): loads GET /api/settings and /api/system, keeps the
// draft, Save (one PUT for every hub-owned row) and Revert, the restart note, the mock note and the Save bar;
// draws the current section's groups from schema.js with rows.js and the blocks. Hub.dc.html mounts it and
// asks `ref.current.dirty()` before leaving with unsaved changes. Written by us (web/PATCHES.md).

import { h, T, MONO, usePref, chipSt, Badge } from '../chat/chat-ui.js';
import { sections, rowsOf, validateDraft, saveBody, isDirty, summaryOf, changedRows, changedMatch, sameValue, showValue } from './schema.js';
import { Row, Group, cardsOf, openGroups, setOpen } from './rows.js';
import { parseSettingsRoute, settingsPlace } from './route.js';
import { SectionNav, SearchBox } from './settings-nav.js';
import { indexRows, matches, highlight, paletteRows } from './search.js';
import { HUB_BLOCKS } from './blocks-hub.js';
import { AGENT_BLOCKS } from './blocks-agent.js';
import { voiceChoices } from '../chat/chat-speak.js';

const R = () => globalThis.React;
const BLOCKS = { ...HUB_BLOCKS, ...AGENT_BLOCKS };
// The flash on a row or group a hash names (2.2): a short accent ring, 1.2 s.
const FLASH_CSS = '@keyframes gaifaFlash{0%{box-shadow:0 0 0 2px var(--acc,#FFB224);background:var(--tacc,rgba(255,178,36,.13))}100%{box-shadow:0 0 0 2px transparent;background:transparent}}.gaifa-flash{animation:gaifaFlash 1.2s ease-out;border-radius:8px}.gaifa-settings-link:hover{background:var(--hov,#161C28)}';
function useFlashCss() {
  R().useEffect(() => {
    if (typeof document === 'undefined' || document.getElementById('gaifa-settings-css')) return;
    const s = document.createElement('style'); s.id = 'gaifa-settings-css'; s.textContent = FLASH_CSS; document.head.appendChild(s);
  }, []);
}
/** Scroll the element for a place into view (below the sticky header) and flash it. */
export function flashPlace(section, group, row) {
  if (typeof document === 'undefined') return false;
  const id = row ? `row-${section}-${group}-${row}` : group ? `grp-${section}-${group}` : null;
  const el = id && document.getElementById(id);
  if (!el) return false;
  const head = document.querySelector('header');
  const top = el.getBoundingClientRect().top + window.scrollY - (head?.offsetHeight || 0) - 12;
  window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
  el.classList.remove('gaifa-flash'); void el.offsetWidth; el.classList.add('gaifa-flash');
  setTimeout(() => el.classList.remove('gaifa-flash'), 1300);
  return true;
}
/** The sections for the shell (palette rows, the header's "where you are"). */
export function settingsSections(ctx) { return sections(ctx); }
export { settingsPlace };
/** The palette's rows for every group and setting (3.3), each with its hash. */
export function settingsPaletteRows(ctx) { const secs = sections(ctx); return paletteRows(indexRows(secs, ctx)); }

const clone = o => (o == null ? o : JSON.parse(JSON.stringify(o)));
const h1St = { margin: 0, fontSize: 20, fontWeight: 600, letterSpacing: '-.01em' };
const btnSt = (pri, dis) => ({ height: 32, padding: '0 12px', borderRadius: 6, font: 'inherit', fontSize: 12.5, fontWeight: pri ? 600 : 500, cursor: dis ? 'not-allowed' : 'pointer', opacity: dis ? 0.5 : 1,
  border: pri ? '1px solid transparent' : '1px solid ' + T.bds, background: pri ? T.acc : T.inset, color: pri ? '#1A1200' : T.tx });

/** The config key under a hint, with the search's matches marked. */
function Hk({ text, q }) {
  const parts = highlight(text, q || '');
  return h(R().Fragment, null, parts.map((p, i) => (p.hit ? h('mark', { key: i, className: 'gaifa-hit', style: { background: 'var(--tacc,rgba(255,178,36,.28))', color: 'inherit' } }, p.text) : p.text)));
}

/** A block of the schema, drawn by its component. */
function BlockRow({ row, ctx }) {
  const C = BLOCKS[row.block];
  const el = C ? h(C, { ctx, row }) : h('div', { role: 'alert', style: { color: T.rd, fontSize: 12 } }, `No block “${row.block}”`);
  return h('div', { id: 'row-' + row.ref.replace(/\//g, '-'), 'data-row': row.ref, style: { opacity: ctx.dim ? 0.45 : 1, minWidth: 0 } }, el);
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
    api.getSettingsDefaults?.().then(x => live && up({ defaults: x }), () => {});   // 4.2: each row's default, for Reset
    api.getJudgeStatus?.().then(x => live && up({ judgeStatus: x }), () => {});
    if ((props.services || []).some(s => s.id === 'tts')) api.callService?.('tts', 'GET', '/v1/voices').then(r => live && up({ voices: r.json }), () => {});   // Speech → Voice's choices
    api.getWebReading?.().then(x => live && up({ reading: x }), () => {});
    api.getToolIndex?.().then(ix => live && up({ toolCounts: ix.reduce((m, t) => ({ ...m, [t.mod]: (m[t.mod] || 0) + 1 }), {}) }), () => {});
    return () => { live = false; };
  }, []);
  useFlashCss();
  const [closed, setClosed] = usePref('gaifa.settings.open', {});
  const [q, setQ] = React.useState(''), [hit, setHit] = React.useState(-1), boxRef = React.useRef(null), [changedOnly, setChangedOnly] = React.useState(false);
  React.useEffect(() => {   // 3.2: '/' focuses the search box when nothing else has focus
    const f = e => {
      const tg = e.target, typing = /INPUT|TEXTAREA|SELECT/.test(tg?.tagName || '') || tg?.isContentEditable;
      if (e.key === '/' && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); boxRef.current?.focus(); }
    };
    window.addEventListener('keydown', f);
    return () => window.removeEventListener('keydown', f);
  }, []);
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
    judgeStatus: st.judgeStatus, reading: st.reading, voiceChoices: st.voices ? voiceChoices(st.voices) : null, toolCounts: st.toolCounts, hasSessions: !!api.listSessions };
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

  // 3.2: with a query, every section with a match shows, only matching groups open, other rows dimmed
  const changed = changedRows(secs, st.draft, st.defaults, ctx), changedM = changedMatch(changed);
  const changedAt = Object.fromEntries(changed.map(c => [c.ref, c]));
  const index = indexRows(secs, ctx), sm = matches(index, q), searching = !!sm.query || changedOnly, m = sm.query ? sm : changedOnly ? changedM : sm;
  const curHit = searching && hit >= 0 ? m.rows[hit % m.rows.length]?.id : null;
  const walk = dir => {
    if (!m.rows.length) return;
    const i = hit < 0 ? (dir > 0 ? 0 : m.rows.length - 1) : (hit + dir + m.rows.length) % m.rows.length;
    setHit(i);
    const e = m.rows[i], [s, g, r] = e.id.split('/');
    setTimeout(() => flashPlace(s, g, r), 60);
  };
  const rowEl = (row, first, view) => {
    const ch = changedAt[row.ref], restartDirty = row.restart && st.orig && !sameValue(row, row.get(st.draft), row.get(st.orig));
    const reset = () => (row.instant ? row.apply(ctx, ch.default) : setDraft(d => row.set(d, JSON.parse(JSON.stringify(ch.default)))));
    const rctx = { ...ctx, ...view.rowCtx(row),
      hintExtras: r => (r.key ? [h('div', { key: 'k', style: { fontFamily: MONO, fontSize: 11, color: T.dim, marginTop: 2, overflowWrap: 'anywhere' } }, h(Hk, { text: r.key, q: view.rowCtx(r).query }))] : []),
      labelExtras: () => (restartDirty ? [h(Badge, { key: 'r', tone: 'accent', title: 'Applies when GAIFA restarts' }, 'restart')] : []),
      controlExtras: () => (ch ? [h('button', { key: 'reset', type: 'button', onClick: reset, title: `The default in config.example.toml: ${showValue(row, ch.default)}`,
        style: { border: 0, background: 'transparent', padding: 0, color: T.cy, fontSize: 12, cursor: 'pointer', font: 'inherit', whiteSpace: 'nowrap', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis' } },
        `Reset to default (${showValue(row, ch.default)})`)] : []) };
    if (row.control === 'block') return h(BlockRow, { key: row.id, row, ctx: rctx });
    const value = row.instant ? row.read(ctx) : row.get(st.draft);
    const onChange = row.instant ? v => row.apply(ctx, v) : v => setDraft(d => row.set(d, v));
    const error = problems[row.path] || (errField && errField === row.path ? st.err.detail : null);
    return h(Row, { key: row.id, row, value, onChange, error, first, ctx: rctx });
  };
  // 2.4: open groups: what you left open, plus the hash's group and any group with a problem
  const problemGroups = sec => sec.groups.filter(g => g.rows.some(r => problems[r.path] || (errField && r.path === errField))).map(g => `${sec.id}/${g.id}`);
  const refsOf = sec => sec.groups.map(g => `${sec.id}/${g.id}`);
  const openSet = openGroups(closed, [place.group ? `${cur.id}/${place.group}` : null, ...problemGroups(cur)].filter(Boolean), refsOf(cur));
  const groupEl = (sec, g) => {
    const ref = `${sec.id}/${g.id}`, shown = g.rows.filter(r => !r.when || r.when(ctx));
    const open = searching ? !!m.perGroup[ref] || problemGroups(sec).includes(ref) : openSet.has(ref);
    const titleHit = searching && m.ids.has(ref), rowHits = shown.some(r => m.ids.has(`${ref}/${r.id}`));
    const view = { rowCtx: row => (searching ? { query: m.query, hlParts: highlight, dim: rowHits && !m.ids.has(row.ref), current: curHit === row.ref } : {}) };
    let firstPlain = true;
    const items = open ? shown.map(r => { const row = { ...r, ref: `${ref}/${r.id}` }, first = !row.card && firstPlain; if (!row.card) firstPlain = false; return { row, el: rowEl(row, first, view) }; }) : [];
    return h(Group, { key: ref, group: { ...g, ref, query: searching ? m.query : '', hlParts: highlight, cur: curHit === ref || (titleHit && false) }, open, summary: summaryOf(g, ctx),
      onToggle: on => (searching ? null : setClosed(setOpen(closed, ref, on))) }, cardsOf(items));
  };
  const refs = refsOf(cur), allOpen = refs.every(r => openSet.has(r)), allClosed = refs.every(r => !openSet.has(r));
  const linkBtn = (label, on, dis) => h('button', { type: 'button', disabled: dis, onClick: () => setClosed(setOpen(closed, refs, on)),
    style: { border: 0, background: 'transparent', padding: 0, color: dis ? T.dim : T.cy, fontSize: 12.5, cursor: dis ? 'default' : 'pointer', font: 'inherit' } }, label);
  const changedChip = !sm.query && st.defaults ? h('button', { type: 'button', 'aria-pressed': changedOnly ? 'true' : 'false', onClick: () => { setChangedOnly(x => !x); setHit(-1); },
    title: 'Only the settings that differ from the defaults (config.example.toml)', style: { ...chipSt(changedOnly, { sm: true }), marginRight: 'auto' } }, `Changed ${changed.length}`) : null;
  const expandBar = !sm.query && (changedChip || refs.length > 1) ? h('div', { style: { display: 'flex', gap: 14, alignItems: 'center', justifyContent: 'flex-end', fontSize: 12.5 } },
    changedChip, !changedOnly && refs.length > 1 ? [linkBtn('Expand all', true, allOpen), linkBtn('Collapse all', false, allClosed)] : null) : null;
  const shownSecs = searching ? secs.filter(s => m.perSection[s.id]) : [cur];
  const body = shownSecs.map(sec => (searching
    ? h('section', { key: sec.id, 'aria-label': sec.label, style: { display: 'flex', flexDirection: 'column', gap: 10 } },
      h('h2', { style: { margin: '6px 0 0', fontSize: 15, fontWeight: 600 } }, sec.label, h('span', { style: { marginLeft: 8, fontSize: 12, fontWeight: 400, color: T.mut } }, `${m.perSection[sec.id]} match${m.perSection[sec.id] === 1 ? '' : 'es'}`)),
      sec.groups.map(g => groupEl(sec, g)))
    : h(R().Fragment, { key: sec.id }, sec.groups.map(g => groupEl(sec, g)))));
  const nSecs = Object.keys(m.perSection).length;
  const status = sm.query ? (m.rows.length ? `${m.rows.length} match${m.rows.length === 1 ? '' : 'es'} in ${nSecs} section${nSecs === 1 ? '' : 's'}` : 'No settings match') : '';
  const search = h(SearchBox, { inputRef: boxRef, value: q, status, onChange: v => { setQ(v); setHit(-1); }, onClear: () => { setQ(''); setHit(-1); }, onNext: () => walk(1), onPrev: () => walk(-1) });
  const miss = (cur.areas || []).filter(a => !isLive(a));

  const restartPending = rowsOf(secs).some(r => r.restart && r.path && !sameValue(r, r.get(st.draft), r.get(st.orig)));
  const pick = id => (props.go ? props.go('#/settings/' + id) : (location.hash = '#/settings/' + id));
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 } },
    h('h1', { style: props.h1St || h1St }, 'Settings'),
    st.restart ? h('div', { role: 'status', style: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', padding: '12px 14px', borderRadius: 10, background: T.tacc, border: '1px solid ' + T.acc } },
      h('span', { style: { flex: 1, minWidth: 200 } }, h('strong', null, 'Saved.'), ' Restart GAIFA to apply the new port: ', h('code', { style: { fontFamily: MONO } }, 'gaifa restart')),
      h('button', { type: 'button', onClick: () => up({ restart: false }), style: { ...btnSt(false), height: 28, fontSize: 12, background: T.card } }, 'Dismiss')) : null,
    st.err && !errField ? h('div', { role: 'alert', style: { padding: '10px 12px', borderRadius: 8, background: T.trd, color: T.rd } }, st.err.detail || String(st.err.message || st.err)) : null,
    h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 20, alignItems: 'flex-start' } },
    h(SectionNav, { sections: secs, current: searching ? null : cur.id, onPick: id => { setQ(''); setHit(-1); setChangedOnly(false); pick(id); }, density: props.density,
      counts: searching ? m.perSection : changedM.perSection, dimmed: searching ? Object.fromEntries(secs.map(s => [s.id, !m.perSection[s.id]])) : {}, search }),
    h('div', { role: searching ? 'region' : undefined, 'aria-label': searching ? 'Search results' : undefined, style: { flex: '1 1 480px', maxWidth: 900, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 14 } },
      !searching && miss.length ? h('div', { role: 'note', style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: T.mut } },
        h('span', { style: { height: 18, padding: '0 6px', borderRadius: 4, border: '1px solid ' + T.pu, background: T.tpu, color: T.pu, fontSize: 10, fontWeight: 600, letterSpacing: '.06em', display: 'inline-flex', alignItems: 'center' } }, 'MOCK'),
        h('span', null, `Mock data: the ${miss.join(' and ')} ${miss.length > 1 ? 'areas aren’t' : 'area isn’t'} live yet.`)) : null,
      expandBar,
      searching && !m.rows.length ? h('div', { style: { color: T.mut, padding: '24px 0' } }, sm.query ? `Nothing in Settings matches “${q.trim()}”.` : 'Nothing differs from the defaults.') : null,
      body,
      dirty ? h('div', { role: 'region', 'aria-label': 'Unsaved changes', style: { position: 'sticky', bottom: 12, zIndex: 20, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', padding: '10px 14px',
        borderRadius: 10, background: T.card, border: '1px solid ' + T.acc, boxShadow: '0 10px 30px rgba(0,0,0,.35)' } },
        h('span', { style: { flex: 1, minWidth: 160, fontWeight: 500 } }, 'Unsaved changes'),
        h('button', { type: 'button', onClick: revert, style: btnSt(false) }, 'Revert'),
        h('button', { type: 'button', onClick: save, disabled: invalid || st.saving, style: btnSt(true, invalid || st.saving) }, st.saving ? 'Saving…' : restartPending ? 'Save and restart later' : 'Save changes')) : null)));
}

export { rowsOf };
