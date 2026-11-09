// The Auto mode's judge in Settings → Permissions (plan 30.5): whether its model answers, what it reads, your command rules
// (chat-rules.js), and the calls it decided, newest first: what ran and what asked, with the reason, a link to the
// chat and, for a command the model asked about, "Always allow <rule>". GET /api/judge/status, GET /api/judge/recent
// and GET/PUT /api/settings (api.getJudgeStatus, api.listJudged, api.getSettings, api.saveSettings).

import { h, T, MONO, Badge, Btn, fmtAgo } from './chat-ui.js';
import { CommandRules, withRule, errText, allowConfirm } from './chat-rules.js';

const R = () => globalThis.React;
const SOURCE = { rules: 'the fixed rules', user: 'your rule', model: 'the model', 'fail-closed': 'failed: asked' };

// The judge is only ever a decision model in the decide mod (plan web-approvals): no backend to pick, only its model.
export const DECIDE_URL = 'http://127.0.0.1:7000/api/s/decide';
export const JUDGE_HINT = 'The judge is a decision model: it answers in a fraction of a second, with probabilities, and never writes text.';
/** What a pick saves: always the decide backend. */
export const judgePick = model => ({ backend: 'decide', model, url: DECIDE_URL });
const modelChoices = (st, model) => [...new Set([...(st?.choices || []), ...(model ? [model] : [])])];

/** Pick the judge's decision model from the decide mod's (GET /api/judge/status `choices`); saved to config.toml [agent.judge]. */
function JudgePicker({ api, st, onSaved }) {
  const React = R(), [model, setModel] = React.useState(st.model);
  const [busy, setBusy] = React.useState(false), [msg, setMsg] = React.useState(null);
  React.useEffect(() => { setModel(st.model); }, [st.model]);
  if (!api?.saveSettings) return null;
  const save = async () => {
    setBusy(true); setMsg(null);
    try { await api.saveSettings({ judge: judgePick(model) }); setMsg('Saved.'); onSaved?.(); }
    catch (e) { setMsg(`Couldn’t save: ${e.detail || e.message}`); } finally { setBusy(false); }
  };
  const sel = { height: 26, fontSize: 12.5, background: T.inset, color: 'inherit', border: '1px solid ' + T.bd, borderRadius: 5 };
  return h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', fontSize: 12.5 } },
    h('span', { style: { color: T.mut }, title: JUDGE_HINT }, 'Judge (decision model)'),
    h(JudgeModelSelect, { choices: modelChoices(st, st.model), model, sel, onPick: setModel }),
    h(Btn, { sm: true, label: busy ? 'Saving…' : 'Save', disabled: busy || !model || model === st.model, onClick: save }),
    msg ? h('span', { role: 'status', style: { color: T.mut } }, msg) : null);
}

function JudgeModelSelect({ choices, model, sel, onPick }) {
  return choices.length ? h('select', { 'aria-label': 'Judge model', value: model, style: sel, onChange: e => onPick(e.target.value) },
    model ? null : h('option', { value: '' }, 'pick one'), choices.map(c => h('option', { key: c, value: c }, c)))
    : h('input', { 'aria-label': 'Judge model', value: model, placeholder: 'd3-lite', style: { ...sel, padding: '0 6px', width: 180 },
        onChange: e => onPick(e.target.value) });
}

// [agent.judge] context (judge_context.py): what the judge reads of the turn besides your words.
export const CONTEXTS = [
  ['none', 'Your words and the call'],
  ['trail', '+ the agent’s earlier calls this turn'],
  ['full', '+ their results and the agent’s text'],
];

/** What the judge reads; saved as soon as it's picked. */
export function JudgeContext({ api, cfg, onSaved }) {
  const React = R(), [msg, setMsg] = React.useState(null);
  if (!cfg?.judge || !api?.saveSettings) return null;
  const pick = async context => {
    setMsg(null);
    try { const r = await api.saveSettings({ judge: { context } }); onSaved?.(r.settings); setMsg('Saved.'); }
    catch (e) { setMsg(`Couldn’t save: ${errText(e)}`); }
  };
  const sel = { height: 26, fontSize: 12.5, background: T.inset, color: 'inherit', border: '1px solid ' + T.bd, borderRadius: 5 };
  return h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', fontSize: 12.5 } },
    h('span', { style: { color: T.mut } }, 'The judge reads'),
    h('select', { 'aria-label': 'What the judge reads', value: cfg.judge.context || 'none', style: sel, onChange: e => pick(e.target.value) },
      CONTEXTS.map(([v, label]) => h('option', { key: v, value: v }, label))),
    msg ? h('span', { role: 'status', style: { color: T.mut } }, msg) : null);
}

/** The judge's backend and model as a controlled picker (Settings → Permissions → Auto judge, on the page's draft). */
export function JudgeModelPick({ st, value, onChange }) {
  const model = value?.model || '';
  const sel = { height: 30, fontSize: 12.5, background: T.sb, color: 'inherit', border: '1px solid ' + T.bds, borderRadius: 6 };
  return h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', fontSize: 12.5 } },
    h(JudgeModelSelect, { choices: modelChoices(st, model), model, sel, onPick: m => onChange(judgePick(m)) }));
}
export const judgeStatusText = st => (st.available ? `Judge: ${st.model} (decision model), answering.`
  : `Judge: ${st.model} (decision model) doesn’t answer: ${st.detail || 'unavailable'}. Auto isn’t offered until it does.`);

/** "Always allow"'s save: the list with the rule, and as `base` the list it was added to, so a rule added elsewhere
 *  since that list loaded stays (settings-that-stick 2.2). Returns `saveSettings`' arguments. */
export function allowRule(list, rule) {
  const was = [...(list || [])];
  return [{ judge: { allow_commands: withRule(was, rule) } }, { base: { judge: { allow_commands: was } } }];
}

/** The judged calls. "Always allow" saves the rule at once; with `onAllow` (the Settings page) the page saves it and
 *  keeps its draft in step, and the judge's own controls are rows of the page (`controls: false`). */
export function JudgedList({ api, limit = 30, onAllow, allowed: allowedList, controls = false }) {
  const React = R(), [rows, setRows] = React.useState(null), [st, setSt] = React.useState(null), [err, setErr] = React.useState(null);
  const [cfg, setCfg] = React.useState(null), [note, setNote] = React.useState(null);
  const load = () => {
    api.listJudged({ limit }).then(setRows, e => setErr(e));
    api.getJudgeStatus?.().then(setSt, () => setSt(null));
    api.getSettings?.().then(setCfg, () => setCfg(null));
  };
  const always = async p => {     // the "Always allow" shortcut: one more allow rule, after a confirm
    if (onAllow) {   // the Settings page saves it at once too (settings-that-stick 2.2), and keeps its draft in step
      if (!globalThis.confirm?.(allowConfirm(p))) return;
      try { await onAllow(p); setNote({ ok: `Added “${p}” to your command rules.` }); } catch (e) { setNote({ error: `Couldn’t add “${p}”: ${errText(e)}` }); }
      return;
    }
    if (!cfg?.judge || !globalThis.confirm?.(allowConfirm(p))) return;
    try { const r = await api.saveSettings(...allowRule(cfg.judge.allow_commands, p)); setCfg(r.settings); setNote({ ok: `Added “${p}” to your command rules.` }); }
    catch (e) { setNote({ error: `Couldn’t add “${p}”: ${errText(e)}` }); }
  };
  const allowed = new Set(allowedList || cfg?.judge?.allow_commands || []);
  React.useEffect(() => { if (api?.listJudged) load(); }, []);
  if (!api?.listJudged) return null;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, borderTop: '1px solid ' + T.bd, paddingTop: 10 } },
    h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' } }, h('span', { style: { fontWeight: 500 } }, 'Judged calls'),
      h('span', { style: { fontSize: 12, color: T.mut } }, 'In Auto, the judge runs commands, fetches and deletes it’s sure you asked for, and asks you about the rest.'),
      h('span', { style: { flex: 1 } }), h(Btn, { sm: true, kind: 'ghost', icon: 'refresh', label: 'Refresh', onClick: load })),
    st ? h('div', { role: 'status', style: { fontSize: 12, color: st.available ? T.mut : T.acct } },
      judgeStatusText(st)) : null,
    st && controls ? h(JudgePicker, { api, st, onSaved: () => setTimeout(load, 300) }) : null,
    controls ? h(JudgeContext, { api, cfg, onSaved: setCfg }) : null,
    controls ? h(CommandRules, { api, cfg, onSaved: setCfg }) : null,
    note ? h('span', { role: note.error ? 'alert' : 'status', style: { fontSize: 12, color: note.error ? T.rd : T.mut } }, note.error || note.ok) : null,
    err ? h('span', { role: 'alert', style: { fontSize: 12, color: T.rd } }, `Couldn’t load the judged calls: ${err.detail || err.message}`) : null,
    rows?.length ? h('span', { style: { fontWeight: 500, marginTop: 4 } }, 'Recent calls') : null,
    rows && !rows.length ? h('span', { style: { fontSize: 12.5, color: T.mut } }, 'None yet. Pick Auto in a chat’s header to let the judge decide.') : null,
    (rows || []).map(r => h('div', { key: r.id, style: { display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap', fontSize: 12.5, padding: '6px 8px', borderRadius: 6, background: T.inset } },
      h(Badge, { tone: r.verdict === 'allow' ? 'green' : 'purple' }, r.verdict === 'allow' ? 'ran' : 'asked'),
      h('span', { style: { fontFamily: MONO, fontSize: 12, minWidth: 0, overflowWrap: 'anywhere' } }, r.summary || r.tool),
      h('span', { style: { color: T.mut, minWidth: 0, overflowWrap: 'anywhere', flexBasis: '100%' } }, r.reason),
      h('span', { style: { fontSize: 11.5, color: T.dim } }, [SOURCE[r.source] || r.source, r.ms != null ? `${Math.round(r.ms)} ms` : null,
        fmtAgo(r.ts) === 'now' ? 'just now' : fmtAgo(r.ts) + ' ago'].filter(Boolean).join(' · ')),
      r.thread ? h('a', { href: '#/chat/' + encodeURIComponent(r.thread), style: { fontSize: 11.5 } }, 'the chat →') : null,
      (onAllow || (cfg?.judge && api.saveSettings)) ? (r.suggest || []).filter(p => !allowed.has(p)).map(p => h(Btn, { key: p, sm: true, kind: 'ghost', icon: 'check',
        title: 'Add it to “Always allow these commands in Auto”', onClick: () => always(p) },
        'Always allow ', h('code', { style: { fontFamily: MONO, fontSize: 11.5 } }, p))) : null)));
}
