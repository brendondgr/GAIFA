// services/mcp/ui/page.js (mcp-client 3.1): splitting a command line, and saying what changed in a server's tools.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const P = await import(pathToFileURL(path.join(root, 'services/mcp/ui/page.js')).href);

test('a command line splits into words, quotes kept together', () => {
  assert.deepEqual(P.splitArgs(`uvx --from 'blender-mcp==2.0.0' blender-mcp`), ['uvx', '--from', 'blender-mcp==2.0.0', 'blender-mcp']);
  assert.deepEqual(P.splitArgs('npx -y "@scope/a b"'), ['npx', '-y', '@scope/a b']);
  assert.deepEqual(P.splitArgs(''), []);
});

test('what changed since approval, in words', () => {
  assert.equal(P.diffText({ added: ['b'], removed: [], changed: ['a', 'c'] }), 'new: b · changed: a, c');
  assert.equal(P.diffText({ added: [], removed: [], changed: [] }), 'the list changed');
  assert.equal(P.diffText(null), '');
  assert.equal(P.default.tabs.map(t => t.id).join(','), 'servers,import');
});
