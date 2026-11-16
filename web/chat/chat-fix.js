// Fix-it cards (plan 46.5): a failed step's error, in a sentence, with the mod's log lines around it and the fixes
// the hub found (utils/tools/fixes.py) as buttons: start or restart the mod, free the GPU, retry (with a lighter
// preset). A fix runs as your own step; Retry runs the call again with the same arguments.

import { h, T, MONO } from './chat-ui.js';
import { errorText } from './chat-steps.js';
import * as kit from '../live-kit.js';

const R = () => globalThis.React;

/** The failed tool rows of a turn whose error carries fixes or log lines, while they still matter: only in the chat's
 *  newest turn (`turn.latest`, chat.js), and not once a later call of the same tool in it worked (the agent got past
 *  it). The fold's step row keeps the error either way. */
export function fixRows(turn) {
  if (!turn.latest) return [];
  const rows = (turn.steps || []).flatMap(s => s.rows).filter(r => r.type === 'tool');
  return rows.filter((r, i) => (r.status === 'error' || r.status === 'failed')
    && (r.item?.result?.error?.fixes?.length || r.item?.result?.error?.log?.length)
    && !rows.slice(i + 1).some(l => l.name === r.name && l.status === 'done'));
}

/** What a fix does when clicked: {kind: 'tool'|'service'|'retry'|'copy', …}. */
export function fixAction(f, row) {
  if (f.retry) return { kind: 'tool', tool: row.name, arguments: { ...(row.item?.call?.arguments || {}), ...f.retry } };
  if (f.tool) return { kind: 'tool', tool: f.tool, arguments: f.arguments || {} };
  if (f.setup) return { kind: 'setup', ids: [].concat(f.setup) };      // capability-enablement 3.6: the Set up dialog
  if (f.service && f.action === 'enable') return { kind: 'tool', tool: 'hub_enable_service', arguments: { id: f.service } };   // capability-enablement 2.3
  if (f.service) return { kind: 'service', service: f.service, action: f.action || 'restart' };
  if (f.command) return { kind: 'copy', text: f.command };
  return null;
}

export function FixCard({ row, ctx }) {
  const React = R(), err = row.item.result.error, [done, setDone] = React.useState({}), [busy, setBusy] = React.useState(null), [open, setOpen] = React.useState(false);
  const run = async (f, i) => {
    const a = fixAction(f, row);
    if (!a) return;
    setBusy(i);
    try {
      if (a.kind === 'tool') await ctx.act?.(a.tool, a.arguments);
      else if (a.kind === 'service') await ctx.api.restartService(a.service);
      else if (a.kind === 'copy') await globalThis.navigator?.clipboard?.writeText(a.text);
      else if (a.kind === 'setup') globalThis.dispatchEvent?.(new CustomEvent('gaifa:setup', { detail: { ids: a.ids } }));
      setDone(d => ({ ...d, [i]: true }));
    } catch (e) { ctx.toast?.(e.detail || e.message || String(e), 'error'); }
    setBusy(null);
  };
  const log = err.log || [];
  return h(kit.LiveCard, { icon: 'job', title: errorText(row.item.result).text || 'It failed', meta: err.code || '', failed: true,
    foot: (err.fixes || []).length ? (err.fixes || []).map((f, i) => h('button', { key: i, type: 'button', disabled: busy != null || done[i], onClick: () => run(f, i),
      style: { border: i === 0 && !done[i] ? 0 : '1px solid ' + T.bds, borderRadius: 6, padding: '3px 10px', fontSize: 12, cursor: busy != null || done[i] ? 'default' : 'pointer',
        background: i === 0 && !done[i] ? T.acc : 'transparent', color: i === 0 && !done[i] ? '#1A1200' : T.tx, fontWeight: i === 0 ? 600 : 400, opacity: done[i] ? 0.6 : 1 } },
      done[i] ? '✓ ' + f.label : busy === i ? f.label + '…' : f.label)) : null },
    err.fix && !(err.fixes || []).length ? h('div', { style: { padding: '0 12px 8px', fontSize: 12.5, color: T.mut } }, err.fix) : null,
    log.length ? h('div', { style: { padding: '0 12px 8px' } },
      h('button', { type: 'button', onClick: () => setOpen(!open), style: { background: 'none', border: 0, padding: 0, color: T.mut, fontSize: 12, cursor: 'pointer' } },
        open ? 'Hide the log' : `Show the log (${log.length} line${log.length > 1 ? 's' : ''})`),
      open ? h('pre', { style: { margin: '6px 0 0', padding: '8px 10px', background: T.inset, borderRadius: 6, fontFamily: MONO, fontSize: 11, lineHeight: 1.5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', color: T.tx, maxHeight: 200, overflow: 'auto' } }, log.join('\n')) : null) : null);
}

export function FixCards({ turn, ctx }) {
  const rows = fixRows(turn);
  return rows.length ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 } }, rows.map(r => h(FixCard, { key: 'fix:' + r.key, row: r, ctx }))) : null;
}
