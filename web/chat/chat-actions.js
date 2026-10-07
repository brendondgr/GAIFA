// The ACTIONS REGISTRY (plan 14.1, 14.5): the buttons under a result card and the composer's quick
// actions. Adding a product means registering an action; nothing else in the page changes.
//
//   registerAction({
//     id: 'image.upscale',            // unique; registering the same id again replaces it
//     label: 'Upscale', icon: 'upscale',  // icon: a name from chat-ui.js ICONS, or an SVG path
//     on: 'image',                    // 'image' | 'video' | 'audio' | 'model3d' | 'composer' (or any output kind)
//     tool: 'comfy_upscale',          // run this tool: opens a parameter card, then POST …/action
//     args: output => ({ image: fileRef(output) }),   // prefilled arguments
//     prompt: output => `Upscale #${output.n}`,       // …or send a chat message instead of a tool
//     attach: true,                   // …or attach the output to the composer
//     run: (output, ctx) => {},       // …or do anything (ctx: see runAction)
//     needs: 'gen3d_make_3d',         // hide unless this tool is in the catalog (implied by `tool`)
//     when: output => true,           // hide for some outputs
//     order: 50,                      // sort key (lower first)
//   })
//
// Besides the registered ones, every catalog tool with a file input (`x-kind`) that fits an
// output's kind becomes an action automatically (`deriveActions`), so a new mod's tool that takes
// an image shows up under image results with no UI code. Pure: tested in utils/tests/web/chat.test.mjs.

import { toolLabel } from './chat-ui.js';

const registry = new Map();
const TARGETS = /^[a-z][a-z0-9_-]*$/;

export function registerAction(a) {
  if (!a || !a.id || !a.label || !a.on) throw new Error('registerAction: id, label and on are required');
  if (!TARGETS.test(a.on)) throw new Error(`registerAction: bad target ${a.on}`);
  if (!a.tool && !a.prompt && !a.attach && !a.run) throw new Error(`registerAction ${a.id}: give tool, prompt, attach or run`);
  registry.set(a.id, { order: 50, ...a });
  return () => registry.delete(a.id);
}
export const unregisterAction = id => registry.delete(id);
export const registeredActions = () => [...registry.values()];

/** `{"$file": "output:<id>"}`: what a tool's file input takes (13.2). */
export const fileRef = o => ({ $file: 'output:' + (o.output_id || o.id) });
// Output kind → the `x-kind` of file inputs that take it.
export const XKIND = { image: 'image', video: 'video', audio: 'audio', model3d: 'mesh' };

/** The name of a tool's file input that takes outputs of `kind`, or null. Required inputs first. */
export function fileInputFor(tool, kind) {
  const want = XKIND[kind] || kind, props = tool?.parameters?.properties || {}, req = tool?.parameters?.required || [];
  const names = Object.keys(props).filter(n => props[n] && props[n]['x-kind'] === want);
  return names.sort((a, b) => (req.includes(b) ? 1 : 0) - (req.includes(a) ? 1 : 0))[0] || null;
}

/** Actions made from the catalog: a tool whose file input fits `kind` (not destructive, not the hub's own). */
export function deriveActions(tools, kind) {
  const out = [];
  for (const t of tools || []) {
    if (t.available === false || t.risk === 'destructive' || t.mod === 'hub') continue;
    const f = fileInputFor(t, kind);
    if (!f) continue;
    out.push({ id: 'tool:' + t.name, label: toolLabel(t.name, [t.mod]), on: kind, tool: t.name, derived: true, order: 80, icon: 'tool',
      args: o => ({ [f]: fileRef(o) }) });
  }
  return out;
}

/** The actions to show for an output of `kind` (or 'composer'), given the tool catalog
 *  (`tools`: full tools or index items; null while it loads: tool actions are hidden then). */
export function actionsFor(target, { tools = null, output = null, derive = true } = {}) {
  const names = new Set((tools || []).filter(t => t.available !== false).map(t => t.name));
  const ok = a => (!a.tool || names.has(a.tool)) && (!a.needs || names.has(a.needs)) && (!a.when || !output || a.when(output));
  const list = registeredActions().filter(a => a.on === target && ok(a));
  if (derive && target !== 'composer' && tools) {
    const have = new Set(list.map(a => a.tool).filter(Boolean));
    for (const a of deriveActions(tools.filter(t => t.parameters), target)) if (!have.has(a.tool)) { list.push(a); have.add(a.tool); }
  }
  return list.sort((a, b) => a.order - b.order);
}

/** Runs an action. ctx: { openTool(tool, args, action), sendPrompt(text), attach(output) }. */
export function runAction(a, output, ctx) {
  if (a.run) return a.run(output, ctx);
  if (a.attach) return ctx.attach(output);
  if (a.prompt) return ctx.sendPrompt(a.prompt(output));
  if (a.tool) return ctx.openTool(a.tool, a.args ? a.args(output || {}) : {}, a);
  return undefined;
}

const ref = o => (o?.n ? `#${o.n}` : 'that output');

// ---------- built-in result actions ----------
registerAction({ id: 'image.animate', on: 'image', label: 'Animate', icon: 'video', tool: 'comfy_animate_image', args: o => ({ image: fileRef(o) }), order: 10 });
registerAction({ id: 'image.edit', on: 'image', label: 'Edit', icon: 'wand', tool: 'comfy_edit_image', args: o => ({ image: fileRef(o) }), order: 20 });
registerAction({ id: 'image.removebg', on: 'image', label: 'Remove background', icon: 'scissors', tool: 'comfy_remove_background', args: o => ({ image: fileRef(o) }), order: 30 });
// gen3d makes 3D from text only, so this one asks the agent (which describes the image first).
registerAction({ id: 'image.make3d', on: 'image', label: 'Make 3D', icon: 'cube', needs: 'gen3d_make_3d', prompt: o => `Make a 3D model of ${ref(o)}`, order: 40 });
registerAction({ id: 'image.describe', on: 'image', label: 'Describe', icon: 'eye', prompt: o => `Describe ${ref(o)}`, order: 60 });
registerAction({ id: 'image.reference', on: 'image', label: 'Use as reference', icon: 'clip', attach: true, order: 70 });
registerAction({ id: 'video.describe', on: 'video', label: 'Describe', icon: 'eye', prompt: o => `Describe ${ref(o)}`, order: 60 });
registerAction({ id: 'model3d.rig', on: 'model3d', label: 'Rig', icon: 'person', needs: 'gen3d_make_3d', prompt: o => `Rig the 3D model ${ref(o)} so it can be posed`, order: 10 });

// ---------- built-in composer quick actions (each opens a parameter card directly) ----------
registerAction({ id: 'quick.image', on: 'composer', label: 'Image', icon: 'image', tool: 'comfy_generate_image', order: 10 });
registerAction({ id: 'quick.video', on: 'composer', label: 'Video', icon: 'video', tool: 'comfy_generate_video', order: 20 });
registerAction({ id: 'quick.3d', on: 'composer', label: '3D', icon: 'cube', tool: 'gen3d_make_3d', order: 30 });
registerAction({ id: 'quick.speech', on: 'composer', label: 'Speech', icon: 'wave', tool: 'tts_speak', order: 40 });
registerAction({ id: 'quick.edit', on: 'composer', label: 'Edit image', icon: 'wand', tool: 'comfy_edit_image', order: 50 });
