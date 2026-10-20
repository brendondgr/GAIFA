// The scripted mock agent for `?mock` (plan 14.1 "Mock"): the same methods and event shapes as the
// agent mod (services/agent/agent/server.py, store.py), on in-memory threads. Asking for an image
// streams thinking and text, asks a question card, shows a parameter card, runs with live progress,
// and ends with a result card and its actions. Result buttons and quick actions run without a
// model call, like POST /action. Outputs are mock.js's (api.listOutputs), so they open in Outputs.

const CANCEL = Symbol('cancelled');
const MODELS = { default: 'skynet', fallback: 'gemma4-26B', models: [
  { id: 'skynet', meta: { context_length: 131072, tools: true, vision: false, reasoning: true }, endpoint: 'skynet', health: 'healthy' },
  { id: 'gemma4-26B', meta: { context_length: 262144, tools: true, vision: true, reasoning: true }, endpoint: 'gemma4-26b-7071', health: 'healthy' }] };
const KIND_OF = { comfy_generate_image: 'image', comfy_edit_image: 'image', comfy_remove_background: 'image', comfy_animate_image: 'video', comfy_generate_video: 'video', gen3d_make_3d: 'model3d', tts_speak: 'audio' };
const QUESTIONS = [
  { question: 'Which style should the image have?', header: 'Style', options: [
    { label: 'Photoreal', description: 'Z-Image Turbo: natural light, fast (8 steps)' },
    { label: 'Watercolor', description: 'IntoRealism with the watercolor LoRA: painterly' },
    { label: 'Ink sketch', description: 'High-contrast line art on paper' }] },
  { question: 'Which shape?', header: 'Aspect', options: [
    { label: '16:9', description: 'Wide, for a desktop or a video' }, { label: '1:1', description: 'Square' }, { label: '9:16', description: 'Tall, for a phone' }] },
  { question: 'Anything to add?', header: 'Extras', multi_select: true, options: [
    { label: 'Falling snow' }, { label: 'Golden hour' }, { label: 'Shallow depth of field' }] },
];
const THINK = 'The user wants an image. The style and the aspect ratio are open choices that no tool default covers, so I should ask with ask_user before generating rather than guess. After that, comfy_generate_image shows a parameter card for the workflow and size.';
const CHAIN = {
  think: ['They want a character picture, then a 3D model made from it. I need the image tool and the 3D tool, so I\'ll find and load those first.',
    'Tools are ready. For image-to-3D a single figure, full body, front view on a plain background works best, so I\'ll ask for exactly that.',
    'The picture came out clean: full body, plain background, nothing cropped. **TRELLIS.2** is the most faithful engine for one object or figure; the balanced preset is enough here.',
    'Both are done. Say what was made in a sentence and offer the likely next steps.'],
  say: ['I\'ll make the picture first, as a full-body front view so it converts cleanly.', 'Now the 3D model. TRELLIS.2 keeps the most detail for a single figure.'],
};
const MD_REPLY = 'I can make **images**, **videos**, **3D models** and **speech**, and chain them: an image, then a 3D model of it, then a narration.\n\nTry:\n- *"make me an image of a fox in the snow"*\n- a quick action below the box (Image, Video, 3D, Speech)\n- `/compact` to summarize a long chat\n\n```\n/model gemma4-26B   switch this chat to the local model\n```';

const now = () => Date.now() / 1000;
const rid = p => p + Math.random().toString(16).slice(2, 14);
const err = (status, detail, code = 'agent_error', data) => Object.assign(new Error(detail), { status, detail, code, data });
const chunks = text => text.match(/\S+\s*|\s+/g) || [];

function mkRun(speed = 1) {
  const r = { cancelled: false, rej: null };
  r.sleep = ms => new Promise((res, rej) => {
    if (r.cancelled) return rej(CANCEL);
    const id = setTimeout(() => { r.rej = null; res(); }, ms / speed);
    r.rej = () => { clearTimeout(id); rej(CANCEL); };
  });
  r.cancel = () => { r.cancelled = true; r.rej?.(); };
  return r;
}

/** api: mock.js's api (listOutputs, listTools). o.speed: >1 runs the script faster (tests). */
export function createMockClient(api, { speed = 1 } = {}) {
  const threads = new Map();
  let seeded = null;
  const settings = { agent_md: '# Standing instructions\n\n- Prefer 16:9 for images unless I say otherwise.\n- Keep replies short.\n', memory: '- likes 16:9 images\n- my voice is Brendon\n',
    topics: ['preferences', 'voices'], skills: [
      { name: 'comfy', description: 'Choosing a ComfyUI workflow and its settings per task', source: 'comfy', id: 'comfy/comfy' },
      { name: 'tts', description: 'Voices and delivery direction', source: 'tts', id: 'tts/tts' },
      { name: 'gen3d', description: 'Presets, parts and rigs for 3D models', source: 'gen3d', id: 'gen3d/gen3d' }],
    model: 'skynet', fallback: 'gemma4-26B', max_steps: 25, modes: ['ask', 'auto', 'read_only'] };

  function newThread(o = {}) {
    const ts = now(), th = { id: rid('t_'), title: o.title || '', model: o.model || null, mode: o.mode || 'ask', state: 'idle', settings: o.settings || {}, created: ts, updated: ts, archived: false, parent_id: o.parent_id || null, fork_seq: o.fork_seq ?? null };
    const t = { thread: th, events: [], subs: new Set(), run: null, queue: [], pending: null };
    threads.set(th.id, t);
    return t;
  }
  const T = tid => { const t = threads.get(tid); if (!t) throw err(404, `no thread '${tid}'`, 'not_found'); return t; };
  const pub = t => ({ ...t.thread, running: !!t.run });
  function emit(t, type, payload) {
    const ev = { thread_id: t.thread.id, seq: t.events.length + 1, ts: now(), type, payload };
    t.events.push(ev); t.thread.updated = ev.ts;
    t.subs.forEach(f => f(ev));
    return ev;
  }
  const transient = (t, type, payload) => t.subs.forEach(f => f({ thread_id: t.thread.id, seq: null, ts: now(), type, payload }));
  const setState = (t, state) => { t.thread.state = state; emit(t, 'state', { state }); };
  const model = t => t.thread.model || MODELS.default;
  const windowOf = m => MODELS.models.find(x => x.id === m)?.meta.context_length || 32768;
  function meter(t) {
    const text = t.events.reduce((a, e) => a + JSON.stringify(e.payload).length, 0), msgs = Math.round(text / 4);
    const breakdown = { instructions: 2150, skills_memory: 420, tool_index: 1310, outputs: 60 * t.events.filter(e => e.type === 'tool_result').length, tools: 2900, messages: Math.round(msgs * 0.6), tool_results: Math.round(msgs * 0.4) };
    const used = Object.values(breakdown).reduce((a, b) => a + b, 0), window = windowOf(model(t));
    return { used, window, percent: Math.round(1000 * used / window) / 10, breakdown, estimated: false, model: model(t) };
  }
  const usage = t => { const m = meter(t); emit(t, 'usage', { prompt_tokens: m.used - 180, completion_tokens: 180, model: model(t), window: m.window }); transient(t, 'context', m); };
  const outputsIn = t => t.events.filter(e => e.type === 'tool_result').reduce((a, e) => a + (e.payload.outputs?.length || 0), 0);

  async function pickOutput(kind) {
    try {
      const page = await api.listOutputs({ kind, limit: 30 });
      const items = (page.items || []).filter(o => kind !== 'video' || o.preview);
      return items.length ? items[Math.floor(Math.random() * Math.min(items.length, 12))] : null;
    } catch { return null; }
  }
  async function makeOutput(t, kind, prompt) {
    const o = await pickOutput(kind);
    const n = outputsIn(t) + 1;
    if (!o) return { n, output_id: rid('o_'), kind, title: prompt || kind, summary: `${kind} (mock)`, url: '', preview: null, prompt };
    return { n, output_id: o.id, kind, title: o.title, summary: `${kind} · ${o.service}${o.dims ? ` · ${o.dims.w}×${o.dims.h}` : ''}`, url: o.url, preview: o.preview, prompt: prompt || o.meta?.prompt };
  }
  async function toolSchema(name) {
    try { return (await api.listTools({ names: [name] }))[0] || null; } catch { return null; }
  }

  // ---- the script ----
  async function say(t, run, text, think, seconds = 3, step = rid('s_')) {
    if (think) {
      for (const c of chunks(think)) { await run.sleep(14 * (seconds > 3 ? 3 : 1)); transient(t, 'delta', { kind: 'thinking', text: c, step }); }
      emit(t, 'thinking', { text: think, seconds, step });
    }
    if (text) {
      for (const c of chunks(text)) { await run.sleep(22); transient(t, 'delta', { kind: 'text', text: c, step }); }
      emit(t, 'assistant', { text, step, model: model(t) });
    }
    return step;
  }
  // The design study's sample turn (plan 19.1): look up tools, make a picture, ask to make it into 3D.
  async function chainTurn(t, run, text) {
    const s1 = await say(t, run, null, CHAIN.think[0], 4);
    const lk = [['find_tools', { query: 'image 3d model' }, { tools: ['comfy_generate_image', 'comfy_edit_image', 'gen3d_make_3d'] }], ['load_tools', { names: ['comfy_generate_image', 'gen3d_make_3d'] }, { loaded: 2 }]]
      .map(([name, args, result]) => { const id = rid('tc_'); emit(t, 'tool_call', { id, name, arguments: args, step: s1, by: 'model' }); return { id, name, result }; });
    await run.sleep(500);
    lk.forEach(x => emit(t, 'tool_result', { id: x.id, name: x.name, status: 'done', content: JSON.stringify({ status: 'done', result: x.result }) }));
    const s2 = await say(t, run, CHAIN.say[0], CHAIN.think[1], 3);
    const subject = /samurai/i.test(text) ? 'A young samurai in a navy kimono and grey hakama' : (text.replace(/,?\s*then.*$/i, '').replace(/^(please\s+)?(make|create|generate)\s+(me\s+)?(an?\s+)?/i, '') || 'A character');
    const iargs = { prompt: `${subject}, full body, front view, plain white background, soft studio light`, workflow: 'zimage-turbo', aspect: '1:1' };
    const ic = rid('tc_');
    emit(t, 'tool_call', { id: ic, name: 'comfy_generate_image', arguments: iargs, step: s2, by: 'model' });
    const img = await runTool(t, run, ic, 'comfy_generate_image', iargs);
    const s3 = await say(t, run, CHAIN.say[1], CHAIN.think[2], 5);
    const tool = await toolSchema('gen3d_make_3d'), cid = rid('tc_');
    const args = { image: 'output:' + img.output_id, engine: 'trellis2', preset: 'balanced' };
    emit(t, 'tool_call', { id: cid, name: 'gen3d_make_3d', arguments: args, step: s3, by: 'model' });
    emit(t, 'approval', { id: cid, approval_id: rid('ap_'), tool: 'gen3d_make_3d', arguments: args, ask_fields: tool?.ask || ['engine', 'preset'],
      schema: tool?.parameters || { type: 'object', properties: {} }, risk: 'generate', description: (tool?.description || '').slice(0, 600) });
    t.pending = { kind: 'approval', id: cid };
    usage(t);
    return 'waiting';
  }
  async function runTool(t, run, cid, name, args) {
    const callId = rid('call_');
    emit(t, 'call', { id: cid, call_id: callId });
    const total = name.startsWith('gen3d') ? 14 : 10;
    for (let i = 1; i <= total; i++) {
      await run.sleep(320);
      transient(t, 'progress', { id: cid, progress: i / total, note: i < total ? (i < 3 ? 'loading the model' : `step ${i}/${total}`) : 'saving', elapsed_s: i * 0.32, job_id: 'j_mock' });
    }
    const kind = KIND_OF[name];
    const out = kind ? [await makeOutput(t, kind, args.prompt || args.text)] : [];
    emit(t, 'tool_result', { id: cid, name, status: 'done', call_id: callId, content: JSON.stringify({ status: 'done', outputs: out.map(o => ({ ref: '#' + o.n, output: 'output:' + o.output_id, kind: o.kind })) }),
      ...(out.length ? { outputs: out } : {}) });
    return out[0];
  }
  async function imageTurn(t, run, text) {
    await say(t, run, 'Sure. A few quick choices first:', THINK, 4);
    const cid = rid('tc_');
    emit(t, 'tool_call', { id: cid, name: 'ask_user', arguments: { questions: QUESTIONS }, step: rid('s_'), by: 'model' });
    emit(t, 'question', { id: cid, questions: QUESTIONS });
    t.pending = { kind: 'question', id: cid, prompt: text.replace(/^(please\s+)?(make|draw|create|generate)\s+(me\s+)?(an?\s+)?(image|picture|photo)\s+(of\s+)?/i, '') || text };
    usage(t);
    return 'waiting';
  }
  async function afterAnswer(t, run, answers) {
    const style = String(answers[QUESTIONS[0].question] || 'Photoreal'), aspect = String(answers[QUESTIONS[1].question] || '16:9');
    const extras = [].concat(answers[QUESTIONS[2].question] || []).filter(Boolean);
    const prompt = [t.pending?.prompt || 'a fox in the snow', style.toLowerCase() === 'photoreal' ? 'photoreal' : style.toLowerCase(), ...extras.map(x => x.toLowerCase())].join(', ');
    emit(t, 'todos', { items: [{ text: 'Ask about style and shape', state: 'done' }, { text: 'Make the image', state: 'in_progress' }, { text: 'Offer next steps', state: 'pending' }] });
    await say(t, run, 'Here are the settings. Change anything you like, then **Run**.', null);
    const tool = await toolSchema('comfy_generate_image'), cid = rid('tc_');
    const args = { prompt, aspect, workflow: style === 'Watercolor' ? 'zimage-intorealism' : 'zimage-turbo' };
    emit(t, 'tool_call', { id: cid, name: 'comfy_generate_image', arguments: args, step: rid('s_'), by: 'model' });
    emit(t, 'approval', { id: cid, approval_id: rid('ap_'), tool: 'comfy_generate_image', arguments: args, ask_fields: tool?.ask || ['workflow', 'aspect', 'megapixels'],
      schema: tool?.parameters || { type: 'object', properties: {} }, risk: 'generate', description: (tool?.description || '').slice(0, 600) });
    t.pending = { kind: 'approval', id: cid };
    usage(t);
    return 'waiting';
  }
  async function afterApproval(t, run, ap, approve, args) {
    const cid = ap.payload.id;
    if (!approve) {
      emit(t, 'tool_result', { id: cid, name: ap.payload.tool, status: 'denied', content: '{"status":"denied"}', error: { code: 'denied_by_user', detail: 'the user said no' } });
      await say(t, run, 'Okay, I didn’t run it. Tell me what to change.', null);
      return 'idle';
    }
    const out = await runTool(t, run, cid, ap.payload.tool, args || ap.payload.arguments);
    if (ap.payload.tool === 'gen3d_make_3d') {
      const src = String((args || ap.payload.arguments).image || '').slice(7), first = t.events.find(e => e.type === 'tool_result' && e.payload.outputs?.some(o => o.output_id === src));
      const n = first ? first.payload.outputs.find(o => o.output_id === src).n : out.n - 1;
      await say(t, run, `Here's your picture **#${n}** and the 3D model made from it **#${out.n}** (TRELLIS.2, balanced).\n\nNext, I can **add a rig** so it can be posed, make a **low-poly** version for a game, or **animate** the picture.`, CHAIN.think[3], 2);
      usage(t);
      return 'idle';
    }
    emit(t, 'todos', { items: [{ text: 'Ask about style and shape', state: 'done' }, { text: 'Make the image', state: 'done' }, { text: 'Offer next steps', state: 'done' }] });
    await say(t, run, `Here it is (#${out.n}). Next, I can **animate** it, make a **3D model** from it, or **remove the background**. Use the buttons under the image, or just ask.`, null);
    usage(t);
    return 'idle';
  }
  async function messageTurn(t, run, text) {
    if (/remember|always|from now on/i.test(text)) {
      await say(t, run, 'Got it. I’ll keep that in mind in every chat.', 'The user stated a lasting preference; save it to memory with remember().', 2);
      emit(t, 'memory', { text: text.replace(/^(please\s+)?remember( that)?\s*/i, ''), topic: 'preferences' });
      usage(t);
      return 'idle';
    }
    if (/\b3d\b/i.test(text) && /then|and turn|into/i.test(text)) return chainTurn(t, run, text);
    if (/image|picture|photo|draw|fox|paint/i.test(text)) return imageTurn(t, run, text);
    await say(t, run, MD_REPLY, 'A general question: answer directly and point at what I can do. No tool call needed.', 2);
    usage(t);
    return 'idle';
  }

  function start(t, fn) {
    const run = t.run = mkRun(speed);
    setState(t, 'running');
    (async () => {
      let final = 'idle';
      try { final = (await fn(run)) || 'idle'; }
      catch (e) {
        if (e === CANCEL) {
          const done = new Set(t.events.filter(x => x.type === 'tool_result').map(x => x.payload.id));
          t.events.filter(x => x.type === 'tool_call' && !done.has(x.payload.id)).forEach(x => emit(t, 'tool_result', { id: x.payload.id, name: x.payload.name, status: 'cancelled', content: '{"status":"cancelled"}', error: { code: 'cancelled', detail: 'stopped by the user' } }));
          emit(t, 'note', { text: 'stopped by the user', level: 'info' });
        } else { emit(t, 'error', { code: 'agent_error', detail: String(e?.message || e) }); final = 'error'; }
      } finally {
        if (t.run === run) {
          t.run = null;
          setState(t, final);
          const q = t.queue.shift();
          if (q) start(t, r => say(t, r, `About “${q.slice(0, 60)}”: noted, I’ll use that from here on.`, null));
        }
      }
    })();
  }

  async function seed() {
    if (seeded) return seeded;
    seeded = (async () => {
      const t = newThread({ title: 'Fox in the snow' });
      const q = QUESTIONS.slice(0, 2), qid = rid('tc_'), cid = rid('tc_'), s = rid('s_');
      const tool = await toolSchema('comfy_generate_image'), out = await makeOutput(t, 'image', 'a red fox in fresh snow, photoreal, 16:9');
      const args = { prompt: 'a red fox in fresh snow, photoreal', aspect: '16:9', workflow: 'zimage-turbo' };
      emit(t, 'user', { text: 'Make me an image of a fox in the snow' });
      emit(t, 'thinking', { text: THINK, seconds: 6, step: s });
      emit(t, 'assistant', { text: 'Sure. A couple of quick choices first:', step: s, model: 'skynet' });
      emit(t, 'tool_call', { id: qid, name: 'ask_user', arguments: { questions: q }, step: s, by: 'model' });
      emit(t, 'question', { id: qid, questions: q });
      emit(t, 'answer', { id: qid, answers: { [q[0].question]: 'Photoreal', [q[1].question]: '16:9' } });
      emit(t, 'tool_result', { id: qid, name: 'ask_user', status: 'done', content: '{}' });
      emit(t, 'tool_call', { id: cid, name: 'comfy_generate_image', arguments: args, step: rid('s_'), by: 'model' });
      const apid = rid('ap_');
      emit(t, 'approval', { id: cid, approval_id: apid, tool: 'comfy_generate_image', arguments: args, ask_fields: tool?.ask || ['workflow', 'aspect'], schema: tool?.parameters || {}, risk: 'generate', description: '' });
      emit(t, 'decision', { id: cid, approval_id: apid, approve: true, arguments: { ...args, megapixels: 1.5 }, reason: null, call_id: 'call_seed', status: 'running' });
      emit(t, 'call', { id: cid, call_id: 'call_seed' });
      emit(t, 'tool_result', { id: cid, name: 'comfy_generate_image', status: 'done', call_id: 'call_seed', content: '{}', outputs: [out] });
      emit(t, 'assistant', { text: `Here it is (#${out.n}). I can animate it, make a 3D model from it, or remove the background.`, step: rid('s_'), model: 'skynet' });
      usage(t); t.thread.state = 'idle'; t.thread.updated = now() - 3600;
      const old = newThread({ title: 'Narrate the product blurb' });
      emit(old, 'user', { text: 'Read this in Brendon’s voice: “AIHub runs every model on this machine.”' });
      emit(old, 'assistant', { text: 'Done: the clip is below.', step: rid('s_'), model: 'skynet' });
      old.thread.updated = now() - 86400 * 2; old.thread.archived = true;
    })();
    return seeded;
  }

  const net = () => new Promise(r => setTimeout(r, (60 + Math.random() * 90) / speed));
  return {
    live: false,
    async models() { await net(); return structuredClone(MODELS); },
    async threads({ q, archived, limit = 200 } = {}) {
      await seed(); await net();
      const qq = (q || '').toLowerCase();
      return [...threads.values()].filter(t => !!t.thread.archived === !!archived)
        .filter(t => !qq || t.thread.title.toLowerCase().includes(qq) || t.events.some(e => ['user', 'assistant'].includes(e.type) && String(e.payload.text).toLowerCase().includes(qq)))
        .sort((a, b) => b.thread.updated - a.thread.updated).slice(0, limit).map(pub);
    },
    async create(body = {}) { await net(); return pub(newThread(body)); },
    async get(tid) { await seed(); await net(); return pub(T(tid)); },
    async patch(tid, p) { await net(); const t = T(tid); for (const k of ['title', 'model', 'mode', 'archived']) if (p[k] != null) t.thread[k] = p[k];
      if (p.settings) t.thread.settings = { ...t.thread.settings, ...p.settings }; t.thread.updated = now(); return pub(t); },
    async remove(tid) { await net(); const t = T(tid); t.run?.cancel(); threads.delete(tid); return { deleted: tid }; },
    async events(tid, after = 0) { await net(); return T(tid).events.filter(e => e.seq > after); },
    stream(tid, after = 0, { onEvent, onReady, onState } = {}) {
      let last = after, closed = false;
      const f = ev => { if (closed) return; if (ev.seq != null) { if (ev.seq <= last) return; last = ev.seq; } onEvent?.(ev); };
      seed().then(() => setTimeout(() => {
        if (closed) return;
        const t = threads.get(tid);
        if (!t) { onState?.('failed'); return; }
        t.events.forEach(f); onState?.('open'); onReady?.({ type: 'ready', thread_id: tid, seq: last, running: !!t.run }); t.subs.add(f);
      }, 40));
      return { close() { closed = true; threads.get(tid)?.subs.delete(f); }, get lastSeq() { return last; } };
    },
    async send(tid, text, attachments = []) {
      await net(); const t = T(tid), queued = !!t.run;
      if (!queued && t.pending) { emit(t, 'tool_result', { id: t.pending.id, name: t.pending.kind === 'question' ? 'ask_user' : 'comfy_generate_image', status: 'skipped', content: '{}', error: { code: 'skipped', detail: 'The user wrote a message instead of answering.' } }); t.pending = null; }
      const ev = emit(t, 'user', { text, ...(attachments.length ? { attachments } : {}), ...(queued ? { queued: true } : {}) });
      if (!t.thread.title) { t.thread.title = text.slice(0, 48); transient(t, 'thread', pub(t)); }
      if (queued) t.queue.push(text); else start(t, run => messageTurn(t, run, text));
      return ev;
    },
    async answer(tid, qid, answers) {
      await net(); const t = T(tid);
      if (t.events.some(e => e.type === 'tool_result' && e.payload.id === qid)) throw err(409, 'that question was already answered');
      emit(t, 'answer', { id: qid, answers });
      const ev = emit(t, 'tool_result', { id: qid, name: 'ask_user', status: 'done', content: JSON.stringify({ answers }) });
      start(t, run => afterAnswer(t, run, answers));
      return ev;
    },
    async approval(tid, { approval_id, approve, arguments: args, reason }) {
      await net(); const t = T(tid);
      const ap = t.events.find(e => e.type === 'approval' && e.payload.approval_id === approval_id);
      if (!ap) throw err(404, `no approval '${approval_id}' in this thread`, 'not_found');
      if (t.events.some(e => e.type === 'decision' && e.payload.approval_id === approval_id)) throw err(409, 'this approval was already decided', 'already_decided');
      const mp = args?.megapixels;
      if (approve && mp != null && (mp < 0.1 || mp > 4)) throw err(422, `megapixels: ${mp} is ${mp > 4 ? 'above the maximum 4' : 'below the minimum 0.1'}`, 'invalid_arguments', { problems: [{ field: 'megapixels', detail: 'out of range', fix: 'use 0.1 to 4' }] });
      const ev = emit(t, 'decision', { id: ap.payload.id, approval_id, approve, arguments: args || null, reason: reason || null, call_id: approve ? rid('call_') : null, status: approve ? 'running' : 'denied' });
      t.pending = null;
      start(t, run => afterApproval(t, run, ap, approve, args));
      return ev;
    },
    async action(tid, tool, args = {}) {
      await net(); const t = T(tid);
      if (t.run) throw err(409, 'a turn is running; wait for it or stop it first', 'busy');
      if (t.pending) { emit(t, 'tool_result', { id: t.pending.id, name: 'ask_user', status: 'skipped', content: '{}', error: { code: 'skipped', detail: 'The user started an action instead.' } }); t.pending = null; }
      const cid = rid('tc_'), ev = emit(t, 'tool_call', { id: cid, name: tool, arguments: args, step: rid('s_'), by: 'user' });
      if (!t.thread.title) t.thread.title = tool.replace(/^[a-z0-9]+_/, '').replace(/_/g, ' ');
      start(t, async run => { await runTool(t, run, cid, tool, args); usage(t); return 'idle'; });
      return ev;
    },
    async fork(tid, seq) {
      await net(); const src = T(tid);
      const t = newThread({ title: (src.thread.title || 'Chat') + ' (branch)', model: src.thread.model, mode: src.thread.mode, settings: src.thread.settings, parent_id: tid, fork_seq: seq });
      let evs = src.events.filter(e => e.seq <= seq);
      const done = new Set(evs.filter(e => e.type === 'tool_result').map(e => e.payload.id));
      while (evs.length) { const l = evs[evs.length - 1]; if ((['tool_call', 'question', 'approval', 'decision', 'answer'].includes(l.type) && !done.has(l.payload.id)) || ['state', 'usage', 'thinking'].includes(l.type)) evs = evs.slice(0, -1); else break; }
      evs.forEach((e, i) => t.events.push({ ...structuredClone(e), thread_id: t.thread.id, seq: i + 1 }));
      return pub(t);
    },
    async cancel(tid) {
      await net(); const t = T(tid);
      if (t.run) t.run.cancel();
      else if (t.pending) { emit(t, 'tool_result', { id: t.pending.id, name: 'ask_user', status: 'skipped', content: '{}', error: { code: 'skipped', detail: 'Cancelled by the user.' } }); t.pending = null; setState(t, 'idle'); }
      return { cancelled: tid, state: t.thread.state };
    },
    async compact(tid) {
      await net(); const t = T(tid);
      if (t.run) throw err(409, 'a turn is running', 'busy');
      const upto = t.events.length;
      emit(t, 'compact', { stage: 'summary', summary: 'The user asked for images; outputs so far are listed in the outputs table. No open questions.', upto_seq: upto, before: meter(t).used });
      transient(t, 'context', { ...meter(t), used: Math.round(meter(t).used * 0.45) });
      return { compacted: true };
    },
    async context(tid) { await net(); return meter(T(tid)); },
    async settings() { await net(); return structuredClone(settings); },
    async feedback(tid, body) { await net(); return { seq: 0, ...body }; },          // plan 21.7: the mock keeps no learning
    async decidePref(pid, approve) { await net(); return { id: pid, state: approve ? 'active' : 'rejected' }; },
    async saveSettings(body) { await net(); if (body.agent_md != null) settings.agent_md = body.agent_md; if (body.memory != null) settings.memory = body.memory; return structuredClone(settings); },
  };
}
