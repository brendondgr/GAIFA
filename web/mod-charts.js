// Charts for mod page modules (design brief §5, Part B): the §11.6 chart components are React,
// and page modules build plain DOM, so these helpers mount a chart into a DOM element.
// Written by us, not Claude Design. Import from a page module as '/mod-charts.js'.
//
//   const card = chartCard({ title: 'Clips per day', ranges: ['7d', '30d'],
//     load: range => ctx.call('GET', '/v1/hub/widgets/clips', { query: { range } }).then(r => r.json),
//     draw: (data, o) => charts.BarChart({ categories: data.categories, series: …, stacked: true, ...o }) });
//   el.append(card);  …  card.unmount() in the page's cleanup.

import { h } from './chart-kit.js';
import * as charts from './charts.js';
import { Card, useData, chartState, Frame } from './views.js';

export { charts };
/** rh(Component, props): a React element. Draw charts with it (rh(charts.BarChart, {...})), never by
 *  calling a component as a function, which breaks its hooks. */
export const rh = (C, p, ...kids) => h(C, p, ...kids);
const R = () => globalThis.React;

/** mountReact(el, element): render a React element into a DOM element; returns { render, unmount }. */
export function mountReact(el, element) {
  const root = globalThis.ReactDOM.createRoot(el);
  root.render(element);
  return { render: e => root.render(e), unmount: () => setTimeout(() => root.unmount(), 0) };
}

function ChartCard({ title, ranges, def, load, draw, every = 0, height = 150, extra, deps = [] }) {
  const React = R();
  const [range, setRange] = React.useState(def || (ranges && ranges[0]) || null);
  const [table, setTable] = React.useState(false);
  const d = useData(() => load(range), [range, ...deps], every);
  const body = d.state === 'ok'
    ? draw(d.data, { table, height, range, label: title })
    : h(Frame, { ...chartState(d), height });
  return h(Card, { title, ranges, range, onRange: setRange, table, onTable: setTable, extra }, body);
}

/** chartCard({ title, ranges?, def?, load(range) → Promise<data>, draw(data, {table, height, range, label}) → React element,
 *  every? (poll ms), height?, deps? }) → a DOM element with .unmount() and .refresh(). */
export function chartCard(o) {
  const el = document.createElement('div');
  el.style.minWidth = '0';
  let n = 0;
  const m = mountReact(el, h(ChartCard, { ...o, deps: [0] }));
  el.refresh = () => m.render(h(ChartCard, { ...o, deps: [++n] }));
  el.unmount = m.unmount;
  return el;
}

/** chart(Component, props) → a DOM element with .update(props) and .unmount(), for charts without a card. */
export function chart(Component, props) {
  const el = document.createElement('div');
  el.style.minWidth = '0';
  const m = mountReact(el, h(Component, props));
  el.update = p => m.render(h(Component, p));
  el.unmount = m.unmount;
  return el;
}

/** waveform(samples Float32Array|number[], { height, progress (0–1), color }) → an SVG element (plain DOM). */
export function waveform(samples, o = {}) {
  const W = 600, H = o.height || 48, n = 120, step = Math.max(1, Math.floor(samples.length / n));
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('aria-hidden', 'true');
  svg.style.cssText = `width:100%;height:${H}px;display:block`;
  const bars = [];
  let peak = 1e-6;
  const lv = [];
  for (let i = 0; i < n; i++) {
    let m = 0;
    for (let j = i * step; j < Math.min(samples.length, (i + 1) * step); j++) m = Math.max(m, Math.abs(samples[j]));
    lv.push(m); peak = Math.max(peak, m);
  }
  lv.forEach((v, i) => {
    const bh = Math.max(2, (v / peak) * (H - 4)), r = document.createElementNS(ns, 'rect');
    r.setAttribute('x', String(i * (W / n) + 1)); r.setAttribute('width', String(W / n - 2));
    r.setAttribute('y', String((H - bh) / 2)); r.setAttribute('height', String(bh)); r.setAttribute('rx', '1.5');
    svg.append(r); bars.push(r);
  });
  svg.setProgress = p => bars.forEach((r, i) => r.setAttribute('fill', i / n <= p ? (o.color || 'var(--acc,#FFB224)') : 'var(--bds,#2A3547)'));
  svg.setProgress(o.progress || 0);
  return svg;
}

/** pcm16 → Float32 samples from a WAV ArrayBuffer (mono, 16-bit), for waveform(). */
export function wavSamples(buf) {
  const v = new DataView(buf);
  let off = 12;
  while (off + 8 <= v.byteLength) {
    const id = String.fromCharCode(v.getUint8(off), v.getUint8(off + 1), v.getUint8(off + 2), v.getUint8(off + 3)), size = v.getUint32(off + 4, true);
    if (id === 'data') {
      const n = Math.floor(Math.min(size, v.byteLength - off - 8) / 2), out = new Float32Array(n);
      for (let i = 0; i < n; i++) out[i] = v.getInt16(off + 8 + i * 2, true) / 32768;
      return out;
    }
    off += 8 + size + (size % 2);
  }
  return new Float32Array(0);
}
