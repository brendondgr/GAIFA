// services/agent/ui/memory.js (structured-memory 5.1): the Memory tab's tree rows and the Review tab's grouping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const M = await import(pathToFileURL(path.join(root, 'services/agent/ui/memory.js')).href);

test('the tree flattens with headings and depth', () => {
  const rows = M.treeRows({ kinds: [{ kind: 'user', entities: [{ id: 'user', name: 'You', kind: 'user', facts: 2, children: [] }] },
    { kind: 'project', entities: [{ id: 'e1', name: 'GAIFA', kind: 'project', facts: 3, children: [{ id: 'e2', name: 'agent', kind: 'topic', facts: 1, children: [] }] }] }] });
  assert.deepEqual(rows.map(r => r.heading || `${'  '.repeat(r.depth)}${r.name}`), ['You', 'You', 'Projects', 'GAIFA', '  agent']);
});

test('proposals group by their chat, and say what approving does', () => {
  const f = (id, ev, extra = {}) => ({ id, evidence: ev, ...extra });
  const g = M.byChat([f('a', [{ thread: 't1', seq: 3 }]), f('b', [{ action: 'merge', entity: 'x', into: 'y' }]), f('c', [{ thread: 't1' }])]);
  assert.deepEqual(g.map(x => [x.thread, x.items.map(i => i.id)]), [['t1', ['a', 'c']], ['', ['b']]]);
  assert.equal(M.actionText(f('d', [{ thread: 't' }, { action: 'rename', entity: 'e', to: 'GAIFA' }])), 'renames it to GAIFA');
  assert.equal(M.actionText(f('e', [], { replaces: 'f_1' })), 'replaces an older fact');
  assert.equal(M.actionText(f('g', [])), '');
});
