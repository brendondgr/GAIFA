// The mods' status cards (plan 46.4): vLLM's load card, lcpp's start card, tts's voices.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadMod, modSkip } from './mods.mjs';

const vllm = await loadMod('services/vllm/ui/chat.js');
const lcpp = await loadMod('services/lcpp/ui/chat.js');
const tts = await loadMod('services/tts/ui/chat.js');

test("vLLM's stages follow the engine", () => {
  const c = vllm.stageChips({ state: 'starting', stage: 'loading weights' });
  assert.deepEqual(c.slice(0, 3).map(x => [x.id, x.state]), [['starting container', 'done'], ['initializing', 'done'], ['loading weights', 'running']]);
  assert.ok(c.every(x => x.state !== 'waiting' || vllm.STAGES.indexOf(x.id) <= 4));      // only the next two wait in view
  assert.ok(vllm.stageChips({ state: 'ready', stage: 'starting server' }).every(x => x.state === 'done'));
  assert.equal(vllm.stageChips({ state: 'failed', stage: 'compiling' }).find(x => x.id === 'compiling').state, 'failed');
  assert.equal(vllm.elapsed({ started_at: 100, ready_at: 157 }), 57);
  assert.equal(vllm.elapsed({}), null);
});

test("lcpp's started instance from its result", { skip: modSkip('services/lcpp/ui/chat.js') }, () => {
  assert.equal(lcpp.startedName({ name: 'gemma-1' }), 'gemma-1');
  assert.equal(lcpp.startedName({ instance: { name: 'qwen-2' }, warnings: [] }), 'qwen-2');
  assert.equal(lcpp.startedName(null), null);
});

test('each registers its cards', { skip: modSkip('services/lcpp/ui/chat.js', 'services/tts/ui/chat.js') }, () => {
  const kinds = [];
  const chat = { ui: { h: () => null }, live: {}, parts: {}, registerCard: k => kinds.push(k) };
  vllm.default(chat); lcpp.default(chat); tts.default(chat);
  for (const k of ['live:vllm_load_llm', 'live:vllm_engine_status', 'live:lcpp_start_llm', 'live:tts_list_voices', 'live:tts_speak']) assert.ok(kinds.includes(k), k);
});
