// Plan settings-redesign 2.4: collapsible groups (web/settings/rows.js openGroups, setOpen, Group).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { render, all, text } from './tinyreact.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const rows = await import(pathToFileURL(path.join(root, 'web', 'settings', 'rows.js')).href);
const refs = ['machine/memory', 'machine/storage', 'machine/hardware'];

test('openGroups: everything open by default; closed ones stay closed unless forced', () => {
  assert.deepEqual([...rows.openGroups({}, [], refs)], refs);
  assert.deepEqual([...rows.openGroups(null, null, refs)], refs);
  const saved = { 'machine/storage': false, 'machine/hardware': false };
  assert.deepEqual([...rows.openGroups(saved, [], refs)], ['machine/memory']);
  assert.deepEqual([...rows.openGroups(saved, ['machine/hardware'], refs)], ['machine/memory', 'machine/hardware']);   // the hash, an error, a match
});

test('setOpen keeps only the closed ones', () => {
  let s = rows.setOpen({}, 'machine/storage', false);
  assert.deepEqual(s, { 'machine/storage': false });
  s = rows.setOpen(s, refs, false);
  assert.deepEqual(Object.keys(s).sort(), [...refs].sort());
  assert.deepEqual(rows.setOpen(s, refs, true), {});   // Expand all
});

test('a closed group shows its summary; its title toggles it', () => {
  let got = null;
  const g = { ref: 'machine/memory', label: 'Memory' };
  const closed = render(rows.Group({ group: g, open: false, summary: 'Reserve 12 GB', onToggle: v => { got = v; }, children: ['ROWS'] }));
  const btn = all(closed, n => n.type === 'button')[0];
  assert.equal(btn.props['aria-expanded'], 'false');
  assert.match(text(closed), /MemoryReserve 12 GB/); assert.doesNotMatch(text(closed), /ROWS/);
  btn.props.onClick(); assert.equal(got, true);
  const open = render(rows.Group({ group: g, open: true, summary: 'Reserve 12 GB', children: ['ROWS'] }));
  assert.match(text(open), /ROWS/); assert.doesNotMatch(text(open), /Reserve 12 GB/);
});
