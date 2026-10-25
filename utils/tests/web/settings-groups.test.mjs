// Plan settings-redesign 2.4: collapsible groups (web/settings/rows.js openGroups, setOpen, Group).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { render, all, text } from './tinyreact.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const rows = await import(pathToFileURL(path.join(root, 'web', 'settings', 'rows.js')).href);
const nav = await import(pathToFileURL(path.join(root, 'web', 'settings', 'settings-nav.js')).href);
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

test('2.3: the section list is a sticky left column of plain links', () => {
  assert.equal(nav.headerHeight('compact'), 44); assert.equal(nav.headerHeight('comfortable'), 52);
  const wide = nav.navColumnSt('compact', true);
  assert.equal(wide.position, 'sticky'); assert.equal(wide.top, 56); assert.equal(wide.flex, '0 1 190px');
  assert.equal(nav.navColumnSt('comfortable', true).top, 64);
  assert.equal(nav.navColumnSt('compact', false).position, undefined);   // under 760 px: above the content, not pinned
  const secs = [{ id: 'general', label: 'General' }, { id: 'machine', label: 'Machine' }];
  const t = render(nav.SectionNav({ sections: secs, current: 'machine', counts: { machine: 3 }, search: 'BOX' }));
  const links = all(t, n => n.type === 'a');
  assert.deepEqual(links.map(a => [a.props.href, a.props['aria-current']]), [['#/settings/general', undefined], ['#/settings/machine', 'page']]);
  assert.equal(text(links[1]), 'Machine3');
  assert.equal(all(t, n => n.props?.role === 'tablist' || n.props?.role === 'tab').length, 0);
  assert.equal(t.type, 'nav'); assert.match(text(t), /^BOX/);   // the search box first
});
