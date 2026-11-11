// Voice mode on a speech-to-speech model (plan voice-speech-model 3.3): the page's side of the voice mod's
// WebSocket (`/api/s/voice/v1/realtime`, services/voice/voice/bridge.py). The microphone goes up as 16 kHz
// PCM16 frames; the reply comes down as PCM16 and plays as it arrives. The mod finds the end of what you said,
// answers, and writes each turn into the chat; this client plays, shows the words, and tells the mod when a
// reply has finished playing or you talked over it (the microphone staying loud while it plays).
// Written by us (web/PATCHES.md).

import { micFrames, toInt16, levelOf } from './chat-mic.js';
import { PcmPlayer } from './chat-speak.js';
import { bargeTracker } from './chat-voice.js';

/** The socket's address for a page served by the hub. */
export const liveUrl = (loc = globalThis.location) => `${loc.protocol === 'https:' ? 'wss' : 'ws'}://${loc.host}/api/s/voice/v1/realtime`;

export const LIVE_WORDS = { connecting: 'Starting…', listening: 'Listening…', hearing: 'Listening…', thinking: 'Thinking…',
  speaking: 'Speaking (talk to interrupt)', paused: 'Waiting for the chat' };
/** Errors that end the session before it could talk: the caller may fall back to the chat-model engine. */
export const FATAL = new Set(['model_missing', 'engine_missing', 'engine_failed', 'engine_timeout', 'needs_room', 'busy', 'bad_start', 'not_found',
  'gpu_cancelled', 'hub_unreachable', 'context_failed', 'unreachable']);

/** The live loop's next state: {mode, you, reply, model, error, note}. Modes: off, connecting, listening, hearing,
 * thinking, speaking. `you`: your words of the turn under way; `reply`: the answer's text so far. */
export function liveStep(s, ev) {
  switch (ev.type) {
    case 'start': return { mode: 'connecting', you: '', reply: '', model: s.model || '', error: null, note: null };
    case 'stop': case 'done': return { ...s, mode: 'off', you: '', reply: '', note: null };
    case 'waiting': return s.mode === 'off' ? s : { ...s, mode: 'connecting', note: ev.text || 'Waiting for the GPU' };
    case 'ready': return s.mode === 'off' ? s : { ...s, model: ev.model || s.model, note: null };
    case 'listening': return s.mode === 'off' ? s : { ...s, mode: 'listening', you: '', reply: '', note: null, asking: false };
    case 'hearing': return s.mode === 'off' ? s : { ...s, mode: 'hearing', you: '', reply: '' };
    case 'thinking': return s.mode === 'off' ? s : { ...s, mode: 'thinking' };
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
 * drops for good, {type:'error', code:'unreachable', fatal:true}. Returns {stop()}. */
export function liveVoice({ thread, voice = 'female', language, pauseMs = 1200, quant, save = true, mics = [], onEvent,
  url = liveUrl(), WebSocketImpl = globalThis.WebSocket, Player = PcmPlayer, frames = micFrames, now = () => globalThis.performance.now() }) {
  let ws = null, mic = null, player = null, stopped = false, retried = false, ready = false, rate = 24000;
  let speaking = false, dropping = false, playedFrom = null, loud = bargeTracker(), finalSeen = false;
  const send = o => { if (ws && ws.readyState === 1) ws.send(typeof o === 'string' || o instanceof ArrayBuffer ? o : JSON.stringify(o)); };
  const endPlayer = () => { player?.stop(); player = null; speaking = false; playedFrom = null; finalSeen = false; };
  const played = () => (playedFrom == null ? 0 : Math.max(0, now() - playedFrom));

  const onFrame = f => {
    if (stopped || !ready) return;
    if (speaking && loud(levelOf(f), now())) {           // you talked over the reply: stop it where it is
      const ms = played();
      dropping = true;
      endPlayer();
      send({ type: 'interrupt', played_ms: Math.round(ms) });
    }
    send(toInt16(f).buffer);
  };

  const handle = ev => {
    if (ev.type === 'ready') { ready = true; rate = ev.sample_rate_out || 24000; }
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
      ...(thread ? { thread } : {}), ...(language ? { language } : {}), ...(quant ? { quant } : {}) });
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
