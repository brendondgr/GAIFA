// web/chat/chat-mentions.js (plan 48.2): the @ token, its choices, the pick, and what's sent.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const m = await import(pathToFileURL(path.join(root, 'web/chat/chat-mentions.js')).href);

const CHOICES = [...m.localChoices([{ n: 3, output_id: 'aaaaaaaaaaaa', kind: 'image', title: 'Fox' }], [{ path: '/home/me/notes', level: 'read' }]),
  { kind: 'voice', id: 'Brendon', label: 'Brendon', fills: ['tts_speak.name'] }, { kind: 'voice', id: 'af_heart', label: 'af_heart', fills: ['tts_speak.name'] },
  { kind: 'workflow', id: 'zimage-turbo', label: 'Z-Image Turbo', fills: ['comfy_generate_image.workflow'] }];

test('the token at the caret', () => {
  assert.deepEqual(m.atToken('say it with @voi', 16), { start: 12, end: 16, kind: null, query: 'voi' });
  assert.deepEqual(m.atToken('say @voice:Bre now', 14), { start: 4, end: 14, kind: 'voice', query: 'Bre' });
  assert.equal(m.atToken('mail me@example.com', 19), null);           // not at a word start
  assert.equal(m.atToken('no token', 8), null);
});

test('choices narrow by kind, words and #n', () => {
  assert.deepEqual(m.filterChoices(CHOICES, m.atToken('@voice:', 7)).map(c => c.id), ['Brendon', 'af_heart']);
  assert.deepEqual(m.filterChoices(CHOICES, m.atToken('@turbo', 6)).map(c => c.id), ['zimage-turbo']);
  assert.deepEqual(m.filterChoices(CHOICES, m.atToken('@voi', 4)).map(c => c.id), ['Brendon', 'af_heart']);   // the start of a kind
  assert.deepEqual(m.filterChoices(CHOICES, m.atToken('@#3', 3)).map(c => c.kind), ['output']);
  assert.deepEqual(m.filterChoices(CHOICES, m.atToken('@notes', 6)).map(c => c.kind), ['folder']);
});

test('a pick writes its token; an output writes none; only tokens still there are sent', () => {
  const tok = m.atToken('say hi with @Bre please', 16);
  const r = m.insertMention('say hi with @Bre please', tok, CHOICES[2]);
  assert.deepEqual(r, { text: 'say hi with @voice:Brendon please', caret: 27 });
  const o = m.insertMention('look at @#3', m.atToken('look at @#3', 11), CHOICES[0]);
  assert.equal(o.text, 'look at ');
  assert.deepEqual(m.mentionsIn(r.text, [CHOICES[2], CHOICES[4]]), [{ kind: 'voice', id: 'Brendon', label: 'Brendon', fills: ['tts_speak.name'] }]);
  assert.deepEqual(m.mentionsIn('say hi with @voice:Brend', [CHOICES[2]]), []);       // edited away: dropped
});
