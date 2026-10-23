// The live kit (plan 44.3): the parts of a live card, for anything being made, wherever AIHub shows it: a step in
// Chat, a running job on the Overview, a run on a mod's page. Plain ES module on the page's React (window.React);
// written by us (web/PATCHES.md). Every colour is a theme token, so it works in both themes; with
// prefers-reduced-motion the shimmer, pulses and fades are off.
//
// A job's `live` (plan 44.2, utils/live.py): {stage, stages, step, steps, eta_s, preview: {url, seq, w, h}, lines, audio}.
// Preview frames are pulled here when `preview.seq` changes (the URL is on the hub's proxy), never pushed.
//
//   LiveCard   the frame: header (icon, title, meta, a pulsing dot while running), body, progress line, footer
//   Stage      a box at an aspect ratio, at most `max` px tall, centred
//   Waiting    shimmer and grain with "Waiting for the GPU · …" or "Loading <model>"
//   PreviewLayers  frames that fade in over each other, then the result over them
//   StageChips ✓ done · ● running with time left · ○ waiting
//   LiveThumb  a small preview with its step, for lists of jobs
//   LivePreview  a generic live card for any job with a preview (used when a tool has no card of its own)

const R = () => globalThis.React;
export const h = (...a) => R().createElement(...a);

export const C = {
  card: 'var(--card,#11151D)', inset: 'var(--inset,#131926)', bd: 'var(--bd,#1D2430)', bds: 'var(--bds,#2A3547)',
  tx: 'var(--tx,#E6EAF2)', mut: 'var(--mut,#8A94A6)', dim: 'var(--dim,#737D90)', acc: 'var(--acc,#FFB224)',
  gr: 'var(--gr,#3FB950)', rd: 'var(--rd,#F85149)', cy: 'var(--cy,#58C4DD)', pu: 'var(--pu,#BC8CFF)',
};
export const MONO = "'JetBrains Mono',ui-monospace,Menlo,monospace";

export const KIT_CSS = `
.lk-shim{position:absolute;inset:0;pointer-events:none;background:linear-gradient(110deg,transparent 30%,rgba(255,255,255,.055) 50%,transparent 70%);background-size:250% 100%;animation:lksh 1.7s linear infinite;transition:opacity .5s}
.lk-grain{position:absolute;inset:0;pointer-events:none;opacity:.5;background-image:radial-gradient(rgba(255,255,255,.05) 1px,transparent 1.2px);background-size:9px 9px;transition:opacity .5s}
.lk-dot{width:7px;height:7px;border-radius:50%;background:var(--acc,#FFB224);flex:none;animation:lkpulse 1.2s ease-in-out infinite}
.lk-fade{transition:opacity .45s ease}
.lk-final{transition:opacity .9s ease}
.lk-say{background:linear-gradient(90deg,var(--mut,#8A94A6) 0%,var(--tx,#E6EAF2) 50%,var(--mut,#8A94A6) 100%);background-size:200% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;animation:lksh 1.4s linear infinite}
@keyframes lksh{from{background-position:150% 0}to{background-position:-100% 0}}
@keyframes lkpulse{50%{opacity:.25}}
@media (prefers-reduced-motion: reduce){.lk-shim,.lk-dot,.lk-say{animation:none}.lk-fade,.lk-final{transition:none}.lk-say{color:var(--tx,#E6EAF2);background:none}}
`;
export function injectLiveCss(doc = globalThis.document) {
  if (!doc || doc.getElementById('aihub-live-kit')) return;
  const s = doc.createElement('style');
  s.id = 'aihub-live-kit'; s.textContent = KIT_CSS;
  doc.head.appendChild(s);
}

// ---------- the pure parts (tested in utils/tests/web/live-kit.test.mjs) ----------

/** 6.5 → "7 s left", 65 → "1:05 left"; null for no estimate. */
export function fmtLeft(s) {
  if (s == null || !isFinite(s) || s < 0) return null;
  s = Math.ceil(s);
  return (s < 60 ? s + ' s' : Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0')) + ' left';
}

const STAGE_WORDS = { queued: 'Queued', loading: 'Loading', sampling: 'Making it', decoding: 'Decoding', encoding: 'Encoding',
  saving: 'Saving', waiting_gpu: 'Waiting for the GPU' };
export const stageWord = s => STAGE_WORDS[s] || (s ? s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ') : '');

/** What a box says before its first frame: the GPU queue (the call's note), queued or loading; null once frames flow. */
export function waitInfo(live, note, opts = {}) {
  const lv = live || {};
  if (note && /GPU/.test(note)) {
    const rest = note.replace(/^Waiting for the GPU:?\s*/, '');
    return { title: 'Waiting for the GPU', sub: rest || null };
  }
  if (lv.preview) return null;
  if (lv.stage === 'queued' || (!lv.stage && opts.queued)) return { title: 'Queued', sub: null };
  if (lv.stage === 'loading') return { title: opts.model ? `Loading ${opts.model}` : 'Loading the model', sub: fmtLeft(lv.eta_s) };
  if (lv.stage) return { title: stageWord(lv.stage), sub: fmtLeft(lv.eta_s) };
  return { title: opts.starting || 'Starting', sub: null };
}

/** "Step 3 of 8", else the stage's word. */
export function stepLabel(live) {
  const lv = live || {};
  if (lv.step != null && lv.steps) return `Step ${Math.min(lv.step, lv.steps)} of ${lv.steps}`;
  return stageWord(lv.stage);
}

/** The header's meta: "step 3/8 · 7 s left", "loading", "queued". */
export function metaText(live, status) {
  const lv = live || {};
  if (status === 'queued' || lv.stage === 'queued') return 'queued';
  const left = fmtLeft(lv.eta_s);
  const step = lv.step != null && lv.steps ? `step ${Math.min(lv.step, lv.steps)}/${lv.steps}` : lv.stage ? stageWord(lv.stage).toLowerCase() : '';
  return [step, left].filter(Boolean).join(' · ');
}

/** Stages as chips: [{id, label, mark, state, left}]. */
export function chipsOf(stages) {
  return (stages || []).map(s => ({ id: s.id, label: s.label || s.id, state: s.state,
    mark: s.state === 'done' ? '✓' : s.state === 'running' ? '●' : s.state === 'failed' ? '✕' : s.state === 'skipped' ? '–' : '○',
    left: s.state === 'running' ? fmtLeft(s.eta_s) : null }));
}

/** A preview frame's URL: the hub path with its seq, so a new frame is a new request. */
export function previewSrc(live) {
  const p = live && live.preview;
  if (!p || !p.url) return null;
  return p.url + (p.url.includes('?') ? '&' : '?') + 'seq=' + (p.seq || 0);
}

/** The box's aspect ratio (w / h): the preview's size, else the given fallback. */
export function aspectOf(live, fallback = 1) {
  const p = live && live.preview;
  return p && p.w > 0 && p.h > 0 ? p.w / p.h : fallback;
}

/** The next list of frames shown: the new src on top, at most two kept. */
export function nextFrames(frames, src) {
  if (!src || (frames.length && frames[frames.length - 1].src === src)) return frames;
  return [...frames.slice(-1), { src, key: src }];
}

// ---------- components ----------

const ICONS = {
  image: 'M3 5h18v14H3z M3 16l5-5 4 4 3-3 6 6',
  video: 'M3 6h13v12H3z M16 10l5-3v10l-5-3',
  model3d: 'M12 3l8 4.5v9L12 21l-8-4.5v-9z M12 12l8-4.5 M12 12v9 M12 12L4 7.5',
  audio: 'M4 10v4 M8 7v10 M12 4v16 M16 8v8 M20 11v2',
  job: 'M12 6v6l4 2 M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18z',
};
export function KitIcon({ name = 'job', size = 16, color = C.acc }) {
  return h('svg', { width: size, height: size, viewBox: '0 0 24 24', 'aria-hidden': 'true', style: { flex: 'none', color } },
    h('path', { d: ICONS[name] || ICONS.job, fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round', strokeLinejoin: 'round' }));
}

/** The card's frame. `pct` 0..1 draws the progress line; `done` turns it green and stops the dot. */
export function LiveCard({ icon, title, meta, pct, done, failed, children, foot, style }) {
  injectLiveCss();
  const bar = failed ? C.rd : done ? C.gr : C.acc;
  return h('div', { className: 'lk-card', style: { border: '1px solid ' + C.bd, background: C.card, borderRadius: 10, overflow: 'hidden', minWidth: 0, ...style } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', fontSize: 13, minWidth: 0 } },
      h(KitIcon, { name: icon }),
      h('span', { style: { fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } }, title),
      done || failed ? null : h('span', { className: 'lk-dot', 'aria-hidden': 'true' }),
      h('span', { style: { marginLeft: 'auto', color: C.mut, fontFamily: MONO, fontSize: 11.5, whiteSpace: 'nowrap' } }, meta || '')),
    children,
    h('div', { style: { height: 2, background: C.bd } },
      h('i', { style: { display: 'block', height: '100%', width: Math.round(Math.max(0, Math.min(1, done ? 1 : pct || 0)) * 1000) / 10 + '%', background: bar, transition: 'width .25s linear' } })),
    foot ? h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: '6px 10px', alignItems: 'center', padding: '9px 12px', fontSize: 12.5, color: C.mut, minHeight: 40 } }, foot) : null);
}

/** A box at `aspect` (w / h), at most `max` px tall and the column's width, centred. */
export function Stage({ aspect = 1, max = 420, children, style }) {
  return h('div', { style: { padding: '0 12px 10px' } },
    h('div', { style: { position: 'relative', overflow: 'hidden', background: C.inset, borderRadius: 6, margin: '0 auto',
      width: `min(100%, ${Math.round(max * aspect)}px)`, aspectRatio: String(aspect), ...style } }, children));
}

/** Shimmer and grain with a line of text in the middle; `quiet` keeps only a faint shimmer (frames are showing). */
export function Waiting({ title, sub, quiet }) {
  injectLiveCss();
  return h(R().Fragment, null,
    h('div', { className: 'lk-grain', style: { opacity: quiet ? 0 : 0.5 } }),
    h('div', { className: 'lk-shim', style: { opacity: quiet ? 0.35 : 1 } }),
    title && !quiet ? h('div', { role: 'status', style: { position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 4, padding: 16, textAlign: 'center' } },
      h('b', { style: { fontWeight: 500, fontSize: 13.5, color: C.tx } }, title),
      sub ? h('span', { style: { color: C.mut, fontSize: 12 } }, sub) : null) : null);
}

/** A small label over the box's top-left corner. */
export function Badge({ children }) {
  return h('div', { style: { position: 'absolute', top: 8, left: 8, padding: '2px 9px', borderRadius: 99, background: 'rgba(11,14,20,.72)', color: '#E6EAF2', fontFamily: MONO, fontSize: 11, backdropFilter: 'blur(6px)', zIndex: 5 } }, children);
}

/** Frames that fade in over the one before; `final` (the result) fades in over them all. */
export function PreviewLayers({ src, final, finalKind = 'image', fit = 'contain', alt = '' }) {
  const React = R(), [frames, setFrames] = React.useState([]), [shown, setShown] = React.useState({}), [finalOn, setFinalOn] = React.useState(false);
  React.useEffect(() => { setFrames(f => nextFrames(f, src)); }, [src]);
  const img = { position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: fit };
  return h(R().Fragment, null,
    frames.map((f, i) => h('img', { key: f.key, src: f.src, alt: '', className: 'lk-fade', onLoad: () => setShown(s => ({ ...s, [f.key]: true })),
      style: { ...img, zIndex: 1 + i, opacity: shown[f.key] ? 1 : 0, filter: 'saturate(.9)' } })),
    final ? (finalKind === 'video'
      ? h('video', { key: 'final', src: final, autoPlay: true, loop: true, muted: true, playsInline: true, className: 'lk-final', onLoadedData: () => setFinalOn(true), style: { ...img, zIndex: 4, opacity: finalOn ? 1 : 0, background: '#000' } })
      : h('img', { key: 'final', src: final, alt, className: 'lk-final', onLoad: () => setFinalOn(true), style: { ...img, zIndex: 4, opacity: finalOn ? 1 : 0 } })) : null);
}

/** ✓ Background · ● Shape · 42 s left · ○ Views */
export function StageChips({ stages }) {
  const tone = { done: C.gr, running: C.tx, failed: C.rd };
  return h('span', { style: { display: 'inline-flex', gap: 6, flexWrap: 'wrap' } },
    chipsOf(stages).map(c => h('span', { key: c.id, style: { display: 'inline-flex', gap: 5, alignItems: 'center', padding: '1px 8px', borderRadius: 99, fontSize: 11.5,
      border: '1px solid ' + (c.state === 'running' ? C.acc : C.bd), color: tone[c.state] || C.dim } }, c.mark + ' ' + c.label + (c.left ? ' · ' + c.left : ''))));
}

/** A small preview of a running job with its step, for lists (the Overview's Jobs, a mod page's runs). */
export function LiveThumb({ live, size = 44, href, title }) {
  injectLiveCss();
  const src = previewSrc(live), ar = aspectOf(live, 1);
  const w = ar >= 1 ? size : Math.round(size * ar), hgt = ar >= 1 ? Math.round(size / ar) : size;
  const box = h('span', { title: title || stepLabel(live), style: { position: 'relative', display: 'inline-block', width: w, height: hgt, borderRadius: 4, overflow: 'hidden', background: C.inset, flex: 'none', verticalAlign: 'middle' } },
    src ? h('img', { src, alt: '', style: { width: '100%', height: '100%', objectFit: 'cover', display: 'block' } }) : h('span', { className: 'lk-shim' }));
  return href ? h('a', { href, style: { display: 'inline-flex' } }, box) : box;
}

/** A live card for any job with live progress: the preview while it runs (used for tools without a card of their own). */
export function LivePreview({ live, note, title = 'Working', icon = 'image', status = 'running', pct }) {
  const wait = waitInfo(live, note);
  return h(LiveCard, { icon, title, meta: metaText(live, status), pct },
    h(Stage, { aspect: aspectOf(live, 1), max: 360 },
      h(PreviewLayers, { src: previewSrc(live) }),
      h(Waiting, { title: wait?.title, sub: wait?.sub, quiet: !wait }),
      live?.preview ? h(Badge, null, stepLabel(live)) : null));
}
