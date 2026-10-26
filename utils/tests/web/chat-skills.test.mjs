// web/chat/chat-skills.js (skill-sources 3.2): Settings → Agent → Skills groups the skills by source and reads
// what the user picks (a folder, a zip, a SKILL.md) into the agent's upload body.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const S = await import(pathToFileURL(path.join(root, 'web/chat/chat-skills.js')).href);
const file = (name, text, rel = '') => ({ name, webkitRelativePath: rel, arrayBuffer: async () => new TextEncoder().encode(text).buffer });
const unb64 = s => Buffer.from(s, 'base64').toString();

test('skills are grouped: yours, learned, then each mod', () => {
  const g = S.groupSkills([{ id: 'comfy/a', source: 'comfy' }, { id: 'user/b', source: 'user' }, { id: 'user/c', source: 'harness' },
    { id: 'tts/d', source: 'tts' }, { id: 'comfy/e', source: 'comfy' }]);
  assert.deepEqual(g.map(x => [x.title, x.items.map(i => i.id)]), [['Yours', ['user/b']], ['Learned', ['user/c']],
    ['comfy', ['comfy/a', 'comfy/e']], ['tts', ['tts/d']]]);
  assert.deepEqual(S.groupSkills([]), []);
});

test('a picked folder keeps its paths, hidden files left out', async () => {
  const body = await S.uploadBody([file('SKILL.md', '---\nname: a\n', 'a/SKILL.md'), file('x.md', 'X', 'a/references/x.md'),
    file('.DS_Store', 'junk', 'a/.DS_Store')]);
  assert.deepEqual(body.files.map(f => f.path), ['a/SKILL.md', 'a/references/x.md']);
  assert.equal(unb64(body.files[1].data), 'X');
  assert.equal(body.replace, undefined);
});

test('one zip is sent whole; one SKILL.md by its name', async () => {
  const z = await S.uploadBody([file('skill.zip', 'PK\u0003\u0004')], true);
  assert.equal(unb64(z.zip), 'PK\u0003\u0004');
  assert.equal(z.replace, true);
  const md = await S.uploadBody([file('SKILL.md', '---\nname: b\n')]);
  assert.deepEqual(md.files.map(f => f.path), ['SKILL.md']);
});
