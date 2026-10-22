// Memory pools in the UI (plan 36.4, brief §11.7 `Memory.pools`): on a machine with dedicated GPUs, one bar
// per card's VRAM under the system memory bar, in the header's memory popover and the Overview's
// "Memory now" widget. A machine whose GPUs share the RAM has one pool and shows nothing more. Written by us
// (web/PATCHES.md).

import { h, MONO, MUT, SERIES, fmtBytes } from './chart-kit.js';

// ---------- pure (tested in utils/tests/web/mem-pools.test.mjs) ----------
// The GPU pools as rows: a bar each, split by mod when there's one card (each mod's VRAM is per machine).
export function poolRows(memory, services = []) {
  const pools = (memory?.pools || []).slice(1);
  const name = id => services.find(s => s.id === id)?.name || id;
  const color = id => SERIES[(services.findIndex(s => s.id === id) + SERIES.length) % SERIES.length];
  return pools.map(p => {
    const total = Math.max(1, p.total_bytes);
    const mods = pools.length === 1 ? (memory.by_service || []).filter(r => (r.vram_bytes || 0) > 0.01e9)
      .sort((a, b) => b.vram_bytes - a.vram_bytes).map(r => ({ key: r.id, name: name(r.id), bytes: r.vram_bytes, pct: r.vram_bytes / total * 100, color: color(r.id) })) : [];
    const known = mods.reduce((s, m) => s + m.bytes, 0);
    const other = Math.max(0, p.used_bytes - known);
    return { id: p.id, name: p.name, text: `${fmtBytes(p.used_bytes)} / ${fmtBytes(p.total_bytes)}`, mods,
      other: { bytes: other, pct: other / total * 100 }, free: fmtBytes(p.available_bytes) };
  });
}

// "Unified memory" where GPUs share the RAM, else "System memory".
export const poolTitle = memory => ((memory?.pools || []).length > 1 ? 'System memory' : 'Unified memory');

// ---------- the bars ----------
export function PoolBars({ memory, services }) {
  const rows = poolRows(memory, services);
  if (!rows.length) return null;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10 } }, rows.map(r =>
    h('section', { key: r.id, 'aria-label': r.name, style: { display: 'flex', flexDirection: 'column', gap: 5 } },
      h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 8 } },
        h('h3', { style: { margin: 0, fontSize: 11, fontWeight: 600, letterSpacing: '.07em', textTransform: 'uppercase', color: MUT } }, r.name),
        h('span', { style: { marginLeft: 'auto', fontFamily: MONO, fontSize: 12 } }, r.text)),
      h('div', { style: { display: 'flex', height: 10, borderRadius: 5, overflow: 'hidden', background: 'var(--row,#1A2130)' } },
        ...r.mods.map(m => h('span', { key: m.key, title: `${m.name}: ${fmtBytes(m.bytes)}`, style: { display: 'block', width: m.pct + '%', minWidth: 2, background: m.color } })),
        r.other.bytes > 0 ? h('span', { key: 'o', title: `Other: ${fmtBytes(r.other.bytes)}`, style: { display: 'block', width: r.other.pct + '%', background: 'var(--other,#46526A)' } }) : null),
      r.mods.length ? h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: '4px 12px', fontSize: 12, color: MUT } },
        ...r.mods.map(m => h('span', { key: m.key }, `${m.name} ${fmtBytes(m.bytes)}`)), h('span', { key: 'f' }, `free ${r.free}`)) : null)));
}
