// A chat module (plan 44.1; docs/mods.md "Chat cards"): turn it on with `chat = "ui/chat.js"` under [ui] in
// service.toml. The Chat page imports this file once and calls setup(chat). Delete it (or the mod) and the
// chat falls back to its plain cards.
//
// chat.registerStep(tool, words)        the words of a step in the activity fold
// chat.registerCard('live:' + tool, C)  a live card under the fold while the tool's job runs, and after it ends
// chat.live                             the live kit (web/live-kit.js): LiveCard, Stage, Waiting, PreviewLayers, …
//
// A tool's name in the chat is <mod id>_<tool key> (here: _template_hello).

export default function setup(chat) {
  const { h } = chat.ui, kit = chat.live;

  chat.registerStep('_template_hello', { running: 'Saying hello', done: 'Said hello', icon: 'chat' });

  // While it runs: the job's live progress (stage, step, a preview frame); when done: what it made.
  chat.registerCard('live:_template_hello', ({ ctx }) => {
    const { live, status, outputs } = ctx.live;
    const done = status === 'done';
    return h(kit.LiveCard, { icon: 'job', title: done ? 'Said hello' : 'Saying hello', meta: kit.metaText(live, status), pct: done ? 1 : (live?.step || 0) / (live?.steps || 1), done },
      h(kit.Stage, { aspect: kit.aspectOf(live, 16 / 9), max: 200 },
        h(kit.PreviewLayers, { src: kit.previewSrc(live), final: done ? outputs[0]?.url : null }),
        done ? null : h(kit.Waiting, { ...(kit.waitInfo(live, ctx.live.note) || {}), quiet: !!live?.preview })));
  });
}
