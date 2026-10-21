// The Services page `#/services` (plan 33.4), where the sidebar's "See all" goes: every mod, listed or
// not, with its logo, state, memory and port; filters by state and a search; Open, Start or Stop; an
// "In sidebar" switch per mod and how the sidebar shows services (Settings.ui.nav, nav-model.js).
import { BUCKETS, MODES, bucket, counts, filterServices, normNav, setHidden } from './nav-model.js';
import { ServiceLogo } from './logo.js';
import { CountPills } from './sidebar.js';

const R = () => globalThis.React;
const MONO = "'JetBrains Mono',ui-monospace,monospace";
const fgb = b => b == null ? '—' : b < 1e8 ? `${Math.round(b / 1e6)} MB` : `${(b / 1e9).toFixed(1)} GB`;
const seg = on => ({ height: 26, padding: '0 10px', border: 0, borderRadius: 5, fontSize: 12, fontWeight: 500, cursor: 'pointer', whiteSpace: 'nowrap', background: on ? 'var(--hov,#161C28)' : 'transparent', color: on ? 'var(--tx,#E6EAF2)' : 'var(--mut,#8A94A6)', boxShadow: on ? '0 0 0 1px var(--bds,#2A3547)' : 'none' });
const btn = (pri, danger) => ({ display: 'inline-flex', alignItems: 'center', gap: 6, height: 28, padding: '0 10px', borderRadius: 6, fontSize: 12, fontWeight: 500, cursor: 'pointer', whiteSpace: 'nowrap', textDecoration: 'none',
  border: '1px solid ' + (danger ? 'var(--rd,#F85149)' : 'var(--bds,#2A3547)'), background: danger ? 'var(--trd,rgba(248,81,73,.13))' : 'var(--inset,#131926)', color: danger ? 'var(--rd,#F85149)' : 'var(--tx,#E6EAF2)', ...(pri ? { background: 'var(--acc,#FFB224)', color: '#1A1200', borderColor: 'transparent', fontWeight: 600 } : {}) });

function Switch({ on, onChange, label }) {
  const h = R().createElement;
  return h('button', { role: 'switch', 'aria-checked': on, 'aria-label': label, title: label, onClick: () => onChange(!on), style: { width: 30, height: 17, borderRadius: 99, border: 0, padding: 2, cursor: 'pointer', flex: 'none', background: on ? 'var(--acc,#FFB224)' : 'var(--bds,#2A3547)', display: 'flex', justifyContent: on ? 'flex-end' : 'flex-start', transition: 'background .12s' } },
    h('span', { style: { width: 13, height: 13, borderRadius: 99, background: on ? '#1A1200' : 'var(--mut,#8A94A6)' } }));
}

function Card({ sv, listed, onListed, start, stop }) {
  const h = R().createElement, b = BUCKETS[bucket(sv)], broken = !!sv.manifest_errors?.length;
  const stateText = broken ? 'manifest error' : sv.state, canStart = !broken && ['stopped', 'failed'].includes(sv.state), canStop = !broken && ['ready', 'degraded', 'starting'].includes(sv.state);
  const meta = [['port', sv.port || '—'], ['memory', fgb(sv.memory?.used_bytes || 0)], ...(sv.version ? [['version', sv.version]] : [])];
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10, padding: 14, borderRadius: 10, background: 'var(--card,#11151D)', border: '1px solid var(--bd,#1D2430)', minWidth: 0 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 } },
      h(ServiceLogo, { sv, size: 32, dot: true, ring: 'var(--card,#11151D)' }),
      h('div', { style: { flex: 1, minWidth: 0 } },
        h('a', { href: '#/s/' + sv.id, style: { display: 'block', fontWeight: 600, fontSize: 13.5, color: 'var(--tx,#E6EAF2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, sv.name),
        h('div', { style: { fontFamily: MONO, fontSize: 11, color: 'var(--mut,#8A94A6)' } }, sv.id)),
      h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 6, height: 20, padding: '0 8px', borderRadius: 99, fontSize: 11, fontWeight: 500, color: b.color, background: b.tint, whiteSpace: 'nowrap' } },
        h('span', { style: { width: 6, height: 6, borderRadius: 99, background: b.color } }), stateText)),
    h('div', { title: sv.description, style: { color: 'var(--mut,#8A94A6)', fontSize: 12, lineHeight: 1.45, minHeight: 35, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' } }, broken ? sv.manifest_errors[0] : (sv.description || 'No description')),
    h('div', { style: { display: 'flex', gap: 14, fontSize: 11.5, color: 'var(--mut,#8A94A6)' } },
      ...meta.map(([k, v]) => h('span', { key: k }, `${k} `, h('span', { style: { fontFamily: MONO, color: 'var(--tx,#E6EAF2)' } }, v)))),
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, paddingTop: 10, borderTop: '1px solid var(--bd,#1D2430)' } },
      h('a', { href: '#/s/' + sv.id, style: btn(false) }, 'Open'),
      canStart ? h('button', { onClick: () => start(sv.id), style: btn(true) }, 'Start') : null,
      canStop ? h('button', { onClick: () => stop(sv), style: btn(false) }, 'Stop') : null,
      h('span', { style: { flex: 1 } }),
      h('label', { style: { display: 'flex', alignItems: 'center', gap: 7, fontSize: 12, color: 'var(--mut,#8A94A6)' } }, 'In sidebar',
        h(Switch, { on: listed, onChange: onListed, label: `Show ${sv.name} in the sidebar` }))));
}

export function ServicesPage({ services = [], nav: rawNav, setNav, start, stop, h1St }) {
  const React = R(), h = React.createElement, nav = normNav(rawNav);
  const [filter, setFilter] = React.useState('all'), [q, setQ] = React.useState('');
  const c = counts(services), list = filterServices(services, { filter, q }), hidden = new Set(nav.hidden);
  const filters = [['all', 'All', c.total], ['active', 'Active', c.active], ['inactive', 'Inactive', c.inactive], ['failed', 'Failed', c.failed]];
  const group = { display: 'flex', gap: 2, padding: 2, borderRadius: 7, background: 'var(--card,#11151D)', border: '1px solid var(--bd,#1D2430)' };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 12 } },
    h('div', { style: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12 } },
      h('h1', { style: h1St || { margin: 0, fontSize: 18, fontWeight: 600 } }, 'Services'),
      h(CountPills, { c }),
      h('span', { style: { flex: 1 } }),
      h('span', { style: { fontSize: 12, color: 'var(--mut,#8A94A6)' } }, 'Sidebar shows'),
      h('div', { role: 'radiogroup', 'aria-label': 'The sidebar shows services as', style: group },
        ...MODES.map(([k, l]) => h('button', { key: k, role: 'radio', 'aria-checked': nav.services === k, onClick: () => setNav(n => ({ ...normNav(n), services: k })), style: seg(nav.services === k) }, l)))),
    h('div', { style: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10 } },
      h('div', { role: 'group', 'aria-label': 'Filter by state', style: group },
        ...filters.map(([k, l, n]) => h('button', { key: k, 'aria-pressed': filter === k, onClick: () => setFilter(k), style: seg(filter === k) }, l, ' ', h('span', { style: { fontFamily: MONO, fontSize: 11, opacity: 0.7 } }, n)))),
      h('input', { type: 'search', value: q, onChange: e => setQ(e.target.value), placeholder: 'Search services', 'aria-label': 'Search services', style: { height: 32, minWidth: 200, flex: '0 1 280px', padding: '0 10px', borderRadius: 7, border: '1px solid var(--bds,#2A3547)', background: 'var(--inset,#131926)', fontSize: 12.5 } }),
      h('span', { style: { fontSize: 12, color: 'var(--mut,#8A94A6)' } }, `${services.filter(s => !hidden.has(s.id)).length} of ${services.length} in the sidebar`)),
    list.length
      ? h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))', gap: 12 } },
        ...list.map(sv => h(Card, { key: sv.id, sv, listed: !hidden.has(sv.id), onListed: on => setNav(n => setHidden(n, services, sv.id, !on)), start, stop })))
      : h('div', { style: { padding: '48px 20px', textAlign: 'center', color: 'var(--mut,#8A94A6)', border: '1px dashed var(--bds,#2A3547)', borderRadius: 10 } },
        services.length ? 'No services match.' : 'No services installed. Make one with aihub new <id>.'));
}
