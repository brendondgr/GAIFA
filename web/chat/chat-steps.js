// Step words (plan 19.3): what a tool call is called in the activity fold, while it runs and once
// done, its short grey detail, and the sentence a step opens to. Pure (no React), tested in
// utils/tests/web/chat-turn.test.mjs. A mod's tool gets plain words with no UI code (the fallback
// reads the tool's name and schema); a registered entry gives it better ones:
//
//   registerStep('comfy_upscale_image', {
//     running: 'Upscaling the image', done: 'Upscaled the image', icon: 'upscale',
//     detail: (args, ctx) => `${ref(args.image, ctx)} · ${args.scale}×`,
//     sentence: (args, ctx) => ({ parts: ['Made ', out(args.image, ctx), ` ${args.scale}× bigger.`] }),
//     lookup: false,                  // true: drawn grey and not counted as work
//   })
//
// A sentence is { parts: [string | {b: text} | {ref: output} | {code: text}], quote?: text }.

import { addLookup } from './chat-turn.js';
import { toolLabel } from './chat-ui.js';

const steps = new Map();
export function registerStep(name, words) {
  if (!name || !words) throw new Error('registerStep(name, words)');
  steps.set(name, words);
  if (words.lookup) addLookup(name);
  return () => steps.delete(name);
}
export const stepFor = name => steps.get(name) || null;

// ---------- values in plain words ----------
// Engine and workflow ids → names. The schema's own labels win (`x-options` {value: {label}}, plan 20.7;
// `x-enum-labels` or `oneOf` [{const, title}]); this map covers tools that carry none.
const NAMES = { 'zimage-turbo': 'Z-Image Turbo', 'zimage-intorealism': 'Z-Image IntoRealism', 'qwen21-turbo-t2i': 'Qwen-Image 2.1 Turbo', 'qwen21-t2i': 'Qwen-Image 2.1',
  'qwen21-turbo-edit-multi': 'Qwen-Image 2.1 Edit Turbo', 'qwen21-turbo-remove-bg': 'Qwen-Image 2.1 background removal', 'qwen-edit': 'Qwen-Image-Edit 2511', 'flux2-klein-edit': 'FLUX.2 Klein Edit',
  'wan21-i2v': 'Wan 2.1 image-to-video', 'wan21-t2v': 'Wan 2.1 text-to-video', trellis2: 'TRELLIS.2', hunyuan21: 'Hunyuan3D 2.1', sam3d_objects: 'SAM 3D Objects', sam3d_body: 'SAM 3D Body', cube3d: 'Cube3D' };
const ASPECT = { '1:1': 'square', '16:9': 'wide (16:9)', '9:16': 'tall (9:16)', '4:3': '4:3', '3:4': '3:4', '3:2': '3:2', '2:3': '2:3', '21:9': 'ultrawide (21:9)' };
const schemaOf = (name, ctx) => (ctx?.tools || []).find(t => t.name === name)?.parameters || null;
/** A value's name: the schema's label for it, a known engine or workflow, or the value. */
export function nameOf(value, { tool, key, ctx } = {}) {
  const p = schemaOf(tool, ctx)?.properties?.[key];
  const xo = p?.['x-options']?.[value]?.label;          // the tool's own label for this choice (plan 20.7)
  if (xo) return String(xo);
  const xl = p?.['x-enum-labels'];
  if (xl && !Array.isArray(xl) && xl[value] != null) return String(xl[value]);
  if (Array.isArray(xl) && Array.isArray(p.enum)) { const i = p.enum.indexOf(value); if (i >= 0 && xl[i] != null) return String(xl[i]); }
  const o = (p?.oneOf || p?.anyOf || []).find(x => x.const === value && x.title);
  if (o) return o.title;
  return NAMES[value] || String(value);
}
/** An `output:<id>` (or {$file}) value → the thread's output (its #n), or null. */
export function outputOf(v, ctx) {
  const s = v && typeof v === 'object' ? v.$file : v;
  if (typeof s !== 'string' || !s.startsWith('output:')) return null;
  const id = s.slice(7);
  return (ctx?.outputs || []).find(o => o.output_id === id) || { output_id: id, n: null, title: id };
}
const ref = (v, ctx) => { const o = outputOf(v, ctx); return o ? (o.n ? '#' + o.n : 'a picture') : ''; };
const out = (v, ctx) => { const o = outputOf(v, ctx); return o ? { ref: o } : 'a picture'; };
const b = t => ({ b: t });
const join = xs => xs.filter(x => x != null && x !== '').join(' · ');
const quoted = s => (s ? `“${String(s).length > 60 ? String(s).slice(0, 58) + '…' : s}”` : '');

// ---------- built-in words ----------
const W = {
  find_tools: { running: 'Looking up tools', done: 'Looked up tools', icon: 'search', lookup: true, detail: a => quoted(a.query) },
  load_tools: { running: 'Loading tools', done: a => `Loaded ${(a.names || []).length || 'the'} tool${(a.names || []).length === 1 ? '' : 's'}`, icon: 'search', lookup: true,
    detail: a => a.group ? `the ${a.group} tools` : (a.names || []).map(n => toolLabel(n, ['comfy', 'gen3d', 'tts', 'lcpp', 'vllm', 'relay', 'hub']).toLowerCase()).join(', ') },
  read_skill: { running: 'Reading a guide', done: 'Read a guide', icon: 'bookmark', lookup: true, detail: a => a.name || '' },
  view_output: { running: 'Looking at the output', done: 'Looked at the output', icon: 'eye', lookup: true, detail: (a, ctx) => ref(a.output || a.id || a.ref, ctx) || a.output || '' },
  read_result: { running: 'Reading an earlier result', done: 'Read an earlier result', icon: 'search', lookup: true },
  comfy_list_workflows: { running: 'Listing workflows', done: 'Listed the workflows', icon: 'search', lookup: true },
  show: { running: 'Drawing it', done: a => ({ table: 'Made a table', image: 'Showed a picture', gallery: 'Showed a gallery' }[a.view] || 'Drew a chart'), icon: 'chart', detail: a => a.title || '' },   // plan 47.2
  hub_gpu_status: { running: 'Checking the GPU', done: 'Checked the GPU', icon: 'search', lookup: true },        // plan 46.2
  hub_doctor: { running: 'Checking the install', done: 'Checked the install', icon: 'search', lookup: true },
  hub_free_gpu: { running: 'Freeing the GPU', done: 'Freed the GPU', icon: 'tool', detail: a => (a.services || []).join(', ') },
  comfy_generate_image: { running: 'Generating an image', done: 'Generated an image', icon: 'image',
    detail: (a, ctx) => join([a.workflow && nameOf(a.workflow, { tool: 'comfy_generate_image', key: 'workflow', ctx }), a.aspect, a.preset]),
    sentence: (a, ctx) => ({ parts: ['Generated with ', b(nameOf(a.workflow || 'the default workflow', { tool: 'comfy_generate_image', key: 'workflow', ctx })),
      a.aspect ? `, ${ASPECT[a.aspect] || a.aspect}` : '', a.preset ? `, ${a.preset} preset` : '', a.seed != null && a.seed !== -1 ? `, seed ${a.seed}` : '', a.prompt ? ', from this prompt:' : '.'], quote: a.prompt }) },
  comfy_edit_image: { running: 'Editing the image', done: 'Edited the image', icon: 'wand',
    detail: (a, ctx) => join([ref(a.image, ctx), a.workflow && nameOf(a.workflow, { tool: 'comfy_edit_image', key: 'workflow', ctx }), a.preset]),
    sentence: (a, ctx) => ({ parts: ['Edited ', out(a.image, ctx), a.image_2 ? [' with ', out(a.image_2, ctx), ' as a reference'] : '', ' with ', b(nameOf(a.workflow || 'the default workflow', { tool: 'comfy_edit_image', key: 'workflow', ctx })),
      a.preset ? `, ${a.preset} preset` : '', a.prompt ? ', following this instruction:' : '.'].flat(), quote: a.prompt }) },
  comfy_animate_image: { running: 'Animating the image', done: 'Animated the image', icon: 'video',
    detail: (a, ctx) => join([ref(a.image, ctx), a.seconds ? `${a.seconds} s` : '']),
    sentence: (a, ctx) => ({ parts: ['Animated ', out(a.image, ctx), ' with ', b(nameOf(a.workflow || 'wan21-i2v', { tool: 'comfy_animate_image', key: 'workflow', ctx })), a.seconds ? ` for ${a.seconds} s` : '', a.prompt ? ', guided by:' : '.'], quote: a.prompt }) },
  comfy_generate_video: { running: 'Making a video', done: 'Made a video', icon: 'video',
    detail: a => join([a.aspect, a.seconds ? `${a.seconds} s` : '']),
    sentence: (a, ctx) => ({ parts: ['Made with ', b(nameOf(a.workflow || 'wan21-t2v', { tool: 'comfy_generate_video', key: 'workflow', ctx })), a.seconds ? `, ${a.seconds} s` : '', a.aspect ? `, ${ASPECT[a.aspect] || a.aspect}` : '', a.prompt ? ', from this prompt:' : '.'], quote: a.prompt }) },
  comfy_remove_background: { running: 'Removing the background', done: 'Removed the background', icon: 'scissors', detail: (a, ctx) => ref(a.image, ctx),
    sentence: (a, ctx) => ({ parts: ['Cut the subject out of ', out(a.image, ctx), ', leaving a transparent background.'] }) },
  comfy_upscale_image: { running: 'Upscaling the image', done: 'Upscaled the image', icon: 'upscale', detail: (a, ctx) => join([ref(a.image, ctx), a.scale ? `${a.scale}×` : '']),
    sentence: (a, ctx) => ({ parts: ['Made ', out(a.image, ctx), ` ${a.scale || 2}× bigger.`] }) },
  comfy_run_workflow: { running: 'Running a workflow', done: 'Ran a workflow', icon: 'tool', detail: (a, ctx) => a.workflow ? nameOf(a.workflow, { tool: 'comfy_run_workflow', key: 'workflow', ctx }) : '',
    sentence: (a, ctx) => ({ parts: ['Ran the ', b(nameOf(a.workflow || '?', { tool: 'comfy_run_workflow', key: 'workflow', ctx })), ' workflow', a.inputs?.prompt ? ' with this prompt:' : '.'], quote: a.inputs?.prompt }) },
  gen3d_make_3d: { running: 'Making a 3D model', done: 'Made a 3D model', icon: 'cube',
    detail: (a, ctx) => join([a.engine ? nameOf(a.engine, { tool: 'gen3d_make_3d', key: 'engine', ctx }) : '', a.image ? 'from ' + ref(a.image, ctx) : '', a.preset]),
    sentence: (a, ctx) => {
      const eng = b(nameOf(a.engine || (a.image ? 'trellis2' : 'cube3d'), { tool: 'gen3d_make_3d', key: 'engine', ctx }));
      const extra = [a.preset ? `, ${a.preset} preset` : '', Array.isArray(a.stages) && a.stages.length ? ` (${a.stages.join(', ')})` : ''].join('');
      return a.image ? { parts: ['Made from ', out(a.image, ctx), ' with ', eng, extra, '.'] } : { parts: ['Made with ', eng, extra, a.prompt ? ', from this prompt:' : '.'], quote: a.prompt };
    } },
  tts_speak: { running: 'Recording speech', done: 'Recorded speech', icon: 'wave', detail: a => join([a.voice, quoted(a.text)]),
    sentence: a => ({ parts: ['Spoke', a.voice ? [' in ', b(a.voice), '’s voice'] : '', a.direction ? `, ${a.direction}` : '', ':'].flat(), quote: a.text }) },
  tts_clone_voice: { running: 'Cloning a voice', done: 'Cloned a voice', icon: 'wave', detail: a => a.name || '' },
  tts_design_voice: { running: 'Designing a voice', done: 'Designed a voice', icon: 'wave', detail: a => a.name || '' },
  lcpp_start_llm: { running: 'Starting an LLM', done: 'Started an LLM', icon: 'play', detail: a => a.model || '' },
  lcpp_stop_llm: { running: 'Stopping an LLM', done: 'Stopped an LLM', icon: 'stop', detail: a => a.name || '' },
  vllm_load_llm: { running: 'Loading an LLM in vLLM', done: 'Loaded an LLM in vLLM', icon: 'play', detail: a => a.profile || a.id || '' },
  vllm_unload_llm: { running: 'Unloading the vLLM model', done: 'Unloaded the vLLM model', icon: 'stop' },
};
for (const [k, v] of Object.entries(W)) registerStep(k, v);

// ---------- the fallback, from the tool's name and schema ----------
const VERBS = { list: ['Listing', 'Listed'], start: ['Starting', 'Started'], stop: ['Stopping', 'Stopped'], load: ['Loading', 'Loaded'], unload: ['Unloading', 'Unloaded'],
  get: ['Getting', 'Got'], search: ['Searching', 'Searched'], save: ['Saving', 'Saved'], restore: ['Restoring', 'Restored'], delete: ['Deleting', 'Deleted'], cancel: ['Cancelling', 'Cancelled'],
  design: ['Designing', 'Designed'], clone: ['Cloning', 'Cloned'], make: ['Making', 'Made'], generate: ['Generating', 'Generated'], edit: ['Editing', 'Edited'], run: ['Running', 'Ran'],
  remove: ['Removing', 'Removed'], animate: ['Animating', 'Animated'], speak: ['Speaking', 'Spoke'], read: ['Reading', 'Read'], find: ['Finding', 'Found'], view: ['Viewing', 'Viewed'],
  create: ['Creating', 'Created'], update: ['Updating', 'Updated'], upscale: ['Upscaling', 'Upscaled'], set: ['Setting', 'Set'], send: ['Sending', 'Sent'] };
const MODS = ['comfy', 'gen3d', 'tts', 'lcpp', 'vllm', 'relay', 'hub', 'agent', 'opencode'];
function fallbackWords(name, ctx) {
  const own = (ctx?.tools || []).find(t => t.name === name)?.mod;
  const mods = [...new Set([...MODS, ...(ctx?.mods || []), ...(own ? [own] : [])])], words = toolLabel(name, mods).toLowerCase().split(' ').filter(Boolean);
  const v = VERBS[words[0]], rest = words.slice(v ? 1 : 0).join(' ');
  if (v) return [`${v[0]} ${rest}`.trim(), `${v[1]} ${rest}`.trim()];
  return [`Checking ${rest}`, `Checked ${rest}`];
}
const keyTitle = (k, p) => p?.title || k.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());

/** { label, icon, detail, lookup } for a tool row. done: the call finished. */
export function stepText(name, { args = {}, done = false, ctx = null } = {}) {
  const w = steps.get(name);
  const call = (f, d) => { try { return typeof f === 'function' ? f(args || {}, ctx) : f ?? d; } catch { return d; } };
  if (w) return { label: call(done ? w.done : w.running, ''), icon: w.icon || 'tool', detail: call(w.detail, '') || '', lookup: !!w.lookup };
  const [running, finished] = fallbackWords(name, ctx);
  const v = Object.entries(args || {}).find(([, x]) => typeof x === 'string' && x.length < 40 && !x.startsWith('output:'));
  return { label: done ? finished : running, icon: 'tool', detail: v ? v[1] : '', lookup: false };
}

/** The sentence a step opens to: { parts, quote, fields } (fields: the rest as title → value, fallback only). */
export function stepSentence(name, { args = {}, ctx = null, done = true } = {}) {
  const w = steps.get(name);
  if (w?.sentence) { try { return { fields: [], ...w.sentence(args || {}, ctx) }; } catch { /* the fallback below */ } }
  const props = schemaOf(name, ctx)?.properties || {}, label = stepText(name, { args, done, ctx }).label;
  const fields = Object.entries(args || {}).filter(([k, v]) => v != null && v !== '' && k !== 'prompt' && k !== 'text').map(([k, v]) => {
    const o = outputOf(v, ctx);
    return [keyTitle(k, props[k]), o ? { ref: o } : Array.isArray(v) ? v.map(x => nameOf(x, { tool: name, key: k, ctx })).join(', ')
      : typeof v === 'object' ? JSON.stringify(v) : nameOf(v, { tool: name, key: k, ctx })];
  });
  const quote = args?.prompt || args?.text || null;
  return { parts: [label + (fields.length ? ' with:' : quote ? ':' : '.')], quote, fields };
}

/** A failed call's error, in plain words: the detail as the sentence, the fix under it, the code kept for Raw. */
export function errorText(result) {
  const e = result?.error || {};
  const status = result?.status;
  const raw = e.detail || (status === 'denied' ? 'You said no.' : status === 'cancelled' ? 'Stopped.' : status === 'skipped' ? 'Skipped.' : 'It failed.');
  // "3D Generate refused it (HTTP 422): : Value error, TRELLIS.2 …" → "TRELLIS.2 …" (the mod's own words)
  const text = String(raw).replace(/^.*?\(HTTP \d{3}\):[\s:]*/, '').replace(/^(Value|Assertion|Type) error,\s*/i, '').trim() || String(raw);
  return { text: text.replace(/^./, c => c.toUpperCase()), fix: e.fix || null, code: e.code || null };
}
