// web/chat/chat-projects.js (plan projects 5.1): the projects page's pure parts: sorting with pins first, search by
// name and description, a card's line and New project's checks.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const pp = await load('chat/chat-projects.js');

const LIST = [
  { id: 'p_a', name: 'beta', description: 'fish', created: 1, activity: 50 },
  { id: 'p_b', name: 'Alpha', description: 'about glaciers', created: 3, activity: 10 },
  { id: 'p_c', name: 'gamma', description: 'more glaciers', created: 2, activity: 90, pinned: true },
];

test('sorting: pins first, then recent activity, name or created', () => {
  assert.deepEqual(pp.sortProjects(LIST).map(p => p.id), ['p_c', 'p_a', 'p_b']);
  assert.deepEqual(pp.sortProjects(LIST, 'name').map(p => p.name), ['gamma', 'Alpha', 'beta']);
  assert.deepEqual(pp.sortProjects(LIST, 'created').map(p => p.id), ['p_c', 'p_b', 'p_a']);
  assert.deepEqual(pp.sortProjects(LIST.map(p => ({ ...p, pinned: false })), 'name').map(p => p.name), ['Alpha', 'beta', 'gamma']);
  assert.deepEqual(pp.sortProjects([]), []);
  assert.equal(LIST[0].id, 'p_a', 'the list itself is left as it was');
});

test('search by name and description, any case', () => {
  assert.deepEqual(pp.filterProjects(LIST, 'GLACIER').map(p => p.id), ['p_b', 'p_c']);
  assert.deepEqual(pp.filterProjects(LIST, 'alp').map(p => p.id), ['p_b']);
  assert.equal(pp.filterProjects(LIST, '  ').length, 3);
  assert.deepEqual(pp.filterProjects(LIST, 'nothing'), []);
});

test('the routes: #/chat/projects and #/chat/projects/<id> are pages; a chat id is a chat', async () => {
  const chat = await load('chat/chat.js');
  assert.deepEqual(chat.subPage({ parts: ['chat', 'projects'] }), { page: 'projects' });
  assert.deepEqual(chat.subPage({ parts: ['chat', 'projects', 'p_0a1b'] }), { page: 'project', pid: 'p_0a1b' });
  assert.equal(chat.subPage({ parts: ['chat', 't_abc'] }), null);
  assert.equal(chat.subPage({ parts: ['chat'] }), null);
  assert.equal(chat.subPage(null), null);
});

test('a card line and New project', () => {
  assert.equal(pp.cardLine({ chats: 1, activity: 1000 - 7200 }, 1000), '1 chat · 2h ago');
  assert.match(pp.cardLine({ chats: 3, activity: 990 }, 1000), /^3 chats · /);
  assert.deepEqual(pp.newProjectBody({ name: '  ' }), { error: 'A project needs a name.' });
  assert.deepEqual(pp.newProjectBody({ name: ' My   thesis ', description: ' d ', instructions: '' }).body, { name: 'My thesis', description: 'd', instructions: '' });
  assert.deepEqual(pp.SORTS.map(s => s[0]), ['activity', 'name', 'created']);
});
