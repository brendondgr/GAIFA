// The Auto mode's judge in Settings → Permissions (plan 30.5): whether its model answers, what it reads, your command rules
// (chat-rules.js), and the calls it decided, newest first: what ran and what asked, with the reason, a link to the
// chat and, for a command the model asked about, "Always allow <rule>". GET /api/judge/status, GET /api/judge/recent
// and GET/PUT /api/settings (api.getJudgeStatus, api.listJudged, api.getSettings, api.saveSettings).

import { h, T, MONO, Badge, Btn, fmtAgo } from './chat-ui.js';
import { CommandRules, withRule, errText, allowConfirm } from './chat-rules.js';

const R = () => globalThis.React;
const SOURCE = { rules: 'the fixed rules', user: 'your rule', model: 'the model', 'fail-closed': 'failed: asked' };

const URLS = { relay: 'http://127.0.0.1:4000', decide: 'http://127.0.0.1:7000/api/s/decide' };

/** Pick the judge's model from what its backend offers (GET /api/judge/status `choices`); saved to config.toml [agent.judge]. */
function JudgePicker({ api, st, onSaved }) {
  const React = R(), [backend, setBackend] = React.useState(st.backend), [model, setModel] = React.useState(st.model);
  const [busy, setBusy] = React.useState(false), [msg, setMsg] = React.useState(null);
  React.useEffect(() => { setBackend(st.backend); setModel(st.model); }, [st.backend, st.model]);
  if (!api?.saveSettings) return null;
  const choices = [...new Set([...(backend === st.backend ? st.choices || [] : []), ...(backend === st.backend ? [st.model] : [])])];
  const save = async () => {
    setBusy(true); setMsg(null);
    try { await api.saveSettings({ judge: { backend, model, url: URLS[backend] } }); setMsg('Saved.'); onSaved?.(); }
    catch (e) { setMsg(`Couldn’t save: ${e.detail || e.message}`); } finally { setBusy(false); }
  };
  const sel = { height: 26, fontSize: 12.5, background: T.inset, color: 'inherit', border: '1px solid ' + T.bd, borderRadius: 5 };
  return h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', fontSize: 12.5 } },
    h('span', { style: { color: T.mut } }, 'Judge model'),
    h('select', { 'aria-label': 'Judge backend', value: backend, style: sel, onChange: e => { setBackend(e.target.value); setModel(''); } },
      h('option', { value: 'relay' }, 'a chat model (relay)'), h('option', { value: 'decide' }, 'a decision model (decide mod)')),
    choices.length ? h('select', { 'aria-label': 'Judge model', value: model, style: sel, onChange: e => setModel(e.target.value) },
      model ? null : h('option', { value: '' }, 'pick one'), choices.map(c => h('option', { key: c, value: c }, c)))
      : h('input', { 'aria-label': 'Judge model', value: model, placeholder: backend === 'decide' ? 'd3-lite' : 'a model name', style: { ...sel, padding: '0 6px', width: 180 },
          onChange: e => setModel(e.target.value) }),
    h(Btn, { sm: true, label: busy ? 'Saving…' : 'Save', disabled: busy || !model || (backend === st.backend && model === st.model), onClick: save }),
    msg ? h('span', { role: 'status', style: { color: T.mut } }, msg) : null);
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
  const backend = value?.backend || 'relay', model = value?.model || '';
  const choices = [...new Set([...(st && backend === st.backend ? st.choices || [] : []), ...(model ? [model] : [])])];
  const sel = { height: 30, fontSize: 12.5, background: T.sb, color: 'inherit', border: '1px solid ' + T.bds, borderRadius: 6 };
  return h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', fontSize: 12.5 } },
    h('select', { 'aria-label': 'Judge backend', value: backend, style: sel, onChange: e => onChange({ backend: e.target.value, model: '', url: URLS[e.target.value] }) },
      h('option', { value: 'relay' }, 'a chat model (relay)'), h('option', { value: 'decide' }, 'a decision model (decide mod)')),
    choices.length ? h('select', { 'aria-label': 'Judge model', value: model, style: sel, onChange: e => onChange({ backend, model: e.target.value, url: URLS[backend] }) },
      model ? null : h('option', { value: '' }, 'pick one'), choices.map(c => h('option', { key: c, value: c }, c)))
      : h('input', { 'aria-label': 'Judge model', value: model, placeholder: backend === 'decide' ? 'd3-lite' : 'a model name', style: { ...sel, padding: '0 6px', width: 180 },
          onChange: e => onChange({ backend, model: e.target.value, url: URLS[backend] }) }));
}
export const judgeStatusText = st => (st.available ? `Judge: ${st.model} (${st.backend}), answering.`
  : `Judge: ${st.model} (${st.backend}) doesn’t answer: ${st.detail || 'unavailable'}. Auto isn’t offered until it does.`);

/** The judged calls. With `onAllow` (the Settings page) "Always allow" adds the rule to the page's draft and the
 *  judge's own controls are rows of the page (`controls: false`); without it, it saves at once as before. */
export function JudgedList({ api, limit = 30, onAllow, allowed: allowedList, controls = true }) {
  const React = R(), [rows, setRows] = React.useState(null), [st, setSt] = React.useState(null), [err, setErr] = React.useState(null);
  const [cfg, setCfg] = React.useState(null), [note, setNote] = React.useState(null);
  const load = () => {
    api.listJudged({ limit }).then(setRows, e => setErr(e));
    api.getJudgeStatus?.().then(setSt, () => setSt(null));
    api.getSettings?.().then(setCfg, () => setCfg(null));
  };
  const always = async p => {     // the "Always allow" shortcut: one more allow rule, after a confirm
    if (onAllow) { if (globalThis.confirm?.(allowConfirm(p))) { onAllow(p); setNote({ ok: `Added “${p}” to your command rules: save the page to keep it.` }); } return; }
    if (!cfg?.judge || !globalThis.confirm?.(allowConfirm(p))) return;
    try { const r = await api.saveSettings({ judge: { allow_commands: withRule(cfg.judge.allow_commands, p) } }); setCfg(r.settings); setNote({ ok: `Added “${p}” to your command rules.` }); }
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
      st.available ? `Judge: ${st.model} (${st.backend}), answering.` : `Judge: ${st.model} (${st.backend}) doesn’t answer: ${st.detail || 'unavailable'}. Auto isn’t offered until it does.`) : null,
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
