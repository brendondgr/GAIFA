// The `tools` area on the mock (brief §11.12, plan 13.1–13.2): a small tool catalog with risk
// levels, calls that run as fake jobs, and approvals (one pending from an MCP client, so the
// header's Approvals popover has something in it). Written by us; mixed into mock.js's api.
//
//   Object.assign(api, createToolMocks({ emit, net, err, later, now }))

const P = {
  prompt: { type: 'string', description: 'What to make, in plain words' },
  seed: { type: 'integer', minimum: -1, description: 'Random seed; -1 picks one' },
  aspect: { type: 'string', enum: ['1:1', '4:3', '3:4', '3:2', '2:3', '16:9', '9:16', '21:9'], description: 'Aspect ratio (sets width and height)' },
  megapixels: { type: 'number', minimum: 0.1, maximum: 4, description: 'Image size in megapixels, used with aspect (default 1.0)' },
  seconds: { type: 'number', minimum: 0.5, maximum: 30, description: 'Video length in seconds' },
  steps: { type: 'integer', minimum: 1, maximum: 100, description: 'Sampling steps' },
  image: { type: 'string', format: 'gaifa-file', 'x-kind': 'image', description: 'The input image: a GAIFA output id or an uploaded file' },
};
const wf = (ids, def) => ({ type: 'string', enum: ids, description: `Which workflow to use (default: ${def})` });
const obj = (properties, required) => ({ type: 'object', properties, required, additionalProperties: false });

// name, mod, risk, summary, parameters, ask, core, grant_key (plan 25.2)
const TOOLS = [
  ['hub_list_services', 'hub', 'read', 'List GAIFA\'s mods with their state and what they hold in memory', obj({}, []), [], true],
  ['hub_search_outputs', 'hub', 'read', 'Find earlier outputs (images, videos, audio, 3D models) by words', obj({ q: { type: 'string', description: 'Words to search for' }, kind: { type: 'string', enum: ['image', 'video', 'audio', 'model3d'] } }, []), [], true],
  ['comfy_generate_image', 'comfy', 'generate', 'Make an image from a text description.', obj({ prompt: P.prompt, workflow: wf(['zimage-turbo', 'qwen21-t2i', 'zimage-intorealism'], 'zimage-turbo'), aspect: P.aspect, megapixels: P.megapixels, steps: P.steps, seed: P.seed }, ['prompt']), ['workflow', 'aspect', 'megapixels']],
  ['comfy_generate_video', 'comfy', 'generate', 'Make a short video from a text description.', obj({ prompt: P.prompt, workflow: wf(['wan21-t2v'], 'wan21-t2v'), aspect: P.aspect, seconds: P.seconds, seed: P.seed }, ['prompt']), ['workflow', 'aspect', 'seconds']],
  ['comfy_edit_image', 'comfy', 'generate', 'Change an existing image as the prompt instructs.', obj({ image: P.image, prompt: { type: 'string', description: 'What to change' }, workflow: wf(['qwen21-edit'], 'qwen21-edit'), seed: P.seed }, ['image', 'prompt']), ['workflow']],
  ['comfy_animate_image', 'comfy', 'generate', 'Animate a still image into a short video, guided by a prompt.', obj({ image: P.image, prompt: P.prompt, workflow: wf(['wan21-i2v'], 'wan21-i2v'), aspect: P.aspect, megapixels: P.megapixels, seconds: P.seconds, seed: P.seed }, ['image', 'prompt']), ['workflow', 'aspect', 'megapixels', 'seconds']],
  ['comfy_remove_background', 'comfy', 'generate', 'Cut the subject out of an image, leaving a transparent background.', obj({ image: P.image }, ['image']), []],
  ['comfy_upscale_image', 'comfy', 'generate', 'Upscale an image 2× or 4× (4x Remacri).', obj({ image: P.image, scale: { type: 'integer', enum: [2, 4], description: 'How much bigger' } }, ['image']), ['scale']],
  ['gen3d_make_3d', 'gen3d', 'generate', 'Make a 3D model (GLB) from a picture (TRELLIS.2, Hunyuan3D 2.1, SAM 3D) or from a text description (Cube3D).', obj({ prompt: P.prompt, image: { ...P.image, title: 'Picture' },
    engine: { type: 'string', enum: ['trellis2', 'hunyuan21', 'sam3d_objects', 'sam3d_body', 'cube3d'], description: 'Engine: an image engine with a picture, cube3d with a prompt' },
    preset: { type: 'string', enum: ['draft', 'balanced', 'detailed', 'low-poly', 'fast', 'quality'], description: 'Quality preset (default balanced)' }, template: { type: 'string', enum: ['chair', 'character', 'vehicle', 'weapon', 'creature'], description: 'Part template (Cube3D)' }, seed: P.seed }, []), ['engine', 'preset']],
  // the same inputs as mock.js's POST /v1/speech operation (a tool's schema comes from its operation)
  ['tts_speak', 'tts', 'generate', 'Speak text aloud; the clip is saved to Outputs.', obj({ text: { type: 'string', description: 'Text to speak', 'x-multiline': true }, engine: { type: 'string', enum: ['auto', 'breeze', 'kokoro'], description: 'Engine' },
    voice: { type: 'string', enum: ['Brendon', 'Hope', 'Arabella', 'af_heart', 'am_michael'], description: 'Voice (default Hope)' }, direction: { type: 'string', description: 'Delivery direction (Breeze voices only)' },
    speed: { type: 'number', minimum: 0.5, maximum: 2, description: 'Speed (Kokoro only)' }, format: { type: 'string', enum: ['wav', 'mp3'], description: 'Format' }, timings: { type: 'boolean', description: 'Return word timings' } }, ['text']), ['voice']],
  ['tts_clone_voice', 'tts', 'write', 'Save a voice cloned from a 3-60 s reference clip.', obj({ name: { type: 'string', description: 'Voice name' }, audio: { type: 'string', format: 'gaifa-file', 'x-kind': 'audio', description: 'Reference clip' }, transcript: { type: 'string', description: 'What is said in the clip (empty: transcribe it)' } }, ['name', 'audio']), ['name']],
  ['tts_list_voices', 'tts', 'read', 'List saved voices and the built-in ones', obj({}, []), [], true],
  ['tts_delete_voice', 'tts', 'destructive', 'Delete a saved voice (permanent)', obj({ name: { type: 'string', description: 'Voice name' } }, ['name']), ['name']],
  ['lcpp_start_llm', 'lcpp', 'write', 'Launch a model (asks GAIFA for memory first)', obj({ model: { type: 'string', enum: ['gemma-4-26b-it', 'minicpm-5-2b'] }, ctx: { type: 'integer', minimum: 512, maximum: 262144 } }, ['model']), ['ctx']],
  ['lcpp_stop_llm', 'lcpp', 'destructive', 'Stop an instance', obj({ name: { type: 'string' } }, ['name']), ['name']],
  ['example_hello', 'example', 'read', 'Say hello', obj({ name: { type: 'string', description: 'Who to greet' } }, []), []],
  ['web_fetch', 'web', 'network', 'Fetch a web page as markdown (saved to Outputs).', obj({ url: { type: 'string', description: 'The page (http or https)' }, max_chars: { type: 'integer', minimum: 100, maximum: 100000 } }, ['url']), [], false, 'url:host'],
  ['workspace_python', 'workspace', 'execute', 'Run Python in the sandbox; files written to /out become outputs.', obj({ code: { type: 'string', description: 'The Python to run' } }, ['code']), [], false, 'const:python'],
];

const KIND_OF = { comfy_generate_image: 'image', comfy_edit_image: 'image', comfy_remove_background: 'image', comfy_upscale_image: 'image', comfy_animate_image: 'video', comfy_generate_video: 'video', gen3d_make_3d: 'model3d', tts_speak: 'audio' };

/** outputs(): mock.js's outputs, so a finished generate call returns one of them (optional). */
export function createToolMocks({ emit, net, err, later, now, outputs = () => [] }) {
  const tools = TOOLS.map(([name, mod, risk, summary, parameters, ask, core, grantKey]) => ({ name, mod, risk, core: !!core, summary, available: true,
    description: summary + (mod === 'comfy' ? '\nRuns as a job: the call returns when it has finished, with its outputs.' : ''), parameters, ask, examples: [], job: risk === 'generate', source: mod === 'hub' ? 'hub' : 'manifest',
    ...(grantKey ? { grant_key: grantKey } : {}) }));
  const byName = new Map(tools.map(t => [t.name, t]));
  const index = t => ({ name: t.name, mod: t.mod, risk: t.risk, core: t.core, summary: t.summary, available: t.available });
  const calls = new Map(), approvals = new Map(), grants = new Map();   // grants: plan 25.2
  const id = p => p + Math.random().toString(16).slice(2, 14);
  const unknown = name => err(404, 'unknown_tool', `No tool "${name}"`, { close: tools.map(t => t.name).filter(n => n.includes(String(name).split('_').pop())).slice(0, 3) });
  const withSchema = a => { const t = byName.get(a.tool); return { ...structuredClone(a), schema: t?.parameters, description: t?.description, ...(t?.grant_key ? { grant_key: t.grant_key } : {}) }; };
  const keyOf = (t, args) => (t.grant_key === 'url:host' ? (() => { try { return new URL(args.url).hostname; } catch { return null; } })()
    : t.grant_key?.startsWith('arg:') ? (args[t.grant_key.slice(4)] ?? null) : t.grant_key?.startsWith('const:') ? t.grant_key.slice(6) : null);
  const granted = (t, args, origin) => [...grants.values()].find(g => g.tool === t.name && (g.key == null || g.key === keyOf(t, args)) && (g.scope === 'always' || (origin?.thread && g.thread === origin.thread)));
  function check(t, args) {
    const problems = [];
    for (const r of t.parameters.required || []) if (args[r] == null || args[r] === '') problems.push({ field: r, detail: `${r} is required`, fix: `add ${r}` });
    for (const [k, v] of Object.entries(args)) {
      const p = t.parameters.properties[k];
      if (!p) { problems.push({ field: k, detail: `${k} isn't an input of ${t.name}`, fix: `remove ${k}` }); continue; }
      if (typeof v === 'number' && p.maximum != null && v > p.maximum) problems.push({ field: k, detail: `${k}: ${v} is above the maximum ${p.maximum}`, fix: `use ${p.maximum} or less` });
      if (typeof v === 'number' && p.minimum != null && v < p.minimum) problems.push({ field: k, detail: `${k}: ${v} is below the minimum ${p.minimum}`, fix: `use ${p.minimum} or more` });
      if (p.enum && !p.enum.includes(v)) problems.push({ field: k, detail: `${k}: ${JSON.stringify(v)} isn't one of the allowed values`, fix: `allowed: ${p.enum.join(', ')}` });
    }
    if (problems.length) throw err(422, 'invalid_arguments', problems.map(p => p.detail).join('; '), { problems });
  }
  function run(t, args, origin) {
    const c = { status: 'running', tool: t.name, call_id: id('call_'), progress: 0, note: 'starting', elapsed_s: 0, origin, arguments: args };
    calls.set(c.call_id, c);
    emit({ type: 'tool_call', call: structuredClone(c) });
    let i = 0;
    const tick = () => {
      if (c.status !== 'running') return;
      i++; c.progress = Math.min(1, i / 8); c.elapsed_s = i * 0.5; c.note = i < 8 ? `step ${i}/8` : 'saving';
      if (i >= 8) {
        c.status = 'done'; c.result = { ok: true };
        const o = outputs().find(x => x.kind === KIND_OF[t.name]);
        c.outputs = o ? [{ output_id: o.id, ref: 'output:' + o.id, kind: o.kind, title: o.title, url: o.url, preview: o.preview, summary: `${o.kind} · ${o.service}`, prompt: args.prompt || args.text }] : [];
      }
      emit({ type: 'tool_call', call: structuredClone(c) });
      if (c.status === 'running') later(500, tick);
    };
    later(500, tick);
    return c;
  }
  // One request waiting from an outside client (MCP), so the popover shows a parameter card.
  const seed = { id: 'ap_' + 'mock0001', tool: 'tts_speak', arguments: { text: 'Your render finished. The fox model is ready to rig.', voice: 'Hope' }, ask_fields: ['voice'],
    risk: 'generate', origin: { client: 'Claude Code', via: 'mcp' }, state: 'pending', created_ts: now() - 140 };
  approvals.set(seed.id, seed);
  // …and code to run (plan 25.3: the execute card shows it whole).
  const code = { id: 'ap_' + 'mock0002', tool: 'workspace_python', arguments: { code: 'import pandas as pd\ndf = pd.read_csv("/in/sales.csv")\nax = df.groupby("month")["total"].sum().plot.bar()\nax.figure.savefig("/out/sales.png", dpi=150)\nprint(df.describe())' },
    ask_fields: [], risk: 'execute', origin: { client: 'Claude Code', via: 'mcp' }, state: 'pending', created_ts: now() - 40 };
  approvals.set(code.id, code);

  return {
    async listTools({ q, names } = {}) {
      await net();
      if (names) {
        const want = (Array.isArray(names) ? names : String(names).split(',')).map(s => s.trim()).filter(Boolean);
        const miss = want.find(n => !byName.has(n));
        if (miss) throw unknown(miss);
        return want.map(n => structuredClone(byName.get(n)));
      }
      if (q) { const w = String(q).toLowerCase().split(/\s+/); return tools.filter(t => w.some(x => (t.name + ' ' + t.summary).toLowerCase().includes(x))).slice(0, 8).map(t => structuredClone(t)); }
      return tools.map(t => structuredClone(t));
    },
    async getToolIndex() { await net(); return tools.map(index); },
    async callTool(name, args = {}, { mode = 'ask', origin = {} } = {}) {
      await net();
      const t = byName.get(name); if (!t) throw unknown(name);
      check(t, args);
      if ((mode === 'read_only' || mode === 'plan') && t.risk !== 'read') return { status: 'denied', tool: name, error: { code: 'denied', detail: 'Plan mode: only tools that read can run' } };
      const g = granted(t, args, origin);
      if (g) g.used++;
      const asks = !g && (['network', 'execute', 'destructive'].includes(t.risk) || (t.risk !== 'read' && mode !== 'auto'));
      if (asks) {
        const a = { id: id('ap_'), tool: name, arguments: structuredClone(args), ask_fields: t.ask, risk: t.risk, origin, state: 'pending', created_ts: now() };
        approvals.set(a.id, a);
        emit({ type: 'approval', approval: structuredClone(a) });
        return { status: 'needs_approval', tool: name, approval_id: a.id, arguments: args, ask_fields: t.ask, risk: t.risk, schema: t.parameters, description: t.description, ...(t.grant_key ? { grant_key: t.grant_key } : {}) };
      }
      const c = run(t, args, origin);
      return { status: 'running', tool: name, call_id: c.call_id };
    },
    async getToolCall(cid) { await net(); const c = calls.get(cid); if (!c) throw err(404, 'not_found', `no call ${cid}`); return structuredClone(c); },
    async cancelToolCall(cid) { await net(); const c = calls.get(cid); if (!c) throw err(404, 'not_found', `no call ${cid}`); if (c.status === 'running') { c.status = 'cancelled'; emit({ type: 'tool_call', call: structuredClone(c) }); } return structuredClone(c); },
    async listApprovals({ state } = {}) { await net(); return [...approvals.values()].filter(a => state === 'all' || a.state === 'pending').sort((a, b) => b.created_ts - a.created_ts).map(withSchema); },
    async getApproval(aid) { await net(); const a = approvals.get(aid); if (!a) throw err(404, 'not_found', `no approval ${aid}`); return withSchema(a); },
    async decideApproval(aid, { approve, args, reason, remember = 'once', confirm } = {}) {
      await net();
      const a = approvals.get(aid); if (!a) throw err(404, 'not_found', `no approval ${aid}`);
      if (a.state !== 'pending') throw err(409, 'already_decided', 'This approval was already decided');
      const t = byName.get(a.tool), final = { ...a.arguments, ...(args || {}) };
      if (approve && t) check(t, final);
      let grant = null;
      if (approve && t && remember !== 'once') {
        if (remember === 'thread' && !a.origin?.thread) throw err(422, 'no_thread', "this call isn't from a chat, so it can't be allowed in this chat", { fix: 'allow it once, or always' });
        if (remember === 'always' && ['execute', 'destructive'].includes(t.risk) && !confirm) throw err(422, 'confirm_needed', `always allowing a ${t.risk} tool needs a second confirm`);
        grant = { id: id('gr_'), tool: t.name, key: keyOf(t, final), kind: t.grant_key || null, risk: t.risk, scope: remember, thread: remember === 'thread' ? a.origin.thread : null,
          created_ts: now(), note: `from approval ${aid}`, used: 0 };
        grants.set(grant.id, grant);
        emit({ type: 'grant', grant: structuredClone(grant) });
      }
      Object.assign(a, { state: approve ? 'approved' : 'denied', final, reason: reason || null, decided_ts: now() });
      let res = { status: 'denied', tool: a.tool, error: { code: 'denied_by_user', detail: reason || 'the user said no' } };
      if (approve && t) { const c = run(t, final, a.origin); a.call_id = c.call_id; res = { status: 'running', tool: a.tool, call_id: c.call_id, ...(grant ? { grant: structuredClone(grant) } : {}) }; }
      emit({ type: 'approval', approval: structuredClone(a) });
      return res;
    },
    async listGrants({ thread, tool } = {}) { await net(); return [...grants.values()].filter(g => (!thread || g.thread === thread) && (!tool || g.tool === tool)).sort((a, b) => b.created_ts - a.created_ts).map(g => structuredClone(g)); },
    async revokeGrant(gid) { await net(); if (!grants.delete(gid)) throw err(404, 'not_found', `no grant ${gid}`); emit({ type: 'grant_deleted', id: gid }); return { deleted: 1 }; },
  };
}
