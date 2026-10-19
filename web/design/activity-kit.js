// Design study (not wired into the app): the shared pieces the activity options are built from.
// Everything here uses the real chat kit (chat-ui.js tokens, icons, buttons) and, where a piece
// already exists, the real card (user message, answer, result card, approval card).

import { h, T, MONO, Icon, Btn, Badge, cardSt, label11, COL } from '../chat/chat-ui.js';
import { Card, ProgressBar } from '../chat/chat-cards.js';
import '../chat/chat-forms.js';
import '../chat/chat-results.js';
import { renderMarkdown } from '../chat/chat-md.js';
import { fmtDur, FIELD, NAMES, SAMPLE_OUTPUTS } from './activity-model.js';

const R = () => globalThis.React;
export { h, T, MONO, Icon, Btn, Badge, cardSt, label11, COL, ProgressBar, R };

export const KIT_CSS = `
@keyframes dzspin{to{transform:rotate(360deg)}}
.dz-spin{display:inline-block;width:12px;height:12px;border-radius:99px;border:1.7px solid var(--bds);border-top-color:var(--acc);animation:dzspin .8s linear infinite;flex:none}
.dz-shim{background:linear-gradient(90deg,var(--mut) 0%,var(--mut) 38%,var(--tx) 50%,var(--mut) 62%,var(--mut) 100%);background-size:250% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;animation:dzshim 2.4s linear infinite}
@keyframes dzshim{from{background-position:100% 0}to{background-position:-150% 0}}
.dz-row{transition:background .1s}.dz-row:hover{background:var(--hov)}
.dz-link{color:var(--mut)}.dz-link:hover{color:var(--tx)}
.dz-peek{-webkit-mask-image:linear-gradient(to bottom,transparent 0,#000 55%);mask-image:linear-gradient(to bottom,transparent 0,#000 55%)}
.dz-chip:hover{border-color:var(--bdh)!important}
.dz-cap img{max-height:var(--dz-cap,300px)!important}
`;

// ---------- context for the real cards ----------
const STUB_API = {
  listOutputs: async () => ({ items: SAMPLE_OUTPUTS.map(o => ({ id: o.output_id, kind: o.kind, title: o.title, preview: o.preview })) }),
  getOutput: async () => { throw new Error('the design page has no 3D files'); },
};
export function ctxFor(o = {}) {
  return { api: STUB_API, live: false, tid: 'design', thread: null, outputs: o.outputs || [], tools: [], mods: ['comfy', 'gen3d'], showThinking: !!o.showThinking,
    running: !!o.running, answer: async () => {}, decide: async () => {}, cancel: () => {}, branch: null, copy: () => {}, openOutput: null,
    runAction: () => {}, runTool: async () => {}, closeTool: () => {} };
}
export const UserMsg = ({ turn, ctx }) => h(Card, { item: { key: 'u', kind: 'user', ev: turn.user }, ctx });
export const Answer = ({ turn, ctx }) => (turn.answer ? h(Card, { item: { key: 'a', kind: 'assistant', streaming: !!turn.answer.streaming, ev: { type: 'assistant', payload: { text: turn.answer.text } } }, ctx }) : null);
export const Outputs = ({ outputs, ctx }) => (outputs.length ? h(Card, { item: { key: 'r', kind: 'result', result: { outputs }, call: {} }, ctx }) : null);
export const Approval = ({ tool, ctx }) => h(Card, { item: { key: 'ap' + tool.id, kind: 'approval', call: tool.call, approval: tool.approval, decision: tool.decision, result: tool.result, progress: tool.progress }, ctx });

export function Md({ text, muted, size = 13, caret }) {
  const React = R(), html = React.useMemo(() => renderMarkdown(text || ''), [text]);
  return h('div', { className: 'aichat-md' + (caret ? ' aichat-caret' : ''), style: { fontSize: size, color: muted ? T.mut : T.tx }, dangerouslySetInnerHTML: { __html: html } });
}

// ---------- the chat column the options are drawn in ----------
export function Frame({ children, style }) {
  return h('div', { style: { background: T.bg, border: '1px solid ' + T.bd, borderRadius: 10, padding: '18px 16px', minWidth: 0, ...style } },
    h('div', { style: { maxWidth: COL, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 14, minWidth: 0 } }, children));
}

// ---------- status marks ----------
export function Mark({ status, size = 14 }) {
  if (status === 'running') return h('span', { className: 'dz-spin', style: { width: size - 2, height: size - 2 } });
  const m = { done: ['check', T.gr], error: ['x', T.rd], waiting: ['shield', T.pu], stopped: ['stop', T.dim], cancelled: ['stop', T.dim] }[status];
  if (m) return h('span', { style: { color: m[1], display: 'flex', flex: 'none' } }, h(Icon, { d: m[0], size, sw: 2.1 }));
  return h('span', { style: { width: size - 4, height: size - 4, margin: 2, borderRadius: 99, border: '1.5px solid ' + T.bdh, flex: 'none' } });
}
export const Shim = ({ children, style }) => h('span', { className: 'dz-shim', style: { fontWeight: 500, ...style } }, children);
export const Time = ({ s }) => (s == null ? null : h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.dim, flex: 'none' } }, fmtDur(s)));
export const Chev = ({ open, size = 12 }) => h('span', { style: { color: T.dim, display: 'flex', flex: 'none' } }, h(Icon, { d: open ? 'chevD' : 'chevR', size }));
const rowBtn = { display: 'flex', alignItems: 'center', gap: 8, width: '100%', minWidth: 0, padding: '4px 6px', margin: '0 -6px', border: 0, borderRadius: 6, background: 'none', color: T.tx, font: 'inherit', fontSize: 12.5, textAlign: 'left', cursor: 'pointer' };
export const ellip = { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 };

/** The live line: spinner, the shimmering words, percent, time. */
export function LiveLine({ status, elapsed, right }) {
  if (!status) return null;
  const pct = status.pct != null ? Math.round(status.pct * 100) + '%' : null;
  return h('div', { role: 'status', style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, minWidth: 0 } },
    status.tone === 'purple' ? h(Mark, { status: 'waiting' }) : h('span', { className: 'dz-spin' }),
    h(Shim, { style: status.tone === 'purple' ? { color: T.pu, background: 'none', animation: 'none', WebkitBackgroundClip: 'initial' } : null }, status.text + (status.tone === 'purple' ? '' : '…')),
    pct ? h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.acct } }, pct) : null,
    h('span', { style: { flex: 1 } }), h(Time, { s: elapsed }), right || null);
}

// ---------- a step's tool, as one row ----------
/** variant of the opened detail: 'list' (settings table) | 'sentence' | 'json' (today). */
export function ToolRow({ tool, turn, ctx, open, onToggle, variant = 'list', showBar = true, quietLookups = true, noMark }) {
  const quiet = tool.lookup && quietLookups, pct = tool.progress?.progress, pad = noMark ? 0 : 21;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 } },
    h('button', { type: 'button', className: 'dz-row', onClick: onToggle, 'aria-expanded': open ? 'true' : 'false', style: rowBtn },
      noMark ? null : h(Mark, { status: tool.status, size: 13 }),
      h('span', { style: { ...ellip, flex: 'none', maxWidth: '55%', fontWeight: quiet ? 400 : 500, color: quiet ? T.mut : T.tx } }, tool.label),
      tool.detail ? h('span', { style: { ...ellip, color: T.dim, fontSize: 12 } }, tool.detail) : null,
      h('span', { style: { flex: 1 } }),
      tool.status === 'running' && pct != null ? h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.acct } }, Math.round(pct * 100) + '%') : null,
      tool.status === 'waiting' ? h(Badge, { tone: 'purple' }, 'needs you') : h(Time, { s: tool.seconds }),
      h(Chev, { open })),
    showBar && tool.status === 'running' && !tool.lookup ? h('div', { style: { padding: `0 0 2px ${pad}px` } }, h(ProgressBar, { value: pct, note: tool.progress?.note })) : null,
    open ? h('div', { style: { padding: `2px 0 6px ${pad}px` } }, h(ToolDetail, { tool, turn, ctx, variant })) : null);
}

// ---------- what an opened step shows ----------
const json = v => { try { return JSON.stringify(typeof v === 'string' ? JSON.parse(v) : v, null, 2); } catch { return String(v); } };
const pre = t => h('pre', { style: { margin: 0, padding: '8px 10px', borderRadius: 6, background: T.inset, border: '1px solid ' + T.bd, fontFamily: MONO, fontSize: 11.5, lineHeight: 1.5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 220, overflow: 'auto' } }, t);
export function OutRef({ o }) {
  return h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 6, height: 22, padding: '0 7px 0 3px', borderRadius: 5, background: T.inset, border: '1px solid ' + T.bd, fontSize: 12, maxWidth: '100%', verticalAlign: 'middle' } },
    o.preview ? h('img', { src: o.preview, alt: '', style: { width: 16, height: 16, objectFit: 'cover', borderRadius: 3 } }) : null,
    h('span', { style: { fontFamily: MONO, fontSize: 11, color: T.pu, fontWeight: 600 } }, '#' + o.n), h('span', { style: ellip }, o.title));
}
function value(k, v, outputs) {
  if (typeof v === 'string' && v.startsWith('output:')) { const o = outputs.find(x => x.output_id === v.slice(7)); return o ? h(OutRef, { o }) : v; }
  if (Array.isArray(v)) return v.map(x => NAMES[x] || x).join(', ');
  if (k === 'aspect' && v === '1:1') return 'Square (1:1)';
  return NAMES[v] || String(v);
}
export function ToolDetail({ tool, turn, variant = 'list' }) {
  const React = R(), [raw, setRaw] = React.useState(false), a = tool.call.arguments || {}, r = tool.result, outs = turn?.outputs || [];
  if (variant === 'json') {
    return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } }, h('div', { style: label11 }, 'Arguments'), pre(json(a)),
      r ? h('div', { style: label11 }, 'Result') : null, r ? pre(json(r.content ?? r)) : null);
  }
  const result = r?.error ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 2, fontSize: 12.5 } },
    h('span', { style: { color: T.rd } }, r.error.detail), r.error.fix ? h('span', { style: { color: T.mut, fontSize: 12 } }, r.error.fix) : null)
    : tool.outputs?.length ? h('span', { style: { display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' } }, tool.outputs.map(o => h(OutRef, { key: o.n, o })),
      tool.seconds != null ? h('span', { style: { color: T.dim, fontSize: 12 } }, 'in ' + fmtDur(tool.seconds)) : null)
      : r ? h('span', { style: { color: T.mut, fontSize: 12.5 } }, 'Done') : tool.status === 'waiting' ? h('span', { style: { color: T.pu, fontSize: 12.5 } }, 'Waiting for you to approve') : h('span', { style: { color: T.mut, fontSize: 12.5 } }, 'Running…');
  const rawLink = h('button', { type: 'button', className: 'dz-link', onClick: () => setRaw(!raw), style: { alignSelf: 'flex-start', border: 0, background: 'none', padding: 0, font: 'inherit', fontSize: 11.5, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4 } },
    h(Icon, { d: raw ? 'chevD' : 'chevR', size: 11 }), raw ? 'Hide raw call' : 'Raw call');
  const rawBox = raw ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } }, h('span', { style: { fontFamily: MONO, fontSize: 11, color: T.dim } }, tool.call.name), pre(json(a)), r ? pre(json(r.content ?? r)) : null) : null;
  if (variant === 'sentence') {
    const s = sentence(tool, outs);
    return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12.5, minWidth: 0 } },
      h('div', { style: { color: T.tx } }, s),
      a.prompt ? h('div', { style: { padding: '2px 10px', borderLeft: '2px solid ' + T.bds, color: T.mut } }, a.prompt) : null,
      h('div', null, result), rawLink, rawBox);
  }
  const rows = Object.entries(a).filter(([, v]) => v != null && v !== '');
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 } },
    h('div', { style: { display: 'grid', gridTemplateColumns: 'minmax(64px, max-content) 1fr', gap: '5px 14px', fontSize: 12.5, alignItems: 'baseline' } },
      rows.flatMap(([k, v]) => [h('span', { key: k + 'k', style: { color: T.mut, fontSize: 12 } }, FIELD[k] || k), h('span', { key: k + 'v', style: { minWidth: 0, overflowWrap: 'anywhere' } }, value(k, v, outs))]),
      h('span', { style: { color: T.mut, fontSize: 12 } }, 'Result'), h('div', { style: { minWidth: 0 } }, result)),
    rawLink, rawBox);
}
function sentence(tool, outs) {
  const a = tool.call.arguments || {}, b = t => h('strong', { style: { fontWeight: 600 } }, t);
  if (tool.call.name === 'comfy_generate_image') return h('span', null, 'Generated with ', b(NAMES[a.workflow] || a.workflow), a.aspect === '1:1' ? ', square' : a.aspect ? `, ${a.aspect}` : '', a.seed ? `, seed ${a.seed}` : '', ', from this prompt:');
  if (tool.call.name === 'gen3d_make_3d') {
    const o = outs.find(x => 'output:' + x.output_id === a.image);
    return h('span', null, 'Made from ', o ? h(OutRef, { o }) : 'a picture', ' with ', b(NAMES[a.engine] || a.engine), a.preset ? `, ${a.preset} preset` : '', a.stages ? ` (${a.stages.join(', ')})` : '', '.');
  }
  return h('span', null, tool.label, tool.detail ? ': ' + tool.detail : '');
}

// ---------- thinking, as a row ----------
export function ThinkRow({ thinking, open, onToggle, peek, noIcon }) {
  if (!thinking) return null;
  const live = thinking.streaming;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 } },
    h('button', { type: 'button', className: 'dz-row', onClick: onToggle, style: { ...rowBtn, color: T.mut } },
      noIcon ? null : h('span', { style: { display: 'flex', color: T.dim, flex: 'none' } }, h(Icon, { d: 'bulb', size: 13, style: live ? { animation: 'aichatpulse 1.2s ease-in-out infinite' } : null })),
      live ? h(Shim, null, 'Thinking…') : h('span', null, `Thought for ${fmtDur(thinking.seconds)}`), h('span', { style: { flex: 1 } }), h(Chev, { open })),
    open ? h('div', { style: { margin: `0 0 4px ${noIcon ? 0 : 21}px`, padding: '2px 10px', borderLeft: '2px solid ' + T.bds } }, h(Md, { text: thinking.text, muted: true, size: 12.5, caret: live }))
      : peek && live ? h('div', { className: 'dz-peek', style: { margin: '0 0 2px 21px', maxHeight: 54, overflow: 'hidden', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', color: T.dim, fontSize: 12, lineHeight: 1.5 } }, thinking.text + '…') : null);
}

// ---------- a compact output tile (thumbnail, #n, title, two actions) ----------
export function OutputTile({ o, size = 132 }) {
  return h('div', { style: { ...cardSt({ pad: 6, gap: 6 }), width: size + 14, flex: 'none' } },
    h('div', { style: { position: 'relative' } },
      h('img', { src: o.preview, alt: o.title, style: { display: 'block', width: size, height: size, objectFit: 'contain', borderRadius: 5, background: T.inset } }),
      o.kind === 'model3d' ? h('span', { style: { position: 'absolute', top: 5, left: 5 } }, h(Badge, { tone: 'purple' }, '3D')) : null),
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 5, minWidth: 0 } },
      h('span', { style: { fontFamily: MONO, fontSize: 11, fontWeight: 600, padding: '0 5px', borderRadius: 4, background: T.tpu, color: T.pu, flex: 'none' } }, '#' + o.n),
      h('span', { title: o.title, style: { ...ellip, fontSize: 12 } }, o.title)),
    h('div', { style: { display: 'flex', gap: 4 } },
      h(Btn, { sm: true, kind: 'ghost', icon: o.kind === 'model3d' ? 'cube' : 'ext', title: o.kind === 'model3d' ? 'View in 3D' : 'Open', style: { height: 22, width: 22 } }),
      h(Btn, { sm: true, kind: 'ghost', icon: 'download', title: 'Download', style: { height: 22, width: 22 } }),
      h(Btn, { sm: true, kind: 'ghost', icon: 'more', title: 'More: edit, animate, make 3D…', style: { height: 22, width: 22 } })));
}

/** One open-at-a-time set of toggles keyed by id; `init` is the open id (or a Set for many). */
export function useOpen(init = null) {
  const React = R(), [s, set] = React.useState(() => new Set(init == null ? [] : [].concat(init)));
  return [id => s.has(id), id => set(x => { const n = new Set(x); if (n.has(id)) n.delete(id); else n.add(id); return n; })];
}
