// web/chat/chat-voice-live.js (plan voice-speech-model 3.3): the live client of the voice mod's WebSocket.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const L = await import(pathToFileURL(path.join(root, 'web/chat/chat-voice-live.js')).href);
const run = (evs, s = { mode: 'off' }) => evs.reduce(L.liveStep, s);
const tick = () => new Promise(r => setTimeout(r, 0));

test('the state machine: a round, the words, an error that ends it and one that doesn’t', () => {
  let s = run([{ type: 'start' }]);
  assert.equal(s.mode, 'connecting');
  s = run([{ type: 'waiting', text: 'Waiting for the GPU: comfy Image' }], s);
  assert.deepEqual([s.mode, s.note], ['connecting', 'Waiting for the GPU: comfy Image']);
  s = run([{ type: 'ready', model: 'LFM3-Omni-2B Q4_K_M' }, { type: 'listening' }], s);
  assert.deepEqual([s.mode, s.model, s.note], ['listening', 'LFM3-Omni-2B Q4_K_M', null]);
  s = run([{ type: 'hearing' }, { type: 'thinking' }, { type: 'heard', text: 'What is the capital of France?' }, { type: 'speaking' }, { type: 'said', text: 'Paris.' }], s);
  assert.deepEqual([s.mode, s.you, s.reply], ['speaking', 'What is the capital of France?', 'Paris.']);
  s = run([{ type: 'turn' }, { type: 'listening' }], s);
  assert.deepEqual([s.mode, s.you, s.reply], ['listening', '', '']);
  const soft = run([{ type: 'error', code: 'engine_error', detail: 'a reply failed' }], s);
  assert.deepEqual([soft.mode, soft.note], ['listening', 'a reply failed']);
  const hard = run([{ type: 'error', code: 'model_missing', detail: 'not downloaded', fix: 'gaifa setup voice' }], s);
  assert.deepEqual([hard.mode, hard.error, hard.fix], ['off', 'not downloaded', 'gaifa setup voice']);
  const tool = run([{ type: 'tool', name: 'ask_chat', state: 'running', text: 'Asking the chat’s model…' }], s);     // Phase 5
  assert.deepEqual([tool.note, tool.asking], ['Asking the chat’s model…', true]);
  assert.deepEqual([run([{ type: 'tool', name: 'ask_chat', state: 'done' }], tool).note, run([{ type: 'tool', name: 'ask_chat', state: 'done' }], tool).asking], [null, false]);
  assert.match(run([{ type: 'tool', name: 'calendar_add', state: 'refused' }], tool).note, /needs your approval/);
  // 6.3: the chat's agent answers: the turn that follows `thinking` is this conversation's own, until it listens again
  let ag = run([{ type: 'start' }, { type: 'ready', model: 'm', answers: 'agent' }, { type: 'listening' }, { type: 'hearing' }, { type: 'thinking' }]);
  assert.deepEqual([ag.answers, ag.asking], ['agent', true]);
  ag = run([{ type: 'speaking' }, { type: 'said', text: 'Done.' }, { type: 'turn' }, { type: 'listening' }], ag);
  assert.equal(ag.asking, false);
  assert.equal(run([{ type: 'start' }, { type: 'ready', model: 'm', answers: 'speech' }, { type: 'listening' }, { type: 'thinking' }]).asking, false);
  assert.equal(L.LIVE_WORDS.card, 'Waiting for you on screen');
  assert.equal(run([{ type: 'stop' }], s).mode, 'off');
  assert.equal(run([{ type: 'listening' }], { mode: 'off' }).mode, 'off');     // a late event after it ended changes nothing
  assert.equal(L.liveUrl({ protocol: 'https:', host: 'h:1' }), 'wss://h:1/api/s/voice/v1/realtime');
});

// ---- liveVoice with a fake socket, player and microphone
function rig(opts = {}) {
  const sockets = [], players = [], events = [];
  let clock = 0, frame = null;
  class WS {
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
    send(d) { this.sent.push(d); }
    close() { this.readyState = 3; }
    open() { this.readyState = 1; this.onopen(); }
    json(o) { this.onmessage({ data: JSON.stringify(o) }); }
    audio(n = 4800) { this.onmessage({ data: new ArrayBuffer(n) }); }
    drop(code = 1006) { this.readyState = 3; this.onclose({ code }); }
    get texts() { return this.sent.filter(x => typeof x === 'string').map(x => JSON.parse(x)); }
    get frames() { return this.sent.filter(x => typeof x !== 'string'); }
  }
  class Player {
    constructor(rate) { this.rate = rate; this.pushed = 0; this.stopped = false; players.push(this); }
    push(b) { this.pushed += b.byteLength; }
    finish(cb) { this.end = cb; }
    stop() { this.stopped = true; }
  }
  const mic = { stopped: false, stop() { this.stopped = true; } };
  const talk = L.liveVoice({ url: 'ws://x/rt', WebSocketImpl: WS, Player, now: () => clock, onEvent: e => events.push(e), thread: 't_1', voice: 'male', quant: 'q8_0', pauseMs: 800,
    frames: async ({ onFrame }) => { frame = onFrame; return mic; }, ...opts });
  const speak = (level, ms = 100) => { clock += ms; frame(new Float32Array(1600).fill(level)); };
  return { talk, sockets, players, events, mic, speak, advance: ms => { clock += ms; } };
}

test('the microphone goes up once the mod is ready; the reply plays and its end is told', async () => {
  const r = rig();
  await tick();
  const ws = r.sockets[0];
  ws.open();
  assert.deepEqual(ws.texts[0], { type: 'start', voice: 'male', pause_ms: 800, sample_rate: 16000, save: true, thread: 't_1', quant: 'q8_0' });
  r.speak(0.01);
  assert.equal(ws.frames.length, 0);                       // not before `ready`
  ws.json({ type: 'ready', sample_rate_out: 24000, model: 'LFM3-Omni-2B Q8_0' }); ws.json({ type: 'listening' });
  r.speak(0.01); r.speak(0.01);
  assert.equal(ws.frames.length, 2); assert.equal(ws.frames[0].byteLength, 3200);     // 100 ms of PCM16 at 16 kHz
  ws.json({ type: 'thinking' }); ws.json({ type: 'speaking' });
  ws.audio(); ws.audio();
  assert.equal(r.players.length, 1); assert.equal(r.players[0].rate, 24000); assert.equal(r.players[0].pushed, 9600);
  ws.json({ type: 'said', text: 'Paris.', final: true, audio_ms: 200 });
  assert.equal(ws.texts.some(t => t.type === 'played'), false);          // not until it has played out
  r.players[0].end();
  assert.equal(ws.texts.filter(t => t.type === 'played').length, 1);
  ws.json({ type: 'turn', user: 'q', assistant: 'Paris.' });
  assert.deepEqual(r.events.map(e => e.type), ['ready', 'listening', 'thinking', 'speaking', 'said', 'turn']);
  r.talk.stop();
  assert.ok(r.mic.stopped); assert.equal(ws.texts.at(-1).type, 'stop');
});

test('talking over the reply sends one interrupt with what was played, and drops the rest of it', async () => {
  const r = rig();
  await tick();
  const ws = r.sockets[0];
  ws.open(); ws.json({ type: 'ready', sample_rate_out: 24000 }); ws.json({ type: 'listening' });
  ws.json({ type: 'thinking' }); ws.json({ type: 'speaking' }); ws.audio();
  r.advance(1000);
  for (let i = 0; i < 6; i++) r.speak(0.5);                 // loud for 500 ms: past the barge time
  const ints = ws.texts.filter(t => t.type === 'interrupt');
  assert.equal(ints.length, 1); assert.ok(ints[0].played_ms >= 900 && ints[0].played_ms <= 1500, String(ints[0].played_ms));
  assert.ok(r.players[0].stopped);
  ws.audio(); ws.json({ type: 'said', text: 'x', final: true });
  assert.equal(r.players.length, 1);                        // late audio of the cancelled reply isn't played
  assert.equal(ws.texts.some(t => t.type === 'played'), false);
  ws.json({ type: 'turn', interrupted: true }); ws.json({ type: 'hearing' }); ws.json({ type: 'thinking' }); ws.json({ type: 'speaking' }); ws.audio();
  assert.equal(r.players.length, 2);                        // the next reply plays
  for (let i = 0; i < 3; i++) r.speak(0.05);
  assert.equal(ws.texts.filter(t => t.type === 'interrupt').length, 1);   // a quiet room doesn't interrupt
});

test('a dropped socket is opened again once; a second drop ends it; a refusal is not retried', async () => {
  const r = rig();
  await tick();
  r.sockets[0].open(); r.sockets[0].json({ type: 'ready' }); r.sockets[0].json({ type: 'listening' });
  r.sockets[0].drop();
  assert.equal(r.sockets.length, 2); assert.equal(r.events.at(-1).type, 'waiting');
  r.sockets[1].open(); r.sockets[1].json({ type: 'ready' });
  r.sockets[1].drop();
  assert.equal(r.sockets.length, 2);
  assert.deepEqual(r.events.slice(-2).map(e => [e.type, e.code || null]), [['error', 'unreachable'], ['done', null]]);
  assert.ok(r.mic.stopped);

  const busy = rig();
  await tick();
  busy.sockets[0].open(); busy.sockets[0].json({ type: 'error', code: 'busy', detail: 'Another voice conversation is open.' });
  busy.sockets[0].drop(4409);
  assert.equal(busy.sockets.length, 1);
  assert.deepEqual(busy.events.map(e => [e.type, e.fatal || false]), [['error', true], ['done', false]]);   // an error before ready ends it

  const gone = rig();
  await tick();
  gone.sockets[0].drop(4503);                               // the hub's proxy: the mod isn't running
  assert.match(gone.events[0].detail, /isn’t running/);
});

test('one conversation per page, and a refused microphone', async () => {
  const a = rig();
  await tick();
  const b = rig();
  await tick();
  assert.ok(a.mic.stopped); assert.equal(b.mic.stopped, false);     // starting another ended the first
  b.talk.stop();
  const c = rig({ answers: 'agent' });                                // 6.3: who answers goes up with the start
  await tick();
  c.sockets[0].open();
  assert.equal(c.sockets[0].texts[0].answers, 'agent');
  c.talk.stop();
  const events = [];
  L.liveVoice({ url: 'ws://x', WebSocketImpl: class {}, onEvent: e => events.push(e), frames: async () => { const e = new Error('no'); e.name = 'NotAllowedError'; throw e; } });
  await tick();
  assert.deepEqual(events, [{ type: 'error', code: 'microphone', fatal: true, detail: 'Microphone access was refused' }]);
});

test('voice-mute 1.2: muted, no frames go up and nothing interrupts; a reconnect keeps it', async () => {
  const r = rig({ muted: true });
  await tick();
  const ws = r.sockets[0];
  ws.open();
  assert.equal(ws.texts[0].muted, true);                     // the start says so
  ws.json({ type: 'ready', sample_rate_out: 24000, muted: true }); ws.json({ type: 'listening' });
  r.speak(0.5); r.speak(0.5);
  assert.equal(ws.frames.length, 0);
  r.talk.mute(false);
  assert.deepEqual(ws.texts.at(-1), { type: 'mute', on: false });
  r.speak(0.01);
  assert.equal(ws.frames.length, 1);
  ws.json({ type: 'thinking' }); ws.json({ type: 'speaking' }); ws.audio();
  r.talk.mute(true);
  r.advance(500);
  for (let i = 0; i < 8; i++) r.speak(0.9);                  // loud for 800 ms while it speaks: muted, no interrupt
  assert.equal(ws.texts.some(t => t.type === 'interrupt'), false);
  assert.equal(r.players[0].stopped, false); assert.equal(ws.frames.length, 1);
  ws.drop();                                                 // the one reconnect starts muted again
  r.sockets[1].open();
  assert.equal(r.sockets[1].texts[0].muted, true);
  r.talk.stop();
});

test('voice-mute 1.2: the state and the words, muted', () => {
  let s = run([{ type: 'start' }, { type: 'ready', model: 'm', muted: true }, { type: 'listening' }]);
  assert.equal(s.muted, true);
  assert.equal(L.liveWords('listening', s.muted), 'Muted');
  assert.equal(L.liveWords('speaking', true), 'Speaking (muted)');
  assert.equal(L.liveWords('thinking', true), 'Thinking…');
  assert.equal(L.liveWords('listening', false), 'Listening…');
  s = run([{ type: 'muted', on: false }, { type: 'hearing' }, { type: 'heard', text: 'half a' }], s);
  assert.deepEqual([s.muted, s.mode], [false, 'hearing']);
  s = run([{ type: 'muted', on: true }], s);                 // muting mid-sentence: it listens again, the words dropped
  assert.deepEqual([s.muted, s.mode, s.you], [true, 'listening', '']);
  assert.equal(run([{ type: 'start' }], s).muted, true);     // a new session (after a pause) keeps it
});

test('voice-mute 2.2: push to talk sends frames only while held, with the 400 ms before the press', async () => {
  const r = rig({ talk: 'push' });
  await tick();
  const ws = r.sockets[0];
  ws.open();
  assert.equal(ws.texts[0].talk, 'push');
  ws.json({ type: 'ready', sample_rate_out: 24000, talk: 'push' }); ws.json({ type: 'listening' });
  for (let i = 0; i < 10; i++) r.speak(0.9);                // a second of loud noise, not held
  assert.equal(ws.frames.length, 0);
  r.talk.talk(true);
  assert.deepEqual(ws.texts.at(-1), { type: 'talk', on: true });
  assert.equal(ws.frames.length, 4);                        // the pre-roll: 4 frames of 100 ms
  r.speak(0.3); r.speak(0.3);
  assert.equal(ws.frames.length, 6);
  r.talk.talk(false);
  assert.deepEqual(ws.texts.at(-1), { type: 'talk', on: false });
  r.speak(0.3);
  assert.equal(ws.frames.length, 6);
  ws.json({ type: 'thinking' }); ws.json({ type: 'speaking' }); ws.audio();
  r.advance(800);
  for (let i = 0; i < 8; i++) r.speak(0.9);                 // loud while it speaks: nothing in push to talk
  assert.equal(ws.texts.some(t => t.type === 'interrupt'), false); assert.equal(r.players[0].stopped, false);
  r.talk.talk(true);                                         // the press stops the reply and says how much played
  const press = ws.texts.at(-1);
  assert.equal(press.type, 'talk'); assert.ok(press.played_ms >= 700, String(press.played_ms));
  assert.ok(r.players[0].stopped);
  r.talk.talk(false);
  const words = run([{ type: 'start' }, { type: 'ready', talk: 'push' }, { type: 'listening' }]);
  assert.equal(words.talk, 'push');
  assert.equal(L.liveWords('listening', false, { key: 'Space', held: false }), 'Hold Space to talk');
  assert.equal(L.liveWords('hearing', false, { key: 'Space', held: true }), 'Listening… (let go to send)');
  assert.equal(L.liveWords('speaking', false, { key: 'F8', held: false }), 'Speaking (hold F8 to interrupt)');
  const open = rig();                                        // always listening: talk() does nothing
  await tick();
  open.sockets[0].open(); open.sockets[0].json({ type: 'ready' });
  open.talk.talk(true);
  assert.equal(open.sockets[0].texts.some(t => t.type === 'talk'), false);
  open.talk.stop(); r.talk.stop();
});
