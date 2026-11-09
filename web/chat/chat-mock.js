// The scripted mock agent for `?mock` (plan 14.1 "Mock"): the same methods and event shapes as the
// agent mod (services/agent/agent/server.py, store.py), on in-memory threads. Asking for an image
// streams thinking and text, asks a question card, shows a parameter card, runs with live progress,
// and ends with a result card and its actions. Result buttons and quick actions run without a
// model call, like POST /action. Outputs are mock.js's (api.listOutputs), so they open in Outputs.

import { webTurn } from './chat-mock-web.js';
import { createProjectMocks } from './chat-mock-projects.js';

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
    model: 'skynet', fallback: 'gemma4-26B', max_steps: 25, modes: ['plan', 'manual', 'accept_edits', 'auto', 'bypass'], documents: { inline_tokens: 6000, reply_reserve: 4096 },
    memory_settings: { recall: true, fade_days: 180, auto_approve: true, auto_threshold: 0.8, auto_after_seen: 2, always_review: ['health', 'money', 'legal', 'relationships', 'religion', 'politics', 'sexuality'] }, memory_stats: { facts: 2, entities: 1, proposed: 0 } };

  function newThread(o = {}) {
    const ts = now(), th = { id: rid('t_'), title: o.title || '', model: o.model || null, mode: o.mode || 'manual', state: 'idle', settings: o.settings || {}, created: ts, updated: ts, archived: false, parent_id: o.parent_id || null, fork_seq: o.fork_seq ?? null };
    const t = { thread: th, events: [], subs: new Set(), run: null, queue: [], pending: null, held: [], paused: null };   // held, paused: the queue (chat-responsive 2.1)
    threads.set(th.id, t);
    return t;
  }
  const T = tid => { const t = threads.get(tid); if (!t) throw err(404, `no thread '${tid}'`, 'not_found'); return t; };
  const pub = t => ({ ...t.thread, running: !!t.run });
  const proj = createProjectMocks({ threads, newThread, emit: (...a) => emit(...a), net: () => net(), err, now, rid, pub });   // plan projects 1.3
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
  // Live progress (plan 44.2) the way the mods report it: frames from web/chat/mock-live/ for pictures, stages for 3D.
  function mockLive(name, i, total) {
    if (name.startsWith('gen3d')) {
      const st = (id, label, from, to) => ({ id, label, state: i >= to ? 'done' : i >= from ? 'running' : 'waiting', eta_s: Math.max(0, (to - i) * 0.32) });
      return { stage: i < 4 ? 'background' : i < 12 ? 'shape' : 'preview', stages: [st('background', 'Background', 1, 4), st('shape', 'Shape', 4, 12), st('preview', 'Views', 12, total)],
        eta_s: (total - i) * 0.32, ...(i >= 13 ? { preview: { url: '/chat/mock-live/views.png', seq: 2, w: 768, h: 768 } }
          : i >= 2 ? { preview: { url: '/chat/mock-live/input_rgba.png', seq: 1, w: 480, h: 360 } } : {}),
        ...(i >= 4 && i < 12 ? { step: i - 3, steps: 8 } : {}) };
    }
    if (name === 'tts_speak') return i < 2 ? { stage: 'loading' } : { stage: 'speaking', lines: [Math.min(3, Math.floor((i - 2) / 2)), 4], eta_s: (total - i) * 0.32 };
    if (i < 3) return { stage: 'loading', eta_s: (total - i) * 0.32 };
    const k = Math.min(6, i - 2), steps = Math.min(6, total - 3);
    return i >= total ? { stage: 'decoding', step: steps, steps } : { stage: 'sampling', step: k, steps, eta_s: (total - i) * 0.32,
      preview: { url: `/chat/mock-live/frame-${k}.jpg`, seq: k, w: 480, h: 360 } };
  }
  async function runTool(t, run, cid, name, args) {
    const callId = rid('call_');
    emit(t, 'call', { id: cid, call_id: callId });
    const total = name.startsWith('gen3d') ? 16 : 10;
    for (let i = 1; i <= total; i++) {
      await run.sleep(320);
      transient(t, 'progress', { id: cid, progress: i / total, note: i < total ? (i < 3 ? 'loading the model' : `step ${i}/${total}`) : 'saving', elapsed_s: i * 0.32, job_id: 'j_mock',
        live: mockLive(name, i, total) });
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
  // Plan 24.6: attached text and documents, numbered like outputs and read with hub_read_document.
  async function describe(t, ids, modes = {}) {
    let n = t.events.reduce((a, e) => a + (e.type === 'tool_result' ? (e.payload.outputs || []).length : e.type === 'user' ? (e.payload.docs || []).length : 0), 0);
    const docs = [];
    for (const id of ids) {
      const o = await api.getOutput?.(id).catch(() => null);
      if (!o || !['text', 'document'].includes(o.kind)) continue;
      const w = await api.outputText?.(id, { limit: 24000 }).catch(() => null);
      const mode = modes[id] || t.thread.settings?.doc_mode || 'auto', lim = settings.documents.inline_tokens === 'window' ? 1e9 : settings.documents.inline_tokens;   // plan 24.9
      const inline = !!w && w.next_offset == null && mode !== 'card' && (mode === 'whole' || w.tokens <= lim);
      docs.push({ ref: '#' + (++n), id, name: o.title, kind: o.kind, subtype: o.subtype, tokens: w?.tokens || 0, pages: w?.pages || 0, lines: w?.lines || 0, outline: [], mode, inline, ...(inline ? { text: w.text } : {}) });
    }
    return docs;
  }

  async function docTurn(t, run, docs) {
    const d = docs[0], s = await say(t, run, null, `The user attached ${d.name}. ${d.inline ? 'It is short and in the message, so I can answer from it.' : 'It is long: I should read it with hub_read_document.'}`, 2);
    if (!d.inline) {
      const id = rid('tc_');
      emit(t, 'tool_call', { id, name: 'hub_read_document', arguments: { ref: d.ref }, step: s, by: 'model' });
      await run.sleep(400);
      const w = await api.outputText?.(d.id, { limit: 12000 }).catch(() => null);
      emit(t, 'tool_result', { id, name: 'hub_read_document', status: 'done', content: `output:${d.id} ${d.name}\n<untrusted source="output:${d.id} ${d.name}">\n${(w?.text || '').slice(0, 2000)}\n</untrusted>` });
    }
    const first = (d.text || '').split('\n').find(l => l.trim()) || d.name;
    await say(t, run, `**${d.name}** (${d.pages ? d.pages + ' pages' : d.lines + ' lines'}) starts with "${first.replace(/^#+\s*/, '').slice(0, 80)}" (${d.ref}${d.pages ? ' p.' + Math.min(2, d.pages) : ':1'}). Ask me anything about it.`, null, 1);
    usage(t);
    return 'idle';
  }

  async function messageTurn(t, run, text, docs = []) {
    if (docs.length) return docTurn(t, run, docs);
    if (/remember|always|from now on/i.test(text)) {
      await say(t, run, 'Got it. I’ll keep that in mind in every chat.', 'The user stated a lasting preference; save it to memory with remember().', 2);
      emit(t, 'memory', { text: text.replace(/^(please\s+)?remember( that)?\s*/i, ''), topic: 'preferences' });
      usage(t);
      return 'idle';
    }
    if (/^(please\s+)?(search|look up)\b|\b(the web|sources?)\b/i.test(text)) return webTurn(t, run, text, { emit, say, usage, rid });   // the reply bar's Sources
    if (/\b3d\b/i.test(text) && /then|and turn|into/i.test(text)) return chainTurn(t, run, text);
    if (/image|picture|photo|draw|fox|paint/i.test(text)) return imageTurn(t, run, text);
    if (/\b(chart|graph|plot|table|stats)\b/i.test(text)) {          // show: a chart, a table and GAIFA's own data (plan 47.2)
      const s = await say(t, run, 'Here is what you made this week, and how memory looked today.', 'Use show: inline numbers, a table, and hub:memory.', 2);
      const shows = [
        { view: 'bar', title: 'Made per day', x: ['Thu', 'Fri', 'Sat', 'Sun', 'Mon', 'Tue', 'Wed'], series: [{ name: 'Images', values: [4, 7, 2, 0, 9, 5, 6] }, { name: 'Speech', values: [1, 0, 3, 2, 1, 4, 2] }] },
        { view: 'table', title: 'Longest jobs', columns: ['Job', 'Mod', 'Seconds'], rows: [['Lighthouse 3D', 'gen3d', 241], ['Fox portrait', 'comfy', 53], ['Sonnet 18', 'tts', 22], ['Samurai', 'comfy', 49], ['Lantern 3D', 'gen3d', 118]] },
        { view: 'area', title: 'Memory by mod', source: 'hub:memory', range: '24h' },
      ];
      for (const sh of shows) {
        const cid = rid('tc_'), { source, range, ...rest } = sh;
        emit(t, 'tool_call', { id: cid, name: 'show', arguments: sh, step: s, by: 'model' });
        await run.sleep(300);
        const spec = source ? { view: sh.view, title: sh.title, hub: { name: source.slice(4), range } } : { view: rest.view, title: rest.title, data: rest.view === 'table' ? { columns: rest.columns, rows: rest.rows } : { x: rest.x, series: rest.series } };
        emit(t, 'tool_result', { id: cid, name: 'show', status: 'done', content: 'Shown.', data: { show: spec } });
      }
      await say(t, run, 'Mondays are your busiest day; the 3D jobs take the longest.', '', 1);
      usage(t);
      return 'idle';
    }
    if (/\b(fail|broken|break)\b/i.test(text)) {        // a step that fails with the hub's fixes (plan 46.5)
      const s = await say(t, run, 'Making it at the quality preset.', 'Run gen3d_make_3d.', 2);
      const cid = rid('tc_'), fargs = { prompt: 'a dragon', engine: 'trellis2', preset: 'quality' };
      emit(t, 'tool_call', { id: cid, name: 'gen3d_make_3d', arguments: fargs, step: s, by: 'model' });
      emit(t, 'call', { id: cid, call_id: rid('call_') });
      await run.sleep(900);
      const error = { code: 'job_failed', detail: 'the job failed: HIP out of memory', fix: 'read the error; change the inputs or try again',
        fixes: [{ label: 'Free the GPU', tool: 'hub_free_gpu', arguments: {} }, { label: 'Retry with the fast preset', retry: { preset: 'fast' } }, { label: 'Retry', retry: {} }],
        log: ['trellis2: refine 1536, 24 steps', 'Traceback (most recent call last):', 'torch.OutOfMemoryError: HIP out of memory. Tried to allocate 18.00 GiB'] };
      emit(t, 'tool_result', { id: cid, name: 'gen3d_make_3d', status: 'error', error, content: JSON.stringify({ status: 'error', error }) });
      await say(t, run, 'It ran out of memory. Free the GPU or retry with the fast preset (buttons above).', '', 1);
      usage(t);
      return 'idle';
    }
    if (/^(please\s+)?(say|speak|read|narrate)\b/i.test(text)) {     // a speech step with its live card (plan 45.4)
      const s = await say(t, run, 'Here it is in that voice.', 'Speak it with tts_speak.', 2);
      const cid = rid('tc_'), sargs = { text: 'Welcome to GAIFA.\nEvery model on this machine, in one place.\nPictures, video, 3D and speech.\nAsk for anything.', name: 'Hope' };
      emit(t, 'tool_call', { id: cid, name: 'tts_speak', arguments: sargs, step: s, by: 'model' });
      await runTool(t, run, cid, 'tts_speak', sargs);
      usage(t);
      return 'idle';
    }
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
          else if (t.held.length && final === 'error') { t.paused = 'error'; pubQ(t); }
          else if (t.held.length && final === 'idle' && !t.paused) drain(t);   // Stop included: what was held goes now
        }
      }
    })();
  }

  // chat-responsive 2.1: messages held during a turn, sent together (one turn answers them) when it ends
  const qstate = t => ({ items: t.held.map((x, i) => ({ ...x, position: i })), paused: t.paused });
  const pubQ = t => transient(t, 'queue', qstate(t));
  function drain(t, qid = null) {
    if (qid == null) t.paused = null;
    const items = t.held.filter(x => qid == null || x.id === qid);
    t.held = t.held.filter(x => !items.includes(x)); pubQ(t);
    if (!items.length) return null;
    if (t.pending) { emit(t, 'tool_result', { id: t.pending.id, name: 'ask_user', status: 'skipped', content: '{}', error: { code: 'skipped', detail: 'The user wrote a message instead of answering.' } }); t.pending = null; }
    const evs = items.map(x => emit(t, 'user', { text: x.text, ...(x.quotes?.length ? { quotes: x.quotes } : {}), ...(x.client_id ? { client_id: x.client_id } : {}),
      ...(t.run ? { queued: true, steer: true } : {}) }));
    const said = items.map(x => x.text).join('\n\n');
    if (t.run) t.queue.push(said); else start(t, run => messageTurn(t, run, said, []));
    return evs[0];
  }

  async function seed() {
    if (seeded) return seeded;
    seeded = (async () => {
      proj.seed();
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
      emit(old, 'user', { text: 'Read this in Brendon’s voice: “GAIFA runs every model on this machine.”' });
      emit(old, 'assistant', { text: 'Done: the clip is below.', step: rid('s_'), model: 'skynet' });
      old.thread.updated = now() - 86400 * 2; old.thread.archived = true;
    })();
    return seeded;
  }

  const net = () => new Promise(r => setTimeout(r, (60 + Math.random() * 90) / speed));
  return {
    live: false,
    async models() { await net(); return structuredClone(MODELS); },
    async threads({ q, archived, limit = 200, environment, sort = 'updated', offset = 0, project } = {}) {
      await seed(); await net();
      const qq = (q || '').toLowerCase(), envs = environment ? String(environment).split(',') : null, projs = project ? String(project).split(',') : null;
      const order = { title: (a, b) => a.thread.title.toLowerCase().localeCompare(b.thread.title.toLowerCase()), created: (a, b) => b.thread.created - a.thread.created }[sort]
        || ((a, b) => b.thread.updated - a.thread.updated);
      return [...threads.values()].filter(t => !!t.thread.archived === !!archived)
        .filter(t => !envs || envs.includes(t.thread.settings?.environment || 'default'))
        .filter(t => !projs || projs.includes(t.thread.settings?.project || 'none'))
        .filter(t => !qq || t.thread.title.toLowerCase().includes(qq) || t.events.some(e => ['user', 'assistant'].includes(e.type) && String(e.payload.text).toLowerCase().includes(qq)))
        .sort(order).slice(offset, offset + limit).map(pub);
    },
    async threadGroups({ archived, by: key = 'environment' } = {}) {   // plan 41.1, as the agent's /v1/threads/groups (by project: plan projects 1.2)
      await seed(); await net();
      const by = new Map(), field = key === 'project' ? 'project' : 'environment', none = field === 'project' ? 'none' : 'default';
      for (const t of threads.values()) {
        if (!!t.thread.archived !== !!archived) continue;
        const env = t.thread.settings?.[field] || none, g = by.get(env) || { [field]: env, count: 0, updated: 0, running: 0 };
        g.count += 1; g.updated = Math.max(g.updated, t.thread.updated); g.running += ['running', 'waiting'].includes(t.thread.state) ? 1 : 0;
        by.set(env, g);
      }
      return [...by.values()].sort((a, b) => b.updated - a.updated);
    },
    // plan 28.5: chats by meaning; the mock gives a cosine-like score from shared words (0.3–0.8, no minimum,
    // like the embed mod) and uses the first reply as the summary
    async searchChats(q, limit = 8) {
      await seed(); await net();
      const words = new Set(String(q).toLowerCase().split(/\W+/).filter(Boolean));
      return [...threads.values()].map(t => {
        const text = t.events.filter(e => ['user', 'assistant'].includes(e.type)).map(e => String(e.payload.text)).join(' ');
        const shared = [...new Set(text.toLowerCase().split(/\W+/))].filter(w => words.has(w)).length;
        const summary = String(t.events.find(e => e.type === 'assistant')?.payload.text || '').slice(0, 240);
        return { thread_id: t.thread.id, title: t.thread.title, summary, date: new Date(t.thread.updated * 1000).toISOString().slice(0, 10),
          link: '#/chat/' + t.thread.id, score: Math.round(1000 * (0.3 + 0.45 * shared / Math.max(1, words.size) + 0.05 * (t.thread.id.length % 7) / 7)) / 1000 };
      }).sort((a, b) => b.score - a.score).slice(0, limit);
    },
    async create(body = {}) {        // with a message, the thread and its first message at once (chat-responsive 1.2)
      await net(); body = proj.newChatBody(body); const t = newThread(body), m = body.message;
      if (!m) return pub(t);
      const event = await this.send(t.thread.id, m.text, m.attachments || [], m.doc_modes || {}, m.quotes || [], m.mentions || [], m.client_id);
      return { ...pub(t), event };
    },
    async get(tid) { await seed(); await net(); return pub(T(tid)); },
    async patch(tid, p) { await net(); const t = T(tid); for (const k of ['title', 'model', 'mode', 'archived']) if (p[k] != null) t.thread[k] = p[k];
      if (p.settings) t.thread.settings = proj.movePatch(t.thread.settings, p.settings); t.thread.updated = now(); return pub(t); },
    async remove(tid) { await net(); const t = T(tid); t.run?.cancel(); threads.delete(tid); return { deleted: tid }; },
    async events(tid, after = 0) { await net(); return T(tid).events.filter(e => e.seq > after); },
    stream(tid, after = 0, { onEvent, onReady, onState } = {}) {
      let last = after, closed = false;
      const f = ev => { if (closed) return; if (ev.seq != null) { if (ev.seq <= last) return; last = ev.seq; } onEvent?.(ev); };
      seed().then(() => setTimeout(() => {
        if (closed) return;
        const t = threads.get(tid);
        if (!t) { onState?.('failed'); return; }
        t.events.forEach(f); onState?.('open'); onReady?.({ type: 'ready', thread_id: tid, seq: last, running: !!t.run, queue: qstate(t) }); t.subs.add(f);
      }, 40));
      return { close() { closed = true; threads.get(tid)?.subs.delete(f); }, get lastSeq() { return last; } };
    },
    async send(tid, text, attachments = [], docModes = {}, quotes = [], mentions = [], clientId = null, when = 'auto') {
      await net(); const t = T(tid), queued = !!t.run;
      // as the agent: quotes [{text 1–8,000, reply 0–4,000, seq?}], any number, 200,000 characters in all; an older single quote too
      const qs = Array.isArray(quotes) ? quotes : quotes?.text != null ? [{ text: quotes.text, reply: '', seq: quotes.seq }] : [];
      let total = 0;
      for (const [i, q] of qs.entries()) {
        if (!String(q.text || '').trim() || q.text.length > 8000) throw err(422, `quote ${i + 1}: 1 to 8,000 characters`, 'invalid_quote');
        if (String(q.reply || '').length > 4000) throw err(422, `reply ${i + 1}: at most 4,000 characters`, 'invalid_quote');
        if (q.seq != null && !t.events.some(e => e.seq === q.seq && e.type === 'assistant')) throw err(422, `quote.seq ${q.seq} isn't a reply in this chat`, 'invalid_quote');
        total += q.text.length + String(q.reply || '').length;
      }
      if (total > 200000) throw err(422, `the quoted parts and replies are ${total} characters in all; at most 200,000`, 'invalid_quote');
      const replies = qs.map(q => String(q.reply || '').trim()).filter(Boolean), said = [...replies, String(text || '').trim()].filter(Boolean).join('\n\n');
      if (!said) throw err(422, qs.length ? 'say something: a reply to a quoted part or a message' : 'the message is empty', qs.length ? 'invalid_quote' : 'empty_message');
      if (when !== 'now' && (t.run || t.held.length)) {    // held until the turn ends (chat-responsive 2.1)
        const item = { id: rid('q_'), text, ...(attachments.length ? { attachments } : {}), ...(qs.length ? { quotes: qs.map(q => ({ text: q.text, reply: String(q.reply || '') })) } : {}),
          ...(clientId ? { client_id: clientId } : {}), created: now(), edited: null };
        t.held.push(item); pubQ(t);
        if (!t.run) drain(t);
        return { queued: { ...item, position: t.held.indexOf(item) } };
      }
      if (!queued && t.pending) { emit(t, 'tool_result', { id: t.pending.id, name: t.pending.kind === 'question' ? 'ask_user' : 'comfy_generate_image', status: 'skipped', content: '{}', error: { code: 'skipped', detail: 'The user wrote a message instead of answering.' } }); t.pending = null; }
      const docs = attachments.length ? await describe(t, attachments, docModes) : [];
      const stored = qs.map(q => ({ text: q.text, reply: String(q.reply || ''), ...(q.seq != null ? { seq: q.seq } : {}) }));
      const ev = emit(t, 'user', { text, ...(stored.length ? { quotes: stored } : {}), ...(attachments.length ? { attachments } : {}), ...(docs.length ? { docs } : {}), ...(queued ? { queued: true, steer: true } : {}), ...(clientId ? { client_id: clientId } : {}) });
      if (!t.thread.title) { t.thread.title = said.slice(0, 48); transient(t, 'thread', pub(t)); }
      if (queued) t.queue.push(said); else start(t, run => messageTurn(t, run, said, docs));
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
    async approval(tid, { approval_id, approve, arguments: args, reason, remember = 'once' }) {
      await net(); const t = T(tid);
      const ap = t.events.find(e => e.type === 'approval' && e.payload.approval_id === approval_id);
      if (!ap) throw err(404, `no approval '${approval_id}' in this thread`, 'not_found');
      if (t.events.some(e => e.type === 'decision' && e.payload.approval_id === approval_id)) throw err(409, 'this approval was already decided', 'already_decided');
      const mp = args?.megapixels;
      if (approve && mp != null && (mp < 0.1 || mp > 4)) throw err(422, `megapixels: ${mp} is ${mp > 4 ? 'above the maximum 4' : 'below the minimum 0.1'}`, 'invalid_arguments', { problems: [{ field: 'megapixels', detail: 'out of range', fix: 'use 0.1 to 4' }] });
      const ev = emit(t, 'decision', { id: ap.payload.id, approval_id, approve, arguments: args || null, reason: reason || null, call_id: approve ? rid('call_') : null, status: approve ? 'running' : 'denied',
        ...(approve && remember !== 'once' ? { remember, grant: rid('gr_') } : {}) });
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
    async queue(tid) { await net(); return qstate(T(tid)); },
    async queueEdit(tid, qid, { text, index } = {}) {
      await net(); const t = T(tid), x = t.held.find(i => i.id === qid);
      if (!x) throw err(404, `no held message '${qid}'`, 'not_found');
      if (text != null) { if (!String(text).trim()) throw err(422, 'the message is empty: remove it instead', 'empty_message'); x.text = text; x.edited = now(); }
      if (index != null) { t.held = t.held.filter(i => i !== x); t.held.splice(Math.max(0, Math.min(index, t.held.length)), 0, x); }
      pubQ(t); return { ...x, position: t.held.indexOf(x) };
    },
    async queueRemove(tid, qid) { await net(); const t = T(tid); if (!t.held.some(i => i.id === qid)) throw err(404, `no held message '${qid}'`, 'not_found'); t.held = t.held.filter(i => i.id !== qid); pubQ(t); return qstate(t); },
    async queueSend(tid, qid) { await net(); const t = T(tid); if (!t.held.some(i => i.id === qid)) throw err(404, `no held message '${qid}'`, 'not_found'); return drain(t, qid) || {}; },
    async queueResume(tid) { await net(); const t = T(tid); t.paused = null; if (t.run || t.pending) pubQ(t); else drain(t); return qstate(t); },
    async queueClear(tid) { await net(); const t = T(tid); t.held = []; t.paused = null; pubQ(t); return qstate(t); },
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
    async saveSettings(body) { await net(); if (body.agent_md != null) settings.agent_md = body.agent_md; if (body.memory != null) settings.memory = body.memory;
      if (body.documents) settings.documents = { ...settings.documents, ...body.documents };
      if (body.memory_settings) settings.memory_settings = { ...settings.memory_settings, ...body.memory_settings }; return structuredClone(settings); },
    // skill-sources 3.1: your own skills, kept until the page reloads
    async uploadSkill(body) { await net();
      if (body.zip) throw { status: 422, code: 'bad_zip', detail: 'The mock can’t open zips: upload the folder or its SKILL.md' };
      const md = (body.files || []).find(f => /(^|\/)SKILL\.md$/.test(f.path)) || (body.files?.length === 1 ? body.files[0] : null);
      const text = md ? decodeURIComponent(escape(atob(md.data))) : '';
      const name = /^name:\s*(\S+)/m.exec(text)?.[1], description = /^description:\s*(.+)$/m.exec(text)?.[1] || '';
      if (!name) throw { status: 422, code: 'no_skill', detail: 'there’s no SKILL.md with a name at the top of the skill' };
      if (settings.skills.some(k => k.id === 'user/' + name) && !body.replace) throw { status: 409, code: 'exists', detail: `you already have a skill named ${name}` };
      const row = { name, description, source: 'user', id: 'user/' + name, enabled: true, problems: [], from: { kind: 'upload' } };
      settings.skills = [...settings.skills.filter(k => k.id !== row.id), row]; return structuredClone(row); },
    async copySkill(body) { await net(); const name = body.id.split(':')[1];
      const row = { name, description: `Copied from ${body.id}`, source: 'user', id: 'user/' + name, enabled: true, problems: [], from: { kind: 'workspace', id: body.id } };
      settings.skills = [...settings.skills.filter(k => k.id !== row.id), row]; return structuredClone(row); },
    async setSkill(name, enabled) { await net(); const k = settings.skills.find(x => x.id === 'user/' + name); if (k) k.enabled = enabled; return structuredClone(k); },
    ...Object.fromEntries(Object.entries(proj).filter(([k]) => !['newChatBody', 'movePatch', 'seed'].includes(k))),   // plan projects 1.3
    async deleteSkill(name) { await net(); settings.skills = settings.skills.filter(x => x.id !== 'user/' + name); return { deleted: name }; },
  };
}
