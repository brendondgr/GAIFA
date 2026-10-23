// Read replies aloud (plan 49.1): a speaker under each finished reply plays it in the voice set in Settings → Agent →
// Voice (`speech_output`), through the tts mod's streaming speech (raw PCM as it's made, not saved), so it starts
// within a moment. What's read is the reply as plain text: no citations, sources or links' addresses, and a code
// block is named, not spelled out. Clicking again stops. Only shown while the tts mod is installed.

import { h, T, Icon } from './chat-ui.js';
import { textOnly } from './chat-copy.js';

const R = () => globalThis.React;
const MAX_CHARS = 4000;

/** A reply's markdown → the words to read. */
export function speakable(md) {
  let s = String(md || '').replace(/^\s*<think>[\s\S]*?<\/think>\s*/i, '');
  s = s.replace(/^(\s*)(`{3,}|~{3,})[^\n]*\n[\s\S]*?\n\s*\2\s*$/gm, '\n(a code block)\n');
  s = textOnly(s);
  s = s.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')                       // a picture: its caption
    .replace(/`([^`\n]+)`/g, '$1').replace(/\*\*([^*]+)\*\*/g, '$1').replace(/(^|[^*])\*([^*\n]+)\*/g, '$1$2')
    .replace(/^#{1,6}\s+/gm, '').replace(/^\s*[-*+]\s+/gm, '').replace(/^\s*\|.*\|\s*$/gm, '').replace(/^\s*>\s?/gm, '')
    .replace(/https?:\/\/\S+/g, '').replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
  return s.length > MAX_CHARS ? s.slice(0, s.lastIndexOf('.', MAX_CHARS - 1) + 1 || MAX_CHARS) : s;
}

/** The speech request for the settings: {text, stream, no_save, name?, engine, speed}. */
export function speechBody(text, so = {}) {
  return { text, stream: true, no_save: true, ...(so.voice ? { name: so.voice } : {}), engine: so.engine || 'auto', speed: so.speed || 1 };
}

/** Plays 16-bit PCM chunks one after another as they arrive (WebAudio). */
export class PcmPlayer {
  constructor(rate = 24000, AC = globalThis.AudioContext || globalThis.webkitAudioContext) {
    this.rate = rate; this.ctx = AC ? new AC() : null; this.next = 0; this.carry = null; this.ended = null; this.sources = new Set();
  }
  push(bytes) {
    if (!this.ctx) return;
    let u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    if (this.carry) { const m = new Uint8Array(this.carry.length + u8.length); m.set(this.carry); m.set(u8, this.carry.length); u8 = m; this.carry = null; }
    if (u8.length % 2) { this.carry = u8.slice(-1); u8 = u8.slice(0, -1); }
    if (!u8.length) return;
    const pcm = new Int16Array(u8.buffer, u8.byteOffset, u8.length / 2), buf = this.ctx.createBuffer(1, pcm.length, this.rate), d = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) d[i] = pcm[i] / 32768;
    const src = this.ctx.createBufferSource(); src.buffer = buf; src.connect(this.ctx.destination);
    const at = Math.max(this.ctx.currentTime + 0.05, this.next); src.start(at); this.next = at + buf.duration;
    this.sources.add(src); src.onended = () => { this.sources.delete(src); if (!this.sources.size && this.done && this.ended) this.ended(); };
  }
  finish(onEnd) { this.done = true; this.ended = onEnd; if (!this.sources.size) onEnd?.(); }
  stop() { this.done = true; this.ended = null; for (const s of this.sources) { try { s.stop(); } catch { /* ended */ } } this.sources.clear(); this.ctx?.close().catch(() => {}); }
}

/** Speak `text` in the voice of `so` (speech_output); returns {stop, done: Promise}. */
export function speak(text, so = {}, { fetchImpl = globalThis.fetch, Player = PcmPlayer } = {}) {
  const ctrl = new AbortController();
  let player = null, stopped = false;
  const done = (async () => {
    const r = await fetchImpl('/api/s/tts/v1/speech', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(speechBody(text, so)), signal: ctrl.signal });
    if (!r.ok) { let d = ''; try { d = (await r.json()).detail; } catch { /* not json */ } throw new Error(d || `the speech mod answered ${r.status}`); }
    player = new Player(+r.headers.get('x-sample-rate') || 24000);
    const reader = r.body.getReader();
    for (;;) { const { value, done: end } = await reader.read(); if (end || stopped) break; player.push(value); }
    if (!stopped) await new Promise(res => player.finish(res));
  })();
  return { done, stop: () => { stopped = true; ctrl.abort(); player?.stop(); } };
}

let current = null;   // one reply reads at a time
/** The speaker under a reply: Read aloud / Stop. */
export function SpeakButton({ text, ctx }) {
  const React = R(), [state, setState] = React.useState('idle'), me = React.useRef(null);
  React.useEffect(() => () => { if (current === me.current) { current?.stop(); current = null; } }, []);
  if (!ctx?.mods?.includes?.('tts') && !ctx?.speech) return null;
  const go = () => {
    if (state !== 'idle') { me.current?.stop(); current = null; setState('idle'); return; }
    current?.stop();
    const words = speakable(text);
    if (!words) return;
    const s = speak(words, ctx?.speechOutput || {});
    me.current = s; current = s; setState('loading');
    s.done.then(() => setState('idle'), e => { if (e?.name !== 'AbortError') ctx?.toast?.(`Couldn't read it aloud: ${e.message || e}`, 'error'); setState('idle'); });
    setTimeout(() => setState(st => (st === 'loading' ? 'playing' : st)), 600);
  };
  const label = state === 'idle' ? 'Read aloud' : 'Stop reading';
  return h('button', { type: 'button', onClick: go, title: label, 'aria-label': label, 'aria-pressed': state !== 'idle' ? 'true' : 'false',
    style: { display: 'grid', placeItems: 'center', width: 24, height: 24, border: 0, borderRadius: 5, cursor: 'pointer', background: state !== 'idle' ? T.tacc : 'none', color: state !== 'idle' ? T.acc : T.dim } },
    h(Icon, { d: state === 'idle' ? 'speaker' : 'stop', size: 13 }));
}

/** Settings → Agent → Voice: the voice that reads replies, its engine and speed, auto-read, voice mode's pause. */
export function SpeechOutputSection({ api, toast = () => {} }) {
  const React = R(), [so, setSo] = React.useState(null), [voices, setVoices] = React.useState(null), [saving, setSaving] = React.useState(false);
  React.useEffect(() => {
    api.getSettings?.().then(s => setSo(s.speech_output || null)).catch(() => {});
    api.callService?.('tts', 'GET', '/v1/voices').then(r => setVoices(r.json)).catch(() => setVoices(null));
  }, []);
  if (!so || !voices) return null;      // no tts mod: nothing to set
  const save = async patch => {
    const next = { ...so, ...patch };
    setSo(next); setSaving(true);
    try { await api.saveSettings({ speech_output: next }); } catch (e) { toast(e.detail || 'Not saved', 'error'); }
    setSaving(false);
  };
  const names = [...(voices.custom || []).map(v => v.name), ...(voices.kokoro || [])];
  const sel = { height: 30, padding: '0 8px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.sb, color: T.tx, font: 'inherit', fontSize: 12.5 };
  const row = (label, hint, ctl) => h('div', { style: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' } },
    h('div', { style: { flex: '1 1 240px', minWidth: 0 } }, h('div', { style: { fontSize: 13 } }, label), h('div', { style: { fontSize: 12, color: T.mut } }, hint)), ctl);
  return h('section', { style: { background: T.card, border: '1px solid ' + T.bd, borderRadius: 10, padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 10 } },
    h('h2', { style: { fontSize: 11, fontWeight: 600, letterSpacing: '.07em', textTransform: 'uppercase', color: T.mut, margin: 0 } }, 'Voice', saving ? ' · saving…' : ''),
    row('Read replies in', 'The voice under each reply’s speaker, and voice mode’s answers.',
      h('select', { value: so.voice, onChange: e => save({ voice: e.target.value }), style: sel },
        h('option', { value: '' }, 'The speech mod’s default'), names.map(n => h('option', { key: n, value: n }, n)))),
    row('Speed', 'Built-in (Kokoro) voices only.',
      h('input', { type: 'range', min: 0.5, max: 2, step: 0.1, value: so.speed, onChange: e => save({ speed: +e.target.value }), 'aria-label': 'Speed' }), ),
    row('Read every reply aloud', 'When a reply is finished. With a model on this GPU it waits for the reply to end.',
      h('input', { type: 'checkbox', checked: !!so.auto_read, onChange: e => save({ auto_read: e.target.checked }), 'aria-label': 'Read every reply aloud' })),
    row('Voice mode: end of what you said', 'The quiet that sends your message.',
      h('select', { value: so.pause_ms, onChange: e => save({ pause_ms: +e.target.value }), style: sel },
        [800, 1200, 1600, 2400].map(ms => h('option', { key: ms, value: ms }, (ms / 1000) + ' s')))));
}
