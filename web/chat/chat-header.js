// The thread header (plan 14.1): title (click to rename), model picker with each model's context
// window, the mode (plan 27.4), the environment (plan 34, chat-env.js), the context meter with its breakdown popover, and Branch.

import { h, T, MONO, Icon, Btn, Popover, inputSt, fmtTokens, label11 } from './chat-ui.js';

const R = () => globalThis.React;
// The five chat modes (plan 27.4, after Claude Code's). The stricter of the mode and a workspace folder's level wins.
export const MODES = [
  ['plan', 'Plan', 'Reads and explains; edits, commands and anything that changes something are refused'],
  ['manual', 'Manual', 'Everything that changes something asks first: edits show their diff, commands their command'],
  ['accept_edits', 'Accept edits', 'Edits and generations apply without asking (undo per turn); commands, the internet and deletes ask'],
  ['auto', 'Auto', 'As Accept edits; a small local judge decides commands, fetches and deletes: it runs what you asked for, and asks when unsure'],
  ['bypass', 'Bypass', 'Edits and commands in the sandbox run without asking, only in folders that allow Bypass; your machine still asks']];
const OLD_MODES = { ask: 'manual', read_only: 'plan' };
export const modeOf = m => { const k = OLD_MODES[m] || m; return MODES.some(x => x[0] === k) ? k : 'manual'; };
const PARTS = [['instructions', 'Instructions'], ['skills_memory', 'Skills & memory'], ['tool_index', 'Tool index'], ['tools', 'Loaded tools'], ['outputs', 'Outputs table'], ['messages', 'Messages'], ['documents', 'Documents'], ['tool_results', 'Tool results']];
const PART_COLOR = ['var(--s6,#79C0FF)', 'var(--s3,#BC8CFF)', 'var(--s7,#D2A8FF)', 'var(--s1,#58C4DD)', 'var(--s8,#E3B341)', 'var(--s4,#3FB950)', 'var(--s2,#FFB224)', 'var(--s5,#F78166)'];
const selSt = { ...inputSt, height: 28, paddingRight: 6, fontSize: 12, cursor: 'pointer', maxWidth: 210 };

export const modelLabel = m => `${m.id}${m.meta?.context_length ? ' · ' + fmtTokens(m.meta.context_length) : ''}${m.health && m.health !== 'healthy' ? ` (${m.health})` : ''}`;

export function ModelSelect({ models, value, onChange }) {
  const list = models?.models || [];
  const cur = value || models?.default || '';
  const known = list.some(m => m.id === cur);
  return h('select', { value: cur, onChange: e => onChange(e.target.value), 'aria-label': 'Model', title: 'Model (from the relay) and its context window', style: selSt },
    !known && cur ? h('option', { value: cur }, cur) : null,
    list.map(m => h('option', { key: m.id, value: m.id }, modelLabel(m) + (m.id === models.default ? ' (default)' : ''))));
}
// bypass: offer Bypass (every workspace folder this chat uses allows it); a chat already in Bypass keeps it listed.
// judge (plan 30.5): GET /api/judge/status; while its model doesn't answer, Auto is offered disabled with the reason
// (a chat already in Auto keeps it: its calls ask until the judge is back).
export function ModeSelect({ value, onChange, bypass = false, judge = null }) {
  const cur = modeOf(value), down = judge && !judge.available;
  const label = (k, l) => (k === 'auto' && down ? l + ' (judge unavailable)' : l);
  const title = cur === 'auto' && down ? `The judge's model doesn't answer (${judge.detail || judge.model}): calls ask until it's back`
    : MODES.find(m => m[0] === cur)?.[2];
  return h('select', { value: cur, onChange: e => onChange(e.target.value), 'aria-label': 'Mode', title, style: selSt },
    MODES.filter(([k]) => k !== 'bypass' || bypass || cur === 'bypass').map(([k, l]) => h('option', {
      key: k, value: k, disabled: k === 'auto' && down && cur !== 'auto',
      title: k === 'auto' && down ? `Not available: ${judge.detail || "the judge's model doesn't answer"}` : undefined }, label(k, l))));
}

/** Bypass is offered when the workspace folders this chat has used all allow it (or, before it used any, one does). */
export function bypassAllowed(folders, events = []) {
  if (!Array.isArray(folders) || !folders.length) return false;
  const used = new Set();
  for (const e of events) if (e.type === 'tool_call' && /^workspace_/.test(e.payload?.name || '') && e.payload?.arguments?.folder) used.add(String(e.payload.arguments.folder));
  const find = id => folders.find(f => f.id === id || f.path === id || f.name === id);
  return used.size ? [...used].every(id => !!find(id)?.allow_bypass) : folders.some(f => f.allow_bypass);
}

function meterTone(p) { return p >= 85 ? T.rd : p >= 70 ? T.acc : T.cy; }

export function ContextMeter({ meter, open, onOpen, onClose, onCompact, compacts, running, compact }) {
  const used = meter?.used, win = meter?.window, pct = meter?.percent ?? (used && win ? 100 * used / win : 0), tone = meterTone(pct);
  const bd = meter?.breakdown || {}, total = PARTS.reduce((a, [k]) => a + (bd[k] || 0), 0) || 1;
  return h('span', { style: { position: 'relative', flex: 'none' } },
    h('button', { type: 'button', onClick: open ? onClose : onOpen, 'aria-haspopup': 'dialog', 'aria-expanded': open ? 'true' : 'false', 'aria-label': `Context: ${fmtTokens(used)} of ${fmtTokens(win)} tokens used`,
      title: 'Context window: what the model sees on the next step',
      style: { display: 'inline-flex', alignItems: 'center', gap: 7, height: 28, padding: '0 9px', borderRadius: 6, border: '1px solid ' + T.bd, background: T.card, color: T.tx, cursor: 'pointer', font: 'inherit' } },
      h('span', { style: { fontFamily: MONO, fontSize: 11.5, whiteSpace: 'nowrap' } }, meter ? (compact ? `${Math.round(pct)}%` : `${fmtTokens(used)} / ${fmtTokens(win)}`) : '—'),
      h('span', { 'aria-hidden': true, style: { width: compact ? 28 : 44, height: 5, borderRadius: 9, background: T.row, overflow: 'hidden', display: 'block' } },
        h('span', { style: { display: 'block', height: '100%', width: `${Math.min(100, pct)}%`, background: tone, borderRadius: 9, transition: 'width .5s ease' } }))),
    h(Popover, { open, onClose, width: 330, label: 'Context window' },
      h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 8 } }, h('span', { style: label11 }, 'Context'), h('span', { style: { flex: 1 } }),
        meter?.model ? h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.mut } }, meter.model) : null),
      meter ? h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 6 } },
        h('span', { style: { fontFamily: MONO, fontSize: 18, fontWeight: 500 } }, fmtTokens(used)),
        h('span', { style: { color: T.mut, fontSize: 12.5 } }, `of ${fmtTokens(win)} tokens · ${Math.round(pct)}%${meter.estimated ? ' (estimated)' : ''}`)) : h('div', { style: { color: T.mut } }, 'No usage yet: it appears after the first reply.'),
      meter ? h('div', { style: { position: 'relative', height: 10, borderRadius: 5, background: T.row, overflow: 'hidden', display: 'flex' } },
        PARTS.map(([k], i) => bd[k] ? h('span', { key: k, title: k, style: { width: `${100 * (bd[k] / (win || total))}%`, background: PART_COLOR[i] } }) : null),
        h('span', { title: 'Compaction starts at 70%', style: { position: 'absolute', left: '70%', top: 0, bottom: 0, width: 1, background: T.acc } }),
        h('span', { title: 'Summary at 85%', style: { position: 'absolute', left: '85%', top: 0, bottom: 0, width: 1, background: T.rd } })) : null,
      meter ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 3 } }, PARTS.map(([k, l], i) => h('div', { key: k, style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 } },
        h('span', { style: { width: 8, height: 8, borderRadius: 2, background: PART_COLOR[i], flex: 'none' } }), h('span', { style: { flex: 1, color: T.mut } }, l),
        h('span', { style: { fontFamily: MONO, fontSize: 11.5 } }, fmtTokens(bd[k] || 0))))) : null,
      h('div', { style: { fontSize: 11.5, color: T.mut } }, `Older tool results are cleared at 70%; earlier turns are summarized at 85%.${compacts ? ` Compacted ${compacts}× in this chat (the divider marks where).` : ''}`),
      onCompact ? h(Btn, { sm: true, icon: 'compress', label: 'Compact now', disabled: running, title: running ? 'Wait for the turn to finish' : 'Summarize earlier messages now (/compact)', onClick: () => { onClose(); onCompact(); }, style: { alignSelf: 'flex-start' } }) : null));
}

function Title({ title, onRename }) {
  const React = R(), [edit, setEdit] = React.useState(null);
  if (edit != null) {
    const save = () => { const v = edit.trim(); setEdit(null); if (v && v !== title) onRename(v); };
    return h('input', { autoFocus: true, value: edit, 'aria-label': 'Chat title', onChange: e => setEdit(e.target.value), onBlur: save,
      onKeyDown: e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') { e.stopPropagation(); setEdit(null); } }, style: { ...inputSt, height: 28, minWidth: 120, flex: '0 1 320px' } });
  }
  return h('button', { type: 'button', onClick: onRename ? () => setEdit(title || '') : undefined, title: onRename ? 'Rename' : undefined,
    style: { minWidth: 0, flex: '0 1 auto', border: 0, background: 'none', padding: '0 2px', color: T.tx, font: 'inherit', fontSize: 13, fontWeight: 600, cursor: onRename ? 'text' : 'default', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textAlign: 'left' } },
  title || 'New chat');
}

// envChip (plan 34): the chat's environment (chat-env.js EnvChip), next to the mode
export function ThreadHeader({ thread, models, model, mode, bypass, judge, onModel, onMode, onRename, meter, meterOpen, setMeterOpen, onCompact, compacts, running, state, onBranch, onMenu, narrow, learn, onLearn, envChip }) {
  const React = R(), [more, setMore] = React.useState(false);
  const st = running ? ['running', T.acc] : state === 'waiting' ? ['waiting for you', T.pu] : null;
  const controls = [h(ModelSelect, { key: 'm', models, value: model, onChange: onModel }), h(ModeSelect, { key: 'a', value: mode, onChange: onMode, bypass, judge })];
  return h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, height: 44, padding: '0 12px', borderBottom: '1px solid ' + T.bd, background: T.bg, flex: 'none', minWidth: 0 } },
    onMenu ? h(Btn, { kind: 'ghost', sm: true, icon: 'menu', title: 'Chats', onClick: onMenu }) : null,
    h(Title, { title: thread?.title, onRename: thread ? onRename : null }),
    st ? h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11.5, color: st[1], whiteSpace: 'nowrap', flex: 'none' } },
      h('span', { style: { width: 6, height: 6, borderRadius: 99, background: st[1], animation: running ? 'aichatpulse 1.2s ease-in-out infinite' : 'none' } }), narrow ? null : st[0]) : null,
    h('span', { style: { flex: 1 } }),
    narrow ? h('span', { style: { position: 'relative', flex: 'none' } },
      h(Btn, { kind: 'ghost', sm: true, icon: 'sliders', title: 'Model and mode', onClick: () => setMore(!more) }),
      h(Popover, { open: more, onClose: () => setMore(false), width: 260, label: 'Model and mode' }, h('span', { style: label11 }, 'Model'), controls[0], h('span', { style: label11 }, 'Mode'), controls[1]))
      : controls,
    envChip || null,
    thread || meter ? h(ContextMeter, { meter, open: meterOpen, onOpen: () => setMeterOpen(true), onClose: () => setMeterOpen(false), onCompact: thread ? onCompact : null, compacts, running, compact: narrow }) : null,
    onLearn ? h(Btn, { kind: 'ghost', sm: true, icon: 'bulb', 'aria-pressed': learn ? 'true' : 'false',   // plan 21.7: this chat teaches the agent, or not
      title: learn ? 'Learning from this chat: your choices here become preferences. Click to stop.' : 'Not learning from this chat. Click to learn from it again.',
      label: narrow ? undefined : learn ? 'Learning' : 'Not learning', onClick: () => onLearn(!learn), style: learn ? undefined : { opacity: 0.6 } }) : null,
    thread && onBranch ? h(Btn, { kind: 'ghost', sm: true, icon: 'branch', title: 'Branch: copy this chat into a new one', label: narrow ? undefined : 'Branch', onClick: onBranch }) : null);
}
