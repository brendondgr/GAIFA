// A mod's logo (plan 33.1): its `logo_url` (services/<id>/ui/logo.svg), else a monogram on a colour
// from its id; with an optional state dot at the bottom right (green active, grey inactive, red failed).
import { BUCKETS, bucket, monogram, pulses } from './nav-model.js';

const R = () => globalThis.React;

export function ServiceLogo({ sv, size = 16, dot = false, ring = 'var(--sb,#0D1119)' }) {
  const React = R(), h = React.createElement;
  const [broken, setBroken] = React.useState(false);
  // A hub from before plan 33.1 sends no `logo_url`: try the mod's ui/logo.svg anyway (a miss falls back below)
  const src = sv?.logo_url !== undefined ? sv.logo_url : sv?.id ? `/ui/services/${sv.id}/logo.svg` : null;
  const url = src && !broken ? src : null, radius = Math.round(size * 0.26);
  const box = { position: 'relative', display: 'inline-flex', flex: 'none', width: size, height: size };
  let mark;
  if (url) mark = h('img', { src: url, alt: '', width: size, height: size, draggable: false, onError: () => setBroken(true), style: { width: size, height: size, borderRadius: radius, display: 'block' } });
  else {
    const m = monogram(sv?.id || '?', sv?.name);
    mark = h('span', { style: { width: size, height: size, borderRadius: radius, background: m.bg, color: '#fff', display: 'grid', placeItems: 'center', fontSize: Math.max(7, Math.round(size * 0.42)), fontWeight: 600, letterSpacing: '-.02em', lineHeight: 1 } }, m.text);
  }
  if (!dot) return h('span', { style: box, 'aria-hidden': true }, mark);
  const d = Math.max(7, Math.round(size * 0.42)), b = BUCKETS[bucket(sv)];
  return h('span', { style: box, 'aria-hidden': true }, mark,
    h('span', { style: { position: 'absolute', right: -Math.round(d / 3), bottom: -Math.round(d / 3), width: d, height: d, borderRadius: 99, background: b.color, boxShadow: `0 0 0 2px ${ring}`, animation: pulses(sv) ? 'hubpulse 1.2s ease-in-out infinite' : 'none' } }));
}

/** The state dot on its own (the expanded sidebar's rows, the Services page). */
export function StateDot({ sv, size = 7 }) {
  const b = BUCKETS[bucket(sv)];
  return R().createElement('span', { 'aria-hidden': true, style: { width: size, height: size, borderRadius: 99, background: b.color, flex: 'none', display: 'inline-block', animation: pulses(sv) ? 'hubpulse 1.2s ease-in-out infinite' : 'none' } });
}
