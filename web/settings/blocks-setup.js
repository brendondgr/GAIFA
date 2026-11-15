// Settings → Services: what each mod's state means and what turns it on (plan capability-enablement 3.5), and the
// Recommended for chat group: the mods a chat uses, what each gives, Set up the rest (one job) or have your coding
// agent do it. The buttons open the Set up dialog (web/setup-dialog.js) through a `gaifa:setup` event.
// Written by us (web/PATCHES.md).

import { h, T } from '../chat/chat-ui.js';

const WORDS = { on: 'On', starts_on_use: 'Starts when used', off: 'Turned off', not_set_up: 'Not set up', cant_run: "Can't run here", failed: 'Failed', broken: 'Broken' };

/** A service's state in words and the one action that turns it on: {text, tone, action: {id, label} | null}. Pure. */
export function statusWords(x) {
  const st = x?.availability?.status || (x?.state === 'ready' || x?.state === 'degraded' ? 'on' : 'starts_on_use');
  const name = x?.name || x?.id;
  const action = st === 'not_set_up' || st === 'cant_run' ? { id: 'setup', label: 'Set up' }
    : st === 'off' ? { id: 'enable', label: 'Turn on' }
    : st === 'failed' ? { id: 'start', label: 'Start' }
    : st === 'starts_on_use' && x?.state === 'stopped' ? { id: 'start', label: 'Start' } : null;
  const tone = st === 'on' ? 'green' : st === 'failed' || st === 'broken' ? 'red' : st === 'not_set_up' || st === 'off' || st === 'cant_run' ? 'accent' : 'dim';
  return { status: st, text: WORDS[st] || st, tone, action: action && { ...action, title: `${action.label} ${name}` } };
}

/** The recommended mods: [{id, name, provides, status, text}], and the ids that aren't set up. Pure. */
export function recommendedRows(services) {
  const rows = (services || []).filter(s => s.recommended).map(s => ({ id: s.id, name: s.name, provides: s.provides || s.description || '', ...statusWords(s) }));
  return { rows, missing: rows.filter(r => r.status === 'not_set_up').map(r => r.id) };
}

/** What a button does: open the dialog, turn the mod on, or start it. */
export async function act(api, id, action) {
  if (action === 'setup') { globalThis.dispatchEvent?.(new CustomEvent('gaifa:setup', { detail: { ids: [].concat(id) } })); return; }
  if (action === 'enable') { await api.saveServiceConfig(id, { enabled: true }); await api.startService(id); return; }
  if (action === 'start') await api.startService(id);
}

const TONE = { green: 'var(--gr,#3FB950)', red: 'var(--rd,#F85149)', accent: 'var(--acct,#FFB224)', dim: T.mut };
const smallBtn = primary => ({ height: 26, padding: '0 10px', borderRadius: 6, font: 'inherit', fontSize: 12, cursor: 'pointer',
  ...(primary ? { border: 0, background: T.acc, color: '#1A1200', fontWeight: 600 } : { border: '1px solid ' + T.bds, background: 'transparent', color: T.tx }) });

/** The status cell of a Services row: words, the action, and Test on this machine for a mod with a test. */
export function StatusCell({ x, ctx }) {
  const React = globalThis.React, [busy, setBusy] = React.useState(false), w = statusWords(x);
  const run = async (fn, okText) => { setBusy(true); try { await fn(); if (okText) ctx.toast?.(okText, 'success'); } catch (e) { ctx.toast?.(e?.detail || e?.message || String(e), 'error'); } setBusy(false); };
  return h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginTop: 3 } },
    h('span', { style: { fontSize: 12, color: TONE[w.tone] } }, w.text),
    w.action ? h('button', { type: 'button', disabled: busy, title: w.action.title, style: smallBtn(true), onClick: () => run(() => act(ctx.api, x.id, w.action.id)) }, w.action.label) : null,
    x.testable && (w.status === 'on' || w.status === 'starts_on_use') ? h('button', { type: 'button', disabled: busy, style: smallBtn(false),
      onClick: () => run(async () => { const t = await ctx.api.testSetup(x.id);
        ctx.toast?.(`${x.name}: test ${t.passed ? 'passed' : 'failed'} in ${t.seconds} s${t.device ? ` on ${t.device}` : ''}`, t.passed ? 'success' : 'error'); }) },
      busy ? 'Testing…' : 'Test on this machine') : null);
}

/** Recommended for chat: each with what it gives and its state; Set up the rest and the coding-agent prompt. */
export function RecommendedCard({ ctx }) {
  const { rows, missing } = recommendedRows(ctx.services);
  if (!rows.length) return null;
  const copy = async () => {
    try { await globalThis.navigator?.clipboard?.writeText(await ctx.api.getSetupPrompt(missing.length ? missing : rows.map(r => r.id))); ctx.toast?.('Copied: paste it into Claude Code or Codex', 'success'); }
    catch (e) { ctx.toast?.(e?.detail || e?.message || String(e), 'error'); }
  };
  return h('section', { style: { background: T.card, border: '1px solid ' + T.bd, borderRadius: 10, padding: 16, display: 'flex', flexDirection: 'column', gap: 8 } },
    h('div', { style: { fontSize: 12.5, color: T.mut } }, missing.length ? `${missing.length} of ${rows.length} aren't set up: a chat without them says what it can't do.` : 'All set up.'),
    rows.map(r => h('div', { key: r.id, style: { display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' } },
      h('a', { href: `#/s/${r.id}`, style: { fontWeight: 500, color: T.tx, minWidth: 120 } }, r.name),
      h('span', { style: { flex: '1 1 220px', fontSize: 12.5, color: T.mut } }, r.provides),
      h('span', { style: { fontSize: 12, color: TONE[r.tone] } }, r.text))),
    missing.length ? h('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 4 } },
      h('button', { type: 'button', style: smallBtn(true), onClick: () => act(ctx.api, missing, 'setup') }, 'Set up the rest'),
      h('button', { type: 'button', style: smallBtn(false), onClick: copy }, 'Have your coding agent do it')) : null);
}

export const SETUP_BLOCKS = { RecommendedCard };
