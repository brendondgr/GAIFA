// Plan 29.3: the composer's dictation (web/chat/chat-mic.js): the 16 kHz resampler the AudioWorklet
// runs, int16 framing, and the message protocol with the stt mod's WS /v1/stream (driven with a fake
// socket, microphone and AudioContext).
import test from 'node:test';
import assert from 'node:assert/strict';
import { Resampler, toInt16, startMessage, initial, reduce, dictated, joinDraft, streamUrl, dictate, RATE } from '../../../web/chat/chat-mic.js';

const sine = (rate, hz, secs) => Float32Array.from({ length: Math.round(rate * secs) }, (_, i) => Math.sin(2 * Math.PI * hz * i / rate));
const crossings = a => { let n = 0; for (let i = 1; i < a.length; i++) if ((a[i - 1] < 0) !== (a[i] < 0)) n++; return n; };
function chunked(r, input, size) {
  const parts = [];
  for (let i = 0; i < input.length; i += size) parts.push(r.push(input.subarray(i, i + size)));
  const out = new Float32Array(parts.reduce((n, p) => n + p.length, 0));
  let p = 0; for (const x of parts) { out.set(x, p); p += x.length; }
  return out;
}

test('48 kHz → 16 kHz keeps the length, the pitch and the level', () => {
  const out = chunked(new Resampler(48000), sine(48000, 440, 1), 128);
  assert.ok(Math.abs(out.length - 16000) <= 3, `length ${out.length}`);
  assert.ok(Math.abs(crossings(out) - 880) <= 4, `crossings ${crossings(out)}`);
  const peak = Math.max(...out.slice(100).map(Math.abs));
  assert.ok(peak > 0.97 && peak <= 1.0001, `peak ${peak}`);
});

test('a tone above 8 kHz is damped rather than folded back at full level', () => {
  const out = chunked(new Resampler(48000), sine(48000, 15000, 0.5), 128);
  const rms = Math.sqrt(out.reduce((s, x) => s + x * x, 0) / out.length);
  assert.ok(rms < 0.35, `rms ${rms}`);                       // a full-level sine has rms 0.707
});

test('chunked output equals the whole-array output, whatever the chunk size', () => {
  const input = sine(44100, 300, 0.7);
  const whole = new Resampler(44100).push(input);
  for (const size of [128, 441, 1000]) {
    const parts = chunked(new Resampler(44100), input, size);
    assert.equal(parts.length, whole.length, `size ${size}`);
    for (let i = 0; i < whole.length; i++) assert.ok(Math.abs(parts[i] - whole[i]) < 1e-6);
  }
  assert.ok(Math.abs(whole.length - 0.7 * RATE) <= 3);
});

test('16 kHz passes through unchanged', () => {
  const input = sine(16000, 200, 0.1);
  const out = new Resampler(16000).push(input);
  assert.equal(out.length, input.length - 1);                   // the last sample waits for the next chunk
  for (let i = 0; i < out.length; i++) assert.ok(Math.abs(out[i] - input[i]) < 1e-6);
});

test('int16 frames clip and round', () => {
  assert.deepEqual([...toInt16(Float32Array.from([0, 1, -1, 2, -2, 0.5]))], [0, 32767, -32767, 32767, -32768, 16384]);
});

test('the protocol: start, then committed text plus the replaceable tail', () => {
  assert.deepEqual(startMessage(), { type: 'start', encoding: 'int16', sample_rate: 16000 });
  assert.deepEqual(startMessage({ preset: 'fast', language: 'en' }).preset, 'fast');
  let s = initial();
  for (const ev of [{ type: 'ready', model: 'small' }, { type: 'hypothesis', text: 'hello wor', start: 0 },
    { type: 'committed', segment: { id: 1, text: 'Hello world.' } }, { type: 'hypothesis', text: 'how are', start: 1.2 }]) s = reduce(s, ev);
  assert.equal(s.ready, true);
  assert.equal(dictated(s), 'Hello world. how are');
  s = reduce(s, { type: 'hypothesis', text: '', start: 2 });
  assert.equal(dictated(s), 'Hello world.');
  s = reduce(s, { type: 'done', text: 'Hello world. How are you?' });
  assert.equal(s.done, true);
  assert.equal(dictated(s), 'Hello world. How are you?');
  assert.equal(reduce(initial(), { type: 'error', detail: 'nope' }).error, 'nope');
});

test('dictation joins what was typed', () => {
  assert.equal(joinDraft('', 'hi'), 'hi');
  assert.equal(joinDraft('Note:', 'hi'), 'Note: hi');
  assert.equal(joinDraft('Note: ', 'hi'), 'Note: hi');
  assert.equal(joinDraft('Note:', ''), 'Note:');
  assert.equal(streamUrl({ protocol: 'http:', host: '127.0.0.1:7000' }), 'ws://127.0.0.1:7000/api/s/stt/v1/stream');
  assert.equal(streamUrl({ protocol: 'https:', host: 'hub.localhost' }), 'wss://hub.localhost/api/s/stt/v1/stream');
});

test('dictate(): start → frames once ready → stop → done, and the microphone is released', async () => {
  const sent = [], sockets = [], tracks = [{ stopped: false, stop() { this.stopped = true; } }];
  globalThis.WebSocket = class { constructor(url) { this.url = url; this.readyState = 1; sockets.push(this); } send(d) { sent.push(d); } close() { this.readyState = 3; } };
  globalThis.AudioContext = class { constructor() { this.audioWorklet = { addModule: async () => {} }; } createMediaStreamSource() { return { connect() {}, disconnect() {} }; } close() { this.closed = true; return Promise.resolve(); } };
  let node;
  globalThis.AudioWorkletNode = class { constructor(_, name) { this.name = name; this.port = {}; node = this; } disconnect() {} };
  const media = { getUserMedia: async () => ({ getTracks: () => tracks }) };
  const states = [];
  const d = await dictate({ media, url: 'ws://x/api/s/stt/v1/stream', onState: s => states.push(s) });
  const ws = sockets[0];
  assert.equal(node.name, 'mic-16k');
  ws.onopen();
  assert.deepEqual(JSON.parse(sent[0]), startMessage());
  node.port.onmessage({ data: new Float32Array(1600) });           // before ready: dropped
  assert.equal(sent.length, 1);
  ws.onmessage({ data: JSON.stringify({ type: 'ready', model: 'small' }) });
  node.port.onmessage({ data: new Float32Array(1600).fill(0.5) });
  assert.ok(sent[1] instanceof ArrayBuffer && sent[1].byteLength === 3200);
  assert.equal(new Int16Array(sent[1])[0], 16384);
  ws.onmessage({ data: JSON.stringify({ type: 'committed', segment: { id: 1, text: 'Hello there.' } }) });
  const over = d.stop();
  assert.deepEqual(JSON.parse(sent.at(-1)), { type: 'stop' });
  assert.ok(tracks[0].stopped);
  ws.onmessage({ data: JSON.stringify({ type: 'done', text: 'Hello there.', duration: 1.2 }) });
  const last = await over;
  assert.equal(last.done, true);
  assert.equal(dictated(states.at(-1)), 'Hello there.');
});

test('dictate(): a refused stream reports why', async () => {
  const sockets = [];
  globalThis.WebSocket = class { constructor() { this.readyState = 1; sockets.push(this); } send() {} close() {} };
  const media = { getUserMedia: async () => ({ getTracks: () => [] }) };
  const states = [];
  const d = await dictate({ media, onState: s => states.push(s), url: 'ws://x' });
  sockets[0].onclose({ code: 4503, reason: 'Speech to Text is not running' });
  assert.equal(states.at(-1).error, 'Speech to Text is not running');
  assert.equal((await d.stop()).error, 'Speech to Text is not running');
});
