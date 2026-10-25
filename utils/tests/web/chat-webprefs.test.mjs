// Settings → Agent → Reading web pages (chat-webprefs.js): which "Screen pages with" choice a config is, the patch
// each choice saves ([agent.screen]: null fields fall back to the judge's or the backend's defaults), and the days
// field for [outputs] hidden_keep_days.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const w = await import(pathToFileURL(path.join(root, 'web/chat/chat-webprefs.js')).href);

test('screenWay: the judge unless [agent.screen] names a backend or a model', () => {
  assert.equal(w.screenWay({ backend: null, model: null }), 'judge');
  assert.equal(w.screenWay(null), 'judge');
  assert.equal(w.screenWay({ backend: 'decide', model: null }), 'decide');
  assert.equal(w.screenWay({ backend: 'relay', model: 'qwen' }), 'relay');
  assert.equal(w.screenWay({ backend: null, model: 'qwen' }), 'relay');
});

test('screenPatch: what each choice saves', () => {
  assert.deepEqual(w.screenPatch('judge'), { backend: null, model: null, url: null, threshold: null });
  assert.deepEqual(w.screenPatch('decide', { model: 'd3-lite', threshold: 0.9, confirm: false }),
    { backend: 'decide', model: 'd3-lite', url: null, threshold: 0.9, confirm: false });
  assert.deepEqual(w.screenPatch('decide', {}), { backend: 'decide', model: 'd3-lite', url: null, threshold: 0.95, confirm: true });
  assert.deepEqual(w.screenPatch('relay', { model: 'gemma4-26B', threshold: 0.5 }), { backend: 'relay', model: 'gemma4-26B', url: null, threshold: null });
});

test('checkDays: 0 or more, at most 3650', () => {
  assert.deepEqual(w.checkDays('2'), { value: 2 });
  assert.deepEqual(w.checkDays(' 0 '), { value: 0 });
  assert.deepEqual(w.checkDays('1.5'), { value: 1.5 });
  for (const bad of ['', '-1', 'two', '4000', null]) assert.ok(w.checkDays(bad).error, String(bad));
});

test('the relevance choices match [agent.web] relevance', () => {
  assert.deepEqual(w.RELEVANCE.map(r => r[0]), ['auto', 'decide', 'lexical', 'off']);
  assert.deepEqual(w.SCREEN_WAYS.map(r => r[0]), ['judge', 'decide', 'relay']);
});

test('settings-redesign 4.3: screening and reading are rows of the Settings page; the screening model edits its draft', async () => {
  assert.equal(w.WebReadingSection, undefined);   // no card that saves on its own any more
  const { render, all } = await import('./tinyreact.mjs');
  let patch = null;
  const t = render(w.ScreenModelPick({ screen: { backend: 'decide', model: 'd3-lite', threshold: 0.9, confirm: true }, reading: { choices: { decide: ['d3-lite', 'd3'] }, decide_up: true }, onChange: p => { patch = p; } }));
  const way = all(t, n => n.type === 'select' && n.props['aria-label'] === 'Screen pages with')[0];
  assert.equal(way.props.value, 'decide');
  way.props.onChange({ target: { value: 'judge' } });
  assert.deepEqual(patch, { backend: null, model: null, url: null, threshold: null });
  all(t, n => n.type === 'select' && n.props['aria-label'] === 'Screening model')[0].props.onChange({ target: { value: 'd3' } });
  assert.deepEqual(patch, { model: 'd3' });
});
