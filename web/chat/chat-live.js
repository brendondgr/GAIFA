// Live cards in Chat (plan 44.3): under a turn's activity fold, each tool step that has a live card shows it, running
// or done; a running step of a tool without one shows the kit's generic preview while its job reports a frame.
//
//   registerCard('live:comfy_generate_image', ({ row, item, live, note, status, outputs, ctx, kit }) => …)
//
// `live` is the job's live progress (plan 44.2), `note` the GPU queue's words, `status` running | done | failed |
// queued | waiting, `outputs` the call's outputs with their #n, `kit` web/live-kit.js. The output strip leaves out
// the outputs of a tool with a live card: its card shows them where they were made.

import { h } from './chat-ui.js';
import { Card, hasCard } from './chat-cards.js';
import * as kit from '../live-kit.js';

const R = () => globalThis.React;

/** The tool rows of a turn that draw a live card: [{row, own}] (own: the tool registered `live:<name>`). */
export function liveRows(turn) {
  return (turn.steps || []).flatMap(s => s.rows).filter(r => r.type === 'tool').flatMap(r => {
    if (hasCard('live:' + r.name)) return [{ row: r, own: true }];
    if (r.status === 'running' && r.progress?.live?.preview) return [{ row: r, own: false }];
    return [];
  });
}

/** Does a live card show this output (so the strip leaves it out)? */
export const shownLive = o => !!(o && o.tool && hasCard('live:' + o.tool));

function outputsOf(row, ctx) {
  return (row.item.result?.outputs || []).map(o => (ctx.outputs || []).find(x => x.output_id === o.output_id) || o);
}

export function LiveCards({ turn, ctx }) {
  const rows = liveRows(turn);
  if (!rows.length) return null;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 } },
    rows.map(({ row, own }) => {
      const live = row.progress?.live || null, note = row.progress?.note || null;
      if (!own) return h(kit.LivePreview, { key: row.key, live, note, title: 'Working', pct: row.progress?.progress });
      const item = { ...row.item, kind: 'live', key: 'live:' + row.key };
      return h('div', { key: row.key, style: { minWidth: 0 } },
        h(Card, { item, ctx: { ...ctx, live: { row, live, note, status: row.status, outputs: outputsOf(row, ctx), kit } } }));
    }));
}
