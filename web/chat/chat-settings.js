// Settings → Agent (plan 14.9, Wire — Phase 14): AGENT.md, the memory index and its topics, the
// models, skills, the ask modes and permissions, and "Show thinking" (this browser only:
// localStorage `aihub.chat.showThinking`). Mounted by Hub.dc.html's Settings page.

import { h, T, MONO, Icon, Btn, Badge, cardSt, label11, usePref, SHOW_THINKING, fmtTokens } from './chat-ui.js';
import { getChatClient } from './chat.js';
import { MODES } from './chat-header.js';

const R = () => globalThis.React;
const section = (title, ...kids) => h('section', { style: cardSt({ pad: '14px 16px', gap: 10, style: { borderRadius: 10 } }) }, h('h2', { style: { ...label11, margin: 0 } }, title), ...kids);
const row = (label, hint, control) => h('div', { style: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' } },
  h('div', { style: { flex: '1 1 220px', minWidth: 0 } }, h('div', { style: { fontWeight: 500 } }, label), hint ? h('div', { style: { fontSize: 12, color: T.mut } }, hint) : null), control);

function Switch({ on, onChange, label }) {
  return h('button', { type: 'button', role: 'switch', 'aria-checked': on ? 'true' : 'false', 'aria-label': label, onClick: () => onChange(!on),
    style: { position: 'relative', width: 34, height: 20, flex: 'none', borderRadius: 99, border: 0, padding: 0, cursor: 'pointer', background: on ? T.gr : T.bds, transition: 'background .15s' } },
    h('span', { style: { position: 'absolute', top: 3, left: on ? 17 : 3, width: 14, height: 14, borderRadius: 99, background: '#fff', transition: 'left .15s' } }));
}

function Editor({ label, hint, value, onSave, rows = 10, placeholder }) {
  const React = R(), [text, setText] = React.useState(value ?? ''), [busy, setBusy] = React.useState(false);
  React.useEffect(() => setText(value ?? ''), [value]);
  const dirty = text !== (value ?? ''), lines = text ? text.split('\n').length : 0;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
    h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' } }, h('span', { style: { fontWeight: 500 } }, label),
      h('span', { style: { fontSize: 12, color: T.mut, flex: 1, minWidth: 160 } }, hint), h('span', { style: { fontFamily: MONO, fontSize: 11, color: lines > 200 ? T.rd : T.dim } }, `${lines} / 200 lines`)),
    h('textarea', { value: text, rows, placeholder, 'aria-label': label, onChange: e => setText(e.target.value),
      style: { width: '100%', padding: '8px 10px', borderRadius: 7, border: '1px solid ' + T.bds, background: T.sb, color: T.tx, fontFamily: MONO, fontSize: 12, lineHeight: 1.55, resize: 'vertical', outline: 'none' } }),
    h('div', { style: { display: 'flex', gap: 8 } },
      h(Btn, { kind: 'pri', sm: true, label: busy ? 'Saving…' : 'Save', disabled: !dirty || busy, onClick: async () => { setBusy(true); try { await onSave(text); } finally { setBusy(false); } } }),
      dirty ? h(Btn, { kind: 'ghost', sm: true, label: 'Revert', onClick: () => setText(value ?? '') }) : null));
}

export function AgentSettings({ api, toast = () => {} }) {
  const React = R(), c = getChatClient(api);
  const [s, setS] = React.useState(null), [models, setModels] = React.useState(null), [err, setErr] = React.useState(null);
  const [think, setThink] = usePref(SHOW_THINKING, false);
  React.useEffect(() => {
    c.settings().then(setS).catch(setErr);
    c.models().then(setModels).catch(() => {});
  }, []);
  const save = async body => {
    try { setS(await c.saveSettings(body)); toast('Saved', 'success'); } catch (e) { toast(e.detail || String(e), 'error'); throw e; }
  };
  const window_ = id => { const m = models?.models?.find(x => x.id === id); return m?.meta?.context_length ? ` · ${fmtTokens(m.meta.context_length)}` : ''; };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 14 } },
    c.live ? null : h('div', { role: 'note', style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: T.mut } }, h(Badge, { tone: 'purple' }, 'MOCK'), 'The scripted mock agent: changes last until the page reloads.'),
    err ? h('div', { role: 'alert', style: { padding: '10px 12px', borderRadius: 8, background: T.trd, color: T.rd } }, `The agent didn’t answer: ${err.detail || err.message}. Start the Agent mod, then reload.`) : null,
    section('Chat',
      row('Show thinking', 'One folded line per step (“Thought for 6 s”) that opens in place. This browser only.', h(Switch, { on: !!think, onChange: setThink, label: 'Show thinking' })),
      row('Models', 'The model comes from the relay; each chat can pick its own in the header.',
        h('div', { style: { display: 'flex', flexDirection: 'column', gap: 2, fontFamily: MONO, fontSize: 12, textAlign: 'right' } },
          h('span', null, h('span', { style: { color: T.mut } }, 'default '), s ? s.model + window_(s.model) : '—'),
          h('span', null, h('span', { style: { color: T.mut } }, 'fallback '), s?.fallback ? s.fallback + window_(s.fallback) : 'none'),
          h('span', null, h('span', { style: { color: T.mut } }, 'max steps '), s?.max_steps ?? '—')))),
    section('Instructions',
      s ? h(Editor, { label: 'AGENT.md', hint: 'Standing instructions, read every turn (data/agent/AGENT.md).', value: s.agent_md, placeholder: '# How I like things\n- Prefer 16:9 images', onSave: v => save({ agent_md: v }) }) : h('span', { style: { color: T.mut } }, 'Loading…')),
    section('Memory',
      s ? h(Editor, { label: 'MEMORY.md', hint: 'The memory index, in every prompt. The agent adds to it with remember().', value: s.memory, rows: 8, placeholder: '- likes 16:9 images\n- my voice is Brendon', onSave: v => save({ memory: v }) }) : null,
      s?.topics?.length ? h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' } }, h('span', { style: { fontSize: 12, color: T.mut } }, 'Topic files (read on demand):'),
        s.topics.map(t => h('span', { key: t, style: { fontFamily: MONO, fontSize: 11.5, padding: '2px 7px', borderRadius: 5, background: T.inset, border: '1px solid ' + T.bd } }, t + '.md'))) : null),
    section('Skills',
      h('div', { style: { fontSize: 12, color: T.mut } }, 'Loaded only when needed. Each one is also a slash command in the chat.'),
      s && !s.skills?.length ? h('span', { style: { color: T.mut, fontSize: 12.5 } }, 'No skills yet: mods ship them in services/<id>/skills/, yours go in data/agent/skills/.') : null,
      ...(s?.skills || []).map(k => h('div', { key: k.id, style: { display: 'flex', gap: 10, alignItems: 'baseline', fontSize: 12.5 } },
        h('span', { style: { fontFamily: MONO, fontSize: 12, minWidth: 90 } }, '/' + k.name), h('span', { style: { flex: 1, color: T.mut } }, k.description), h(Badge, null, k.source)))),
    section('Permissions',
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } }, MODES.map(([k, l, d]) => h('div', { key: k, style: { display: 'flex', gap: 10, fontSize: 12.5, alignItems: 'baseline' } },
        h('span', { style: { minWidth: 130, fontWeight: 500 } }, l), h('span', { style: { color: T.mut } }, d)))),
      h('div', { style: { fontSize: 12, color: T.mut, display: 'flex', gap: 6, alignItems: 'flex-start' } }, h(Icon, { d: 'shield', size: 13, style: { marginTop: 2 } }),
        h('span', null, 'Each chat picks its mode in the header (new chats: Ask about choices). Per-tool rules are name globs in ', h('code', { style: { fontFamily: MONO } }, '[agent.permissions]'),
          ' of config.toml, checked deny → ask → allow before the mode. Pending approvals from any client are in the header’s Approvals button.'))));
}
