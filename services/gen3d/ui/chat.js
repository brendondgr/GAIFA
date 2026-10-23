// 3D Generate in Chat (plan 45.3): the live card for gen3d_make_3d, after the prototype the user approved
// (docs/reference/live-cards-2026-10/). From a picture: a scan line turns the picture into its cut-out, then a
// point cloud built from the cut-out's outline turns slowly while the shape is made ("Shape · n%": the cloud is
// decoration, gen3d sends no geometry until the end), then the rendered views, then View in 3D. From text: the
// stages and their time left. The stages show as chips under the box. Loaded from `[ui] chat` (plan 44.1).

const SCAN_MS = 2600;

/** Points from a cut-out's alpha: [x, y, z, lightness] in about -1..1, front and back of each row's span.
 *  `data` is RGBA bytes of a w × h image; `rand` a 0..1 generator (tests pass a fixed one). */
export function pointsFromAlpha(data, w, h, rand = Math.random, keep = 0.5, max = 6000) {
  const rows = [];
  for (let y = 0; y < h; y++) {
    let a = -1, b = -1;
    for (let x = 0; x < w; x++) if (data[(y * w + x) * 4 + 3] > 128) { if (a < 0) a = x; b = x; }
    if (a >= 0) rows.push([y, a, b]);
  }
  if (!rows.length) return [];
  const cy = (rows[0][0] + rows[rows.length - 1][0]) / 2, scale = Math.max(w, h) / 2, pts = [];
  for (const [y, a, b] of rows) {
    const c = (a + b) / 2, half = Math.max(1, (b - a) / 2);
    for (let x = a; x <= b; x++) {
      const i = (y * w + x) * 4;
      if (data[i + 3] <= 128 || rand() > keep) continue;
      const t = (x - c) / half, d = Math.sqrt(Math.max(0, 1 - t * t)) * half * 0.8;
      const l = (data[i] * 0.3 + data[i + 1] * 0.59 + data[i + 2] * 0.11) / 255;
      pts.push([(x - w / 2) / scale, (y - cy) / scale, d / scale, l]);
      if (rand() < 0.6) pts.push([(x - w / 2) / scale, (y - cy) / scale, -d / scale, l]);
    }
  }
  for (let i = pts.length - 1; i > 0; i--) { const j = Math.floor(rand() * (i + 1)); [pts[i], pts[j]] = [pts[j], pts[i]]; }
  return pts.slice(0, max);
}

/** Which picture the card shows: 'wait' (nothing yet), 'cutout' (the shape is being made from it), 'views'. */
export function phaseOf(live, status) {
  if (status === 'done') return 'done';
  const url = live?.preview?.url || '';
  if (/(preview|views)\.png(\?|$)/.test(url)) return 'views';
  if (/input_rgba\.png(\?|$)/.test(url)) return 'cutout';
  return 'wait';
}

export default function setup(chat) {
  const { h } = chat.ui, kit = chat.live, { ActionBar, nameOf, Model3DPreview } = chat.parts || {};
  const R = () => globalThis.React;
  const fill = { position: 'absolute', inset: 0, width: '100%', height: '100%' };
  const reduce = () => !!globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

  function Cloud({ src, frac, fade }) {
    const React = R(), ref = React.useRef(null), fracRef = React.useRef(frac);
    fracRef.current = frac;
    React.useEffect(() => {
      let alive = true, raf = 0, pts = null;
      const img = new Image();
      img.onload = () => {
        const w = 160, hh = Math.max(1, Math.round(160 * img.naturalHeight / img.naturalWidth));
        const c = document.createElement('canvas'); c.width = w; c.height = hh;
        const x = c.getContext('2d'); x.drawImage(img, 0, 0, w, hh);
        try { pts = pointsFromAlpha(x.getImageData(0, 0, w, hh).data, w, hh); } catch { pts = []; }
      };
      img.src = src;
      const t0 = performance.now(), still = reduce();
      const draw = now => {
        if (!alive) return;
        const cv = ref.current;
        if (cv && pts && pts.length) {
          const ctx = cv.getContext('2d'), W = cv.width, H = cv.height, S = Math.min(W, H) * 0.47;
          const a = still ? 0.35 : Math.sin((now - t0) / 1000 * 0.7) * 1.1, ca = Math.cos(a), sa = Math.sin(a);
          const n = Math.floor(pts.length * Math.min(1, 0.06 + 0.94 * (fracRef.current || 0)));
          const view = [];
          for (let i = 0; i < n; i++) { const p = pts[i]; view.push([p[0] * ca + p[2] * sa, p[1], -p[0] * sa + p[2] * ca, p[3]]); }
          view.sort((u, v) => u[2] - v[2]);
          ctx.clearRect(0, 0, W, H);
          for (const [px, py, pz, l] of view) {
            const d = 0.55 + 0.45 * (pz + 1) / 2, g = Math.round(110 + 140 * l * d);
            ctx.fillStyle = `rgba(${Math.round(g * 0.78)},${Math.round(g * 0.95)},${g},${0.35 + 0.55 * d})`;
            ctx.fillRect(W / 2 + px * S, H / 2 + py * S, 2.2, 2.2);
          }
        }
        raf = requestAnimationFrame(draw);
      };
      raf = requestAnimationFrame(draw);
      return () => { alive = false; cancelAnimationFrame(raf); };
    }, [src]);
    return h('canvas', { ref, width: 800, height: 600, className: 'lk-fade', style: { ...fill, opacity: fade ? 0 : 1 } });
  }

  function Scan({ input, cutout }) {
    const React = R(), [x, setX] = React.useState(0);
    React.useEffect(() => {
      if (reduce()) { setX(1); return undefined; }
      let raf = 0; const t0 = performance.now();
      const step = now => { const f = Math.min(1, (now - t0) / SCAN_MS); setX(f); if (f < 1) raf = requestAnimationFrame(step); };
      raf = requestAnimationFrame(step);
      return () => cancelAnimationFrame(raf);
    }, []);
    return h(R().Fragment, null,
      h('img', { src: input, alt: '', style: { ...fill, objectFit: 'contain' } }),
      h('div', { style: { ...fill, clipPath: `inset(0 ${100 - x * 100}% 0 0)`, background: 'repeating-conic-gradient(#1a2130 0 25%,#151b27 0 50%) 0 0/18px 18px' } },
        h('img', { src: cutout, alt: '', style: { ...fill, objectFit: 'contain' } })),
      x < 1 ? h('div', { style: { position: 'absolute', top: 0, bottom: 0, left: x * 100 + '%', width: 2, background: 'var(--cy,#58C4DD)', boxShadow: '0 0 12px var(--cy,#58C4DD)' } }) : null);
  }

  function ModelCard({ ctx }) {
    const React = R(), { row, live, note, status, outputs } = ctx.liveCard;
    const args = row.item.call?.arguments || {}, out = outputs[0];
    const done = status === 'done', failed = status === 'failed' || status === 'error';
    const [scanned, setScanned] = React.useState(false), [viewer, setViewer] = React.useState(false);
    const phase = phaseOf(live, status);
    React.useEffect(() => {
      if (phase !== 'cutout' || scanned) return undefined;
      const t = setTimeout(() => setScanned(true), reduce() ? 0 : SCAN_MS + 200);
      return () => clearTimeout(t);
    }, [phase]);
    const engine = args.engine && nameOf ? nameOf(args.engine, { tool: row.name, key: 'engine', ctx }) : null;
    const url = live?.preview?.url || '';
    const cut = phase === 'cutout' ? kit.previewSrc(live) : null;
    const input = cut ? url.replace(/input_rgba\.png$/, 'input.png') : null;
    const shape = (live?.stages || []).find(s => s.id === 'shape');
    const frac = live?.stage === 'shape' && live.steps ? live.step / live.steps : shape?.state === 'done' ? 1 : 0;
    const secs = row.seconds == null ? '' : row.seconds < 60 ? Math.round(row.seconds) + ' s' : Math.floor(row.seconds / 60) + 'm ' + Math.round(row.seconds % 60) + 's';
    const title = done ? 'Made a 3D model' : failed ? "Couldn't make the 3D model" : 'Making a 3D model';
    const meta = done || failed ? secs : [engine, kit.fmtLeft(live?.eta_s)].filter(Boolean).join(' · ');
    const wait = phase === 'wait' && !done && !failed ? kit.waitInfo(live, note, { starting: args.image ? 'Reading the picture' : 'Starting the engine' }) : null;
    let badge = null;
    if (!done && !failed && phase === 'cutout') badge = !scanned ? 'Removing the background' : live?.stage === 'preview' ? 'Rendering views' : `Shape · ${Math.round(frac * 100)}%`;
    if (!done && !failed && phase === 'views') badge = 'Views';
    let body;
    if (done && viewer && Model3DPreview && out) body = h('div', { style: { padding: '0 12px 10px' } }, h(Model3DPreview, { output: out, ctx, autoOpen: true }));
    else body = h(kit.Stage, { aspect: 4 / 3 },
      phase === 'cutout' && input ? h(Scan, { input, cutout: cut }) : null,
      phase === 'cutout' && scanned ? h('div', { style: { ...fill, background: 'var(--inset,#131926)' } }) : null,
      phase === 'cutout' && scanned ? h(Cloud, { src: cut, frac, fade: live?.stage === 'preview' }) : null,
      phase === 'cutout' && scanned ? h('img', { src: cut, alt: '', style: { position: 'absolute', left: 10, bottom: 10, width: '22%', borderRadius: 6, border: '1px solid var(--bd,#1D2430)', background: 'var(--card,#11151D)', zIndex: 3 } }) : null,
      h(kit.PreviewLayers, { src: phase === 'views' ? kit.previewSrc(live) : null, final: done ? (out?.preview || null) : null, alt: out?.title || '' }),
      wait ? h(kit.Waiting, { title: wait.title, sub: wait.sub }) : null,
      badge ? h(kit.Badge, null, badge) : null,
      done && out && Model3DPreview && ctx.live ? h('span', { style: { position: 'absolute', right: 8, bottom: 8, zIndex: 6 } },
        h('button', { type: 'button', onClick: () => setViewer(true), style: { border: 0, borderRadius: 6, padding: '4px 10px', background: 'var(--acc,#FFB224)', color: '#1A1200', fontWeight: 600, fontSize: 12, cursor: 'pointer' } }, 'View in 3D')) : null);
    const foot = done && out ? [
      h('span', { key: 'n', style: { fontFamily: kit.MONO, fontSize: 11, fontWeight: 600, color: 'var(--pu,#BC8CFF)' } }, out.n ? '#' + out.n : 'output'),
      h('span', { key: 't', style: { color: 'var(--tx,#E6EAF2)', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '50%' } }, out.title || ''),
      ActionBar ? h('span', { key: 'a', style: { marginLeft: 'auto' } }, h(ActionBar, { output: out, ctx })) : null,
    ] : live?.stages?.length ? h(kit.StageChips, { stages: live.stages }) : null;
    return h(kit.LiveCard, { icon: 'model3d', title, meta, pct: row.progress?.progress, done, failed, foot }, body);
  }

  chat.registerCard('live:gen3d_make_3d', ({ ctx }) => h(ModelCard, { ctx }));
}
