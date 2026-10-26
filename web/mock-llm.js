// The mock's local LLM engines (plan llm-servers 4.1): GET /api/llm/engines and load/unload, as lcpp and
// vLLM answer through the hub. Written by us.

export function createLlmMocks({ net, clone, err }) {
  const ENGINES = [
    { id: 'lcpp', name: 'LLM Launcher', state: 'ready', running: true, error: null, models: [
      { id: 'gemma-4-26B-it', name: 'gemma-4-26B-it', format: 'gguf', size_gb: 16.99, memory_gb: null, context: 262144, downloaded: true, loaded: true, relay_model: 'gemma4-26B' },
      { id: 'smollm2-135m-instruct', name: 'smollm2-135m-instruct', format: 'gguf', size_gb: 0.1, memory_gb: null, context: 8192, downloaded: true, loaded: false, relay_model: 'smollm2' }] },
    { id: 'vllm', name: 'vLLM', state: 'ready', running: true, error: null, models: [
      { id: 'qwen3.6-35b-a3b-awq', name: 'Qwen3.6 35B-A3B (AWQ 4-bit)', format: 'hf', size_gb: 20.4, memory_gb: 40, context: 65536, downloaded: true, loaded: false, relay_model: 'Qwen3.6-35B-A3B-vLLM' }] },
  ];
  const engineOf = e => ({ state: e.models.some(m => m.loaded) ? 'ready' : 'idle', loaded: e.models.filter(m => m.loaded).map(m => m.id) });
  const find = sid => { const e = ENGINES.find(x => x.id === sid); if (!e) throw err(404, 'engine_not_found', `${sid} isn't a mod with [llm]`); return e; };
  return {
    async getLlmEngines() { await net(); return ENGINES.map(e => clone({ ...e, engine: e.running ? engineOf(e) : null, models: e.running ? e.models : [] })); },
    async loadLlm(sid, id, makeRoom = false) {
      await net(); const e = find(sid);
      const m = e.models.find(x => x.id === id); if (!m) throw err(404, 'model_not_found', `no model ${id}`);
      if (sid === 'vllm' && !makeRoom) throw err(409, 'needs_room', 'Not enough memory for vLLM', { plan: { needs_bytes: 43e9, available_bytes: 30e9, enough: false, unload: [{ id: 'comfy', name: 'Images & Video', bytes: 18e9 }] } });
      if (sid === 'vllm') e.models.forEach(x => { x.loaded = false; });
      m.loaded = true; return { id, state: 'loading' };
    },
    async unloadLlm(sid, id) { await net(); const e = find(sid); e.models.forEach(m => { if (!id || m.id === id) m.loaded = false; }); return { loaded: e.models.filter(m => m.loaded).map(m => m.id) }; },
  };
}
