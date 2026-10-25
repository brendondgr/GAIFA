// The Settings page's section list (plan settings-redesign 2.3): the sections as plain links in a left column, as the
// page had them before the redesign, kept in view (sticky under the shell's header, 44 px compact, 52 px comfortable)
// while a long section scrolls; the search box at its top; a small count at the end of a link (search matches, changed
// values). Under 760 px the list sits above the content and isn't pinned. Written by us (web/PATCHES.md).
// (A bar of tabs across the top was built first and replaced on the user's call, 2026-10-25.)

import { h, T } from '../chat/chat-ui.js';

const R = () => globalThis.React;
export const headerHeight = density => (density === 'comfortable' ? 52 : 44);
export const NARROW = 760;
const GAP = 12;
export const navSt = on => ({ position: 'relative', display: 'flex', alignItems: 'center', gap: 10, height: 32, padding: '0 10px', borderRadius: 6, fontSize: 13, fontWeight: on ? 600 : 400,
  textDecoration: 'none', color: on ? T.tx : T.mut, background: on ? T.hov : 'transparent' });

/** The column's style: pinned under the header when wide, in the flow when narrow. */
export function navColumnSt(density, wide) {
  const base = { flex: '0 1 190px', minWidth: 160, display: 'flex', flexDirection: 'column', gap: 2 };
  if (!wide) return { ...base, flex: '1 1 100%' };
  const top = headerHeight(density) + GAP;
  return { ...base, position: 'sticky', top, alignSelf: 'flex-start', maxHeight: `calc(100vh - ${top + GAP}px)`, overflowY: 'auto' };
}

function useWide() {
  const React = R(), get = () => (typeof window === 'undefined' ? true : window.innerWidth >= NARROW), [w, setW] = React.useState(get);
  React.useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const f = () => setW(get());
    window.addEventListener('resize', f);
    return () => window.removeEventListener('resize', f);
  }, []);
  return w;
}

export function SectionNav({ sections, current, counts = {}, dimmed = {}, onPick, search, density }) {
  const wide = useWide();
  const link = s => {
    const on = s.id === current, n = counts[s.id];
    return h('a', { key: s.id, href: '#/settings/' + s.id, 'aria-current': on ? 'page' : undefined, onClick: e => { if (onPick) { e.preventDefault(); onPick(s.id); } },
      className: 'gaifa-settings-link', style: { ...navSt(on), opacity: dimmed[s.id] ? 0.5 : 1 } },
    h('span', { style: { flex: 1, minWidth: 0 } }, s.label),
    n ? h('span', { 'aria-label': `${n} here`, style: { fontSize: 11, color: T.mut, fontVariantNumeric: 'tabular-nums' } }, String(n)) : null);
  };
  return h('nav', { 'aria-label': 'Settings sections', 'data-settings-nav': true, style: navColumnSt(density, wide) },
    search ? h('div', { style: { paddingBottom: 8 } }, search) : null,
    sections.map(link));
}

/** The search box at the top of the list (3.2): `/` focuses it (the page's key handler), Esc or × clears, Enter and ↓ go
 *  to the next match, ↑ to the previous; the matches are announced ("12 matches in 4 sections"). */
export function SearchBox({ value, onChange, onClear, onNext, onPrev, status, inputRef }) {
  const onKey = e => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onClear(); }
    else if (e.key === 'Enter' || e.key === 'ArrowDown') { e.preventDefault(); (e.shiftKey ? onPrev : onNext)(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); onPrev(); }
  };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } },
    h('div', { style: { position: 'relative', display: 'flex', alignItems: 'center' } },
      h('svg', { width: 13, height: 13, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.75, strokeLinecap: 'round', 'aria-hidden': true, style: { position: 'absolute', left: 9, color: T.mut } },
        h('path', { d: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4' })),
      h('input', { ref: inputRef, type: 'text', value, placeholder: 'Search settings', 'aria-label': 'Search settings', onChange: e => onChange(e.target.value), onKeyDown: onKey,
        style: { height: 30, width: '100%', padding: '0 26px 0 28px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.sb, color: T.tx, font: 'inherit', fontSize: 12.5, outline: 'none' } }),
      value ? h('button', { type: 'button', 'aria-label': 'Clear the search', onClick: onClear, style: { position: 'absolute', right: 4, width: 22, height: 22, border: 0, borderRadius: 4, background: 'transparent', color: T.mut, cursor: 'pointer', display: 'grid', placeItems: 'center' } },
        h('svg', { width: 12, height: 12, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', 'aria-hidden': true }, h('path', { d: 'M6 6l12 12M18 6L6 18' }))) : null),
    h('span', { 'aria-live': 'polite', role: 'status', style: { fontSize: 11.5, color: T.mut } }, status));
}
