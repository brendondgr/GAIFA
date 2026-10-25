// Live cards in Chat (plan 44.3): under a turn's activity fold, each tool step that has a live card shows it, running
// or done; a running step of a tool without one shows the kit's generic preview while its job reports a frame.
//
//   registerCard('live:comfy_generate_image', ({ item, ctx }) => …)
//
// The card's ctx.liveCard = { row, live, note, status, outputs, kit } (ctx.live stays "connected to the live hub"):
// `live` is the job's live progress (plan 44.2), `note` the GPU queue's words, `status` running | done | failed |
// queued | waiting, `outputs` the call's outputs with their #n, `turnOutputs` all the turn's outputs, `kit` web/live-kit.js. The output strip leaves out
// the outputs of a tool with a live card: its card shows them where they were made.

import { h } from './chat-ui.js';
import { Card, hasCard } from './chat-cards.js';
import * as kit from '../live-kit.js';
import { FixCards } from './chat-fix.js';
import { viewOf, ViewCard } from './chat-view.js';

const R = () => globalThis.React;

// Refused before it ran: no card (the fold says why); a step waiting for your approval gets its card once it runs.
const NEVER_RAN = new Set(['invalid_arguments', 'unknown_tool', 'unknown_call', 'denied', 'tool_unavailable', 'service_not_running', 'service_not_found', 'needs_room']);
const ran = r => r.status === 'running' || r.status === 'done'
  || ((r.status === 'error' || r.status === 'failed') && !NEVER_RAN.has(r.item?.result?.error?.code) && r.item?.result?.status !== 'denied'
      && !r.item?.result?.error?.fixes?.length && !r.item?.result?.error?.log?.length);   // a fix-it card stands in for it

/** The tool rows of a turn that draw a live card: [{row, own, view?}] (own: the tool registered `live:<name>`;
 *  view: the tool declares a default view, plan 46.1, drawn once it's done). */
export function liveRows(turn, tools = null) {
  return (turn.steps || []).flatMap(s => s.rows).filter(r => r.type === 'tool' && ran(r)).flatMap(r => {
    if (hasCard('live:' + r.name)) return [{ row: r, own: true }];
    const view = viewOf(tools, r.name);
    if (view && r.status === 'done') return [{ row: r, own: false, view }];
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
  const rows = liveRows(turn, ctx.tools), fix = h(FixCards, { key: 'fixes', turn, ctx });      // plan 46.5: failed steps' fixes
  if (!rows.length) return fix;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 } }, fix,
    rows.map(({ row, own, view }) => {
      if (view) return h(ViewCard, { key: row.key, row, view, ctx });                   // plan 46.1: a tool's default view
      const live = row.progress?.live || null, note = row.progress?.note || null;
      if (!own) return h(kit.LivePreview, { key: row.key, live, note, title: 'Working', pct: row.progress?.progress });
      const item = { ...row.item, kind: 'live', key: 'live:' + row.key };
      return h('div', { key: row.key, style: { minWidth: 0 } },
        h(Card, { item, ctx: { ...ctx, liveCard: { row, live, note, status: row.status, outputs: outputsOf(row, ctx), turnOutputs: turn.outputs || [], kit } } }));
    }));
}
