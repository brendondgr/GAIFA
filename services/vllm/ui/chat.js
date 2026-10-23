// vLLM in Chat (plan 46.4): loading a profile draws a live card that follows the engine through its stages
// (starting container → initializing → loading weights → … → starting server) until it serves, with the time so far;
// the engine's status draws the same card once. Loaded from `[ui] chat` (plan 44.1).

export const STAGES = ['starting container', 'initializing', 'loading weights', 'profiling', 'compiling', 'capturing graphs',
  'allocating KV cache', 'warming up', 'starting server'];

/** The engine's view → the card's stages as chips: done before the current one, running at it. */
export function stageChips(engine) {
  const st = engine?.state, cur = STAGES.indexOf(engine?.stage);
  return STAGES.map((s, i) => ({ id: s, label: s[0].toUpperCase() + s.slice(1),
    state: st === 'ready' ? 'done' : st === 'failed' ? (i < cur ? 'done' : i === cur ? 'failed' : 'waiting') : i < cur ? 'done' : i === cur ? 'running' : 'waiting' }))
    .filter((c, i) => c.state !== 'waiting' || i <= cur + 2 || st !== 'starting');
}

/** Seconds since the engine started (or until it was ready). */
export function elapsed(engine, now = Date.now() / 1000) {
  if (!engine?.started_at) return null;
  return Math.max(0, (engine.ready_at || now) - engine.started_at);
}

export default function setup(chat) {
  const { h } = chat.ui, kit = chat.live, R = () => globalThis.React;

  function EngineCard({ ctx, follow }) {
    const React = R(), { row } = ctx.liveCard;
    const [eng, setEng] = React.useState(null), [, tick] = React.useState(0);
    React.useEffect(() => {
      let alive = true, t = 0;
      const poll = async () => {
        try { const r = await ctx.api.callService('vllm', 'GET', '/v1/engine'); if (alive) setEng(r.json); if (!follow || !r.json || r.json.state !== 'starting') return; } catch { /* the mod is restarting */ }
        if (alive) t = setTimeout(poll, 2000);
      };
      poll();
      const c = setInterval(() => tick(x => x + 1), 1000);
      return () => { alive = false; clearTimeout(t); clearInterval(c); };
    }, []);
    const name = eng?.name || row.item.call?.arguments?.profile || 'the profile';
    const state = eng?.state, secs = elapsed(eng);
    const title = state === 'ready' ? `vLLM is serving ${name}` : state === 'failed' ? `vLLM couldn't load ${name}` : state === 'starting' ? `Loading ${name} in vLLM` : 'vLLM is idle';
    const meta = [eng?.stage && state === 'starting' ? eng.stage : null, secs != null ? Math.round(secs) + ' s' : null].filter(Boolean).join(' · ');
    return h(kit.LiveCard, { icon: 'job', title, meta, done: state === 'ready' || state === 'unloaded', failed: state === 'failed',
      foot: h(kit.StageChips, { stages: stageChips(eng || { state: 'starting', stage: 'starting container' }) }) },
      state === 'failed' && (eng.error || eng.last_error) ? h('div', { style: { padding: '0 12px 8px', fontSize: 12, color: 'var(--rd,#F85149)' } }, eng.error || eng.last_error) : null,
      state === 'ready' && eng.endpoint ? h('div', { style: { padding: '0 12px 8px', fontSize: 12, color: 'var(--mut,#8A94A6)' } }, `Serving as ${eng.served_name || name} at `, h('code', null, eng.endpoint)) : null);
  }

  chat.registerCard('live:vllm_load_llm', ({ ctx }) => h(EngineCard, { ctx, follow: true }));
  chat.registerCard('live:vllm_engine_status', ({ ctx }) => h(EngineCard, { ctx, follow: true }));
}
