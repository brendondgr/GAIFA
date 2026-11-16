// capability-enablement 7.3: the embed model in use and Change… in words (web/embed-model.js), the Settings block that
// draws them, and each decide model's line under the Auto judge's picker (chat-judge.js judgeModelLine).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
globalThis.React = {
  createElement: (type, props, ...children) => ({ type, props: { ...(props || {}), children: children.flat() } }),
  useState: init => [typeof init === 'function' ? init() : init, () => {}], useEffect: () => {}, useRef: v => ({ current: v }),
};
const W = await load('embed-model.js');
const J = await load('chat/chat-judge.js');
const S = await load('settings/schema.js');
const B = await load('settings/blocks-agent.js');

const GEMMA = { id: 'embeddinggemma-2', name: 'EmbeddingGemma 2', dim: 768, kinds: ['text', 'image', 'audio', 'video'], full: true, size_gb: 1.5, weights: true };
const SMALL = { id: 'bge-small-en-v1.5', name: 'BGE small (English)', dim: 384, kinds: ['text'], full: false, size_gb: 0.13, weights: true };
const GONE = { id: 'bge-base-en-v1.5', name: 'BGE base (English)', dim: 768, kinds: ['text'], full: false, weights: false };

test('the model in use and what a change gives up', () => {
  const d = { model: 'embeddinggemma-2', models: [GEMMA, SMALL, GONE], switch: null };
  assert.equal(W.inUseText(d), 'Search uses EmbeddingGemma 2 (768-d; reads text, pictures, audio and video).');
  assert.deepEqual(W.others(d).map(m => m.id), ['bge-small-en-v1.5']);          // one without weights isn't offered
  assert.match(W.changeNote(SMALL), /^Reads text only: pictures, audio and video are found by their titles/);
  assert.equal(W.changeNote(GEMMA), 'Reads every kind, like EmbeddingGemma 2.');
  assert.equal(W.switchText(d), '');
});

test('a switch in words', () => {
  const d = s => ({ model: 'embeddinggemma-2', models: [GEMMA, SMALL], switch: { model: SMALL.id, name: SMALL.name, ...s } });
  assert.equal(W.switchText(d({ state: 'building', done: 120, pending: 300 })),
    'Building BGE small (English)’s index: 120 done, 300 to go. Search uses EmbeddingGemma 2 until it’s ready.');
  assert.ok(W.busy(d({ state: 'building' })) && !W.busy(d({ state: 'done' })));
  assert.match(W.switchText(d({ state: 'failed', error: 'no room' })), /failed: no room\. EmbeddingGemma 2 stays in use\.$/);
  assert.match(W.switchText(d({ state: 'done' })), /restarting on it/);
});

test('each decide model under the judge: cutoff, tuning, last test', () => {
  assert.equal(J.judgeModelLine({ id: 'd3-lite', name: 'd3-lite', usable: true, threshold: 0.35, tuned: true,
    test: { passed: true, sentence: 'd3-lite on your GPU: 0.04 s per answer, 7.7 GB' } }),
    'd3-lite · cutoff 0.35, measured on the judge’s eval · tested: d3-lite on your GPU: 0.04 s per answer, 7.7 GB');
  assert.equal(J.judgeModelLine({ id: 'x', name: 'X', usable: true, threshold: 0.5, tuned: false, test: null }),
    'X · cutoff 0.5, not tuned for this model · not tested on this machine');
  assert.match(J.judgeModelLine({ id: 'y', usable: false, problems: ['no card'] }), /^y: can’t be used yet: no card$/);
  assert.match(J.judgeModelLine({ id: 'z', name: 'Z', usable: true, tuned: false, test: { passed: false, sentence: 'z on the CPU: 3 s' } }), /test failed: z on the CPU/);
});

test('Settings → Agent → Memory has the embed model when the embed mod is there', () => {
  const memory = svcs => S.sections({ services: svcs, draft: {} }).find(s => s.id === 'agent')?.groups.find(g => g.id === 'memory');
  assert.ok(memory([{ id: 'agent' }, { id: 'embed' }]).rows.some(r => r.block === 'EmbedModelBlock'));
  assert.ok(!memory([{ id: 'agent' }]).rows.some(r => r.block === 'EmbedModelBlock'));
  assert.equal(typeof B.AGENT_BLOCKS.EmbedModelBlock, 'function');
});
