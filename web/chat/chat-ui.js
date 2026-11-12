// Shared pieces of the Chat page (plan 14.1): theme tokens, icons, buttons, chips, a popover,
// per-browser preferences and formatting. Plain ES module on the page's React (window.React);
// written by us (web/PATCHES.md). Every color is a theme token, so cards work in both themes.

const R = () => globalThis.React;
export const h = (...a) => R().createElement(...a);

// Theme tokens (dark values are the fallbacks; the shell sets the light ones on :root).
export const T = {
  bg: 'var(--bg,#0B0E14)', sb: 'var(--sb,#0D1119)', card: 'var(--card,#11151D)', inset: 'var(--inset,#131926)',
  hov: 'var(--hov,#161C28)', row: 'var(--row,#1A2130)', bd: 'var(--bd,#1D2430)', bds: 'var(--bds,#2A3547)', bdh: 'var(--bdh,#3A4A63)',
  tx: 'var(--tx,#E6EAF2)', mut: 'var(--mut,#8A94A6)', dim: 'var(--dim,#737D90)',
  acc: 'var(--acc,#FFB224)', acct: 'var(--acct,#FFB224)', cy: 'var(--cy,#58C4DD)', gr: 'var(--gr,#3FB950)', rd: 'var(--rd,#F85149)', pu: 'var(--pu,#BC8CFF)',
  tacc: 'var(--tacc,rgba(255,178,36,.13))', tcy: 'var(--tcy,rgba(88,196,221,.13))', tgr: 'var(--tgr,rgba(63,185,80,.13))',
  trd: 'var(--trd,rgba(248,81,73,.13))', tpu: 'var(--tpu,rgba(188,140,255,.13))', ov: 'var(--ov,rgba(3,5,9,.62))',
};
export const MONO = "'JetBrains Mono',ui-monospace,Menlo,monospace";
export const ON_ACC = '#1A1200';   // text on the amber primary button (same in both themes, as in the shell)
export const SHADOW = '0 14px 40px rgba(0,0,0,.35)';
export const COL = 760;            // the thread column's max width

export const ICONS = {
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2',    // scheduled-tasks 4.2
  calendar: 'M4 6.5A1.5 1.5 0 0 1 5.5 5h13A1.5 1.5 0 0 1 20 6.5v12a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5zM4 10h16M8.5 3v4M15.5 3v4',   // calendar 7.1
  undo: 'M9 14L4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3',   // plan 27.7: Undo this turn
  chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2',        // plan 47.2: show
  speaker: 'M4 10v4h4l5 4V6L8 10zM16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11',   // plan 49.1: read aloud
  home: 'M3 11l9-7 9 7M5 10v10h14V10M10 20v-6h4v6', folder: 'M3 6h6l2 2h10v11H3z',   // plan 33: environments, folders
  reply: 'M10 9V5l-7 7 7 7v-4.1c5 0 8.5 1.6 11 5.1-1-5-4-10-11-11z',   // plan 32.2: Reply to a selected part
  code: 'M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16', globe: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18',   // plan 25.3: execute, network
  plus: 'M12 5v14M5 12h14', search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4', x: 'M6 6l12 12M18 6L6 18',
  more: 'M4 12a1 1 0 1 0 2 0 1 1 0 1 0-2 0M11 12a1 1 0 1 0 2 0 1 1 0 1 0-2 0M18 12a1 1 0 1 0 2 0 1 1 0 1 0-2 0',
  edit: 'M4 20h4L19 9l-4-4L4 16z', trash: 'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13', archive: 'M3 5h18v4H3zM5 9v10h14V9M10 13h4',
  branch: 'M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9c0 5-6 4-11.5 7',
  upload: 'M12 15V4M7 9l5-5 5 5M4 20h16', send: 'M12 19V5M6 11l6-6 6 6', stop: 'M7 7h10v10H7z', clip: 'M20 11l-8 8a5 5 0 0 1-7-7l8.5-8.5a3.5 3.5 0 0 1 5 5L10 17a2 2 0 0 1-3-3l7.5-7.5',
  image: 'M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M15 8.5h.01', video: 'M3 6h13v12H3zM16 10l5-3v10l-5-3z',
  cube: 'M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9', wave: 'M3 12h1M7 8v8M11 4v16M15 8v8M19 10v4',
  chevR: 'M9 6l6 6-6 6', chevD: 'M6 9l6 6 6-6', chevL: 'M15 6l-6 6 6 6', check: 'M5 12l5 5 9-10',
  alert: 'M12 3l10 18H2zM12 10v4M12 17.5v.01', info: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v6M12 7.5v.01',
  tool: 'M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z',
  sliders: 'M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1M15 4v4M9 10v4M17 16v4',
  bulb: 'M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z',
  up: 'M7 11v9H4v-9zM7 11l4-8a2 2 0 0 1 2 2v4h5a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 16.8 20H7', down: 'M7 13V4H4v9zM7 13l4 8a2 2 0 0 0 2-2v-4h5a2 2 0 0 0 2-2.3l-1.2-7A2 2 0 0 0 16.8 4H7',
  menu: 'M4 6h16M4 12h16M4 18h16', play: 'M8 5v14l11-7z', eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
  scissors: 'M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM8.1 8.1L20 20M8.1 15.9L20 4',
  wand: 'M4 20L15 9M14 4v3M18.5 5.5l-2 2M20 10h-3M12 6l1 2-2-1', person: 'M12 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM12 8v7M7 11h10M12 15l-3 6M12 15l3 6',
  mic: 'M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v3',
  micOff: 'M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v3M4 4l16 16',   // voice-mute 1.3
  bookmark: 'M6 3h12v18l-6-4-6 4z',
  download: 'M12 4v11M7 10l5 5 5-5M4 20h16', ext: 'M14 4h6v6M20 4l-9 9M18 14v6H4V6h6', shield: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM9 12l2 2 4-4',
  compress: 'M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7', pin: 'M12 17v5M5 17h14l-2-5V4H7v8z', chat: 'M4 5h16v11H9l-5 4z',
  refresh: 'M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7', ref: 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1',
  doc: 'M6 3h8l5 5v13H6zM14 3v5h5M9 13h7M9 17h7', code: 'M9 8l-4 4 4 4M15 8l4 4-4 4',
  slash: 'M15 4L9 20', copy: 'M9 9h11v11H9zM5 15V4h11', upscale: 'M4 14v6h6M20 10V4h-6M4 20l7-7M20 4l-7 7',
};

export function Icon({ d, size = 14, sw = 1.75, fill = 'none', style }) {
  return h('svg', { width: size, height: size, viewBox: '0 0 24 24', fill, stroke: fill === 'none' ? 'currentColor' : 'none', strokeWidth: sw,
    strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, style: { flex: 'none', ...style } }, h('path', { d: ICONS[d] || d }));
}

// ---------- buttons, chips, badges ----------
export function btnSt(kind = 'sec', o = {}) {
  const base = { display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6, height: o.sm ? 26 : 30, padding: o.icon ? 0 : (o.sm ? '0 9px' : '0 12px'),
    width: o.icon ? (o.sm ? 26 : 30) : undefined, borderRadius: 6, font: 'inherit', fontSize: o.sm ? 12 : 12.5, fontWeight: 500, cursor: o.dis ? 'not-allowed' : 'pointer',
    whiteSpace: 'nowrap', opacity: o.dis ? 0.5 : 1, flex: 'none', border: '1px solid ' + T.bds, background: T.inset, color: T.tx };
  const k = { pri: { background: T.acc, color: ON_ACC, borderColor: 'transparent', fontWeight: 600 },
    danger: { background: T.trd, color: T.rd, borderColor: T.rd }, ghost: { background: 'transparent', borderColor: 'transparent', color: T.mut },
    purple: { background: T.tpu, color: T.pu, borderColor: 'transparent' } }[kind];
  return { ...base, ...(k || {}) };
}
// The composer's square buttons (send/stop, microphone, voice mode): one shape, filled so they read as buttons;
// the quiet ones in a muted tone (`on`: a tint of `tone` while they're active), Send and Stop in the accent.
export const boxBtn = (on = false, tone = 'acc') => ({ display: 'grid', placeItems: 'center', width: 30, height: 28, padding: 0, borderRadius: 7, flex: 'none',
  border: '1px solid ' + (on ? 'transparent' : T.bds), background: on ? T['t' + tone] : T.row, color: on ? T[tone] : T.tx });
export function Btn({ kind = 'sec', sm, icon, label, title, onClick, disabled, children, style, ...rest }) {
  const iconOnly = !!icon && children == null && label == null;
  return h('button', { type: 'button', onClick, disabled, title, 'aria-label': iconOnly ? title : undefined,
    style: { ...btnSt(kind, { sm, dis: disabled, icon: iconOnly }), ...style }, ...rest },
  icon ? h(Icon, { d: icon, size: sm ? 13 : 14 }) : null, label ?? children);
}
export function chipSt(on, o = {}) {
  return { display: 'inline-flex', alignItems: 'center', gap: 6, height: o.sm ? 24 : 28, padding: o.sm ? '0 8px' : '0 10px', borderRadius: 99, font: 'inherit', fontSize: o.sm ? 11.5 : 12,
    cursor: 'pointer', whiteSpace: 'nowrap', border: '1px solid ' + (on ? T.cy : T.bds), background: on ? T.tcy : 'transparent', color: on ? T.tx : T.mut, flex: 'none' };
}
export function Badge({ tone = 'dim', children, mono, title, style }) {
  const c = { dim: [T.mut, T.hov], cyan: [T.cy, T.tcy], green: [T.gr, T.tgr], red: [T.rd, T.trd], accent: [T.acct, T.tacc], purple: [T.pu, T.tpu] }[tone] || [T.mut, T.hov];
  return h('span', { title, style: { display: 'inline-flex', alignItems: 'center', gap: 5, height: 18, padding: '0 6px', borderRadius: 4, fontSize: 10.5, fontWeight: 600,
    color: c[0], background: c[1], whiteSpace: 'nowrap', fontFamily: mono ? MONO : undefined, flex: 'none', ...style } }, children);
}
export const label11 = { fontSize: 11, fontWeight: 600, letterSpacing: '.07em', textTransform: 'uppercase', color: T.mut };
export const cardSt = (o = {}) => ({ background: T.card, border: '1px solid ' + (o.accent || T.bd), borderRadius: 8, padding: o.pad ?? '10px 12px', display: 'flex',
  flexDirection: 'column', gap: o.gap ?? 8, minWidth: 0, ...(o.style || {}) });
export const inputSt = { height: 30, padding: '0 9px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.sb, color: T.tx, font: 'inherit', fontSize: 12.5, minWidth: 0, outline: 'none' };

// ---------- a popover anchored in a position:relative wrapper ----------
// place: 'down-left' | 'down-right' | 'up-left' | 'up-right'
export function Popover({ open, onClose, place = 'down-right', width = 320, children, label, style }) {
  const React = R();
  React.useEffect(() => {
    if (!open) return undefined;
    const k = e => { if (e.key === 'Escape') { e.stopPropagation(); onClose?.(); } };
    window.addEventListener('keydown', k, true);
    return () => window.removeEventListener('keydown', k, true);
  }, [open]);
  if (!open) return null;
  const [v, hz] = place.split('-');
  return h(React.Fragment, null,
    h('div', { onClick: onClose, 'aria-hidden': true, style: { position: 'fixed', inset: 0, zIndex: 48 } }),
    h('div', { role: 'dialog', 'aria-label': label, style: { position: 'absolute', zIndex: 49, [v === 'up' ? 'bottom' : 'top']: 'calc(100% + 6px)', [hz === 'left' ? 'left' : 'right']: 0,
      width: `min(${width}px, calc(100vw - 24px))`, maxHeight: 'min(70vh, 520px)', overflow: 'auto', background: T.card, border: '1px solid ' + T.bds, borderRadius: 10,
      boxShadow: SHADOW, padding: 10, display: 'flex', flexDirection: 'column', gap: 8, ...style } }, children));
}

// ---------- per-browser preferences (localStorage, wrapped: it can throw) ----------
const subs = new Set();
// A key saved before the rename to GAIFA (plan 50.2) is read once under its old `aihub.` name.
const legacy = k => (k.startsWith('gaifa.') ? localStorage.getItem('aihub.' + k.slice(6)) : null);
export function getPref(k, d) { try { const v = localStorage.getItem(k) ?? legacy(k); return v == null ? d : JSON.parse(v); } catch { return d; } }
export function setPref(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private window */ } subs.forEach(f => { try { f(k, v); } catch { /* listener */ } }); }
export function usePref(k, d) {
  const React = R(), [v, set] = React.useState(() => getPref(k, d));
  React.useEffect(() => {
    const f = (kk, vv) => { if (kk === k) set(vv); };
    const s = e => { if (e.key === k) set(getPref(k, d)); };
    subs.add(f); window.addEventListener('storage', s);
    return () => { subs.delete(f); window.removeEventListener('storage', s); };
  }, [k]);
  return [v, x => setPref(k, x)];
}

// ---------- a width hook (thread list → drawer under 760 px) ----------
export function useWidth(initial = 1000) {
  const React = R(), ref = React.useRef(null), [w, setW] = React.useState(initial);
  React.useLayoutEffect(() => {
    const el = ref.current; if (!el) return undefined;
    const set = x => { x = Math.floor(x); if (x > 0) setW(p => (p === x ? p : x)); };
    set(el.getBoundingClientRect().width);
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(es => set(es[0].contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

// ---------- formatting ----------
export function fmtTokens(n) {
  if (n == null || isNaN(n)) return '—';
  if (n < 1000) return String(Math.round(n));
  const k = n / 1000;
  return (k >= 100 ? Math.round(k) : Math.round(k * 10) / 10) + 'k';
}
export function fmtAgo(ts, now = Date.now() / 1000) {
  if (!ts) return '';
  const d = Math.max(0, now - ts);
  if (d < 60) return 'now';
  if (d < 3600) return Math.floor(d / 60) + 'm';
  if (d < 86400) return Math.floor(d / 3600) + 'h';
  if (d < 7 * 86400) return Math.floor(d / 86400) + 'd';
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
export function fmtSecs(s) { if (s == null) return ''; s = Math.max(0, Math.round(s)); return s < 60 ? `${s} s` : `${Math.floor(s / 60)}m ${s % 60}s`; }
// A tool's arguments in one short line: `prompt: "a fox…" · aspect: 16:9`.
export function shortArgs(args, max = 120) {
  if (!args || typeof args !== 'object') return '';
  const parts = Object.entries(args).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => {
    let s = typeof v === 'string' ? (v.length > 48 ? `"${v.slice(0, 46)}…"` : `"${v}"`) : v && typeof v === 'object' ? (v.$file ? v.$file : JSON.stringify(v)) : String(v);
    if (s.length > 60) s = s.slice(0, 58) + '…';
    return `${k}: ${s}`;
  });
  const out = parts.join(' · ');
  return out.length > max ? out.slice(0, max - 1) + '…' : out;
}
// "comfy_generate_image" → "Generate image" (the mod prefix dropped, when it's a known mod).
export function toolLabel(name, mods = []) {
  let n = String(name || '');
  const mod = mods.find(m => n.startsWith(m + '_'));
  if (mod) n = n.slice(mod.length + 1);
  n = n.replace(/_/g, ' ');
  return n.charAt(0).toUpperCase() + n.slice(1);
}
