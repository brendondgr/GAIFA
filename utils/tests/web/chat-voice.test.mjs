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
  assert.equal(loud(0.2, 250), false);       // a short dip between syllables keeps counting
  assert.equal(loud(0.9, 310), true);
  const l2 = v.bargeTracker(0.5, 300, 250);
  l2(0.9, 0); l2(0.9, 100);
  assert.equal(l2(0.9, 500), false);         // a long gap starts it over
  l2(0.9, 650);
  assert.equal(l2(0.9, 810), true);
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
  assert.deepEqual(v.lastAnswer(evs.map((e, i) => ({ ...e, seq: i + 1 }))), { seq: 4, text: 'two' });
  assert.deepEqual(v.lastAnswer([]), { seq: 0, text: '' });
});

test('the turn has ended only with a newer reply and nothing running', () => {
  assert.equal(v.turnEnded(false, { seq: 4, text: 'old' }, 4), false);    // running blinked off before the reply
  assert.equal(v.turnEnded(true, { seq: 9, text: 'partial' }, 4), false);
  assert.equal(v.turnEnded(false, { seq: 9, text: 'new' }, 4), true);
});

test('voice-speech-model 3.4: which engine a start uses', () => {
  assert.deepEqual(v.pickEngine({ engine: 'speech' }, true, true), { engine: 'speech' });
  assert.deepEqual(v.pickEngine({ engine: 'chat' }, true, true), { engine: 'chat' });
  assert.deepEqual(v.pickEngine(undefined, false, true), { engine: 'chat' });
  const fb = v.pickEngine({ engine: 'speech' }, false, true);                // the Voice mod is missing or stopped
  assert.equal(fb.engine, 'chat'); assert.match(fb.note, /isn’t available: using the chat’s model/);
  assert.equal(v.pickEngine({ engine: 'speech' }, false, false).engine, null);
  const only = v.pickEngine({ engine: 'chat' }, true, false);                // only the Voice mod is installed
  assert.equal(only.engine, 'speech'); assert.match(only.note, /Using the speech model/);
  assert.match(v.pickEngine({ engine: 'chat' }, false, false).error, /needs the Speech to Text and Speech mods, or the Voice mod/);
});

test('voice-mute 1.3: M toggles the mute, except while you type or with a modifier', () => {
  const key = (k, o = {}) => ({ key: k, ctrlKey: false, metaKey: false, altKey: false, repeat: false, target: { tagName: 'DIV' }, ...o });
  assert.equal(v.isMuteKey(key('m')), true);
  assert.equal(v.isMuteKey(key('M')), true);
  assert.equal(v.isMuteKey(key('n')), false);
  for (const o of [{ ctrlKey: true }, { metaKey: true }, { altKey: true }, { repeat: true }]) assert.equal(v.isMuteKey(key('m', o)), false);
  for (const t of [{ tagName: 'TEXTAREA' }, { tagName: 'INPUT' }, { tagName: 'SELECT' }, { tagName: 'DIV', isContentEditable: true }]) assert.equal(v.isMuteKey(key('m', { target: t })), false);
  assert.equal(v.typingIn(null), false);
});

test('voice-mute 2.2: the push-to-talk key, pressed and let go, but not while typing', () => {
  const ev = (type, code, o = {}) => ({ type, code, repeat: false, ctrlKey: false, metaKey: false, altKey: false, target: { tagName: 'BODY' }, ...o });
  assert.equal(v.pushKeyOf(ev('keydown', 'Space'), 'Space'), true);
  assert.equal(v.pushKeyOf(ev('keyup', 'Space'), 'Space'), false);
  assert.equal(v.pushKeyOf(ev('keydown', 'Space', { repeat: true }), 'Space'), null);     // held down: one press
  assert.equal(v.pushKeyOf(ev('keydown', 'KeyM'), 'Space'), null);
  assert.equal(v.pushKeyOf(ev('keydown', 'Space', { target: { tagName: 'TEXTAREA' } }), 'Space'), null);
  assert.equal(v.pushKeyOf(ev('keydown', 'Space', { ctrlKey: true }), 'Space'), null);
  assert.equal(v.pushKeyOf(ev('keydown', 'ControlRight', { ctrlKey: true }), 'ControlRight'), true);
  assert.equal(v.chatPushWords('listening', false, 'Space'), 'Hold Space to talk');
  assert.equal(v.chatPushWords('listening', true, 'Space'), 'Listening… (let go to send)');
  assert.equal(v.chatPushWords('speaking', false, 'F8'), 'Speaking (hold F8 to interrupt)');
  assert.equal(v.KEY_NAMES.ControlRight, 'Right Ctrl');
});
