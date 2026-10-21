// The sidebar (plan 33.3): Overview, Chat and Outputs on top; the services as a list (folding under
// its header), one button, or a button with counts; Learning, Models and Settings at the bottom; the
// footer. Collapsed, it is a 56 px rail of icons where each service's logo carries its state colour.
// Hovering the services shows a gear: a menu to pick how they show and which are listed. Hub.dc.html
// mounts it in its <aside> (`{{ sb.navEl }}`); the choices are Settings.ui.nav (nav-model.js).
import { BUCKETS, MODES, counts, countsText, groups, serviceOn, setAllHidden, setHidden, visible, normNav, bucket } from './nav-model.js';
import { ServiceLogo, StateDot } from './logo.js';
export { ServiceLogo };  // the Overview tiles and the service page header (Hub.dc.html)

const R = () => globalThis.React;
export const RAIL_W = 56;
export const ICONS = {
  apps: 'M5 5h4v4H5zM10 5h4v4h-4zM15 5h4v4h-4zM5 10h4v4H5zM10 10h4v4h-4zM15 10h4v4h-4zM5 15h4v4H5zM10 15h4v4h-4zM15 15h4v4h-4z',
  collapse: 'M4 5h16v14H4zM9 5v14M15.5 10l-2 2 2 2', expand: 'M4 5h16v14H4zM9 5v14M13.5 10l2 2-2 2',
};
const MONO = "'JetBrains Mono',ui-monospace,monospace";
const CSS = `
.hubnav-a{position:relative;display:flex;align-items:center;gap:10px;height:32px;padding:0 10px;border-radius:6px;font-size:13px;color:var(--mut,#8A94A6);text-decoration:none;flex:none}
.hubnav-a:hover{background:var(--hov,#161C28);color:var(--tx,#E6EAF2);text-decoration:none}
.hubnav-a[aria-current=page]{background:var(--hov,#161C28);color:var(--tx,#E6EAF2);font-weight:600}
.hubnav-rail .hubnav-a{justify-content:center;width:40px;height:36px;padding:0;margin:0 auto;gap:0}
.hubnav-ib{width:24px;height:24px;display:grid;place-items:center;border:0;border-radius:5px;background:transparent;color:var(--mut,#8A94A6);cursor:pointer;flex:none;padding:0}
.hubnav-ib:hover{background:var(--hov,#161C28);color:var(--tx,#E6EAF2)}
.hubnav-gear{opacity:0;transition:opacity .12s}
.hubnav-sec:hover .hubnav-gear,.hubnav-sec:focus-within .hubnav-gear,.hubnav-gear[aria-expanded=true]{opacity:1}
@media (hover:none){.hubnav-gear{opacity:1}}
.hubnav-row:hover{background:var(--hov,#161C28)}
`;
function ensureCss() {
  if (typeof document === 'undefined' || document.getElementById('hubnav-css')) return;
  const el = document.createElement('style'); el.id = 'hubnav-css'; el.textContent = CSS; document.head.appendChild(el);
}

const Icon = ({ d, size = 16 }) => R().createElement('svg', { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.75, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, style: { flex: 'none' } }, R().createElement('path', { d }));
const Mark = ({ size }) => {
  const h = R().createElement;
  return h('svg', { width: size, height: size, viewBox: '0 0 32 32', 'aria-hidden': true, style: { flex: 'none' } },
    h('rect', { x: 1, y: 1, width: 30, height: 30, rx: 8, fill: '#FFB224' }),
    h('g', { stroke: '#1A1200', strokeWidth: 2.2, strokeLinecap: 'round' }, h('path', { d: 'M16 16 9.5 9.5M16 16l6.5-6.5M16 16l-6.5 6.5M16 16l6.5 6.5' })),
    h('g', { fill: '#1A1200' }, ...[[16, 16, 4.6], [8.6, 8.6, 2.7], [23.4, 8.6, 2.7], [8.6, 23.4, 2.7], [23.4, 23.4, 2.7]].map(([cx, cy, r], i) => h('circle', { key: i, cx, cy, r }))),
    h('circle', { cx: 16, cy: 16, r: 1.8, fill: '#FFB224' }));
};

/** Three pills: green active, grey inactive, red failed (zero ones faded). */
export function CountPills({ c, small }) {
  const h = R().createElement;
  return h('span', { style: { display: 'inline-flex', gap: small ? 5 : 6, alignItems: 'center', fontFamily: MONO, fontSize: small ? 10.5 : 11, flex: 'none' }, title: countsText(c), 'aria-label': countsText(c) },
    ...['active', 'inactive', 'failed'].map(k => h('span', { key: k, style: { display: 'inline-flex', alignItems: 'center', gap: 3, opacity: c[k] ? 1 : 0.4, color: c[k] ? 'var(--tx,#E6EAF2)' : 'var(--mut,#8A94A6)' } },
      h('span', { style: { width: 6, height: 6, borderRadius: 99, background: BUCKETS[k].color } }), c[k])));
}
/** The rail's bar under the Services icon: each bucket's share of the services. */
function CountBar({ c }) {
  const h = R().createElement, n = c.total || 1;
  return h('span', { 'aria-hidden': true, style: { display: 'flex', width: 24, height: 3, borderRadius: 2, overflow: 'hidden', background: 'var(--row,#1A2130)', marginTop: 3 } },
    ...['active', 'inactive', 'failed'].map(k => c[k] ? h('span', { key: k, style: { width: `${(c[k] / n) * 100}%`, background: BUCKETS[k].color } }) : null));
}

/** The gear's menu: how the services show, and which the list has. */
function ServicesMenu({ at, nav, setNav, services, close, go }) {
  const React = R(), h = React.createElement, ref = React.useRef(null);
  React.useEffect(() => {
    const down = e => { if (ref.current && !ref.current.contains(e.target) && !e.target.closest?.('.hubnav-gear')) close(); };
    const key = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
    document.addEventListener('mousedown', down); document.addEventListener('keydown', key, true);
    setTimeout(() => ref.current?.querySelector('input,button')?.focus(), 0);
    return () => { document.removeEventListener('mousedown', down); document.removeEventListener('keydown', key, true); };
  }, []);
  const hidden = new Set(nav.hidden), shown = services.filter(s => !hidden.has(s.id)).length;
  const seg = on => ({ flex: 1, height: 26, border: 0, borderRadius: 5, fontSize: 12, cursor: 'pointer', whiteSpace: 'nowrap', padding: '0 6px', background: on ? 'var(--hov,#161C28)' : 'transparent', color: on ? 'var(--tx,#E6EAF2)' : 'var(--mut,#8A94A6)', boxShadow: on ? '0 0 0 1px var(--bds,#2A3547)' : 'none', fontWeight: on ? 600 : 500 });
  const label = { fontSize: 11, fontWeight: 600, letterSpacing: '.07em', textTransform: 'uppercase', color: 'var(--mut,#8A94A6)' };
  const link = { border: 0, background: 'transparent', color: 'var(--cy,#58C4DD)', cursor: 'pointer', fontSize: 12, padding: 0 };
  return h('div', { ref, role: 'dialog', 'aria-label': 'Services in the sidebar', style: { position: 'fixed', zIndex: 90, ...at, width: 272, maxHeight: 'min(560px, calc(100vh - 24px))', display: 'flex', flexDirection: 'column', background: 'var(--card,#11151D)', border: '1px solid var(--bds,#2A3547)', borderRadius: 10, boxShadow: '0 16px 48px rgba(0,0,0,.45)', fontSize: 12.5, color: 'var(--tx,#E6EAF2)' } },
    h('div', { style: { padding: '12px 12px 10px', display: 'flex', flexDirection: 'column', gap: 8, borderBottom: '1px solid var(--bd,#1D2430)' } },
      h('div', { style: label }, 'Show services as'),
      h('div', { role: 'radiogroup', 'aria-label': 'Show services as', style: { display: 'flex', gap: 2, padding: 2, borderRadius: 7, background: 'var(--inset,#131926)' } },
        ...MODES.map(([k, l]) => h('button', { key: k, role: 'radio', 'aria-checked': nav.services === k, onClick: () => setNav(n => ({ ...n, services: k })), style: seg(nav.services === k) }, k === 'counts' ? 'Counts' : l))),
      h('div', { style: { color: 'var(--mut,#8A94A6)', fontSize: 11.5 } }, nav.services === 'list' ? 'Each service has its own item, with its state.' : nav.services === 'button' ? 'One Services item that opens the Services page.' : 'One Services item with how many are active, inactive and failed.')),
    h('div', { style: { padding: '10px 12px 4px', display: 'flex', alignItems: 'center', gap: 8 } },
      h('span', { style: label }, 'In the list'), h('span', { style: { color: 'var(--mut,#8A94A6)', fontFamily: MONO, fontSize: 11 } }, `${shown}/${services.length}`),
      h('span', { style: { flex: 1 } }),
      h('button', { style: link, onClick: () => setNav(n => setAllHidden(n, services, false)) }, 'Show all'),
      h('button', { style: link, onClick: () => setNav(n => setAllHidden(n, services, true)) }, 'Hide all')),
    h('div', { style: { overflowY: 'auto', padding: '2px 6px 8px', opacity: nav.services === 'list' ? 1 : 0.55 } },
      ...services.map(sv => h('label', { key: sv.id, className: 'hubnav-row', style: { display: 'flex', alignItems: 'center', gap: 9, height: 30, padding: '0 6px', borderRadius: 6, cursor: 'pointer' } },
        h('input', { type: 'checkbox', checked: !hidden.has(sv.id), onChange: e => { const hide = !e.target.checked; setNav(n => setHidden(n, services, sv.id, hide)); }, style: { accentColor: 'var(--acc,#FFB224)', margin: 0 } }),
        h(ServiceLogo, { sv, size: 16 }),
        h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, sv.name),
        h(StateDot, { sv })))),
    h('div', { style: { borderTop: '1px solid var(--bd,#1D2430)', padding: '8px 12px', display: 'flex' } },
      h('button', { style: link, onClick: () => { close(); go('#/services'); } }, 'See all services →')));
}

export function Sidebar(p) {
  const React = R(), h = React.createElement;
  ensureCss();
  const { services = [], route, icons: I = {}, mob } = p, nav = normNav(p.nav), rail = nav.collapsed && !mob;
  const [menu, setMenu] = React.useState(null);
  React.useEffect(() => setMenu(null), [route?.hash, rail]);
  const set = next => p.setNav(typeof next === 'function' ? n => normNav(next(normNav(n))) : normNav(next)), ic = k => I[k] || ICONS[k] || I.puzzle;
  const g = groups(route, services), listed = visible(services, nav), c = counts(services), onSvcs = route?.page === 'services';
  const openMenu = e => {
    if (menu) return setMenu(null);
    const r = e.currentTarget.getBoundingClientRect(), W = 272, vw = window.innerWidth, vh = window.innerHeight;
    const left = Math.max(8, Math.min(r.right + 8, vw - W - 8));
    setMenu(r.top > vh * 0.55 ? { left, bottom: Math.max(12, vh - r.bottom) } : { left, top: Math.max(12, r.top - 8) });
  };
  const gear = () => h('button', { className: 'hubnav-ib hubnav-gear', onClick: openMenu, 'aria-label': 'Choose the services in the sidebar', title: 'Choose the services in the sidebar', 'aria-haspopup': 'dialog', 'aria-expanded': !!menu }, h(Icon, { d: I.gear, size: 14 }));
  const cur = on => on ? 'page' : undefined;
  const fixed = n => rail
    ? h('a', { key: n.key, href: n.href, className: 'hubnav-a', 'aria-current': cur(n.on), title: n.label, 'aria-label': n.label }, h(Icon, { d: ic(n.icon) }))
    : h('a', { key: n.key, href: n.href, className: 'hubnav-a', 'aria-current': cur(n.on) }, h(Icon, { d: ic(n.icon) }), h('span', null, n.label));
  const svcTitle = sv => `${sv.name} · ${sv.manifest_errors?.length ? 'manifest error' : sv.state}`;
  const svcItem = sv => rail
    ? h('a', { key: sv.id, href: '#/s/' + sv.id, className: 'hubnav-a', 'aria-current': cur(serviceOn(route, sv.id)), title: svcTitle(sv), 'aria-label': svcTitle(sv) }, h(ServiceLogo, { sv, size: 20, dot: true }))
    : h('a', { key: sv.id, href: '#/s/' + sv.id, className: 'hubnav-a', 'aria-current': cur(serviceOn(route, sv.id)) },
      h(ServiceLogo, { sv, size: 16 }),
      h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, sv.name,
        h('span', { style: { position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' } }, `, ${BUCKETS[bucket(sv)].label.toLowerCase()}`)),
      h(StateDot, { sv }));
  const seeAll = () => rail
    ? h('a', { key: 'all', href: '#/services', className: 'hubnav-a', 'aria-current': cur(onSvcs), title: `See all services (${c.total})`, 'aria-label': 'See all services' }, h(Icon, { d: ICONS.apps }))
    : h('a', { key: 'all', href: '#/services', className: 'hubnav-a', 'aria-current': cur(onSvcs) }, h(Icon, { d: ICONS.apps }), h('span', { style: { flex: 1 } }, 'See all'),
      h('span', { style: { fontFamily: MONO, fontSize: 11, color: 'var(--dim,#737D90)' } }, c.total));
  const svcButton = withCounts => rail
    ? h('a', { key: 'svcs', href: '#/services', className: 'hubnav-a', 'aria-current': cur(onSvcs), title: `Services · ${countsText(c)}`, 'aria-label': `Services, ${countsText(c)}`, style: { flexDirection: 'column' } }, h(Icon, { d: ICONS.apps }), h(CountBar, { c }))
    : h('div', { key: 'svcs', className: 'hubnav-sec', style: { position: 'relative' } },
      h('a', { href: '#/services', className: 'hubnav-a', 'aria-current': cur(onSvcs), style: { paddingRight: 32 } }, h(Icon, { d: ICONS.apps }), h('span', { style: { flex: 1 } }, 'Services'),
        withCounts ? h(CountPills, { c, small: true }) : null),
      h('span', { style: { position: 'absolute', right: 4, top: 4 } }, gear()));

  let svcs;
  if (rail) {
    const asList = nav.services === 'list' && !nav.folded;
    svcs = [h('div', { key: 'div', 'aria-hidden': true, style: { height: 1, margin: '8px 12px', background: 'var(--bd,#1D2430)', flex: 'none' } }),
      ...(asList ? [...listed.map(svcItem), seeAll()] : [svcButton(true)])];
  } else if (nav.services === 'list') {
    svcs = [h('div', { key: 'hd', className: 'hubnav-sec', style: { display: 'flex', alignItems: 'center', gap: 4, padding: '14px 4px 4px 10px', flex: 'none' } },
      h('button', { onClick: () => set(n => ({ ...n, folded: !n.folded })), 'aria-expanded': !nav.folded, title: nav.folded ? 'Show the services' : 'Fold the services', style: { flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 6, border: 0, background: 'transparent', cursor: 'pointer', padding: '3px 0', fontSize: 11, fontWeight: 600, letterSpacing: '.07em', textTransform: 'uppercase', color: 'var(--mut,#8A94A6)' } },
        'Services', h('span', { style: { display: 'flex', transform: nav.folded ? 'rotate(-90deg)' : 'none', transition: 'transform .12s' } }, h(Icon, { d: I.chevD, size: 12 })),
        h('span', { style: { flex: 1 } }), nav.folded ? h(CountPills, { c, small: true }) : null),
      gear()),
    ...(nav.folded ? [] : listed.map(svcItem)), seeAll()];
  } else svcs = [h('div', { key: 'sp', style: { height: 6, flex: 'none' } }), svcButton(nav.services === 'counts')];

  const head = rail
    ? h('div', { style: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, padding: '14px 0 10px', flex: 'none' } },
      h('a', { href: '#/overview', title: 'AIHub', 'aria-label': 'AIHub, go to Overview', style: { display: 'flex' } }, h(Mark, { size: 26 })),
      h('button', { className: 'hubnav-ib', onClick: () => set(n => ({ ...n, collapsed: false })), title: 'Expand the sidebar', 'aria-label': 'Expand the sidebar', style: { width: 32, height: 28 } }, h(Icon, { d: ICONS.expand })))
    : h('div', { style: { display: 'flex', alignItems: 'center', gap: 10, padding: '16px 12px 14px 16px', flex: 'none' } },
      h(Mark, { size: 26 }), h('span', { style: { fontWeight: 600, fontSize: 15, letterSpacing: '-.01em' } }, 'AIHub'), h('span', { style: { flex: 1 } }),
      mob ? h('button', { className: 'hubnav-ib', onClick: p.close, 'aria-label': 'Close navigation', style: { width: 32, height: 32 } }, h(Icon, { d: I.x }))
        : h('button', { className: 'hubnav-ib', onClick: () => set(n => ({ ...n, collapsed: true })), title: 'Collapse the sidebar', 'aria-label': 'Collapse the sidebar', style: { width: 28, height: 28 } }, h(Icon, { d: ICONS.collapse })));
  const hubDot = h('span', { 'aria-hidden': true, style: { width: 7, height: 7, borderRadius: 99, flex: 'none', background: p.hubDown ? 'var(--rd,#F85149)' : 'var(--gr,#3FB950)' } });
  const mockBtn = p.showMock ? h('button', { onClick: p.openMock, title: 'Mock scenarios (Shift+D)', style: { height: 20, padding: rail ? '0 4px' : '0 7px', borderRadius: 4, border: '1px solid var(--pu,#BC8CFF)', background: 'var(--tpu,rgba(188,140,255,.13))', color: 'var(--pu,#BC8CFF)', fontSize: 10.5, fontWeight: 600, letterSpacing: '.06em', cursor: 'pointer' } }, rail ? 'M' : 'MOCK') : null;
  const foot = rail
    ? h('div', { title: `${p.hubDown ? 'AIHub down' : 'AIHub'} ${p.version || ''}`, style: { padding: '12px 0', borderTop: '1px solid var(--bd,#1D2430)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, flex: 'none' } }, hubDot, mockBtn)
    : h('div', { style: { padding: '12px 16px', borderTop: '1px solid var(--bd,#1D2430)', display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--mut,#8A94A6)', flex: 'none' } },
      hubDot, h('span', null, p.hubDown ? 'AIHub down' : 'AIHub'), h('span', { style: { fontFamily: MONO, fontSize: 11.5 } }, p.version), h('span', { style: { flex: 1 } }), mockBtn);

  return h('div', { className: rail ? 'hubnav-rail' : '', style: { display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 } },
    head,
    // the top and bottom groups stay put; only the services between them scroll
    h('nav', { 'aria-label': 'Pages and services', style: { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', padding: rail ? '0 0 10px' : '0 8px 10px' } },
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: 2, flex: 'none' } }, ...g.top.map(fixed)),
      h('div', { className: 'hubnav-scroll', style: { flex: '0 1 auto', minHeight: 0, overflowY: 'auto', overflowX: 'hidden', display: 'flex', flexDirection: 'column', gap: 2, margin: rail ? 0 : '0 -8px', padding: rail ? '0 0 4px' : '0 8px 4px', scrollbarWidth: rail ? 'none' : 'thin' } }, ...svcs),
      h('div', { style: { flex: 1, minHeight: 10 } }),
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: 2, flex: 'none', paddingTop: 6, borderTop: '1px solid var(--bd,#1D2430)' } }, ...g.bottom.map(fixed))),
    foot,
    menu ? h(ServicesMenu, { at: menu, nav, setNav: set, services, close: () => setMenu(null), go: p.go }) : null);
}
