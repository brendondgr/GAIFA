// The `sessions` area on the mock (plan 15, brief §11.14): named setups of what runs and what's
// loaded, restored as a plan of steps. Mirrors utils/sessions.py's plan (stop LLMs not in the
// session, unload, start, launch LLMs, load) on mock.js's services. Written by us; mixed into
// mock.js's api:   Object.assign(api, createSessionMocks({ emit, net, err, later, now, api }))

const GB = 1e9;

export function createSessionMocks({ emit, net, err, later, now, api }) {
  const id = () => 'ss_' + Math.random().toString(16).slice(2, 12);
  let llms = [{ name: 'gemma4-26B-7071', model_id: 'gemma-4-26b-it', port: 7071, relay: { enabled: true, alias: 'gemma4-26B' }, rss_bytes: 18.6 * GB }];
  const snap = (mods, lcpp = []) => ({ version: 1, ts: now(), mods, lcpp, notes: [] });
  const M = (o = {}) => Object.fromEntries(['relay', 'lcpp', 'tts', 'gen3d', 'comfy', 'example'].map(k => [k, { running: k !== 'example', load: 'n/a', ...(o[k] || {}) }]));
  const unl = { load: 'unloaded' };
  const sessions = [
    { id: id(), name: 'Image work', auto: false, created_ts: now() - 5 * 86400, updated_ts: now() - 2 * 86400,
      snapshot: snap(M({ lcpp: unl, tts: unl, gen3d: unl, comfy: { load: 'loaded' } })) },
    { id: id(), name: 'Writing with Gemma', auto: false, created_ts: now() - 9 * 86400, updated_ts: now() - 86400,
      snapshot: snap(M({ lcpp: { load: 'loaded' }, tts: { load: 'loaded' }, gen3d: unl, comfy: unl }), [{ ...llms[0] }]) },
    { id: id(), name: 'Last session', auto: true, created_ts: now() - 30 * 86400, updated_ts: now() - 600,
      snapshot: snap(M({ lcpp: { load: 'loaded' }, tts: unl, gen3d: { load: 'loaded' }, comfy: unl }), [{ ...llms[0] }]) },
  ];
  let restoring = null;
  const summary = s => {
    const loaded = Object.entries(s.mods).filter(([, v]) => v.load === 'loaded').map(([k]) => k);
    const parts = [];
    if (s.lcpp.length) parts.push('LLMs: ' + s.lcpp.map(i => i.relay?.alias || i.model_id || i.name).join(', '));
    if (loaded.length) parts.push('loaded: ' + loaded.join(', '));
    parts.push(`${Object.values(s.mods).filter(v => v.running).length} mods running`);
    return parts.join('; ');
  };
  const pub = s => ({ ...structuredClone(s), summary: summary(s.snapshot) });
  const find = sid => { const s = sessions.find(x => x.id === sid || x.name === sid); if (!s) throw err(404, 'not_found', `no session '${sid}'`); return s; };
  const sorted = () => [...sessions].sort((a, b) => (a.auto - b.auto) || (b.updated_ts - a.updated_ts));
  async function current() {
    const svcs = await api.listServices();
    return snap(Object.fromEntries(svcs.filter(s => !s.manifest_errors.length).map(s => [s.id, { running: ['ready', 'degraded', 'starting'].includes(s.state), load: s.load }])), structuredClone(llms));
  }
  async function plan(sid) {
    const target = find(sid).snapshot, cur = await current(), mem = await api.getMemory(), svcs = await api.listServices();
    const est = Object.fromEntries(svcs.map(s => [s.id, s.memory]));
    const steps = [], key = i => `${i.model_id}:${i.port}`, want = new Set(target.lcpp.map(key)), have = new Set(cur.lcpp.map(key));
    let freed = 0, needed = 0;
    cur.lcpp.filter(i => !want.has(key(i))).forEach(i => { steps.push({ action: 'stop_llm', target: i.name, detail: `stop ${i.relay?.alias || i.name}`, bytes: -i.rss_bytes }); freed += i.rss_bytes; });
    for (const [m, v] of Object.entries(cur.mods)) if (v.load === 'loaded' && target.mods[m]?.load !== 'loaded') { const b = est[m]?.used_bytes || 0; steps.push({ action: 'unload', target: m, detail: `unload ${m}`, bytes: -b }); freed += b; }
    for (const [m, t] of Object.entries(target.mods)) {
      if (!cur.mods[m]) { steps.push({ action: 'skip', target: m, detail: `${m} isn't installed any more` }); continue; }
      if (t.running && !cur.mods[m].running) steps.push({ action: 'start', target: m, detail: `start ${m}` });
    }
    target.lcpp.filter(i => !have.has(key(i))).forEach(i => { steps.push({ action: 'launch_llm', target: i.name, detail: `launch ${i.relay?.alias || i.name}`, bytes: i.rss_bytes, spec: structuredClone(i) }); needed += i.rss_bytes; });
    for (const [m, t] of Object.entries(target.mods)) if (cur.mods[m] && t.load === 'loaded' && cur.mods[m].load !== 'loaded') { const b = est[m]?.estimate_bytes || 0; steps.push({ action: 'load', target: m, detail: `load ${m}`, bytes: b }); needed += b; }
    const after = mem.available_bytes + freed - needed - mem.reserve_bytes;
    return { session: find(sid).id, steps, memory: { available_bytes: mem.available_bytes, freed_bytes: freed, needed_bytes: needed, reserve_bytes: mem.reserve_bytes, after_bytes: after, fits: after >= 0 } };
  }
  const waitFor = async (cond, ms = 15000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await cond()) return true; await new Promise(r => later(250, r)); } return false; };
  const svc = async m => (await api.listServices()).find(s => s.id === m);

  return {
    async listSessions() { await net(); return sorted().map(pub); },
    async getSessionState() { await net(); const last = sorted().find(s => s.auto); return { unclean_shutdown: true, last_auto: last ? pub(last) : null, restoring, restore_on_boot: false }; },
    async saveSession(name) {
      await net(); name = String(name || '').trim();
      if (!name || name.length > 80) throw err(422, 'invalid_request', 'name: 1–80 characters');
      const s0 = sessions.find(x => x.name === name), snapshot = await current();
      const s = s0 || { id: id(), name, auto: false, created_ts: now() };
      Object.assign(s, { snapshot, updated_ts: now() });
      if (!s0) sessions.push(s);
      const p = pub(s); delete p.snapshot; emit({ type: 'session', session: p });
      return pub(s);
    },
    async renameSession(sid, name) {
      await net(); const s = find(sid); name = String(name || '').trim();
      if (!name || name.length > 80) throw err(422, 'invalid_request', 'name: 1–80 characters');
      if (sessions.some(x => x.name === name && x !== s)) throw err(409, 'conflict', `a session is already called '${name}'`);
      Object.assign(s, { name, updated_ts: now() }); return pub(s);
    },
    async deleteSession(sid) { await net(); const s = find(sid); sessions.splice(sessions.indexOf(s), 1); return null; },
    async restoreSession(sid, { dryRun = false } = {}) {
      await net();
      const p = await plan(sid);
      if (dryRun) return { ...p, dry_run: true };
      if (restoring) throw err(409, 'busy', `already restoring ${restoring}`);
      restoring = p.session; const results = [];
      try {
        for (const st of p.steps) {
          const res = { ...st, ok: true }; delete res.spec;
          try {
            if (st.action === 'stop_llm') { llms = llms.filter(i => i.name !== st.target); await new Promise(r => later(600, r)); }
            else if (st.action === 'launch_llm') { await new Promise(r => later(1500, r)); llms.push(structuredClone(st.spec)); }
            else if (st.action === 'unload') { await api.unloadService(st.target); res.ok = await waitFor(async () => ['unloaded', 'n/a'].includes((await svc(st.target))?.load)); }
            else if (st.action === 'start') { await api.startService(st.target); res.ok = await waitFor(async () => (await svc(st.target))?.state === 'ready'); }
            else if (st.action === 'load') { await api.loadService(st.target, { makeRoom: true }); res.ok = await waitFor(async () => (await svc(st.target))?.load === 'loaded', 30000); }
            if (!res.ok) res.error = `${st.target} didn't get there in time`;
          } catch (e) { res.ok = false; res.error = String(e.detail || e.message || e).slice(0, 300); }
          results.push(res);
          emit({ type: 'session_step', session: p.session, step: res });
        }
      } finally { restoring = null; }
      return { ...p, dry_run: false, results, ok: results.every(r => r.ok) };
    },
  };
}
