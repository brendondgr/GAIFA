// llama.cpp in Chat (plan 46.4): launching a model draws a live card that follows the instance until it serves
// (starting → ready, with its port, memory and the log's last lines while it starts) or fails with its error.
// Loaded from `[ui] chat` (plan 44.1).

/** The instance this call started, from its result ({name} or {instance: {name}}). */
export function startedName(result) {
  const r = result?.instance || result || {};
  return r.name || null;
}

export default function setup(chat) {
  const { h } = chat.ui, kit = chat.live, R = () => globalThis.React;

  function StartCard({ ctx }) {
    const React = R(), { row } = ctx.liveCard;
    let res = null;
    try { res = JSON.parse(row.item.result?.content || 'null')?.result; } catch { res = null; }
    const name = startedName(res), model = row.item.call?.arguments?.model_id || row.item.call?.arguments?.model || res?.model_id;
    const [inst, setInst] = React.useState(res?.instance || res || null);
    React.useEffect(() => {
      if (!name) return undefined;
      let alive = true, t = 0;
      const poll = async () => {
        try {
          const r = await ctx.api.callService('lcpp', 'GET', '/api/instances');
          const me = (Array.isArray(r.json) ? r.json : []).find(i => i.name === name);
          if (alive && me) setInst(me);
          if (me && me.state !== 'starting') return;
        } catch { /* the mod is restarting */ }
        if (alive) t = setTimeout(poll, 2000);
      };
      poll();
      return () => { alive = false; clearTimeout(t); };
    }, [name]);
    const st = inst?.state || (row.status === 'done' ? 'starting' : row.status);
    const secs = inst?.started_ts ? ((inst.ready_ts || Date.now() / 1000) - inst.started_ts) : null;
    const title = st === 'ready' ? `${model || inst?.model_id || 'The model'} is serving` : st === 'failed' ? `${model || 'The model'} didn't start` : `Starting ${model || inst?.model_id || 'the model'}`;
    const meta = [inst?.port ? `port ${inst.port}` : null, inst?.rss_bytes ? (inst.rss_bytes / 1e9).toFixed(1) + ' GB' : null, secs != null ? Math.round(secs) + ' s' : null].filter(Boolean).join(' · ');
    const lines = st === 'starting' ? (inst?.last_log_lines || []).slice(-3) : [];
    return h(kit.LiveCard, { icon: 'job', title, meta, done: st === 'ready', failed: st === 'failed', pct: st === 'ready' ? 1 : null },
      lines.length ? h('pre', { style: { margin: '0 12px 8px', padding: '6px 8px', background: 'var(--inset,#131926)', borderRadius: 6, fontSize: 11, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', color: 'var(--mut,#8A94A6)' } }, lines.join('\n')) : null,
      st === 'failed' && inst?.last_error ? h('div', { style: { padding: '0 12px 8px', fontSize: 12, color: 'var(--rd,#F85149)' } }, inst.last_error) : null,
      st === 'ready' && inst?.url ? h('div', { style: { padding: '0 12px 8px', fontSize: 12, color: 'var(--mut,#8A94A6)' } }, 'At ', h('code', null, inst.url), inst.relay?.alias ? ` · in the relay as ${inst.relay.alias}` : '') : null);
  }

  chat.registerCard('live:lcpp_start_llm', ({ ctx }) => h(StartCard, { ctx }));
}
