// Settings → Agent (plan 14.9, Wire — Phase 14): AGENT.md, the memory index and its topics, documents
// (plan 24.9: whole documents up to a size or the model's window, and the reply reserve), the
// models, skills, the ask modes and permissions with the grants (plan 25.2: what was allowed in a
// chat or always, with revoke). (Show thinking is retired: thinking is a row in each turn's
// activity fold, plan 19.4.) Mounted by Hub.dc.html's Settings page.

import { h, T, MONO, Icon, Btn, Badge, cardSt, label11, fmtTokens, fmtAgo } from './chat-ui.js';
import { getChatClient } from './chat.js';
import { MODES } from './chat-header.js';
import { RISK_TONE, grantText } from './chat-risk.js';

const R = () => globalThis.React;
const section = (title, ...kids) => h('section', { style: cardSt({ pad: '14px 16px', gap: 10, style: { borderRadius: 10 } }) }, h('h2', { style: { ...label11, margin: 0 } }, title), ...kids);
const row = (label, hint, control) => h('div', { style: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' } },
  h('div', { style: { flex: '1 1 220px', minWidth: 0 } }, h('div', { style: { fontWeight: 500 } }, label), hint ? h('div', { style: { fontSize: 12, color: T.mut } }, hint) : null), control);

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
      row('Models', 'The model comes from the relay; each chat can pick its own in the header.',
        h('div', { style: { display: 'flex', flexDirection: 'column', gap: 2, fontFamily: MONO, fontSize: 12, textAlign: 'right' } },
          h('span', null, h('span', { style: { color: T.mut } }, 'default '), s ? s.model + window_(s.model) : '—'),
          h('span', null, h('span', { style: { color: T.mut } }, 'fallback '), s?.fallback ? s.fallback + window_(s.fallback) : 'none'),
          h('span', null, h('span', { style: { color: T.mut } }, 'max steps '), s?.max_steps ?? '—')))),
    s?.documents ? section('Documents', h(DocSettings, { value: s.documents, onSave: d => save({ documents: d }) })) : null,
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
    h(LearningSection, { api, toast }),
    section('Permissions',
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } }, MODES.map(([k, l, d]) => h('div', { key: k, style: { display: 'flex', gap: 10, fontSize: 12.5, alignItems: 'baseline' } },
        h('span', { style: { minWidth: 130, fontWeight: 500 } }, l), h('span', { style: { color: T.mut } }, d)))),
      h('div', { style: { fontSize: 12, color: T.mut, display: 'flex', gap: 6, alignItems: 'flex-start' } }, h(Icon, { d: 'shield', size: 13, style: { marginTop: 2 } }),
        h('span', null, 'Each chat picks its mode in the header (new chats: Ask about choices). Per-tool rules are name globs in ', h('code', { style: { fontFamily: MONO } }, '[agent.permissions]'),
          ' of config.toml. A call is decided by the deny list, then the chat’s mode, then a mod’s own limits, then your grants (below), then the ask and allow lists, then its risk: reading runs; writing and generating ask unless the chat uses defaults; using the internet, running code and deleting always ask. Pending approvals from any client are in the header’s Approvals button.')),
      h(GrantsList, { api, toast })));
}

// Documents (plan 24.9): how big an attached document may be to go into the message whole, and what the
// reply keeps free. A chip's Whole / Card overrides it for one document (and is remembered for the chat).
function DocSettings({ value, onSave }) {
  const React = R(), [v, setV] = React.useState(value), [busy, setBusy] = React.useState(false);
  React.useEffect(() => setV(value), [value]);
  const win = v.inline_tokens === 'window', dirty = JSON.stringify(v) !== JSON.stringify(value);
  const num = (k, disabled, label) => h('input', { type: 'number', min: 0, step: 500, value: disabled ? '' : v[k], disabled, 'aria-label': label,
    placeholder: disabled ? 'window' : '', onChange: e => setV(x => ({ ...x, [k]: Math.max(0, Math.round(Number(e.target.value) || 0)) })),
    style: { width: 96, height: 28, padding: '0 8px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.sb, color: T.tx, fontFamily: MONO, fontSize: 12 } });
  return h(R().Fragment, null,
    row('Whole documents up to', 'An attached document this size or smaller goes into the message whole; a larger one is a card (name, size, outline) the agent reads in parts. Whole / Card on a chip overrides it.',
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } }, num('inline_tokens', win, 'Whole documents up to (tokens)'),
        h('span', { style: { fontSize: 12, color: T.mut } }, 'tokens'),
        h('label', { style: { display: 'flex', alignItems: 'center', gap: 5, fontSize: 12.5 } },
          h('input', { type: 'checkbox', checked: win, onChange: e => setV(x => ({ ...x, inline_tokens: e.target.checked ? 'window' : 6000 })) }), 'up to the model’s window'))),
    row('Reply reserve', 'Tokens kept free for the reply and tools: a document goes whole only if it fits the window after this and what the chat already holds.',
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } }, num('reply_reserve', false, 'Reply reserve (tokens)'), h('span', { style: { fontSize: 12, color: T.mut } }, 'tokens'))),
    dirty ? h('div', { style: { display: 'flex', gap: 8 } },
      h(Btn, { kind: 'pri', sm: true, label: busy ? 'Saving…' : 'Save', disabled: busy, onClick: async () => { setBusy(true); try { await onSave(v); } catch { /* toasted */ } finally { setBusy(false); } } }),
      h(Btn, { kind: 'ghost', sm: true, label: 'Revert', onClick: () => setV(value) })) : null);
}

// Grants (plan 25.2): what a card's "Allow in this chat" or "Always allow" covers, newest first, with revoke.
function GrantsList({ api, toast }) {
  const React = R(), [gs, setGs] = React.useState(null), [err, setErr] = React.useState(null);
  const load = () => api?.listGrants?.().then(setGs, e => setErr(e));
  React.useEffect(() => { load(); }, []);
  if (!api?.listGrants) return null;
  const revoke = async g => {
    try { await api.revokeGrant(g.id); setGs(l => l.filter(x => x.id !== g.id)); toast(`Revoked: ${g.tool} asks again`, 'success'); }
    catch (e) { toast(e.detail || String(e), 'error'); }
  };
  const scope = g => (g.scope === 'always' ? h(Badge, { tone: 'accent', title: 'Every chat, MCP and the API' }, 'always')
    : h('a', { href: '#/chat/' + encodeURIComponent(g.thread || ''), title: 'The chat it was allowed in', style: { fontSize: 11.5 } }, 'in a chat →'));
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, borderTop: '1px solid ' + T.bd, paddingTop: 10 } },
    h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 8 } }, h('span', { style: { fontWeight: 500 } }, 'Grants'),
      h('span', { style: { fontSize: 12, color: T.mut } }, 'Calls you allowed in a chat or always: they run without a card. A chat’s grants end when the chat is deleted.')),
    err ? h('span', { role: 'alert', style: { fontSize: 12, color: T.rd } }, `Couldn’t load the grants: ${err.detail || err.message}`) : null,
    gs && !gs.length ? h('span', { style: { fontSize: 12.5, color: T.mut } }, 'None yet. Approval cards offer “Allow in this chat” and “Always allow”.') : null,
    (gs || []).map(g => h('div', { key: g.id, style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 12.5, padding: '6px 8px', borderRadius: 6, background: T.inset } },
      h('span', { style: { fontFamily: MONO, fontSize: 12 } }, g.tool),
      g.risk ? h(Badge, { tone: RISK_TONE[g.risk] || 'dim' }, g.risk) : null,
      h('span', { style: { color: T.mut, minWidth: 0, overflowWrap: 'anywhere' } }, grantText(g.kind, g.key) || 'every call'),
      scope(g),
      h('span', { style: { flex: 1 } }),
      h('span', { style: { fontSize: 11.5, color: T.dim } }, [`used ${g.used || 0}×`, fmtAgo(g.created_ts) === 'now' ? 'just now' : fmtAgo(g.created_ts) + ' ago',
        g.expires_ts ? `ends ${new Date(g.expires_ts * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}` : null].filter(Boolean).join(' · ')),
      h(Btn, { sm: true, kind: 'ghost', icon: 'x', label: 'Revoke', onClick: () => revoke(g) }))));
}


// Learning (plan 21.7): the hub's [learning] settings; the Learning page lists what was learned.
function LearningSection({ api, toast }) {
  const React = R(), [l, setL] = React.useState(null);
  React.useEffect(() => { api?.getSettings?.().then(x => setL(x?.learning || null)).catch(() => {}); }, []);
  if (!l) return null;
  const save = async patch => {
    try { const r = await api.saveSettings({ learning: { ...l, ...patch } }); setL(r.settings.learning); toast('Saved', 'success'); }
    catch (e) { toast(e.detail || String(e), 'error'); }
  };
  const num = (k, min) => h('input', { type: 'number', min, value: l[k], style: { width: 70 }, onChange: e => save({ [k]: Number(e.target.value) }) });
  return section('Learning',
    row('Learn from chats', 'Card edits, answers and thumbs become preferences that fill your cards; each chat can turn it off in its header. The Learning page lists them.',
      h('label', { style: { display: 'flex', alignItems: 'center', gap: 6 } }, h('input', { type: 'checkbox', checked: !!l.enabled, onChange: e => save({ enabled: e.target.checked }) }), l.enabled ? 'On' : 'Off')),
    row('Propose after', 'An inferred preference is proposed once you chose it this many times, in as many chats.', num('infer_after', 1)),
    row('Fade after (days)', 'Inferred preferences unused this long are retired; ones you stated never fade.', num('fade_days', 1)),
    row('Nightly run', 'When the learner improves its instructions (plan 22), plus after an hour without a chat.',
      h('input', { type: 'time', value: l.nightly_at, onChange: e => e.target.value && save({ nightly_at: e.target.value }) })),
    h('a', { href: '#/s/agent/learning', style: { fontSize: 12.5 } }, 'Open the Learning page →'));
}
