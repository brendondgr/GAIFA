// web/chat/chat-voice.js (plan 49.2): voice mode's loop, barge-in and the last reply.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const v = await import(pathToFileURL(path.join(root, 'web/chat/chat-voice.js')).href);
const run = (evs, s = { mode: 'off', text: '', error: null }) => evs.reduce(v.voiceStep, s);

test('a round: listen, a pause sends, think, speak, listen again', () => {
  let s = run([{ type: 'start' }, { type: 'heard', text: 'make a fox' }]);
  assert.equal(s.mode, 'listening');
  assert.equal(v.voiceStep(s, { type: 'quiet', ms: 800, pause: 1200 }).mode, 'listening');     // not quiet long enough
  s = run([{ type: 'quiet', ms: 1300, pause: 1200 }], s);
  assert.deepEqual([s.mode, s.text], ['sending', 'make a fox']);
  s = run([{ type: 'sent' }], s);
  assert.deepEqual([s.mode, s.text], ['thinking', '']);
  s = run([{ type: 'turn_end', text: 'Here it is.' }], s);
  assert.equal(s.mode, 'speaking');
  assert.equal(run([{ type: 'spoken' }], s).mode, 'listening');
  assert.equal(run([{ type: 'turn_end', text: '' }], { mode: 'thinking', text: '' }).mode, 'listening');   // nothing to read
});

test('silence with nothing said sends nothing', () => {
  assert.equal(run([{ type: 'start' }, { type: 'quiet', ms: 9000, pause: 1200 }]).mode, 'listening');
  assert.equal(run([{ type: 'start' }, { type: 'heard', text: '  ' }, { type: 'quiet', ms: 9000, pause: 1200 }]).mode, 'listening');
});

test('talking over the reply stops it and listens', () => {
  assert.equal(run([{ type: 'barge' }], { mode: 'speaking', text: '' }).mode, 'listening');
  assert.equal(run([{ type: 'barge' }], { mode: 'thinking', text: '' }).mode, 'thinking');
  const loud = v.bargeTracker(0.5, 300);
  assert.equal(loud(0.9, 0), false);
  assert.equal(loud(0.9, 200), false);
  assert.equal(loud(0.2, 250), false);       // a dip starts it over
  assert.equal(loud(0.9, 300), false);
  assert.equal(loud(0.9, 620), true);
});

test('a waiting card pauses it; answering carries on', () => {
  let s = run([{ type: 'card' }], { mode: 'thinking', text: '' });
  assert.equal(s.mode, 'paused');
  assert.equal(run([{ type: 'card_done', running: true }], s).mode, 'thinking');
  assert.equal(run([{ type: 'card_done', running: false }], s).mode, 'listening');
  assert.equal(run([{ type: 'card' }], { mode: 'off', text: '' }).mode, 'off');
  assert.equal(run([{ type: 'card_done', running: false }], { mode: 'off', text: '' }).mode, 'off');
});

test('stop and errors end it', () => {
  assert.equal(run([{ type: 'start' }, { type: 'stop' }]).mode, 'off');
  const s = run([{ type: 'start' }, { type: 'error', error: 'Microphone access was refused' }]);
  assert.deepEqual([s.mode, s.error], ['off', 'Microphone access was refused']);
});

test('the last reply', () => {
  const evs = [{ type: 'user', payload: { text: 'hi' } }, { type: 'assistant', payload: { text: 'one' } }, { type: 'tool_call', payload: {} }, { type: 'assistant', payload: { text: 'two' } }, { type: 'assistant', payload: {} }];
  assert.equal(v.lastAnswer(evs), 'two');
  assert.equal(v.lastAnswer([]), '');
});
