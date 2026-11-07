// web/chat/chat-memory-note.js (memory-auto-learning 3.3): what the learner took from a chat, as one line.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const { noteOf } = await import(pathToFileURL(path.join(root, 'web/chat/chat-memory-note.js')).href);

test('saved facts first, the rest counted; nothing learned, no note', () => {
  const f = (text, state) => ({ text, state });
  assert.equal(noteOf([]), null);
  assert.equal(noteOf([f('Gone', 'rejected')]), null);
  assert.deepEqual(noteOf([f('The user is learning Rust.', 'active'), f('Prefers tea.', 'active'), f('Health', 'proposed')]),
    { first: 'The user is learning Rust.', more: 1, waiting: 1 });
  assert.deepEqual(noteOf([f('Health', 'proposed')]), { first: '', more: 0, waiting: 1 });
});
