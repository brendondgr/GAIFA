// The chat activity sample turn (plan 19): the design study's event log ("make a samurai, then
// turn it into a 3D model") in the agent's real event shapes, its seven stages, and a turn with a
// failed call and a retry. A test fixture, independent of web/design/ (removed in 19.7).

export const IMG_ID = '80bcb2c38362', M3D_ID = 'e9a79af1fd7e';
const pv = id => `/api/outputs/${id}/preview`;
const t0 = 1760900000, at = s => t0 + s;

const OUT_IMG = { n: 1, output_id: IMG_ID, kind: 'image', title: 'Samurai, front view', summary: 'image 790×790', url: pv(IMG_ID), preview: pv(IMG_ID),
  prompt: 'A young samurai in a navy kimono and grey hakama, full body, front view, plain white background, soft studio light' };
const OUT_3D = { n: 2, output_id: M3D_ID, kind: 'model3d', title: 'Samurai 3D model', summary: '3D model · 412k faces', preview: pv(M3D_ID), prompt: 'from #1 · TRELLIS.2 · balanced' };

const IMG_ARGS = { prompt: OUT_IMG.prompt, workflow: 'zimage-turbo', aspect: '1:1', seed: 81723 };
const M3D_ARGS = { image: 'output:' + IMG_ID, engine: 'trellis2', preset: 'balanced', stages: ['shape', 'texture'] };
export const M3D_SCHEMA = {
  type: 'object', required: ['engine'],
  properties: {
    image: { type: 'string', format: 'aihub-file', 'x-kind': 'image', title: 'Picture' },
    engine: { type: 'string', title: 'Engine', enum: ['trellis2', 'hunyuan21', 'sam3d_objects', 'sam3d_body', 'cube3d'], default: 'trellis2' },
    preset: { type: 'string', title: 'Preset', enum: ['draft', 'balanced', 'detailed'], default: 'balanced' },
    stages: { type: 'array', title: 'Stages', items: { type: 'string', enum: ['shape', 'texture', 'parts', 'rig'] } },
  },
};
export const APPROVAL = { id: 'c4', approval_id: 'ap1', tool: 'gen3d_make_3d', arguments: M3D_ARGS, ask_fields: ['engine', 'preset'], schema: M3D_SCHEMA, risk: 'generates',
  description: 'Makes a 3D model from a picture (TRELLIS.2, Hunyuan3D 2.1, SAM 3D) or from a text prompt (Cube3D).' };

const THINK = {
  s1: 'They want a samurai picture, then a 3D model made from it. I need the image tool and the 3D tool, so I\'ll find and load those first.',
  s2: 'Tools are ready. For image-to-3D a single figure, full body, front view on a plain background works best, so I\'ll ask for exactly that.',
  s3: 'The picture came out clean: full body, plain background, nothing cropped. **TRELLIS.2** is the most faithful engine for one object or figure; the balanced preset is enough here.',
  s4: 'Both are done. Say what was made in a sentence and offer the likely next steps.',
};
const ANSWER = 'Here\'s your samurai **#1** and the 3D model made from it **#2** (TRELLIS.2, balanced).\n\nNext, I can **add a rig** so it can be posed, make a **low-poly** version for a game, or **animate** the picture.';

const ev = (seq, s, type, payload) => ({ seq, ts: at(s), type, payload });
export const EVENTS = [
  ev(1, 0, 'user', { text: 'Make me a samurai character, then turn it into a 3D model.' }),
  ev(2, 4, 'thinking', { text: THINK.s1, seconds: 4, step: 's1' }),
  ev(3, 4, 'tool_call', { id: 'c1', name: 'find_tools', arguments: { query: 'image 3d model' }, step: 's1', by: 'model' }),
  ev(4, 4, 'tool_call', { id: 'c2', name: 'load_tools', arguments: { names: ['comfy_generate_image', 'gen3d_make_3d'] }, step: 's1', by: 'model' }),
  ev(5, 5, 'tool_result', { id: 'c1', name: 'find_tools', status: 'done', content: '{"status":"done","result":{"tools":["comfy_generate_image","comfy_edit_image","gen3d_make_3d"]}}' }),
  ev(6, 5, 'tool_result', { id: 'c2', name: 'load_tools', status: 'done', content: '{"status":"done","result":{"loaded":2}}' }),
  ev(7, 8, 'thinking', { text: THINK.s2, seconds: 3, step: 's2' }),
  ev(8, 9, 'assistant', { text: 'I\'ll make the picture first, as a full-body front view so it converts cleanly.', step: 's2', model: 'qwen3.6-35b' }),
  ev(9, 9, 'tool_call', { id: 'c3', name: 'comfy_generate_image', arguments: IMG_ARGS, step: 's2', by: 'model' }),
  ev(10, 9, 'call', { id: 'c3', call_id: 'j1' }),
  ev(11, 27, 'tool_result', { id: 'c3', name: 'comfy_generate_image', status: 'done', outputs: [OUT_IMG],
    content: JSON.stringify({ status: 'done', result: { workflow: 'zimage-turbo', seconds: 18 }, outputs: [{ id: IMG_ID, kind: 'image' }] }) }),
  ev(12, 32, 'thinking', { text: THINK.s3, seconds: 5, step: 's3' }),
  ev(13, 33, 'assistant', { text: 'Now the 3D model. TRELLIS.2 keeps the most detail for a single figure.', step: 's3', model: 'qwen3.6-35b' }),
  ev(14, 33, 'tool_call', { id: 'c4', name: 'gen3d_make_3d', arguments: M3D_ARGS, step: 's3', by: 'model' }),
  ev(15, 33, 'approval', APPROVAL),
  ev(16, 41, 'decision', { id: 'c4', approval_id: 'ap1', approve: true, arguments: M3D_ARGS, status: 'approved' }),
  ev(17, 41, 'call', { id: 'c4', call_id: 'j2' }),
  ev(18, 171, 'tool_result', { id: 'c4', name: 'gen3d_make_3d', status: 'done', outputs: [OUT_3D],
    content: JSON.stringify({ status: 'done', result: { engine: 'trellis2', faces: 412000, seconds: 130 }, outputs: [{ id: M3D_ID, kind: 'model3d' }] }) }),
  ev(19, 174, 'thinking', { text: THINK.s4, seconds: 2, step: 's4' }),
  ev(20, 178, 'assistant', { text: ANSWER, step: 's4', model: 'qwen3.6-35b' }),
  ev(21, 178, 'usage', { input: 18234, output: 412 }),
  ev(22, 178, 'state', { state: 'idle' }),
];

// The stages the page steps through: the log up to `upto`, the live (unsaved) deltas and progress, and "now".
export const STAGES = [
  { id: 'think', label: 'Thinking', upto: 1, now: 2.5, live: { deltas: { s1: { thinking: THINK.s1.slice(0, 70), t0: at(0.5) } } } },
  { id: 'lookup', label: 'Looking up tools', upto: 4, now: 4.6 },
  { id: 'image', label: 'Generating', upto: 10, now: 17, live: { progress: { c3: { id: 'c3', progress: 0.42, note: 'sampling 4/8', elapsed_s: 8 } } } },
  { id: 'approval', label: 'Needs approval', upto: 15, now: 36 },
  { id: '3d', label: 'Making 3D', upto: 17, now: 120, live: { progress: { c4: { id: 'c4', progress: 0.63, note: 'texture', elapsed_s: 79 } } } },
  { id: 'answer', label: 'Writing answer', upto: 19, now: 176, live: { deltas: { s4: { text: ANSWER.slice(0, 92), t0: at(175) } } } },
  { id: 'done', label: 'Done', upto: 99, now: 178, done: true },
];
export function stageData(i) {
  const s = STAGES[i];
  return { events: EVENTS.filter(e => e.seq <= s.upto), live: { deltas: {}, progress: {}, meter: null, ...(s.live || {}) }, running: !s.done, now: at(s.now) };
}

export const ERROR_EVENTS = [
  ev(1, 0, 'user', { text: 'Make #1 into a 3D model' }),
  ev(2, 2, 'tool_call', { id: 'e1', name: 'read_skill', arguments: { name: 'making-3d' }, step: 'x1', by: 'model' }),
  ev(3, 3, 'tool_result', { id: 'e1', name: 'read_skill', status: 'done', content: '{}' }),
  ev(4, 5, 'tool_call', { id: 'e2', name: 'gen3d_make_3d', arguments: { image: 'output:' + IMG_ID, engine: 'cube3d', preset: 'balanced' }, step: 'x2', by: 'model' }),
  ev(5, 6, 'tool_result', { id: 'e2', name: 'gen3d_make_3d', status: 'error', content: '{}',
    error: { code: 'invalid_arguments', detail: 'Cube3D makes a model from text and can\'t use a picture.', fix: 'Use an image engine, e.g. engine: "trellis2".' } }),
  ev(6, 7, 'note', { text: 'the model\'s reply was empty; asked again', level: 'info' }),
  ev(7, 9, 'tool_call', { id: 'e3', name: 'gen3d_make_3d', arguments: { image: 'output:' + IMG_ID, engine: 'trellis2', preset: 'balanced' }, step: 'x3', by: 'model' }),
  ev(8, 139, 'tool_result', { id: 'e3', name: 'gen3d_make_3d', status: 'done', outputs: [{ ...OUT_3D, n: 2 }], content: '{}' }),
  ev(9, 142, 'assistant', { text: 'Done: **#2** is the 3D model of the samurai.', step: 'x4' }),
];
