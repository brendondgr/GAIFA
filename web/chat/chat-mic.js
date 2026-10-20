// Dictation into the composer (plan 29.3): the microphone → an AudioWorklet that resamples to
// 16 kHz mono → int16 frames over the stt mod's `WS /v1/stream` (through the hub's proxy) → the
// committed text plus the live tail, written into the draft. The button shows only while the stt
// mod is up, so deleting services/stt removes it. Click to toggle; press and hold to talk.
// The pure parts (Resampler, toInt16, startMessage, reduce, dictated) are unit-tested in
// utils/tests/web/chat-mic.test.mjs.

import { h, T, Btn } from './chat-ui.js';

const R = () => globalThis.React;
export const RATE = 16000;
export const HOLD_MS = 400;           // pressed longer than this: releasing stops (push to talk)

/** Streaming resampler to 16 kHz: a box filter as wide as the decimation step (against aliasing),
 * then linear interpolation. Keeps its position between chunks, so chunked output equals whole. */
export class Resampler {
  constructor(from, to = 16000) {
    this.ratio = from / to;
    this.w = Math.max(1, Math.round(this.ratio));
    this.pos = 0;
    this.buf = new Float32Array(0);
  }

  push(input) {
    const all = new Float32Array(this.buf.length + input.length);
    all.set(this.buf);
    all.set(input, this.buf.length);
    const w = this.w, out = [];
    while (Math.floor(this.pos) + w <= all.length - 1) {
      const i = Math.floor(this.pos), f = this.pos - i;
      let a = 0, b = 0;
      for (let k = 0; k < w; k++) { a += all[i + k]; b += all[i + k + 1]; }
      out.push(((1 - f) * a + f * b) / w);
      this.pos += this.ratio;
    }
    const keep = Math.floor(this.pos);
    this.buf = all.slice(keep);
    this.pos -= keep;
    return Float32Array.from(out);
  }
}

/** −1…1 floats → little-endian int16 samples. */
export function toInt16(f32) {
  const out = new Int16Array(f32.length);
  for (let i = 0; i < f32.length; i++) out[i] = Math.max(-32768, Math.min(32767, Math.round(f32[i] * 32767)));
  return out;
}

/** The first message on the socket. */
export const startMessage = (o = {}) => ({ type: 'start', encoding: 'int16', sample_rate: RATE,
  ...(o.preset ? { preset: o.preset } : {}), ...(o.language ? { language: o.language } : {}) });

export const initial = () => ({ committed: [], hypothesis: '', ready: false, done: false, error: null });

/** One server event → the next state (committed segments append; the hypothesis is replaced). */
export function reduce(s, ev) {
  switch (ev?.type) {
    case 'ready': return { ...s, ready: true };
    case 'committed': return { ...s, committed: [...s.committed, ev.segment.text] };
    case 'hypothesis': return { ...s, hypothesis: ev.text || '' };
    case 'done': return { ...s, done: true, hypothesis: '', committed: ev.text ? [ev.text] : s.committed };
    case 'error': return { ...s, error: ev.detail || 'speech to text failed' };
    default: return s;
  }
}

/** What goes into the draft: the committed text, then the live tail. */
export const dictated = s => [...s.committed, s.hypothesis].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();

/** Joins dictation onto what was in the box when it started. */
export const joinDraft = (before, said) => !said ? before : !before ? said : before + (/\s$/.test(before) ? '' : ' ') + said;

// Runs inside the AudioWorklet: the Resampler above (its source is inlined), batching ~100 ms.
const WORKLET = `${Resampler.toString()}
class Mic16k extends AudioWorkletProcessor {
  constructor() { super(); this.r = new Resampler(sampleRate, ${RATE}); this.acc = []; this.n = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) { const o = this.r.push(ch); if (o.length) { this.acc.push(o); this.n += o.length; } }
    if (this.n >= ${RATE / 10}) {
      const out = new Float32Array(this.n); let p = 0;
      for (const a of this.acc) { out.set(a, p); p += a.length; }
      this.port.postMessage(out, [out.buffer]); this.acc = []; this.n = 0;
    }
    return true;
  }
}
registerProcessor('mic-16k', Mic16k);`;

/** The socket's address for a page served by the hub. */
export const streamUrl = (loc = globalThis.location) => `${loc.protocol === 'https:' ? 'wss' : 'ws'}://${loc.host}/api/s/stt/v1/stream`;

/** Starts dictating; returns { stop() } (stop flushes and resolves with the final state). */
export async function dictate({ onState, url = streamUrl(), media = globalThis.navigator?.mediaDevices, preset, language }) {
  const stream = await media.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  const ctx = new AudioContext();
  const mod = URL.createObjectURL(new Blob([WORKLET], { type: 'text/javascript' }));
  await ctx.audioWorklet.addModule(mod);
  URL.revokeObjectURL(mod);
  const node = new AudioWorkletNode(ctx, 'mic-16k');
  const src = ctx.createMediaStreamSource(stream);
  let state = initial(), finished;
  const over = new Promise(r => { finished = r; });
  const ws = new WebSocket(url);
  ws.binaryType = 'arraybuffer';
  const close = () => { src.disconnect(); node.disconnect(); stream.getTracks().forEach(t => t.stop()); ctx.close().catch(() => {}); };
  ws.onopen = () => ws.send(JSON.stringify(startMessage({ preset, language })));
  ws.onmessage = e => { state = reduce(state, JSON.parse(e.data)); onState(state); if (state.done) finished(state); };
  ws.onclose = e => {
    close();
    if (!state.done) { state = { ...state, error: state.error || (e.code !== 1000 ? (e.reason || `the stream closed (${e.code})`) : null) }; onState(state); finished(state); }
  };
  node.port.onmessage = e => { if (state.ready && ws.readyState === 1) ws.send(toInt16(e.data).buffer); };
  src.connect(node);
  return {
    stop() {
      close();
      if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'stop' })); else if (ws.readyState === 0) ws.close();
      return over;
    },
  };
}

/** True while the stt mod is up; checked on mount and every 20 s (a deleted mod answers 404). */
export function useSttUp(api) {
  const React = R(), [up, setUp] = React.useState(false);
  React.useEffect(() => {
    let live = true;
    const check = () => api?.getService?.('stt').then(s => live && setUp(['ready', 'degraded'].includes(s.state))).catch(() => live && setUp(false));
    check();
    const t = setInterval(check, 20000);
    return () => { live = false; clearInterval(t); };
  }, [api]);
  return up;
}

/** The composer's microphone: dictation goes into the draft after what was already typed. */
export function MicButton({ api, draft, setDraft, disabled }) {
  const React = R(), up = useSttUp(api);
  const [on, setOn] = React.useState(false), [err, setErr] = React.useState(null);
  const sess = React.useRef(null), want = React.useRef(false), base = React.useRef(''), press = React.useRef({ t: 0, started: false });
  React.useEffect(() => () => { want.current = false; sess.current?.stop(); }, []);
  if (!up) return null;
  const start = async () => {
    setErr(null); base.current = draft || ''; want.current = true; setOn(true);
    try {
      const s = await dictate({ onState: st => {
        if (st.error) setErr(st.error);
        setDraft(joinDraft(base.current, dictated(st)));
        if (st.done || st.error) { setOn(false); sess.current = null; }
      } });
      if (want.current) sess.current = s; else s.stop();          // released before the microphone opened
    } catch (e) {
      want.current = false; setOn(false);
      setErr(e?.name === 'NotAllowedError' ? 'Microphone access was refused' : (e?.message || 'No microphone'));
    }
  };
  const stop = () => { want.current = false; setOn(false); const s = sess.current; sess.current = null; s?.stop(); };
  return h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 4 } },
    h(Btn, { kind: on ? 'pri' : 'ghost', sm: true, icon: 'mic', disabled: disabled && !on, 'aria-pressed': on ? 'true' : 'false',
      title: on ? 'Stop dictating' : 'Dictate (click to start and stop, or hold to talk)',
      // Pointer: a press that starts it and is held past HOLD_MS stops on release (push to talk); a short
      // press leaves it on, and the next press stops it. Keyboard (detail 0): Enter or Space toggles.
      onPointerDown: e => { if (e.button) return; press.current = { t: Date.now(), started: !on }; if (!on) start(); },
      onPointerUp: () => { if (!press.current.t) return; const { t, started } = press.current; press.current = { t: 0, started: false };
        if (!started || Date.now() - t > HOLD_MS) stop(); },
      onClick: e => { if (e.detail === 0) (on ? stop() : start()); } }),
    on ? h('span', { role: 'status', style: { fontSize: 11.5, color: T.rd } }, 'Listening…') : null,
    err ? h('span', { role: 'alert', style: { fontSize: 11.5, color: T.rd } }, err) : null);
}
