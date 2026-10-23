// Images & Video in Chat (plan 45.2): live cards for the picture and video tools, after the prototype the user
// approved (docs/reference/live-cards-2026-10/). While a run waits it says so ("Waiting for the GPU · …",
// "Loading <workflow>"); then ComfyUI's preview frames fade in over each other with "Step k of n" (plan 45.1);
// then the result fades in in the same box, with its #n, title and buttons. Loaded by the Chat page from
// `[ui] chat` (plan 44.1); deleting the mod removes these cards.

const PICTURE = ['comfy_generate_image', 'comfy_edit_image', 'comfy_upscale_image', 'comfy_remove_background', 'comfy_run_workflow'];
const VIDEO = ['comfy_animate_image', 'comfy_generate_video'];
const WORDS = {
  comfy_generate_image: ['Making a picture', 'Made a picture', "Couldn't make the picture"],
  comfy_edit_image: ['Editing the picture', 'Edited the picture', "Couldn't edit the picture"],
  comfy_upscale_image: ['Upscaling the picture', 'Upscaled the picture', "Couldn't upscale the picture"],
  comfy_remove_background: ['Removing the background', 'Removed the background', "Couldn't remove the background"],
  comfy_run_workflow: ['Running the workflow', 'Ran the workflow', "The workflow failed"],
  comfy_animate_image: ['Making a video', 'Made a video', "Couldn't make the video"],
  comfy_generate_video: ['Making a video', 'Made a video', "Couldn't make the video"],
};

/** The box's shape from the call's arguments: "16:9", "4:3 (Standard)", or width and height; null when it doesn't say. */
export function aspectFromArgs(a) {
  const m = /(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)/.exec(String(a?.aspect || ''));
  if (m && +m[2] > 0) return +m[1] / +m[2];
  if (a?.width > 0 && a?.height > 0) return a.width / a.height;
  return null;
}

/** Title, meta line and state of a card from its step. */
export function cardState(name, status, live, seconds, kit) {
  const [running, done, failed] = WORDS[name] || WORDS.comfy_run_workflow;
  const isDone = status === 'done', isFailed = status === 'failed' || status === 'error';
  const secs = seconds == null ? '' : seconds < 60 ? Math.round(seconds) + ' s' : Math.floor(seconds / 60) + 'm ' + Math.round(seconds % 60) + 's';
  return { title: isDone ? done : isFailed ? failed : running, done: isDone, failed: isFailed,
    meta: isDone || isFailed ? secs : kit.metaText(live, status === 'queued' ? 'queued' : status) };
}

export default function setup(chat) {
  const { h } = chat.ui, kit = chat.live, { ActionBar, nameOf } = chat.parts || {};

  function MediaCard({ ctx, video }) {
    const { row, live, note, status, outputs } = ctx.live;
    const args = row.item.call?.arguments || {}, out = outputs[0];
    const st = cardState(row.name, status, live, row.seconds, kit);
    const outAspect = out?.width > 0 && out?.height > 0 ? out.width / out.height : null;
    const aspect = aspectFromArgs(args) || kit.aspectOf(live, outAspect || (video ? 16 / 9 : 1));
    const wf = args.workflow && nameOf ? nameOf(args.workflow, { tool: row.name, key: 'workflow', ctx }) : null;
    const wait = st.done || st.failed ? null : kit.waitInfo(live, note, { model: wf || null, starting: 'Starting ComfyUI' });
    const final = st.done && out ? (video ? out.url : out.url || out.preview) : null;
    const badge = st.done || st.failed || !live?.preview ? null
      : live.stage === 'decoding' ? (video ? 'Encoding' : 'Decoding')
      : kit.stepLabel(live) + (video && args.frames ? ` · ${args.frames} frames at once` : '');
    const foot = st.done && out ? [
      h('span', { key: 'n', style: { fontFamily: kit.MONO, fontSize: 11, fontWeight: 600, color: 'var(--pu,#BC8CFF)' } }, out.n ? '#' + out.n : 'output'),
      h('span', { key: 't', style: { color: 'var(--tx,#E6EAF2)', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '50%' } }, out.title || ''),
      wf ? h('span', { key: 'w' }, wf) : null,
      ActionBar ? h('span', { key: 'a', style: { marginLeft: 'auto' } }, h(ActionBar, { output: out, ctx })) : null,
    ] : null;
    return h(kit.LiveCard, { icon: video ? 'video' : 'image', title: st.title, meta: st.meta, pct: row.progress?.progress, done: st.done, failed: st.failed, foot },
      h(kit.Stage, { aspect },
        h(kit.PreviewLayers, { src: st.done ? null : kit.previewSrc(live), final, finalKind: video ? 'video' : 'image', alt: out?.title || '' }),
        st.done || st.failed ? null : h(kit.Waiting, { title: wait?.title, sub: wait?.sub, quiet: !wait }),
        badge ? h(kit.Badge, null, badge) : null,
        st.done && out && ctx.openOutput ? h('button', { type: 'button', title: 'Open in Outputs', onClick: () => ctx.openOutput(out.output_id),
          style: { position: 'absolute', inset: 0, zIndex: 6, background: 'none', border: 0, cursor: 'zoom-in' } }) : null));
  }

  for (const name of PICTURE) chat.registerCard('live:' + name, ({ ctx }) => h(MediaCard, { ctx, video: false }));
  for (const name of VIDEO) chat.registerCard('live:' + name, ({ ctx }) => h(MediaCard, { ctx, video: true }));
}
