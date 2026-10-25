// The Settings page's section strip (plan settings-redesign 2.3): the title and the sections as tabs in one bar,
// pinned under the shell's header (44 px compact, 52 px comfortable), scrolling sideways when narrow with the
// current tab kept in view; a count badge per tab (search matches, changed values) and the search box's slot at
// its right end. Written by us (web/PATCHES.md).

import { h, T } from '../chat/chat-ui.js';

const R = () => globalThis.React;
export const headerHeight = density => (density === 'comfortable' ? 52 : 44);

/** The tab after `i` in direction `d` (ArrowLeft/Right, Home/End), wrapping. */
export function stepTab(i, key, n) {
  if (key === 'ArrowRight') return (i + 1) % n;
  if (key === 'ArrowLeft') return (i - 1 + n) % n;
  if (key === 'Home') return 0;
  if (key === 'End') return n - 1;
  return i;
}

export function SectionStrip({ sections, current, counts = {}, dimmed = {}, onPick, search, density, h1St }) {
  const React = R(), bar = React.useRef(null);
  React.useEffect(() => {   // keep the current tab in view when the strip scrolls sideways
    const el = bar.current?.querySelector('[aria-selected="true"]');
    el?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
  }, [current]);
  const idx = Math.max(0, sections.findIndex(s => s.id === current));
  const onKey = e => {
    const j = stepTab(idx, e.key, sections.length);
    if (j === idx) return;
    e.preventDefault(); onPick(sections[j].id);
    setTimeout(() => bar.current?.querySelectorAll('[role="tab"]')[j]?.focus(), 0);
  };
  const tab = (s, i) => {
    const on = s.id === current, n = counts[s.id];
    return h('a', { key: s.id, role: 'tab', href: '#/settings/' + s.id, 'aria-selected': on ? 'true' : 'false', tabIndex: on ? 0 : -1, id: 'stab-' + s.id,
      onClick: e => { e.preventDefault(); onPick(s.id); }, onKeyDown: onKey,
      style: { display: 'inline-flex', alignItems: 'center', gap: 6, height: 30, padding: '0 10px', borderRadius: 6, fontSize: 13, whiteSpace: 'nowrap', textDecoration: 'none', flex: 'none',
        fontWeight: on ? 600 : 400, color: on ? T.tx : T.mut, background: on ? T.hov : 'transparent', opacity: dimmed[s.id] ? 0.45 : 1,
        boxShadow: on ? 'inset 0 -2px 0 ' + T.acc : 'none' } },
    s.label, n ? h('span', { 'aria-label': `${n} here`, style: { minWidth: 16, height: 16, padding: '0 5px', borderRadius: 99, fontSize: 10.5, fontWeight: 600, display: 'inline-grid', placeItems: 'center',
      background: T.tacc, color: T.acct } }, String(n)) : null);
  };
  return h('div', { 'data-strip': true, style: { position: 'sticky', top: headerHeight(density), zIndex: 30, background: T.bg, margin: '0 -4px', padding: '8px 4px', borderBottom: '1px solid ' + T.bd,
    display: 'flex', alignItems: 'center', gap: '8px 12px', flexWrap: 'wrap', minWidth: 0 } },
    h('h1', { style: { ...(h1St || { margin: 0, fontSize: 18, fontWeight: 600 }), flex: 'none' } }, 'Settings'),
    h('div', { ref: bar, role: 'tablist', 'aria-label': 'Settings sections', style: { display: 'flex', gap: 2, overflowX: 'auto', minWidth: 0, flex: '1 1 240px', scrollbarWidth: 'thin' } }, sections.map(tab)),
    search ? h('div', { style: { flex: 'none', minWidth: 0 } }, search) : null);
}

/** The search box at the strip's right end (3.2): `/` focuses it (the page's key handler), Esc or × clears, Enter and ↓ go
 *  to the next match, ↑ to the previous; the matches are announced ("12 matches in 4 sections"). */
export function SearchBox({ value, onChange, onClear, onNext, onPrev, status, inputRef }) {
  const onKey = e => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onClear(); }
    else if (e.key === 'Enter' || e.key === 'ArrowDown') { e.preventDefault(); (e.shiftKey ? onPrev : onNext)(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); onPrev(); }
  };
  return h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
    h('div', { style: { position: 'relative', display: 'flex', alignItems: 'center' } },
      h('svg', { width: 13, height: 13, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.75, strokeLinecap: 'round', 'aria-hidden': true, style: { position: 'absolute', left: 9, color: T.mut } },
        h('path', { d: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4' })),
      h('input', { ref: inputRef, type: 'text', value, placeholder: 'Search settings', 'aria-label': 'Search settings', onChange: e => onChange(e.target.value), onKeyDown: onKey,
        style: { height: 30, width: 'clamp(120px, 22vw, 240px)', padding: '0 26px 0 28px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.sb, color: T.tx, font: 'inherit', fontSize: 12.5, outline: 'none' } }),
      value ? h('button', { type: 'button', 'aria-label': 'Clear the search', onClick: onClear, style: { position: 'absolute', right: 4, width: 22, height: 22, border: 0, borderRadius: 4, background: 'transparent', color: T.mut, cursor: 'pointer', display: 'grid', placeItems: 'center' } },
        h('svg', { width: 12, height: 12, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', 'aria-hidden': true }, h('path', { d: 'M6 6l12 12M18 6L6 18' }))) : null),
    h('span', { 'aria-live': 'polite', role: 'status', style: { fontSize: 12, color: T.mut, whiteSpace: 'nowrap', position: status ? 'static' : 'absolute', width: status ? 'auto' : 1, overflow: 'hidden' } }, status));
}
