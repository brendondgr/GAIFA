// Voice mode (plan 49.2): talk to the agent hands-free. The button by the microphone starts it: listen (the stt
// mod's live stream, as dictation) → after a pause (Settings → Agent → Voice, `pause_ms`) send what you said →
// read the reply aloud (chat-speak.js) → listen again. Speaking while it reads stops the reading and listens (the
// mic has echo cancellation; a sustained loud level counts). A card waiting for you (an approval, a question)
// pauses it: the bar says so, and it carries on once you've answered on screen. Escape or the button ends it.

import { h, T, Icon } from './chat-ui.js';
import { dictate, dictated, levelOf, speechSettings, useSttUp } from './chat-mic.js';
import { speak, speakable } from './chat-speak.js';

const R = () => globalThis.React;
export const BARGE_LEVEL = 0.55, BARGE_MS = 350;

/** The voice loop's next state: {mode, text, error}. Modes: off, listening, sending, thinking, speaking, paused. */
export function voiceStep(s, ev) {
  switch (ev.type) {
    case 'start': return { mode: 'listening', text: '', error: null };
    case 'stop': return { mode: 'off', text: '', error: null };
    case 'error': return { mode: 'off', text: '', error: ev.error };
    case 'heard': return s.mode === 'listening' ? { ...s, text: ev.text } : s;
    case 'quiet': return s.mode === 'listening' && s.text.trim() && ev.ms >= ev.pause ? { ...s, mode: 'sending' } : s;
    case 'sent': return s.mode === 'sending' ? { ...s, mode: 'thinking', text: '' } : s;
    case 'turn_end': return s.mode === 'thinking' ? { ...s, mode: ev.text ? 'speaking' : 'listening', text: '' } : s;
    case 'spoken': return s.mode === 'speaking' ? { ...s, mode: 'listening' } : s;
    case 'barge': return s.mode === 'speaking' ? { ...s, mode: 'listening', text: '' } : s;
    case 'card': return s.mode === 'off' || s.mode === 'paused' ? s : { ...s, mode: 'paused', was: s.mode };
    case 'card_done': return s.mode === 'paused' ? { ...s, mode: ev.running ? 'thinking' : 'listening' } : s;
    default: return s;
  }
}

/** True once the mic has been loud for `ms` (barge-in while the reply is read). */
export function bargeTracker(level = BARGE_LEVEL, ms = BARGE_MS) {
  let since = null;
  return (lv, now) => {
    if (lv < level) { since = null; return false; }
    if (since == null) since = now;
    return now - since >= ms;
  };
}

/** The text of the chat's last reply. */
export const lastAnswer = events => ([...(events || [])].reverse().find(e => e.type === 'assistant' && e.payload?.text)?.payload.text || '');

const WORDS = { listening: 'Listening…', sending: 'Sending…', thinking: 'Thinking…', speaking: 'Speaking (talk to interrupt)', paused: 'Waiting for you on screen' };

export function VoiceButton({ api, onSend, running, waiting, lastAnswer, speechOutput, disabled, onMode }) {
  const React = R(), up = useSttUp(api), [s, setS] = React.useState({ mode: 'off', text: '', error: null });
  const st = React.useRef(s), dict = React.useRef(null), reading = React.useRef(null), timers = React.useRef({});
  const go = ev => setS(prev => { const n = voiceStep(prev, ev); st.current = n; return n; });
  const pause = speechOutput?.pause_ms || 1200;

  const stopListening = () => { clearInterval(timers.current.quiet); const d = dict.current; dict.current = null; return d ? d.stop() : Promise.resolve(null); };
  const stopReading = () => { reading.current?.stop(); reading.current = null; clearInterval(timers.current.barge); timers.current.bargeMic?.stop(); };
  const listen = async () => {
    let heardAt = Date.now(), last = '';
    try {
      const settings = await speechSettings(api);
      dict.current = await dictate({ preset: settings.preset, language: settings.language || undefined, mics: settings.mics, onState: d => {
        const text = dictated(d);
        if (text !== last || (d.level || 0) > 0.2) heardAt = Date.now();
        if (text !== last) { last = text; go({ type: 'heard', text }); }
        if (d.error) go({ type: 'error', error: d.error });
        else if (d.done && dict.current && st.current.mode === 'listening') { clearInterval(timers.current.quiet); dict.current = null; setTimeout(() => { if (st.current.mode === 'listening' && !dict.current) listen(); }, 300); }   // the stream ended: listen again
      } });
      timers.current.quiet = setInterval(() => go({ type: 'quiet', ms: Date.now() - heardAt, pause }), 200);
    } catch (e) { go({ type: 'error', error: e?.name === 'NotAllowedError' ? 'Microphone access was refused' : (e?.message || String(e)) }); }
  };

  React.useEffect(() => {     // each state's work
    const m = s.mode;
    onMode?.(m);
    if (m === 'listening' && !dict.current) listen();
    if (m === 'sending') {
      const text = s.text.trim();
      stopListening().then(() => { onSend(text); go({ type: 'sent' }); });
    }
    if (m === 'speaking' && !reading.current) {
      const words = speakable(lastAnswer || '');
      const r = speak(words, speechOutput || {});
      reading.current = r;
      r.done.then(() => { if (reading.current === r) { reading.current = null; go({ type: 'spoken' }); } }, () => { if (reading.current === r) { reading.current = null; go({ type: 'spoken' }); } });
      watchBarge();
    }
    if (m === 'paused' || m === 'off') { stopListening(); stopReading(); }
  }, [s.mode]);

  const watchBarge = async () => {    // a loud, sustained voice while it reads: stop and listen
    try {
      const media = globalThis.navigator.mediaDevices, stream = await media.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      const ctx = new AudioContext(), an = ctx.createAnalyser(), buf = new Float32Array(1024), loud = bargeTracker();
      ctx.createMediaStreamSource(stream).connect(an);
      timers.current.bargeMic = { stop: () => { stream.getTracks().forEach(t => t.stop()); ctx.close().catch(() => {}); } };
      timers.current.barge = setInterval(() => { an.getFloatTimeDomainData(buf); if (loud(levelOf(buf), Date.now())) { stopReading(); go({ type: 'barge' }); } }, 60);
    } catch { /* no mic for barge-in: it reads to the end */ }
  };

  // the turn: thinking → speaking when it ends; a waiting card pauses
  const was = React.useRef(running);
  React.useEffect(() => {
    if (was.current && !running && st.current.mode === 'thinking') go({ type: 'turn_end', text: speakable(lastAnswer || '') });
    was.current = running;
  }, [running]);
  React.useEffect(() => { go({ type: waiting ? 'card' : 'card_done', running }); }, [waiting]);
  React.useEffect(() => {
    if (s.mode === 'off') return undefined;
    const esc = e => { if (e.key === 'Escape') go({ type: 'stop' }); };
    globalThis.addEventListener('keydown', esc);
    return () => globalThis.removeEventListener('keydown', esc);
  }, [s.mode === 'off']);
  React.useEffect(() => () => { stopListening(); stopReading(); }, []);

  const on = s.mode !== 'off';
  if ((!up || !speechOutput) && !on) return null;     // needs the stt mod (listening) and the tts mod (speech_output's voices)
  return h(R().Fragment, null,
    on ? h('div', { role: 'status', style: { position: 'absolute', left: 0, right: 0, bottom: 'calc(100% + 6px)', zIndex: 25, display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
      background: T.card, border: '1px solid ' + T.bds, borderRadius: 9, boxShadow: '0 12px 30px rgba(0,0,0,.3)', fontSize: 12.5 } },
      h('span', { 'aria-hidden': 'true', style: { width: 8, height: 8, borderRadius: '50%', flex: 'none', background: s.mode === 'paused' ? T.pu : s.mode === 'listening' ? T.gr : T.acc } }),
      h('span', { style: { fontWeight: 600 } }, 'Voice mode'),
      h('span', { style: { color: T.mut } }, WORDS[s.mode] || ''),
      s.text ? h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: T.tx } }, '“' + s.text + '”') : h('span', { style: { flex: 1 } }),
      h('span', { style: { color: T.dim, fontSize: 11.5 } }, 'Esc ends')) : null,
    s.error && !on ? h('span', { role: 'alert', style: { fontSize: 11.5, color: T.rd } }, s.error) : null,
    h('button', { type: 'button', disabled, onClick: () => go({ type: on ? 'stop' : 'start' }), title: on ? 'End voice mode' : 'Voice mode: talk, and hear the replies',
      'aria-label': on ? 'End voice mode' : 'Voice mode', 'aria-pressed': on ? 'true' : 'false', className: 'aichat-quiet',
      style: { display: 'grid', placeItems: 'center', width: 28, height: 28, border: 0, borderRadius: 7, cursor: disabled ? 'default' : 'pointer', background: on ? T.tacc : 'transparent', color: on ? T.acc : T.mut } },
      h(Icon, { d: 'speaker', size: 14 })));
}
