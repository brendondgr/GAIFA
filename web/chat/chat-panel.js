// Side panels in Chat (calendar plan 7.1): a mod with `[ui] chat_panel` gets a column on the Chat page's right, like
// Outlook's on the web. A slim rail at the right edge has an icon per panel; one panel is open at a time, 260–440 px
// wide (a divider to drag), a drawer from the right when the page is narrow. Open, which one and the width are kept
// on the hub (`hub.chat.panel`). The mod's module gets `mount(el, ctx)` with ctx = {service, api, navigate, insertText,
// toast, store}: insertText puts words into the composer you last used.

import { h, T, Icon } from './chat-ui.js';
import { store } from '../ui-store.js';

const R = () => globalThis.React;
export const KEY = 'hub.chat.panel';
export const MIN_W = 260, MAX_W = 440, DEF_W = 320;

export const clampWidth = w => Math.round(Math.max(MIN_W, Math.min(MAX_W, Number(w) || DEF_W)));

/** The panels the services offer (a running mod with a chat_panel), in the services' order. */
export const panelsOf = services => (services || []).filter(s => s?.chat_panel?.url && ['ready', 'degraded'].includes(s.state))
  .map(s => ({ id: s.id, label: s.chat_panel.label, url: s.chat_panel.url, logo: s.logo_url, version: s.version, service: s }));

/** The kept state, whole: {open: id | null, width}. */
export function panelState(v) {
  const x = v && typeof v === 'object' ? v : {};
  return { open: typeof x.open === 'string' && x.open ? x.open : null, width: clampWidth(x.width) };
}

/** What a toggle does: the same panel closes, another one opens. */
export const toggled = (st, id) => ({ ...st, open: st.open === id ? null : id });

/** Words into the composer last used (or the first): a React textarea, so through its value setter and an input event. */
export function insertInto(text, doc = globalThis.document) {
  const all = [...(doc?.querySelectorAll?.('textarea[aria-label="Message"]') || [])];
  const ta = all.find(x => x === lastComposer) || all[0];
  if (!ta) return false;
  const set = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(ta), 'value')?.set;
  const cur = ta.value || '', next = cur + (cur && !/\s$/.test(cur) ? ' ' : '') + text + ' ';
  if (set) set.call(ta, next); else ta.value = next;
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  ta.focus();
  return true;
}
let lastComposer = null;
if (typeof document !== 'undefined') document.addEventListener('focusin', e => { if (e.target?.matches?.('textarea[aria-label="Message"]')) lastComposer = e.target; });

/** The rail of panel icons at the right edge. */
export function PanelRail({ panels, open, onToggle }) {
  return h('div', { role: 'toolbar', 'aria-label': 'Side panels', style: { width: 40, flex: 'none', borderLeft: '1px solid ' + T.bd, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, padding: '10px 0', background: T.bg } },
    panels.map(p => h('button', { key: p.id, type: 'button', onClick: () => onToggle(p.id), 'aria-pressed': open === p.id ? 'true' : 'false', title: `${open === p.id ? 'Hide' : 'Show'} ${p.label}`,
      'aria-label': `${open === p.id ? 'Hide' : 'Show'} ${p.label}`,
      style: { width: 30, height: 30, borderRadius: 8, border: '1px solid ' + (open === p.id ? T.bds : 'transparent'), background: open === p.id ? T.hov : 'transparent', cursor: 'pointer', display: 'grid', placeItems: 'center', padding: 0 } },
      p.logo ? h('img', { src: p.logo, alt: '', width: 18, height: 18, style: { opacity: open === p.id ? 1 : 0.75 } }) : h(Icon, { d: 'calendar', size: 16 }))));
}

/** The open panel: the mod's module mounted in a column with a divider to drag. */
export function SidePanel({ panel, width, setWidth, onClose, narrow, ctx }) {
  const React = R(), ref = React.useRef(null), [err, setErr] = React.useState(null);
  React.useEffect(() => {
    let cleanup = null, alive = true;
    setErr(null);
    import(panel.url + (panel.url.includes('?') ? '&' : '?') + 'v=' + encodeURIComponent(panel.version || '0')).then(m => {
      if (!alive || !ref.current) return;
      const mod = m?.default;
      if (!mod || typeof mod.mount !== 'function') throw new Error('its module must `export default { mount(el, ctx) }`');
      const r = mod.mount(ref.current, { ...ctx, service: panel.service });
      if (typeof r === 'function') cleanup = r;
    }).catch(e => { if (alive) setErr(e?.message || String(e)); });
    return () => { alive = false; try { cleanup?.(); } catch { /* gone */ } ref.current?.replaceChildren(); };
  }, [panel.id, panel.url]);
  const drag = e => {
    e.preventDefault();
    const x0 = e.clientX, w0 = width;
    const move = ev => setWidth(clampWidth(w0 + (x0 - ev.clientX)));
    const up = () => { removeEventListener('pointermove', move); removeEventListener('pointerup', up); };
    addEventListener('pointermove', move); addEventListener('pointerup', up);
  };
  const body = h('div', { style: { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' } },
    err ? h('div', { role: 'alert', style: { padding: 14, fontSize: 12.5, color: T.rd } }, `${panel.label}’s panel couldn’t load (${err}).`) : null,
    h('div', { ref, style: { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' } }));
  const head = h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px 8px 12px', borderBottom: '1px solid ' + T.bd, flex: 'none' } },
    h('span', { style: { fontWeight: 600, fontSize: 13, flex: 1 } }, panel.label),
    h('button', { type: 'button', onClick: onClose, 'aria-label': `Hide ${panel.label}`, style: { width: 24, height: 24, border: 0, background: 'transparent', color: T.mut, cursor: 'pointer', display: 'grid', placeItems: 'center', padding: 0 } }, h(Icon, { d: 'x', size: 14 })));
  if (narrow) {
    return h(React.Fragment, null,
      h('div', { onClick: onClose, 'aria-hidden': true, style: { position: 'absolute', inset: 0, zIndex: 42, background: T.ov } }),
      h('aside', { 'aria-label': panel.label, style: { position: 'absolute', top: 0, bottom: 0, right: 0, zIndex: 43, width: 'min(340px, 90%)', background: T.bg, borderLeft: '1px solid ' + T.bds, boxShadow: '0 0 40px rgba(0,0,0,.4)', display: 'flex', flexDirection: 'column' } }, head, body));
  }
  return h('aside', { 'aria-label': panel.label, style: { width, flex: 'none', position: 'relative', borderLeft: '1px solid ' + T.bd, display: 'flex', flexDirection: 'column', minHeight: 0, background: T.bg } },
    h('div', { role: 'separator', 'aria-orientation': 'vertical', 'aria-label': 'Resize the panel', onPointerDown: drag, style: { position: 'absolute', left: -3, top: 0, bottom: 0, width: 6, cursor: 'col-resize', zIndex: 2 } }),
    head, body);
}

/** The Chat page's panels: the rail and the open one, with their state kept on the hub. */
export function ChatPanels({ services, narrow, api, go, toast }) {
  const React = R(), panels = panelsOf(services);
  const [st, setSt] = React.useState(() => panelState(store.get(KEY, null)));
  const save = next => { setSt(next); store.set(KEY, next, { wait: 600 }); };
  if (!panels.length) return null;
  const open = panels.find(p => p.id === st.open) || null;
  const ctx = { api, navigate: go, insertText: insertInto, toast, store };
  return h(React.Fragment, null,
    open ? h(SidePanel, { key: open.id, panel: open, width: st.width, setWidth: w => save({ ...st, width: w }), onClose: () => save({ ...st, open: null }), narrow, ctx }) : null,
    h(PanelRail, { panels, open: open?.id || null, onToggle: id => save(toggled(st, id)) }));
}
