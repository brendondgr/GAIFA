// Download, Copy and Save to… on every output (plan 48.4), as actions in the registry (chat-actions.js): Download
// (the browser's own save dialog), Copy (a picture as PNG on the clipboard; anything else, its link), and Save to
// folder… (the desktop's folder chooser, plan 43.1, then the workspace mod writes it into a folder of the chat's
// environment at Edit or above, with Undo; elsewhere is refused with how to allow it).

import { registerAction } from './chat-actions.js';

export const KINDS = ['image', 'video', 'audio', 'model3d', 'text', 'document'];
const fileUrl = o => `/api/outputs/${encodeURIComponent(o.output_id || o.id)}/file`;

/** What Copy does for an output: a picture as an image, anything else as its link. */
export const copyKind = o => (o.kind === 'image' ? 'image' : 'link');

/** A picture (any type the browser draws) as a PNG blob. */
async function asPng(blob) {
  if (blob.type === 'image/png') return blob;
  const bmp = await createImageBitmap(blob), c = document.createElement('canvas');
  c.width = bmp.width; c.height = bmp.height; c.getContext('2d').drawImage(bmp, 0, 0);
  return new Promise(r => c.toBlob(r, 'image/png'));
}

export async function download(o) {
  const a = document.createElement('a');
  a.href = fileUrl(o); a.download = ''; document.body.appendChild(a); a.click(); a.remove();
}

export async function copy(o, ctx) {
  try {
    if (copyKind(o) === 'image' && globalThis.ClipboardItem) {
      const blob = await asPng(await (await fetch(fileUrl(o))).blob());
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
      ctx.toast?.('Copied the picture', 'success');
    } else {
      await navigator.clipboard.writeText(new URL(fileUrl(o), location.href).href);
      ctx.toast?.('Copied its link', 'success');
    }
  } catch (e) { ctx.toast?.(`Couldn't copy: ${e.message || e}`, 'error'); }
}

/** The folder to save into: the desktop's chooser, or a typed path when there's none; null when cancelled. */
async function pickFolder(api) {
  try {
    const r = await api.callService('workspace', 'POST', '/v1/pick-folder', { json: { start: '/', title: 'Save into a folder' } });
    return r.json?.cancelled ? null : r.json?.path || null;
  } catch (e) {
    if (e.status === 501) return globalThis.prompt?.('The folder to save into (a full path):') || null;   // no chooser here
    throw e;
  }
}

/** A refusal's words: the mod's detail and its fix. */
export const refusal = e => { const b = e?.data?.body || {}; return `${b.detail || e?.detail || e?.message || e}${b.fix ? ' — ' + b.fix : ''}`; };

export async function saveTo(o, ctx) {
  try {
    const folder = await pickFolder(ctx.api);
    if (!folder) return;
    const r = await ctx.api.callService('workspace', 'POST', '/v1/save-output', { json: { output_id: o.output_id || o.id, folder, environment: ctx.environment || undefined, thread: ctx.thread || undefined } });
    ctx.toast?.(`Saved to ${r.json.path}`, 'success');
  } catch (e) { ctx.toast?.(`Not saved: ${refusal(e)}`, 'error'); }
}

for (const kind of KINDS) {
  registerAction({ id: `${kind}.download`, on: kind, label: 'Download', icon: 'download', run: o => download(o), order: 90 });
  registerAction({ id: `${kind}.copy`, on: kind, label: 'Copy', icon: 'copy', run: (o, ctx) => copy(o, ctx), order: 91 });
  registerAction({ id: `${kind}.save`, on: kind, label: 'Save to…', icon: 'folder', needs: 'workspace_write', run: (o, ctx) => saveTo(o, ctx), order: 92 });
}
