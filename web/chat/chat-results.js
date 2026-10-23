// The result card (plan 14.1, 14.8): a tool's outputs with their `#n` reference, a preview by kind,
// and the action buttons from the actions registry (chat-actions.js). Previews are a registry too:
//
//   registerPreview('pointcloud', ({ output, ctx }) => h(MyViewer, { src: output.url }));
//
// Built in: image, video, audio, model3d (preview image, then the three.js viewer on demand).

import { h, T, MONO, Icon, Btn, Badge, cardSt } from './chat-ui.js';
import { registerCard, hasCard, Card, Thumbs } from './chat-cards.js';
import { actionsFor } from './chat-actions.js';
import { shownLive } from './chat-live.js';

const R = () => globalThis.React;
const previews = new Map();
export function registerPreview(kind, Component) { previews.set(kind, Component); return () => previews.delete(kind); }

// A media stage: full column width, at most 420 px tall, the picture contained (works for files without intrinsic size too).
const media = { display: 'block', width: '100%', maxHeight: 420, borderRadius: 6, background: T.inset };
const KIND_LABEL = { image: 'image', video: 'video', audio: 'audio', model3d: '3D model', text: 'text' };

function ImagePreview({ output, ctx, cap }) {
  const src = output.url || output.preview;
  if (!src) return h(NoPreview, { output });
  return h('button', { type: 'button', onClick: () => ctx.openOutput?.(output.output_id), title: 'Open in Outputs', style: { display: 'block', width: '100%', padding: 0, border: 0, background: 'none', cursor: 'zoom-in' } },
    h('img', { src, alt: output.title || 'image', loading: 'lazy', style: { ...media, height: 'auto', objectFit: 'contain', ...(cap ? { maxHeight: cap } : null) } }));
}
function VideoPreview({ output, cap }) {
  if (!output.url) {
    return h('div', { style: { position: 'relative' } },
      output.preview ? h('img', { src: output.preview, alt: '', style: { ...media, height: 'auto', maxHeight: 360, objectFit: 'contain' } }) : h(NoPreview, { output }),
      h('span', { style: { position: 'absolute', left: 8, bottom: 8, padding: '2px 8px', borderRadius: 99, fontSize: 11.5, background: T.card, color: T.mut } }, 'No video stream in the mock'));
  }
  return h('video', { src: output.url, poster: output.preview || undefined, controls: true, preload: 'metadata', style: { ...media, width: '100%', background: '#000', ...(cap ? { maxHeight: cap } : null) } });
}
function AudioPreview({ output }) {
  return output.url ? h('audio', { src: output.url, controls: true, preload: 'metadata', style: { width: '100%', height: 36 } }) : h(NoPreview, { output });
}
export function Model3DPreview({ output, ctx, cap, autoOpen }) {
  const React = R(), ref = React.useRef(null), [state, setState] = React.useState('poster'), [err, setErr] = React.useState(null);
  const open = async () => {
    setState('loading'); setErr(null);
    try {
      const [{ mountViewer }, o] = await Promise.all([import('../viewer3d.js'), ctx.api.getOutput(output.output_id)]);
      const glbs = (o.files || []).map(f => f.path.slice(o.path.length + 1)).filter(p => /^[^/]+\.(glb|gltf)$/i.test(p));
      const order = ['rigged.glb', 'parts.glb', 'mesh.glb'];
      glbs.sort((a, b) => (order.indexOf(a) + 1 || 9) - (order.indexOf(b) + 1 || 9));
      if (!glbs.length) throw new Error('this output has no GLB files');
      setState('viewer');
      await mountViewer(ref.current, { files: glbs, height: 380, url: async f => `/api/outputs/${encodeURIComponent(o.id)}/files/${f.split('/').map(encodeURIComponent).join('/')}` });
    } catch (e) { setErr(e.detail || e.message || String(e)); setState('poster'); }
  };
  React.useEffect(() => { if (autoOpen && ctx.live) open(); }, []);   // a live card's View in 3D (plan 45.3)
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 } },
    h('div', { ref, style: { display: state === 'viewer' ? 'block' : 'none' } }),
    state !== 'viewer' ? h('div', { style: { position: 'relative' } },
      output.preview ? h('img', { src: output.preview, alt: output.title || '3D model', style: { ...media, height: 'auto', maxHeight: cap || 360, objectFit: 'contain' } }) : h(NoPreview, { output }),
      h('span', { style: { position: 'absolute', top: 8, left: 8 } }, h(Badge, { tone: 'purple' }, '3D')),
      h('span', { style: { position: 'absolute', right: 8, bottom: 8 } }, h(Btn, { sm: true, icon: 'cube', label: state === 'loading' ? 'Loading…' : 'View in 3D', disabled: state === 'loading' || !ctx.live,
        title: ctx.live ? 'Orbit, see parts and pose the rig' : 'The 3D viewer needs the live hub (the mock has no GLB files)', onClick: open }))) : null,
    err ? h('div', { style: { fontSize: 12, color: T.rd } }, err) : null);
}
function NoPreview({ output }) {
  return h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '14px 12px', borderRadius: 6, background: T.inset, color: T.mut, fontSize: 12.5 } },
    h(Icon, { d: 'clip', size: 14 }), output.summary || output.title || output.kind);
}
registerPreview('image', ImagePreview);
registerPreview('video', VideoPreview);
registerPreview('audio', AudioPreview);
registerPreview('model3d', Model3DPreview);

/** The buttons for one output: registered actions for its kind plus the ones derived from the catalog. */
export function ActionBar({ output, ctx }) {
  const list = actionsFor(output.kind, { tools: ctx.tools, output });
  if (!list.length) return null;
  return h('div', { role: 'group', 'aria-label': 'Next steps', style: { display: 'flex', flexWrap: 'wrap', gap: 6 } },
    list.map(a => h(Btn, { key: a.id, sm: true, icon: a.icon || (a.tool ? 'tool' : 'chat'), label: a.label, disabled: ctx.busyAction,
      title: a.tool ? `Opens ${a.tool} with this ${KIND_LABEL[output.kind] || 'output'} filled in` : a.prompt ? `Asks the agent: “${a.prompt(output)}”` : a.label,
      onClick: () => ctx.runAction(a, output) })));
}

function OutputBlock({ output, ctx, cap }) {
  const P = previews.get(output.kind) || NoPreview;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 } },
      h('span', { title: `Refer to it as #${output.n}`, style: { fontFamily: MONO, fontSize: 11.5, fontWeight: 600, padding: '1px 6px', borderRadius: 4, background: T.tpu, color: T.pu, flex: 'none' } }, '#' + output.n),
      h('span', { title: output.title, style: { fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 } }, output.title || output.summary || output.kind),
      h(Badge, null, KIND_LABEL[output.kind] || output.kind),
      h('span', { style: { flex: 1 } }),
      h(Thumbs, { ctx, target: { output_id: output.output_id }, label: 'this result' }),
      ctx.openOutput ? h(Btn, { kind: 'ghost', sm: true, icon: 'ext', title: 'Open in Outputs', onClick: () => ctx.openOutput(output.output_id) }) : null,
      output.url && ctx.live ? h('a', { href: output.url, download: '', title: 'Download', 'aria-label': 'Download', style: { display: 'grid', placeItems: 'center', width: 26, height: 26, borderRadius: 6, color: T.mut } }, h(Icon, { d: 'download', size: 13 })) : null),
    h(P, { output, ctx, cap }),
    output.prompt ? h('div', { title: output.prompt, style: { fontSize: 12, color: T.mut, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, output.prompt) : null,
    h(ActionBar, { output, ctx }));
}

function ResultCard({ item, ctx }) {
  const outs = item.result.outputs || [];
  return h('div', { style: cardSt({ pad: '10px 12px', gap: 14 }) }, outs.map(o => h(OutputBlock, { key: o.output_id + ':' + o.n, output: o, ctx })));
}
registerCard('result', ResultCard);

// ---------- the output strip (plan 19.5): a turn's outputs under its activity fold ----------
export const STRIP_CAP = 300;   // the big preview's height cap, px
/** Which output the strip shows big: the picked one, or the newest. */
export function shownOutput(outputs, picked) {
  return (outputs || []).find(o => o.output_id + ':' + o.n === picked) || (outputs || [])[(outputs || []).length - 1] || null;
}
function Thumb({ o, on, onPick }) {
  return h('button', { type: 'button', onClick: onPick, 'aria-pressed': on ? 'true' : 'false', title: `#${o.n} ${o.title || ''}`,
    style: { position: 'relative', flex: 'none', padding: 0, borderRadius: 7, border: '2px solid ' + (on ? T.cy : 'transparent'), background: 'none', cursor: 'pointer' } },
  o.preview || (o.kind === 'image' && o.url) ? h('img', { src: o.preview || o.url, alt: o.title || o.kind, style: { display: 'block', width: 56, height: 56, objectFit: 'cover', borderRadius: 5, background: T.inset } })
    : h('span', { style: { display: 'grid', placeItems: 'center', width: 56, height: 56, borderRadius: 5, background: T.inset, color: T.mut } }, h(Icon, { d: { audio: 'wave', video: 'video', model3d: 'cube' }[o.kind] || 'clip', size: 18 })),
  h('span', { style: { position: 'absolute', left: 3, bottom: 3, fontFamily: MONO, fontSize: 10, fontWeight: 600, padding: '0 4px', borderRadius: 3, background: T.card, color: T.pu } }, '#' + o.n));
}
/** Thumbnails when there's more than one output, the picked one (by default the newest) as the result card, its preview capped. */
export function OutputStrip({ outputs: all, ctx }) {
  const React = R(), [picked, setPicked] = React.useState(null);
  const outputs = all.filter(o => !shownLive(o));    // plan 44.3: a tool's live card shows its own outputs
  const big = shownOutput(outputs, picked);
  if (!big) return null;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 } },
    outputs.length > 1 ? h('div', { role: 'group', 'aria-label': 'Outputs of this turn', style: { display: 'flex', gap: 6, flexWrap: 'wrap' } },
      outputs.map(o => h(Thumb, { key: o.output_id + ':' + o.n, o, on: o === big, onPick: () => setPicked(o.output_id + ':' + o.n) }))) : null,
    big.tool && hasCard('result:' + big.tool)          // a tool's own result card (the card registry) still wins
      ? h(Card, { key: big.output_id + ':' + big.n, item: { key: 'r' + big.output_id, kind: 'result', result: { name: big.tool, outputs: [big] }, call: { name: big.tool } }, ctx })
      : h('div', { style: cardSt({ pad: '10px 12px', gap: 14 }) }, h(OutputBlock, { key: big.output_id + ':' + big.n, output: big, ctx, cap: STRIP_CAP })));
}
