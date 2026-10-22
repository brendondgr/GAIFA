// Dictation into the composer (plans 29.3–29.4). The preferred microphone (a ranked list of labels in the
// hub's settings `speech_input`: the first one present is used, the next on unplug, and a higher one takes
// over when plugged in) → an AudioWorklet that resamples to 16 kHz mono → int16 frames over the stt mod's
// `WS /v1/stream` (through the hub's proxy) → the committed text plus the live tail, written into the draft.
// The button shows only while the stt mod is up, so deleting services/stt removes it. Click to toggle, hold
// to talk, or either (`mode`). The pure parts (Resampler, toInt16, the protocol, pickMic, nextMic, onRelease,
// levelOf) and openMic's fallback and take-over are tested in utils/tests/web/chat-mic.test.mjs.

import { h, T, Btn, Popover } from './chat-ui.js';
import { SpeechInputPanel } from './chat-speech-input.js';

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

export const initial = () => ({ committed: [], hypothesis: '', ready: false, done: false, error: null, device: null, reason: null });

/** One server event → the next state (committed segments append; the hypothesis is replaced). */
export function reduce(s, ev) {
  switch (ev?.type) {
    case 'ready': return { ...s, ready: true, device: ev.device || null, reason: ev.reason || null };
    case 'device': return { ...s, device: ev.device || null, reason: ev.reason || null };   // moved off the GPU mid-stream
    case 'committed': return { ...s, committed: [...s.committed, ev.segment.text] };
    case 'hypothesis': return { ...s, hypothesis: ev.text || '' };
    case 'done': return { ...s, done: true, hypothesis: '', committed: ev.text ? [ev.text] : s.committed };
    case 'error': return { ...s, error: ev.detail || 'speech to text failed' };
    default: return s;
  }
}

/** Dictation on the CPU (the stt mod moved it there while another mod's work holds the GPU, plan 31.3): the note
 * beside "Listening", with why as its title; null on the GPU. */
export const deviceNote = s => s?.device === 'cpu'
  ? { text: 'on the CPU', title: s.reason ? s.reason[0].toUpperCase() + s.reason.slice(1) : 'Dictation runs on the CPU while the GPU is busy' }
  : null;

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

// ---- which microphone (plan 29.4): a ranked list of labels, the first one present wins ----------------

/** Labels as the user sees them: Chrome's "Default - " / "Communications - " prefixes dropped, case ignored. */
export const normLabel = l => String(l || '').replace(/^(default|communications)\s*-\s*/i, '').trim().toLowerCase();

/** The real microphones in an `enumerateDevices()` list (not Chrome's "default"/"communications" aliases). */
export const audioInputs = devices => (devices || []).filter(d => d.kind === 'audioinput' && !['default', 'communications'].includes(d.deviceId));

/** The most preferred microphone that is present: `{deviceId, label, rank}`, or null (none listed is plugged in). */
export function pickMic(devices, prefs = []) {
  const inputs = audioInputs(devices);
  for (let rank = 0; rank < prefs.length; rank++) {
    const d = inputs.find(x => x.label && normLabel(x.label) === normLabel(prefs[rank]));
    if (d) return { deviceId: d.deviceId, label: d.label, rank };
  }
  return null;
}

export const BROWSER_DEFAULT = { deviceId: null, label: 'the browser’s default microphone', rank: null };

/** After a device change: the microphone to switch to, or undefined to keep `current`. A ranked mic that
 * appears takes over from a lower one (or from the browser's default); an unplugged one falls back to the
 * next present, else the browser's default. `lost` says the current track ended. */
export function nextMic(devices, prefs, current, lost = false) {
  const pick = pickMic(devices, prefs);
  const present = !!current?.deviceId && audioInputs(devices).some(d => d.deviceId === current.deviceId);
  const gone = lost || (current?.deviceId && !present);
  if (gone) return pick || BROWSER_DEFAULT;
  if (pick && pick.deviceId !== current?.deviceId && (current?.rank == null || pick.rank < current.rank)) return pick;
  return undefined;
}

/** What a button release does: 'stop' or 'keep'. `started`: this press started dictation. */
export function onRelease(mode, started, heldMs) {
  if (mode === 'hold') return 'stop';
  if (mode === 'toggle') return started ? 'keep' : 'stop';
  return !started || heldMs > HOLD_MS ? 'stop' : 'keep';
}

/** An input level for a meter, 0–1: RMS on a −60…0 dB scale. */
export function levelOf(samples) {
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  const rms = Math.sqrt(sum / Math.max(1, samples.length));
  return rms <= 0.001 ? 0 : Math.min(1, Math.max(0, 1 + Math.log10(rms) / 3));
}

const constraints = mic => ({ audio: { ...(mic?.deviceId ? { deviceId: { exact: mic.deviceId } } : {}), channelCount: 1, echoCancellation: true, noiseSuppression: true } });
const listInputs = async media => audioInputs(await media.enumerateDevices());

/** Opens the preferred microphone and follows plugs and unplugs: `{stream, mic, stop}`; `onSwitch(stream, mic)`
 * is told about each change. Labels are only visible once access is granted, so it picks again after opening. */
export async function openMic({ media, mics = [], onSwitch = () => {} }) {
  let mic = pickMic(await listInputs(media), mics) || BROWSER_DEFAULT;
  let stream = await media.getUserMedia(constraints(mic));
  let busy = false, again = false, closed = false;
  const watch = () => stream.getAudioTracks?.().forEach(t => t.addEventListener?.('ended', () => change(true)));
  const change = async (lost = false) => {
    if (closed) return;
    if (busy) { again = true; return; }             // a change during a switch is looked at once it's done
    busy = true;
    try {
      const next = nextMic(await listInputs(media), mics, mic, lost);
      if (next === undefined) return;
      const s = await media.getUserMedia(constraints(next));
      if (closed) { s.getTracks().forEach(t => t.stop()); return; }
      const old = stream;
      stream = s; mic = next;
      watch(); onSwitch(stream, mic);
      old.getTracks().forEach(t => t.stop());
    } catch { /* the next change tries again */ } finally {
      busy = false;
      if (again) { again = false; change(); }
    }
  };
  watch();
  const first = nextMic(await listInputs(media), mics, mic.deviceId ? mic : null);
  if (first && first.deviceId !== mic.deviceId) {
    stream.getTracks().forEach(t => t.stop());
    mic = first; stream = await media.getUserMedia(constraints(mic)); watch();
  }
  const onDevices = () => change();
  media.addEventListener?.('devicechange', onDevices);
  return {
    get stream() { return stream; }, get mic() { return mic; },
    stop() { closed = true; media.removeEventListener?.('devicechange', onDevices); stream.getTracks().forEach(t => t.stop()); },
  };
}

/** Starts dictating; returns { stop() } (stop flushes and resolves with the final state). The state also
 * carries `mic` (the label in use) and `level` (0–1, about ten times a second). */
export async function dictate({ onState, url = streamUrl(), media = globalThis.navigator?.mediaDevices, preset, language, mics = [] }) {
  const ctx = new AudioContext();
  const mod = URL.createObjectURL(new Blob([WORKLET], { type: 'text/javascript' }));
  await ctx.audioWorklet.addModule(mod);
  URL.revokeObjectURL(mod);
  const node = new AudioWorkletNode(ctx, 'mic-16k');
  let src = null, state = { ...initial(), mic: null, level: 0 }, finished;
  const tell = patch => { state = { ...state, ...patch }; onState(state); };
  const plug = (stream, mic) => {
    src?.disconnect();
    src = ctx.createMediaStreamSource(stream);
    src.connect(node);
    tell({ mic: mic.label });
  };
  const input = await openMic({ media, mics, onSwitch: plug });
  plug(input.stream, input.mic);
  const over = new Promise(r => { finished = r; });
  const ws = new WebSocket(url);
  ws.binaryType = 'arraybuffer';
  const close = () => { src?.disconnect(); node.disconnect(); input.stop(); ctx.close().catch(() => {}); };
  ws.onopen = () => ws.send(JSON.stringify(startMessage({ preset, language })));
  ws.onmessage = e => { state = reduce(state, JSON.parse(e.data)); onState(state); if (state.done) finished(state); };
  ws.onclose = e => {
    close();
    if (!state.done) { tell({ error: state.error || (e.code !== 1000 ? (e.reason || `the stream closed (${e.code})`) : null) }); finished(state); }
  };
  node.port.onmessage = e => {
    if (Math.abs(levelOf(e.data) - state.level) > 0.02) tell({ level: levelOf(e.data) });
    if (state.ready && ws.readyState === 1) ws.send(toInt16(e.data).buffer);
  };
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

/** The saved dictation settings (hub settings `speech_input`), with their defaults. */
export const SPEECH_DEFAULTS = { mics: [], language: '', preset: 'balanced', mode: 'both' };
export const speechSettings = async api => ({ ...SPEECH_DEFAULTS, ...((await api?.getSettings?.().catch(() => null))?.speech_input || {}) });

/** A small level bar (0–1). */
export const LevelBar = ({ level, width = 46 }) => h('span', { 'aria-hidden': 'true', style: { display: 'inline-block', width, height: 5, borderRadius: 3, background: T.inset, overflow: 'hidden' } },
  h('span', { style: { display: 'block', height: '100%', width: `${Math.round((level || 0) * 100)}%`, background: (level || 0) > 0.9 ? T.rd : T.gr, transition: 'width 80ms linear' } }));

/** The composer's microphone: dictation goes into the draft after what was already typed. The menu (▾)
 * holds the same microphone list and options as Settings → Speech input. */
export function MicButton({ api, draft, setDraft, disabled }) {
  const React = R(), up = useSttUp(api);
  const [on, setOn] = React.useState(false), [err, setErr] = React.useState(null), [live, setLive] = React.useState({ mic: null, level: 0, note: null });
  const [menu, setMenu] = React.useState(false), mode = React.useRef('both');
  const sess = React.useRef(null), want = React.useRef(false), base = React.useRef(''), press = React.useRef({ t: 0, started: false });
  React.useEffect(() => () => { want.current = false; sess.current?.stop(); }, []);
  React.useEffect(() => { if (up) speechSettings(api).then(x => { mode.current = x.mode; }); }, [up, menu]);
  if (!up) return null;
  const start = async () => {
    setErr(null); base.current = draft || ''; want.current = true; setOn(true);
    try {
      const prefs = await speechSettings(api);
      mode.current = prefs.mode;
      let said = '';
      const s = await dictate({ mics: prefs.mics, preset: prefs.preset, language: prefs.language || undefined, onState: st => {
        if (st.error) setErr(st.error);
        setLive({ mic: st.mic, level: st.level, note: deviceNote(st) });
        const now = dictated(st);
        if (now !== said) { said = now; setDraft(joinDraft(base.current, now)); }
        if (st.done || st.error) { setOn(false); sess.current = null; }
      } });
      if (want.current) sess.current = s; else s.stop();          // released before the microphone opened
    } catch (e) {
      want.current = false; setOn(false);
      setErr(e?.name === 'NotAllowedError' ? 'Microphone access was refused' : e?.name === 'OverconstrainedError' ? 'That microphone is gone' : (e?.message || 'No microphone'));
    }
  };
  const stop = () => { want.current = false; setOn(false); const s = sess.current; sess.current = null; s?.stop(); };
  return h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 4, position: 'relative' } },
    h(Btn, { kind: on ? 'pri' : 'ghost', sm: true, icon: 'mic', disabled: disabled && !on, 'aria-pressed': on ? 'true' : 'false',
      title: on ? 'Stop dictating' : { hold: 'Dictate (hold to talk)', toggle: 'Dictate (click to start and stop)' }[mode.current] || 'Dictate (click to start and stop, or hold to talk)',
      // Pointer: what a release does depends on the mode (onRelease). Keyboard (detail 0): Enter or Space toggles.
      onPointerDown: e => { if (e.button) return; press.current = { t: Date.now(), started: !on }; if (!on) start(); },
      onPointerUp: () => { if (!press.current.t) return; const { t, started } = press.current; press.current = { t: 0, started: false };
        if (onRelease(mode.current, started, Date.now() - t) === 'stop') stop(); },
      onClick: e => { if (e.detail === 0) (on ? stop() : start()); } }),
    h(Btn, { kind: 'ghost', sm: true, icon: 'chevD', title: 'Microphone and dictation options', 'aria-expanded': menu ? 'true' : 'false', disabled: on, onClick: () => setMenu(!menu), style: { width: 18, padding: 0 } }),
    h(Popover, { open: menu, onClose: () => setMenu(false), place: 'up-left', width: 360, label: 'Speech input' }, menu ? h(SpeechInputPanel, { api, compact: true }) : null),
    on ? h('span', { role: 'status', title: live.mic || '', style: { display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: T.rd, maxWidth: 220 } },
      h(LevelBar, { level: live.level }), h('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, live.mic ? `Listening · ${live.mic}` : 'Listening…'),
      live.note ? h('span', { title: live.note.title, style: { color: T.mut, whiteSpace: 'nowrap' } }, live.note.text) : null) : null,
    err ? h('span', { role: 'alert', style: { fontSize: 11.5, color: T.rd } }, err) : null);
}
