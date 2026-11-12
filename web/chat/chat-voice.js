// Voice mode (plan 49.2): talk to the agent hands-free. The button by the microphone starts it: listen (the stt
// mod's live stream, as dictation) → after a pause (Settings → Speech → Voice, `pause_ms`) send what you said →
// read the reply aloud (chat-speak.js) → listen again. Speaking while it reads stops the reading and listens (the
// mic has echo cancellation; a sustained loud level counts). A card waiting for you (an approval, a question)
// pauses it: the bar says so, and it carries on once you've answered on screen. Escape or the button ends it.
//
// Two engines (plan voice-speech-model 3.4; Settings → Speech → Voice mode, `[voice_mode] engine`): `chat` is the
// loop above (ChatVoiceButton); `speech` is the voice mod's speech-to-speech model (LiveVoice, over
// chat-voice-live.js). With it, `[voice_mode] answers` says who answers (6.3): `agent`, the chat's own model with its
// tools, apps and cards (your words go in as a message; the speech model hears and speaks), or `speech`, the speech
// model by itself. The bar has the switch. VoiceButton reads the setting each time
// voice mode starts, and falls back to the chat engine when the speech model can't run.
//
// Both bars have a mute button (plan voice-mute 1.3; M toggles it when no text field has the focus): muted, nothing
// the microphone picks up starts a turn or stops a reply, which goes on. `[voice_mode] start_muted` starts muted.

import { h, T, Icon, boxBtn } from './chat-ui.js';
import { dictate, dictated, levelOf, speechSettings, useSttUp } from './chat-mic.js';
import { speak, speakable } from './chat-speak.js';
import { liveVoice, liveStep, liveWords } from './chat-voice-live.js';

const R = () => globalThis.React;
export const BARGE_LEVEL = 0.5, BARGE_MS = 350, BARGE_GAP = 250, SETTLE_MS = 700;

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

/** True once the mic has been loud for `ms` (barge-in while the reply is read); dips under `gap` ms between
 * syllables don't start it over. */
export function bargeTracker(level = BARGE_LEVEL, ms = BARGE_MS, gap = BARGE_GAP) {
  let since = null, last = -Infinity;
  return (lv, now) => {
    if (lv < level) return false;
    if (since == null || now - last > gap) since = now;
    last = now;
    return now - since >= ms;
  };
}

/** The chat's last reply: {seq, text} ({seq: 0, text: ''} before any). */
export const lastAnswer = events => {
  const e = [...(events || [])].reverse().find(x => x.type === 'assistant' && x.payload?.text);
  return e ? { seq: e.seq || 0, text: e.payload.text } : { seq: 0, text: '' };
};

/** A turn voice mode sent has ended: not running, and a reply newer than what it saw when it sent. */
export const turnEnded = (running, answer, sentSeq) => !running && answer.seq > sentSeq;

const MUTED_WORDS = { listening: 'Muted', speaking: 'Speaking (muted)' };
const WORDS = { listening: 'Listening…', sending: 'Sending…', thinking: 'Thinking…', speaking: 'Speaking (talk to interrupt)', paused: 'Waiting for you on screen' };

/** Which engine a start uses: {engine: 'speech' | 'chat', note?}. `vm`: settings.voice_mode; `voiceUp`: the voice
 * mod is running; `chatOk`: the stt and tts mods can run the chat engine. */
export function pickEngine(vm, voiceUp, chatOk) {
  if (vm?.engine === 'speech') {
    if (voiceUp) return { engine: 'speech' };
    return chatOk ? { engine: 'chat', note: 'The speech model isn’t available: using the chat’s model' } : { engine: null, error: 'The Voice mod isn’t running' };
  }
  if (chatOk) return { engine: 'chat' };
  return voiceUp ? { engine: 'speech', note: 'Using the speech model: the Speech to Text and Speech mods aren’t running' }
    : { engine: null, error: 'Voice mode needs the Speech to Text and Speech mods, or the Voice mod' };
}

/** The focus is somewhere you type: keys there are text, not voice mode's shortcuts. */
export const typingIn = el => !!el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName));
/** M (no modifier keys, not while typing) toggles the mute. */
export const isMuteKey = e => (e.key === 'm' || e.key === 'M') && !e.ctrlKey && !e.metaKey && !e.altKey && !e.repeat && !typingIn(e.target);

const muteBtn = (muted, onClick) => h('button', { type: 'button', onClick, 'aria-pressed': muted ? 'true' : 'false',
  'aria-label': muted ? 'Unmute the microphone' : 'Mute the microphone',
  title: muted ? 'Muted: nothing is heard (M to unmute). The browser keeps the microphone open so unmuting is instant.' : 'Mute the microphone (M): background noise won’t start a turn or stop a reply',
  style: { display: 'inline-flex', alignItems: 'center', gap: 4, border: '1px solid ' + (muted ? T.rd : T.bds), borderRadius: 6, background: 'none',
    color: muted ? T.rd : T.tx, font: 'inherit', fontSize: 11.5, padding: '2px 7px', cursor: 'pointer', whiteSpace: 'nowrap' } },
  h(Icon, { d: muted ? 'micOff' : 'mic', size: 12 }), muted ? 'Muted' : 'Mute');

const bar = (dot, words, text, extra, sw) => h('div', { role: 'status', style: { position: 'absolute', left: 0, right: 0, bottom: 'calc(100% + 6px)', zIndex: 25, display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
  background: T.card, border: '1px solid ' + T.bds, borderRadius: 9, boxShadow: '0 12px 30px rgba(0,0,0,.3)', fontSize: 12.5 } },
  h('span', { 'aria-hidden': 'true', style: { width: 8, height: 8, borderRadius: '50%', flex: 'none', background: dot } }),
  h('span', { style: { fontWeight: 600, whiteSpace: 'nowrap' } }, 'Voice mode'),
  extra ? h('span', { style: { color: T.dim, whiteSpace: 'nowrap' } }, extra) : null,
  sw || null,
  h('span', { style: { color: T.mut, whiteSpace: 'nowrap' } }, words),
  text ? h('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: T.tx } }, text) : h('span', { style: { flex: 1 } }),
  h('span', { style: { color: T.dim, fontSize: 11.5, whiteSpace: 'nowrap' } }, 'Esc ends'));
const voiceBtn = (on, disabled, onClick) => h('button', { type: 'button', disabled, onClick, title: on ? 'End voice mode' : 'Voice mode: talk, and hear the replies',
  'aria-label': on ? 'End voice mode' : 'Voice mode', 'aria-pressed': on ? 'true' : 'false',
  style: { ...boxBtn(on), cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.5 : 1 } },
  h(Icon, { d: 'speaker', size: 14 }));

/** True while the mod `id` is up; checked on mount and every 20 s. */
export function useModUp(api, id) {
  const React = R(), [up, setUp] = React.useState(false);
  React.useEffect(() => {
    let live = true;
    const check = () => api?.getService?.(id).then(s => live && setUp(['ready', 'degraded'].includes(s.state))).catch(() => live && setUp(false));
    check();
    const t = setInterval(check, 20000);
    return () => { live = false; clearInterval(t); };
  }, [api, id]);
  return up;
}

/** The speech engine while it is on: the bar and the pressed button. `cfg`: {voice, quant, pauseMs, language, mics, note,
 * answers, onAnswers(next)}: who answers, and the bar's switch saving it;
 * `thread()`: the chat's id (made when the chat is new); `onOff(fallback?)`: it ended (fallback: {note} to carry on
 * with the chat engine). A turn of the chat's own (a typed message, a card) pauses it; it starts again afterwards
 * as a new session, which then knows that turn. */
export function LiveVoice({ cfg, thread, running, waiting, disabled, onOff, onMode, start = liveVoice }) {
  const React = R(), [s, setS] = React.useState(() => liveStep({ mode: 'off' }, { type: 'start' }));
  const talk = React.useRef(null), ended = React.useRef(false), asking = React.useRef(false), agent = React.useRef(false);
  const [answers, setAnswers] = React.useState(cfg.answers === 'speech' ? 'speech' : 'agent');
  const [muted, setMuted] = React.useState(!!cfg.startMuted), mutedRef = React.useRef(!!cfg.startMuted);
  const toggleMute = () => { const n = !mutedRef.current; mutedRef.current = n; setMuted(n); talk.current?.mute(n); };
  const hold = (running || waiting) && !asking.current && !s.asking;     // not during the chat's turn this conversation started itself
  const end = fb => { if (ended.current) return; ended.current = true; talk.current?.stop(); talk.current = null; onOff(fb); };
  React.useEffect(() => { onMode?.('listening'); return () => { talk.current?.stop(); talk.current = null; onMode?.('off'); }; }, []);
  React.useEffect(() => {
    if (hold || ended.current) { talk.current?.stop(); talk.current = null; return undefined; }
    let live = true;
    setS(p => liveStep(p, { type: 'start' }));
    Promise.resolve().then(thread).then(tid => {
      if (!live || ended.current) return;
      talk.current = start({ thread: tid, answers, muted: mutedRef.current, voice: cfg.voice, quant: cfg.quant, pauseMs: cfg.pauseMs, language: cfg.language, mics: cfg.mics, onEvent: ev => {
        if (!live) return;
        if (ev.type === 'done') { if (!ended.current && talk.current) end(); return; }
        if (ev.type === 'ready') agent.current = ev.answers === 'agent';
        if (ev.type === 'thinking' && agent.current) asking.current = true;       // the chat's agent answers: its turn is ours
        if (ev.type === 'tool' && ev.name === 'ask_chat') asking.current = ev.state === 'running';
        if (ev.type === 'listening') asking.current = false;
        setS(p => { const n = liveStep(p, ev); if (n.mode === 'off' && n.error) setTimeout(() => end({ note: n.error, code: n.code, fix: n.fix }), 0); return n; });
      } });
    }, e => end({ note: e?.detail || e?.message || 'The chat could not be started' }));
    return () => { live = false; talk.current?.stop(); talk.current = null; };
  }, [hold, answers]);
  React.useEffect(() => {
    const keys = e => { if (e.key === 'Escape') end(); else if (isMuteKey(e)) { e.preventDefault(); toggleMute(); } };
    globalThis.addEventListener('keydown', keys);
    return () => globalThis.removeEventListener('keydown', keys);
  }, []);
  const mode = hold ? 'paused' : waiting && s.asking ? 'card' : s.mode, words = (mode !== 'card' && s.note) || liveWords(mode, muted);
  const flip = () => { const n = answers === 'agent' ? 'speech' : 'agent'; asking.current = false; setAnswers(n); cfg.onAnswers?.(n); };
  const sw = h('button', { type: 'button', onClick: flip, disabled: hold, 'aria-label': 'Who answers: ' + (answers === 'agent' ? 'the chat’s agent' : 'the speech model itself') + '. Switch',
    title: answers === 'agent' ? 'The chat’s agent answers, with its tools and apps. Click to talk to the speech model itself.' : 'The speech model answers by itself. Click to have the chat’s agent answer, with its tools and apps.',
    style: { border: '1px solid ' + T.bds, borderRadius: 6, background: 'none', color: T.tx, font: 'inherit', fontSize: 11.5, padding: '2px 7px', cursor: hold ? 'default' : 'pointer', whiteSpace: 'nowrap' } },
    answers === 'agent' ? 'Agent answers' : 'Speech model answers');
  const quietDot = muted && (mode === 'listening' || mode === 'hearing');
  const text = mode === 'speaking' || (mode === 'thinking' && s.reply) ? s.reply : s.you ? '“' + s.you + '”' : cfg.note || '';
  return h(R().Fragment, null,
    bar(mode === 'paused' || mode === 'card' ? T.pu : quietDot ? T.dim : mode === 'listening' || mode === 'hearing' ? T.gr : T.acc, words, text,
      s.model ? '· ' + s.model.replace(/ Q\d.*$/, '') : '· speech model', h(R().Fragment, null, muteBtn(muted, toggleMute), sw)),
    voiceBtn(true, disabled, () => end()));
}

/** Voice mode's button: reads Settings → Speech → Voice mode when it starts and runs that engine. */
export function VoiceButton(props) {
  const React = R(), { api, thread, running, waiting, disabled, onMode } = props;
  const voiceUp = useModUp(api, 'voice'), [live, setLive] = React.useState(null), [fb, setFb] = React.useState({ n: 0, note: null });
  const intercept = async chatOk => {
    const st = await api?.getSettings?.().catch(() => null);
    const pick = pickEngine(st?.voice_mode, voiceUp, chatOk);
    if (pick.engine === 'speech') {
      setLive({ answers: st?.voice_mode?.answers || 'agent', startMuted: !!st?.voice_mode?.start_muted, onAnswers: n => api?.saveSettings?.({ voice_mode: { answers: n } }).catch(() => {}),
        voice: st?.voice_mode?.voice || 'female', quant: st?.voice_mode?.quant || 'q4_k_m', pauseMs: st?.speech_output?.pause_ms || 1200,
        language: st?.speech_input?.language || undefined, mics: st?.speech_input?.mics || [], note: pick.note });
      return { taken: true };
    }
    return { taken: false, note: pick.note, error: pick.error, startMuted: !!st?.voice_mode?.start_muted };
  };
  if (live) return h(LiveVoice, { cfg: live, thread: thread || (() => null), running, waiting, disabled, onMode,
    onOff: fallback => { setLive(null); if (fallback) setFb(f => ({ n: f.n + 1, note: `The speech model isn’t available (${fallback.note}): using the chat’s model`, error: fallback.fix ? `${fallback.note} Fix: ${fallback.fix}` : fallback.note })); } });
  return h(ChatVoiceButton, { ...props, intercept, show: voiceUp, autoStart: fb });
}

export function ChatVoiceButton({ api, onSend, running, waiting, answer = { seq: 0, text: '' }, speechOutput, disabled, onMode, intercept, show, autoStart }) {
  const React = R(), up = useSttUp(api), [s, setS] = React.useState({ mode: 'off', text: '', error: null });
  const st = React.useRef(s), sentSeq = React.useRef(0), dict = React.useRef(null), reading = React.useRef(null), timers = React.useRef({});
  const go = ev => setS(prev => { const n = voiceStep(prev, ev); st.current = n; return n; });
  const pause = speechOutput?.pause_ms || 1200, [note, setNote] = React.useState(null), chatOk = !!(up && speechOutput);
  const [muted, setMuted] = React.useState(false), mutedRef = React.useRef(false);
  const begin = async () => {        // the button: which engine? (the speech engine takes it over in VoiceButton)
    const r = intercept ? await intercept(chatOk) : { taken: false };
    if (r.taken) return;
    if (!chatOk) { setS(p => ({ ...p, error: r.error || 'Voice mode needs the Speech to Text and Speech mods' })); return; }
    setNote(r.note || null);
    mutedRef.current = !!r.startMuted; setMuted(!!r.startMuted);
    go({ type: 'start' });
  };
  const toggleMute = () => {         // muted: dictation stops (what it had is dropped) and nothing stops the reading
    const n = !mutedRef.current;
    mutedRef.current = n; setMuted(n);
    if (n) { stopListening(); go({ type: 'heard', text: '' }); } else if (st.current.mode === 'listening' && !dict.current) listen();
  };
  React.useEffect(() => {            // the speech engine gave up: carry on with this one, or say why not
    if (!autoStart?.n) return;
    if (chatOk) { setNote(autoStart.note); go({ type: 'start' }); } else setS(p => ({ ...p, error: autoStart.error || autoStart.note }));
  }, [autoStart?.n]);

  const stopListening = () => { clearInterval(timers.current.quiet); const d = dict.current; dict.current = null; return d ? d.stop() : Promise.resolve(null); };
  const stopReading = () => { reading.current?.stop(); reading.current = null; clearInterval(timers.current.barge); timers.current.bargeMic?.stop(); };
  const listen = async () => {
    let heardAt = Date.now(), last = '';
    try {
      const settings = await speechSettings(api);
      dict.current = await dictate({ preset: settings.preset, language: settings.language || undefined, mics: settings.mics, onState: d => {
        if (mutedRef.current) return;
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
    if (m === 'listening' && !dict.current && !mutedRef.current) listen();
    if (m === 'sending') {
      const text = s.text.trim();
      stopListening().then(() => { sentSeq.current = answer.seq; onSend(text); go({ type: 'sent' }); });
    }
    if (m === 'speaking' && !reading.current) {
      const words = speakable(answer.text);
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
      const ctx = new AudioContext(); ctx.resume?.().catch(() => {});
      const an = ctx.createAnalyser(), buf = new Float32Array(1024), loud = bargeTracker();
      ctx.createMediaStreamSource(stream).connect(an);
      timers.current.bargeMic = { stop: () => { stream.getTracks().forEach(t => t.stop()); ctx.close().catch(() => {}); } };
      timers.current.barge = setInterval(() => { an.getFloatTimeDomainData(buf); if (!mutedRef.current && loud(levelOf(buf), Date.now())) { stopReading(); go({ type: 'barge' }); } }, 60);
    } catch { /* no mic for barge-in: it reads to the end */ }
  };

  // the turn: thinking → speaking when it ends; a waiting card pauses
  React.useEffect(() => {     // it settles first: `running` can blink off as the turn starts
    if (s.mode !== 'thinking' || !turnEnded(running, answer, sentSeq.current)) return undefined;
    const t = setTimeout(() => go({ type: 'turn_end', text: speakable(answer.text) }), SETTLE_MS);
    return () => clearTimeout(t);
  }, [running, answer.seq, s.mode]);
  React.useEffect(() => { go({ type: waiting ? 'card' : 'card_done', running }); }, [waiting]);
  React.useEffect(() => {
    if (s.mode === 'off') return undefined;
    const keys = e => { if (e.key === 'Escape') go({ type: 'stop' }); else if (isMuteKey(e)) { e.preventDefault(); toggleMute(); } };
    globalThis.addEventListener('keydown', keys);
    return () => globalThis.removeEventListener('keydown', keys);
  }, [s.mode === 'off']);
  React.useEffect(() => () => { stopListening(); stopReading(); }, []);

  const on = s.mode !== 'off';
  if (!chatOk && !on && !show) return null;     // needs the stt mod (listening) and the tts mod (speech_output's voices), or the voice mod
  return h(R().Fragment, null,
    on ? bar(s.mode === 'paused' ? T.pu : s.mode === 'listening' ? (muted ? T.dim : T.gr) : T.acc, muted ? MUTED_WORDS[s.mode] || WORDS[s.mode] || '' : WORDS[s.mode] || '',
      s.text ? '“' + s.text + '”' : note || '', null, muteBtn(muted, toggleMute)) : null,
    s.error && !on ? h('span', { role: 'alert', style: { fontSize: 11.5, color: T.rd } }, s.error) : null,
    voiceBtn(on, disabled, () => (on ? go({ type: 'stop' }) : begin())));
}
