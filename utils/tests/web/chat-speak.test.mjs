// web/chat/chat-speak.js (plan 49.1): what's read aloud, the request, and the player's queue.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const sp = await import(pathToFileURL(path.join(root, 'web/chat/chat-speak.js')).href);

test('a reply as words to read: no citations, links, code or markup', () => {
  const md = '<think>plan</think>## Done\n\nI made **#1** ([BBC](https://bbc.co.uk) #4:12).\n\n```py\nprint(1)\n```\n\n- one\n- two\n\nSee https://example.com';
  const s = sp.speakable(md);
  assert.ok(!/think|https?:|print\(1\)|\*\*|#4:12|##/.test(s), s);
  assert.ok(s.includes('Done') && s.includes('(a code block)') && s.includes('one') && s.includes('two'), s);
  assert.equal(sp.speakable('![The fox](#1) is ready.'), 'The fox is ready.');
  assert.ok(sp.speakable('word. '.repeat(1000)).length <= 4000);
});

test('the request follows the settings', () => {
  assert.deepEqual(sp.speechBody('hi', { voice: 'af_heart', engine: 'kokoro', speed: 1.2 }), { text: 'hi', stream: true, no_save: true, name: 'af_heart', engine: 'kokoro', speed: 1.2 });
  assert.deepEqual(sp.speechBody('hi', {}), { text: 'hi', stream: true, no_save: true, engine: 'auto', speed: 1 });
});

class FakeCtx {
  constructor() { this.currentTime = 0; this.made = []; this.destination = {}; }
  createBuffer(ch, n, rate) { const d = new Float32Array(n); return { duration: n / rate, getChannelData: () => d, n }; }
  createBufferSource() { const s = { connect() {}, start: at => { s.at = at; this.made.push(s); }, stop() {} }; return s; }
  close() { return Promise.resolve(); }
}

test('the player queues chunks one after another, carrying an odd byte', () => {
  const p = new sp.PcmPlayer(1000, FakeCtx);
  p.push(new Uint8Array(201));               // 100 samples + 1 byte carried
  p.push(new Uint8Array(199));               // the carried byte + 199 = 100 samples
  const [a, b] = p.ctx.made;
  assert.equal(a.buffer.n, 100);
  assert.equal(b.buffer.n, 100);
  assert.ok(Math.abs(b.at - (a.at + 0.1)) < 1e-9);
});

test('speak streams the response into the player and ends', async () => {
  const chunks = [new Uint8Array([0, 1, 2, 3]), new Uint8Array([4, 5])];
  const pushed = [];
  class P { constructor(rate) { this.rate = rate; } push(c) { pushed.push(c.length); } finish(cb) { cb(); } stop() {} }
  const fetchImpl = async (url, o) => {
    assert.equal(url, '/api/s/tts/v1/speech');
    assert.equal(JSON.parse(o.body).stream, true);
    let i = 0;
    return { ok: true, headers: new Map([['x-sample-rate', '24000']]), body: { getReader: () => ({ read: async () => (i < chunks.length ? { value: chunks[i++], done: false } : { done: true }) }) } };
  };
  await sp.speak('hello', {}, { fetchImpl, Player: P }).done;
  assert.deepEqual(pushed, [4, 2]);
});
