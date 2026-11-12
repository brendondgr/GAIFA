// Voice mode on a speech-to-speech model (plan voice-speech-model 3.3): the page's side of the voice mod's
// WebSocket (`/api/s/voice/v1/realtime`, services/voice/voice/bridge.py). The microphone goes up as 16 kHz
// PCM16 frames; the reply comes down as PCM16 and plays as it arrives. The mod finds the end of what you said,
// answers (itself, or by sending your words to the chat's agent and saying its answer: `answers`), and the turn is in the chat; this client plays, shows the words, and tells the mod when a
// reply has finished playing or you talked over it (the microphone staying loud while it plays). Muted (plan
// voice-mute 1.2), no frames go up and nothing interrupts: the mod hears nothing, and a reply goes on. With push to
// talk (2.2) frames go up only while held (with the 400 ms before the press, so a first syllable isn't lost), a
// press during a reply stops it, and letting go sends the turn; loudness interrupts nothing. A mod that decides
// interruptions itself by speech (3.2, `ready.interrupt`: speech | off) says `interrupted`, and this page then stops
// the reply where it is; its own loudness check is only for a mod that doesn't.
// Written by us (web/PATCHES.md).

import { micFrames, toInt16, levelOf } from './chat-mic.js';
import { PcmPlayer } from './chat-speak.js';
import { bargeTracker } from './chat-voice.js';

/** The socket's address for a page served by the hub. */
export const liveUrl = (loc = globalThis.location) => `${loc.protocol === 'https:' ? 'wss' : 'ws'}://${loc.host}/api/s/voice/v1/realtime`;

export const LIVE_WORDS = { connecting: 'Starting…', listening: 'Listening…', hearing: 'Listening…', thinking: 'Thinking…',
  speaking: 'Speaking (talk to interrupt)', paused: 'Waiting for the chat', card: 'Waiting for you on screen', muted: 'Muted' };

/** The bar's words for a mode, muted or not; `push`: {key, held} with push to talk. */
export function liveWords(mode, muted, push) {
  if (push) {
    if (push.held && (mode === 'listening' || mode === 'hearing')) return 'Listening… (let go to send)';
    if (mode === 'listening' || mode === 'hearing') return `Hold ${push.key} to talk`;
    if (mode === 'speaking') return `Speaking (hold ${push.key} to interrupt)`;
    return LIVE_WORDS[mode] || '';
  }
  return !muted ? LIVE_WORDS[mode] || ''
    : mode === 'speaking' ? 'Speaking (muted)' : mode === 'listening' || mode === 'hearing' ? LIVE_WORDS.muted : LIVE_WORDS[mode] || '';
}
export const PREROLL_SAMPLES = 6400;     // push to talk: 400 ms at 16 kHz before the press go up with it
/** Errors that end the session before it could talk: the caller may fall back to the chat-model engine. */
export const FATAL = new Set(['model_missing', 'engine_missing', 'engine_failed', 'engine_timeout', 'needs_room', 'busy', 'bad_start', 'not_found',
  'gpu_cancelled', 'hub_unreachable', 'context_failed', 'unreachable']);

/** The live loop's next state: {mode, you, reply, model, error, note, muted}. Modes: off, connecting, listening, hearing,
 * thinking, speaking. `you`: your words of the turn under way; `reply`: the answer's text so far. */
export function liveStep(s, ev) {
  switch (ev.type) {
    case 'start': return { mode: 'connecting', you: '', reply: '', model: s.model || '', error: null, note: null, muted: !!s.muted };
    case 'stop': case 'done': return { ...s, mode: 'off', you: '', reply: '', note: null };
    case 'waiting': return s.mode === 'off' ? s : { ...s, mode: 'connecting', note: ev.text || 'Waiting for the GPU' };
    case 'ready': return s.mode === 'off' ? s : { ...s, model: ev.model || s.model, answers: ev.answers || 'speech', note: null, muted: ev.muted ?? !!s.muted, talk: ev.talk || 'open' };
    case 'muted': return { ...s, muted: !!ev.on, ...(ev.on && s.mode === 'hearing' ? { mode: 'listening', you: '' } : {}) };
    case 'listening': return s.mode === 'off' ? s : { ...s, mode: 'listening', you: '', reply: '', note: null, asking: false };
    case 'hearing': return s.mode === 'off' ? s : { ...s, mode: 'hearing', you: '', reply: '' };
    case 'thinking': return s.mode === 'off' ? s : { ...s, mode: 'thinking', asking: s.answers === 'agent' || !!s.asking };     // the chat's agent answers (6.3): the turn that follows is this conversation's own
    case 'speaking': return s.mode === 'off' ? s : { ...s, mode: 'speaking' };
    case 'heard': return s.mode === 'off' ? s : { ...s, you: ev.text || '' };
    case 'said': return s.mode === 'off' ? s : { ...s, reply: ev.text || '' };
    // a tool the reply uses (Phase 5): its words while it runs; `asking`: the chat's own model is answering
    case 'tool': return s.mode === 'off' ? s : ev.state === 'running' ? { ...s, note: ev.text || 'Using a tool…', asking: ev.name === 'ask_chat' }
      : { ...s, note: ev.state === 'refused' ? 'That needs your approval in the chat' : null, asking: false };
    case 'error': return FATAL.has(ev.code) || ev.fatal ? { ...s, mode: 'off', you: '', reply: '', error: ev.detail || ev.code, code: ev.code, fix: ev.fix || null }
      : { ...s, note: ev.detail || ev.code };
    default: return s;
  }
}

let current = null;     // one conversation per page: starting another ends this one

/** Start a conversation. `onEvent(ev)` gets every event of the mod, plus {type:'mic', label} and, when the socket
 * drops for good, {type:'error', code:'unreachable', fatal:true}. Returns {stop(), mute(on), talk(on)}. `talk`: open | push. */
export function liveVoice({ thread, voice = 'female', language, pauseMs = 1200, quant, answers, muted: startMuted = false, talk: talkMode = 'open', save = true, mics = [], onEvent,
  url = liveUrl(), WebSocketImpl = globalThis.WebSocket, Player = PcmPlayer, frames = micFrames, now = () => globalThis.performance.now() }) {
  let ws = null, mic = null, player = null, stopped = false, retried = false, ready = false, rate = 24000;
  let speaking = false, dropping = false, playedFrom = null, loud = bargeTracker(), finalSeen = false, muted = !!startMuted, held = false, modBarge = false;
  const ring = [];                                     // push to talk: the frames just before a press
  const send = o => { if (ws && ws.readyState === 1) ws.send(typeof o === 'string' || o instanceof ArrayBuffer ? o : JSON.stringify(o)); };
  const endPlayer = () => { player?.stop(); player = null; speaking = false; playedFrom = null; finalSeen = false; };
  const played = () => (playedFrom == null ? 0 : Math.max(0, now() - playedFrom));

  const onFrame = f => {
    if (stopped || !ready || muted) return;              // muted: the mod hears nothing, and nothing interrupts
    if (talkMode === 'push') {                           // heard only while held; the press, not loudness, interrupts
      const b = toInt16(f).buffer;
      if (held) { send(b); return; }
      ring.push(b);
      let n = ring.reduce((a, x) => a + x.byteLength / 2, 0);
      while (ring.length > 1 && n - ring[0].byteLength / 2 >= PREROLL_SAMPLES) n -= ring.shift().byteLength / 2;
      return;
    }
    if (speaking && !modBarge && loud(levelOf(f), now())) {     // you talked over the reply: stop it where it is
      const ms = played();
      dropping = true;
      endPlayer();
      send({ type: 'interrupt', played_ms: Math.round(ms) });
    }
    send(toInt16(f).buffer);
  };

  const handle = ev => {
    if (ev.type === 'ready') { ready = true; rate = ev.sample_rate_out || 24000; modBarge = !!ev.interrupt; }
    else if (ev.type === 'interrupted') {               // the mod heard a voice over the reply: stop it where it is
      if (speaking && !dropping) { const ms = played(); dropping = true; endPlayer(); send({ type: 'interrupt', played_ms: Math.round(ms) }); }
      else send({ type: 'interrupt', played_ms: Math.round(played()) });
    }
    else if (ev.type === 'thinking') { dropping = false; loud = bargeTracker(); }
    else if (ev.type === 'said' && ev.final && !dropping) {
      finalSeen = true;
      if (player) player.finish(() => { if (!stopped && finalSeen) { endPlayer(); send({ type: 'played' }); } });
      else send({ type: 'played' });                     // a reply with no audio
    } else if (ev.type === 'turn') { dropping = false; }
    else if (ev.type === 'error' && !ready) ev = { ...ev, fatal: true };
    onEvent(ev);
  };

  const open = () => {
    ws = new WebSocketImpl(url);
    ws.binaryType = 'arraybuffer';
    ws.onopen = () => send({ type: 'start', voice, pause_ms: pauseMs, sample_rate: 16000, save,
      ...(thread ? { thread } : {}), ...(language ? { language } : {}), ...(quant ? { quant } : {}), ...(answers ? { answers } : {}), ...(muted ? { muted } : {}), ...(talkMode === 'push' ? { talk: 'push' } : {}) });
    ws.onmessage = e => {
      if (typeof e.data !== 'string') {
        if (dropping || stopped) return;
        if (!player) { player = new Player(rate); speaking = true; playedFrom = now() + 50; }
        player.push(e.data);
        return;
      }
      let ev; try { ev = JSON.parse(e.data); } catch { return; }
      handle(ev);
    };
    ws.onclose = e => {
      endPlayer();
      if (stopped) return;
      const refused = e.code === 4400 || e.code === 4409 || e.code === 4500 || e.code === 4404 || e.code === 4503 || e.code === 4502;
      if (!refused && ready && !retried) { retried = true; ready = false; onEvent({ type: 'waiting', text: 'Reconnecting…' }); open(); return; }
      stopped = true; mic?.stop();
      if (current === handleOut) current = null;
      if (!refused || e.code === 4404 || e.code === 4503 || e.code === 4502) onEvent({ type: 'error', code: 'unreachable', fatal: true,
        detail: e.code === 4404 ? 'The Voice mod isn’t installed.' : e.code === 4503 ? 'The Voice mod isn’t running.' : 'The connection to the speech model was lost.' });
      onEvent({ type: 'done' });
    };
  };

  const handleOut = {
    mute(on) {
      muted = !!on;
      if (muted) loud = bargeTracker();
      send({ type: 'mute', on: muted });
    },
    talk(on) {
      if (talkMode !== 'push' || muted || !!on === held) return;
      held = !!on;
      if (!held) { send({ type: 'talk', on: false }); return; }
      let ms = null;
      if (speaking) { ms = played(); dropping = true; endPlayer(); }      // a press over the reply stops it where it is
      send({ type: 'talk', on: true, ...(ms != null ? { played_ms: Math.round(ms) } : {}) });
      ring.splice(0).forEach(send);
    },
    stop() {
      if (stopped) return;
      stopped = true;
      endPlayer(); mic?.stop();
      try { send({ type: 'stop' }); ws?.close(); } catch { /* closed already */ }
      if (current === handleOut) current = null;
    },
  };
  current?.stop();
  current = handleOut;
  frames({ mics, onFrame, onMic: label => onEvent({ type: 'mic', label }) }).then(m => {
    if (stopped) { m.stop(); return; }
    mic = m; open();
  }, e => {
    stopped = true;
    if (current === handleOut) current = null;
    onEvent({ type: 'error', code: 'microphone', fatal: true, detail: e?.name === 'NotAllowedError' ? 'Microphone access was refused' : (e?.message || String(e)) });
  });
  return handleOut;
}

/** The mod page's Try it box (services/voice/ui/page.js): a conversation with no chat; nothing is saved.
 * `ctx` is the page module's; returns a cleanup function. */
export function mountTry(el, ctx, onChange = () => {}) {
  const { ui } = ctx;
  let s = liveStep({ mode: 'off' }, { type: 'stop' }), talk = null, lines = [];
  const status = ui.text('', { muted: true, small: true }), log = ui.h('div', { style: 'display:flex;flex-direction:column;gap:6px;font-size:13px' });
  const btn = ui.button('Start talking', () => (talk ? stop() : start()), { kind: 'primary' });
  const draw = () => {
    btn.textContent = talk ? 'Stop' : 'Start talking';
    status.textContent = s.error ? `${s.error}${s.fix ? ` Fix: ${s.fix}` : ''}` : s.mode === 'off' ? 'Talk to the speech model with no chat; nothing is saved. Use headphones if it hears itself.'
      : `${s.note || LIVE_WORDS[s.mode] || ''}${s.model ? ` · ${s.model}` : ''}`;
    const live = [s.you ? ['You', s.you] : null, s.reply ? ['It', s.reply] : null].filter(Boolean);
    log.replaceChildren(...[...lines.slice(-8), ...live].map(([who, text]) => ui.h('div', null, ui.h('strong', null, who + ': '), text)));
  };
  const go = ev => {
    if (ev.type === 'turn') { if (ev.user) lines.push(['You', ev.user]); if (ev.assistant) lines.push(['It', ev.assistant + (ev.first_audio_ms != null ? ` (${ev.first_audio_ms} ms)` : '')]); }
    s = liveStep(s, ev);
    if (s.mode === 'off' && talk) { talk = null; onChange(); }
    draw();
  };
  const start = () => { lines = []; go({ type: 'start' }); talk = liveVoice({ save: false, onEvent: go }); onChange(); };
  const stop = () => { const t = talk; talk = null; t?.stop(); go({ type: 'stop' }); onChange(); };
  el.replaceChildren(ui.card(ui.h('h2', { style: 'margin:0;font-size:15px' }, 'Try it'), ui.h('div', { style: 'display:flex;align-items:center;gap:10px;flex-wrap:wrap' }, btn, status), log));
  el.style.maxWidth = '900px'; el.style.marginTop = '12px';
  draw();
  return () => { talk?.stop(); talk = null; };
}
