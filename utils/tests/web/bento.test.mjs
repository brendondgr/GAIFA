// web/bento.js (plan overview-bento 1.1): the grid's sizes and spans, and the saved layout's helpers.
import './tinyreact.mjs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const b = await import(pathToFileURL(path.join(root, 'web/bento.js')).href);

test('every size spans its columns and rows at full width', () => {
  for (const [z, [c, r]] of Object.entries(b.SIZES)) assert.deepEqual(b.spanAt(z, 1440), [c, r]);
  assert.deepEqual(b.spanAt('nope', 1440), b.SIZES.s);
});

test('narrower, the 4-column sizes take half a row and the wide ones the whole', () => {
  assert.deepEqual(b.spanAt('xs', 1000), [3, 1]);
  assert.deepEqual(b.spanAt('s', 1000), [6, 2]);
  assert.deepEqual(b.spanAt('m', 1000), [6, 3]);
  assert.deepEqual(b.spanAt('w', 1000), [6, 3]);
  assert.deepEqual(b.spanAt('l', 1000), [12, 3]);
  assert.deepEqual(b.spanAt('f', 1000), [12, 2]);
});

test('on a phone everything is full width but the small numbers, two to a row', () => {
  assert.deepEqual(b.spanAt('xs', 400), [6, 1]);
  for (const z of ['s', 'm', 'w', 'l', 'f']) assert.equal(b.spanAt(z, 400)[0], 12);
  assert.equal(b.spanAt('m', 400)[1], 3);
});

test('a saved size counts only when the tile allows it', () => {
  const def = { key: 'k', size: 'm', sizes: ['m', 'w'] };
  assert.equal(b.sizeOf(def, {}), 'm');
  assert.equal(b.sizeOf(def, { sizes: { k: 'w' } }), 'w');
  assert.equal(b.sizeOf(def, { sizes: { k: 'xs' } }), 'm');
  assert.equal(b.sizeOf({ key: 'k', size: 's' }, { sizes: { k: 'f' } }), 's');
});

const DEFS = [{ key: 'a' }, { key: 'b' }, { key: 'c', off: true }, { key: 'd' }];

test('visible tiles: the saved order first, hidden ones out, off ones only when shown', () => {
  assert.deepEqual(b.visibleKeys(DEFS, {}), ['a', 'b', 'd']);
  assert.deepEqual(b.visibleKeys(DEFS, { hidden: ['b'] }), ['a', 'd']);
  assert.deepEqual(b.visibleKeys(DEFS, { shown: ['c'] }), ['a', 'b', 'c', 'd']);
  assert.deepEqual(b.visibleKeys(DEFS, { order: ['d', 'gone', 'c', 'd'], shown: ['c'] }), ['d', 'c', 'a', 'b']);
  assert.deepEqual(b.visibleKeys(DEFS, { hidden: ['c'] }), ['a', 'b', 'd']);   // hidden means nothing to an off tile
});

test('turning a tile on or off writes hidden for usual tiles and shown for off ones', () => {
  assert.deepEqual(b.setOn({}, DEFS[0], false), { hidden: ['a'] });
  assert.deepEqual(b.setOn({ hidden: ['a', 'b'] }, DEFS[0], true), { hidden: ['b'] });
  assert.deepEqual(b.setOn({}, DEFS[2], true), { shown: ['c'] });
  assert.deepEqual(b.setOn({ shown: ['c'] }, DEFS[2], false), { shown: [] });
  assert.ok(b.isOn(DEFS[2], b.setOn({}, DEFS[2], true)));
});

test('a drop puts the tile just before the one it lands on', () => {
  const o = ['a', 'b', 'c', 'd'];
  assert.deepEqual(b.dropBefore(o, 'd', 'a'), ['d', 'a', 'b', 'c']);
  assert.deepEqual(b.dropBefore(o, 'a', 'd'), ['b', 'c', 'a', 'd']);
  assert.deepEqual(b.dropBefore(o, 'a', null), ['b', 'c', 'd', 'a']);
  assert.deepEqual(b.dropBefore(o, 'b', 'b'), o);
  assert.deepEqual(b.dropBefore(o, 'zz', 'a'), o);
});

test('the keyboard moves a tile one place among the visible ones', () => {
  const o = ['a', 'x', 'b', 'c'], vis = ['a', 'b', 'c'];
  assert.deepEqual(b.stepKey(o, vis, 'b', -1), ['b', 'a', 'x', 'c']);
  assert.deepEqual(b.stepKey(o, vis, 'b', 1), ['a', 'x', 'c', 'b']);
  assert.deepEqual(b.stepKey(o, vis, 'a', -1), o);
  assert.deepEqual(b.stepKey(o, vis, 'c', 1), o);
});
