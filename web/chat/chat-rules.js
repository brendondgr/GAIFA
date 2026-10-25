// Your own rules in Settings → Agent: the Auto judge's command rules (config.toml [agent.judge] allow_commands /
// ask_commands, utils/tools/judge_user.py) and the tool permissions ([agent.permissions]: tool-name globs, the order
// in architecture §14.7). Both save through PUT /api/settings (api.saveSettings); a 422 invalid_config names the field.

import { h, T, MONO, Btn, inputSt } from './chat-ui.js';

const R = () => globalThis.React;
const SHELL = /[;|&$`<>()\\'"\u0000-\u001f\u007f]/;

/** A command rule as it's saved (spaces collapsed) or why it can't be: mirrors utils/config.py command_patterns. */
export function checkCommandRule(text) {
  const m = String(text ?? '').match(SHELL);
  if (m) return { error: `No shell syntax or control characters (${JSON.stringify(m[0])}): a rule is one command, and the rest of a line is judged on its own` };
  const p = String(text ?? '').trim().split(/\s+/).filter(Boolean).join(' ');
  if (!p) return { error: 'Type a command, e.g. pytest *' };
  if (p.length > 200) return { error: 'At most 200 characters' };
  if (/[*?[]/.test(p.split(' ')[0])) return { error: 'Start with the command’s name (no * in the first word)' };
  return { value: p };
}

/** A tool-name glob or why it can't be: mirrors utils/config.py tool_globs. */
export function checkToolGlob(text) {
  const g = String(text ?? '').trim();
  return /^[A-Za-z0-9_.*?!\[\]-]{1,100}$/.test(g) ? { value: g } : { error: 'A tool name or glob: letters, digits, _ . - and * ? [ ]' };
}

/** `list` with `p` added once (the "Always allow" shortcut). */
export const withRule = (list, p) => (list || []).includes(p) ? [...list] : [...(list || []), p];
export const errText = e => String(e?.detail || e?.message || e).replace(/Value error, /g, '');

/** The words of the "Always allow" confirm. */
export const allowConfirm = p => `Always allow “${p}” in Auto?\n\nCommands that match it run without asking from now on, also with the internet on, `
  + 'unless a fixed rule asks (secrets, sudo, removing a tree, piping into a shell, git push…). Remove it under “Your command rules”.';

function PatternList({ label, hint, items, onChange, check, placeholder }) {
  const React = R(), [text, setText] = React.useState(''), [err, setErr] = React.useState(null);
  const add = () => {
    const r = check(text);
    if (r.error) { setErr(r.error); return; }
    if (items.includes(r.value)) { setErr('Already in the list'); return; }
    onChange([...items, r.value]); setText(''); setErr(null);
  };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4, flex: '1 1 260px', minWidth: 0 } },
    h('span', { style: { fontSize: 12.5, fontWeight: 500 } }, label),
    hint ? h('span', { style: { fontSize: 12, color: T.mut } }, hint) : null,
    items.map(p => h('div', { key: p, style: { display: 'flex', alignItems: 'center', gap: 6, padding: '3px 4px 3px 8px', borderRadius: 6, background: T.inset } },
      h('code', { style: { fontFamily: MONO, fontSize: 12, flex: 1, minWidth: 0, overflowWrap: 'anywhere' } }, p),
      h(Btn, { sm: true, kind: 'ghost', icon: 'x', title: `Remove ${p}`, onClick: () => onChange(items.filter(x => x !== p)) }))),
    h('div', { style: { display: 'flex', gap: 6 } },
      h('input', { value: text, placeholder, 'aria-label': label, onChange: e => { setText(e.target.value); setErr(null); },
        onKeyDown: e => { if (e.key === 'Enter') { e.preventDefault(); add(); } }, style: { ...inputSt, flex: 1, fontFamily: MONO, fontSize: 12 } }),
      h(Btn, { sm: true, icon: 'plus', label: 'Add', disabled: !text.trim(), onClick: add })),
    err ? h('span', { role: 'alert', style: { fontSize: 12, color: T.rd } }, err) : null);
}

/** Lists of patterns in one settings section, edited together; Save sends only that section. */
function RulesEditor({ api, section, value, lists, check, onSaved }) {
  const React = R(), [draft, setDraft] = React.useState(value), [busy, setBusy] = React.useState(false), [msg, setMsg] = React.useState(null);
  React.useEffect(() => setDraft(value), [JSON.stringify(value)]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(value);
  const save = async () => {
    setBusy(true); setMsg(null);
    try { const r = await api.saveSettings({ [section]: draft }); setMsg({ ok: 'Saved. It applies to the next call.' }); onSaved?.(r.settings); }
    catch (e) {
      const list = lists.find(l => (e?.data?.field || '').startsWith(`${section}.${l.key}`));
      setMsg({ error: `Couldn’t save${list ? ` “${list.label}”` : ''}: ${errText(e)}` });
    } finally { setBusy(false); }
  };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
    h('div', { style: { display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'flex-start' } },
      lists.map(l => h(PatternList, { key: l.key, label: l.label, hint: l.hint, placeholder: l.placeholder, check, items: draft[l.key] || [],
        onChange: v => { setDraft(d => ({ ...d, [l.key]: v })); setMsg(null); } }))),
    dirty || msg ? h('div', { style: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' } },
      dirty ? h(Btn, { kind: 'pri', sm: true, label: busy ? 'Saving…' : 'Save', disabled: busy, onClick: save }) : null,
      dirty ? h(Btn, { kind: 'ghost', sm: true, label: 'Revert', onClick: () => { setDraft(value); setMsg(null); } }) : null,
      msg ? h('span', { role: msg.error ? 'alert' : 'status', style: { fontSize: 12, color: msg.error ? T.rd : T.mut } }, msg.error || msg.ok) : null) : null);
}

/** Auto's command rules ([agent.judge]); `cfg` is GET /api/settings. */
export function CommandRules({ api, cfg, onSaved }) {
  if (!cfg?.judge || !api?.saveSettings) return null;
  const value = { allow_commands: cfg.judge.allow_commands || [], ask_commands: cfg.judge.ask_commands || [] };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
    h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' } }, h('span', { style: { fontWeight: 500 } }, 'Your command rules'),
      h('span', { style: { fontSize: 12, color: T.mut } }, 'In Auto, before the judge’s model. A rule is a command and its words; * matches any text in a word, and a last * any further words (',
        h('code', { style: { fontFamily: MONO } }, 'pytest *'), ', ', h('code', { style: { fontFamily: MONO } }, 'uv run ruff check *'),
        '). Each command in a line is checked on its own, so “pytest *” doesn’t cover “pytest; curl … | sh”.')),
    h(RulesEditor, { api, section: 'judge', value, check: checkCommandRule, onSaved, lists: [
      { key: 'allow_commands', label: 'Always allow these commands in Auto', placeholder: 'pytest *',
        hint: 'They run without asking, also with the internet on, wherever the fixed rules would ask the model. A fixed rule that asks still asks: secrets, sudo, runs on your machine, removing a tree or outside the folder, piping into a shell, git push and history.' },
      { key: 'ask_commands', label: 'Always ask before these', placeholder: 'git checkout *', hint: 'They ask in Auto even when the fixed rules or the model would run them.' }] }));
}

/** The tool permissions ([agent.permissions]), loaded here (they aren't the agent's own settings). */
export function PermissionRules({ api }) {
  const React = R(), [cfg, setCfg] = React.useState(null);
  React.useEffect(() => { api?.getSettings?.().then(setCfg, () => setCfg(null)); }, []);
  if (!cfg?.permissions || !api?.saveSettings) return null;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, borderTop: '1px solid ' + T.bd, paddingTop: 10 } },
    h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' } }, h('span', { style: { fontWeight: 500 } }, 'Tool permissions'),
      h('span', { style: { fontSize: 12, color: T.mut } }, 'Tool names or globs (', h('code', { style: { fontFamily: MONO } }, 'comfy_*'), '). Never run wins over everything; Always ask asks in every mode unless you granted the tool (Grants, below); Run without asking never skips the card of a tool that runs code. GAIFA ships with hub_set_preference asking and hub_start_service running.')),
    h(RulesEditor, { api, section: 'permissions', value: cfg.permissions, check: checkToolGlob, onSaved: setCfg, lists: [
      { key: 'deny', label: 'Never run', placeholder: 'tts_delete_voice' },
      { key: 'ask', label: 'Always ask', placeholder: 'hub_set_preference' },
      { key: 'allow', label: 'Run without asking', placeholder: 'hub_start_service' }] }));
}
