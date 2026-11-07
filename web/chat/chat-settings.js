// Settings → Agent (plan 14.9, Wire — Phase 14): AGENT.md, memory (structured-memory 5.2: its settings and counts), documents
// (plan 24.9: whole documents up to a size or the model's window, and the reply reserve), the
// models, how a turn's steps are drawn (one fold, or split at each message; per browser), skills, the ask modes and permissions with the grants (plan 25.2: what was allowed in a
// chat or always, with revoke), and Speech input (plan 29.4, chat-speech-input.js). (Show thinking is retired: thinking is a row in each turn's
// activity fold, plan 19.4.) Mounted by Hub.dc.html's Settings page.

import { h, T, MONO, Icon, Btn, Badge, cardSt, label11, inputSt, fmtTokens, fmtAgo, usePref } from './chat-ui.js';
import { groupSkills, uploadBody } from './chat-skills.js';
import { STEPS_LAYOUT } from './chat-activity.js';
import { getChatClient } from './chat.js';
import { MODES } from './chat-header.js';
import { RISK_TONE, grantText } from './chat-risk.js';

const R = () => globalThis.React;
export const section = (title, ...kids) => h('section', { style: cardSt({ pad: '14px 16px', gap: 10, style: { borderRadius: 10 } }) }, h('h2', { style: { ...label11, margin: 0 } }, title), ...kids);
export const row = (label, hint, control) => h('div', { style: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' } },
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

// One load of the agent's own settings (GET /api/s/agent/v1/settings) and models, shared by the cards below.
const stores = new WeakMap();
function storeFor(api) {
  let st = stores.get(api);
  if (!st) {
    const c = getChatClient(api), subs = new Set();
    st = { c, s: null, models: null, err: null, subs, loaded: false,
      emit() { subs.forEach(f => f()); },
      load() { if (st.loaded) return; st.loaded = true; c.settings().then(s => { st.s = s; st.emit(); }, e => { st.err = e; st.emit(); }); c.models().then(m => { st.models = m; st.emit(); }, () => {}); },
      reload() { return c.settings().then(s => { st.s = s; st.emit(); }, () => {}); },
      async save(body, toast) { try { st.s = await c.saveSettings(body); st.emit(); toast?.('Saved by the agent', 'success'); } catch (e) { toast?.(e.detail || String(e), 'error'); throw e; } } };
    stores.set(api, st);
  }
  return st;
}
/** The agent's settings for a card: {s, models, err, live, save(body)}; every card shares one load. */
export function useAgent(api, toast) {
  const React = R(), st = storeFor(api), [, tick] = React.useState(0);
  React.useEffect(() => { const f = () => tick(n => n + 1); st.subs.add(f); st.load(); return () => st.subs.delete(f); }, []);
  return { s: st.s, models: st.models, err: st.err, live: st.c.live, c: st.c, reload: () => st.reload(), save: body => st.save(body, toast) };
}
const byAgent = () => h('span', { title: 'Saved by the agent mod (/api/s/agent/v1/settings), not with the page’s Save', style: { fontSize: 11, color: T.dim, fontWeight: 400, textTransform: 'none', letterSpacing: 0 } }, ' · saved by the agent');
const agentSection = (title, ...kids) => h('section', { style: cardSt({ pad: '14px 16px', gap: 10, style: { borderRadius: 10 } }) }, h('h2', { style: { ...label11, margin: 0 } }, title, byAgent()), ...kids);

/** The mock note, and the agent not answering. */
export function AgentNotes({ api, toast }) {
  const a = useAgent(api, toast);
  return h(R().Fragment, null,
    a.live ? null : h('div', { role: 'note', style: { display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: T.mut } }, h(Badge, { tone: 'purple' }, 'MOCK'), 'The scripted mock agent: changes last until the page reloads.'),
    a.err ? h('div', { role: 'alert', style: { padding: '10px 12px', borderRadius: 8, background: T.trd, color: T.rd } }, `The agent didn’t answer: ${a.err.detail || a.err.message}. Start the Agent mod, then reload.`) : null);
}

/** The chat's default and fallback models (read-only: the agent's own settings). */
export function ModelsCard({ api, toast, bare }) {
  const { s, models } = useAgent(api, toast);
  const window_ = id => { const m = models?.models?.find(x => x.id === id); return m?.meta?.context_length ? ` · ${fmtTokens(m.meta.context_length)}` : ''; };
  const body = row('Models', 'The model comes from the relay; each chat can pick its own in the header.',
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 2, fontFamily: MONO, fontSize: 12, textAlign: 'right' } },
      h('span', null, h('span', { style: { color: T.mut } }, 'default '), s ? s.model + window_(s.model) : '—'),
      h('span', null, h('span', { style: { color: T.mut } }, 'fallback '), s?.fallback ? s.fallback + window_(s.fallback) : 'none'),
      h('span', null, h('span', { style: { color: T.mut } }, 'max steps '), s?.max_steps ?? '—')));
  const [layout, setLayout] = usePref(STEPS_LAYOUT, 'fold');   // this browser only (gaifa.chat.steps)
  const steps = row('Steps between messages', 'One fold per turn ("Ran 2 tools"), or each thing the agent says between steps as a message of its own, with a fold for the steps before it. This browser only.',
    h('select', { 'aria-label': 'Steps between messages', value: layout === 'split' ? 'split' : 'fold', onChange: e => setLayout(e.target.value),
      style: { height: 28, padding: '0 6px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.sb, color: T.tx, font: 'inherit', fontSize: 12.5 } },
    h('option', { value: 'fold' }, 'One fold per turn'), h('option', { value: 'split' }, 'Split at each message')));
  return bare ? h(R().Fragment, null, body, steps) : section('Chat', body, steps);
}
export function DocumentsCard({ api, toast }) {
  const a = useAgent(api, toast);
  return a.s?.documents ? agentSection('Documents', h(DocSettings, { value: a.s.documents, onSave: d => a.save({ documents: d }) })) : null;
}
export function InstructionsCard({ api, toast }) {
  const a = useAgent(api, toast);
  return agentSection('Instructions',
    a.s ? h(Editor, { label: 'AGENT.md', hint: 'Standing instructions, read every turn (data/agent/AGENT.md).', value: a.s.agent_md, placeholder: '# How I like things\n- Prefer 16:9 images', onSave: v => a.save({ agent_md: v }) })
      : h('span', { style: { color: T.mut } }, a.err ? 'The agent isn’t running.' : 'Loading…'));
}
export function MemoryCard({ api, toast }) {
  const React = R(), { s, save } = useAgent(api, toast);
  const ms = s?.memory_settings, st = s?.memory_stats;      // structured-memory 5.2
  const [days, setDays] = React.useState(null);
  React.useEffect(() => { if (ms) setDays(ms.fade_days); }, [ms?.fade_days]);
  if (!s) return agentSection('Memory', h('span', { style: { color: T.mut } }, 'Loading…'));
  const link = (href, label) => h('a', { href, style: { color: T.acct, fontSize: 12.5 } }, label);
  return agentSection('Memory',
    h('div', { style: { fontSize: 12.5, color: T.mut, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'baseline' } },
      st ? h('span', null, `${st.facts} fact${st.facts === 1 ? '' : 's'} · ${st.entities} entr${st.entities === 1 ? 'y' : 'ies'} besides you`) : null,
      st?.proposed ? link('#/s/agent/review', `${st.proposed} to review`) : null,
      link('#/s/agent/memory', 'Open the Memory page')),
    ms ? row('Recall memories in each message', 'Before the agent answers, the facts your message calls to mind come with it (not what its profile already holds).',
      h('input', { type: 'checkbox', checked: !!ms.recall, 'aria-label': 'Recall memories in each message', onChange: e => save({ memory_settings: { recall: e.target.checked } }) })) : null,
    ms ? row('Let learned facts fade after', 'A fact the agent learned that nothing used this long is proposed for retiring. What you said yourself never fades.',
      h('span', { style: { display: 'flex', gap: 6, alignItems: 'center' } },
        h('input', { type: 'number', min: 7, max: 3650, value: days ?? '', 'aria-label': 'Fade after days', onChange: e => setDays(e.target.value),
          style: { width: 80, height: 28, padding: '0 8px', borderRadius: 6, border: '1px solid ' + T.bds, background: T.sb, color: T.tx } }),
        h('span', { style: { fontSize: 12, color: T.mut } }, 'days'),
        Number(days) !== ms.fade_days ? h(Btn, { sm: true, kind: 'pri', label: 'Save', onClick: () => save({ memory_settings: { fade_days: Number(days) } }) }) : null)) : null,
    ms ? row('Save what it learns without asking when it’s sure', 'From a chat that went quiet, a fact you said in your own words, that it’s sure of and that isn’t personal, is saved at once; Review lists it under “Learned on its own”, where Not this takes it back. The rest waits for you.',
      h('input', { type: 'checkbox', checked: ms.auto_approve !== false, 'aria-label': 'Save learned facts without asking', onChange: e => save({ memory_settings: { auto_approve: e.target.checked } }) })) : null,
    ms && ms.auto_approve !== false ? row('How sure', 'Cautious saves fewer facts on its own; Eager saves more.',
      h('span', { style: { display: 'flex', gap: 4 } }, ...SURE.map(([v, l]) => h(Btn, { key: l, sm: true, kind: Math.abs((ms.auto_threshold ?? 0.8) - v) < 0.001 ? 'pri' : undefined, label: l,
        onClick: () => save({ memory_settings: { auto_threshold: v } }) })))) : null,
    ms && ms.auto_approve !== false ? row('Always ask about', 'Facts on these topics always wait for you in Review.',
      h('span', { style: { display: 'flex', gap: 4, flexWrap: 'wrap' } }, ...SENSITIVE.map(c => {
        const on = (ms.always_review || SENSITIVE).includes(c);
        return h(Btn, { key: c, sm: true, kind: on ? 'pri' : undefined, label: c, 'aria-pressed': on,
          onClick: () => save({ memory_settings: { always_review: on ? (ms.always_review || SENSITIVE).filter(x => x !== c) : [...(ms.always_review || SENSITIVE), c] } }) });
      }))) : null);
}
const SURE = [[0.9, 'Cautious'], [0.8, 'Normal'], [0.65, 'Eager']];          // memory-auto-learning 2.4
const SENSITIVE = ['health', 'money', 'legal', 'relationships', 'religion', 'politics', 'sexuality'];
export function SkillsCard({ api, toast }) {
  const React = R(), { s, c, reload } = useAgent(api, toast);
  const [busy, setBusy] = React.useState(''), [envs, setEnvs] = React.useState(null), [env, setEnv] = React.useState(''), [ws, setWs] = React.useState(null);
  const [askDelete, setAskDelete] = React.useState(null);
  const folderRef = React.useRef(null), fileRef = React.useRef(null);
  React.useEffect(() => { api.callService?.('workspace', 'GET', '/v1/environments').then(r => {   // skill-sources 3.2
    const list = (r.json?.environments || []).filter(e => e.id !== 'none'); setEnvs(list); setEnv(e => e || list[0]?.id || ''); }).catch(() => setEnvs([])); }, []);
  React.useEffect(() => { if (!env) { setWs(null); return; }
    api.callService?.('workspace', 'GET', '/v1/skills', { query: { environment: env } }).then(r => setWs(r.json?.skills || [])).catch(() => setWs([])); }, [env]);
  const act = async (key, fn, done) => {
    setBusy(key);
    try { await fn(); await reload(); if (done) toast(done, 'success'); }
    catch (e) { toast(e.detail || e.message || String(e), 'error'); }
    finally { setBusy(''); }
  };
  const upload = files => files?.length && act('upload', async () => {
    const row = await c.uploadSkill(await uploadBody(files));
    if (row && row.enabled === false) toast(`${row.name} is saved turned off: ${row.screening?.note || 'look it over, then turn it on'}`, 'warning');
  }, 'Skill added');
  const own = s?.skills?.filter(k => k.source === 'user') || [];
  const rowOf = k => {
    const mine = k.source === 'user', name = k.id.split('/')[1], off = k.enabled === false;
    return h('div', { key: k.id, style: { display: 'flex', gap: 10, alignItems: 'baseline', fontSize: 12.5, flexWrap: 'wrap', opacity: off ? 0.65 : 1 } },
      h('span', { style: { fontFamily: MONO, fontSize: 12, minWidth: 90 } }, '/' + k.name),
      h('span', { style: { flex: '1 1 240px', color: T.mut, minWidth: 0 } },
        h('span', { title: k.description, style: { display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' } }, k.description),
        off && k.screening?.note ? h('div', { style: { color: T.acct, fontSize: 12 } }, k.screening.note) : null,
        k.problems?.length ? h('div', { style: { color: T.dim, fontSize: 12 } }, k.problems.join(' · ')) : null),
      h('span', { style: { display: 'flex', gap: 6, alignItems: 'baseline', flex: 'none' } },
      mine && off ? h(Badge, { tone: 'accent' }, 'off') : null,
      mine ? h(Btn, { sm: true, kind: 'ghost', label: off ? 'Turn on' : 'Turn off', disabled: !!busy, onClick: () => act(k.id, () => c.setSkill(name, off)) }) : null,
      mine ? h(Btn, { sm: true, kind: 'ghost', label: askDelete === k.id ? 'Delete it' : 'Delete', disabled: !!busy, style: askDelete === k.id ? { color: T.rd } : undefined,
        onClick: () => askDelete === k.id ? (setAskDelete(null), act(k.id, () => c.deleteSkill(name), `Deleted ${k.name} (kept in data/agent/skills/.trash/)`)) : setAskDelete(k.id) }) : null));
  };
  const picker = (ref, attrs) => h('input', { ref, type: 'file', multiple: true, style: { display: 'none' }, ...attrs, onChange: e => { upload(e.target.files); e.target.value = ''; } });
  return section('Skills',
    h('div', { style: { fontSize: 12, color: T.mut } }, 'Loaded only when needed. Each one is also a slash command in the chat. A chat working in workspace folders also gets the skills other agents keep there.'),
    h('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' } },
      h(Btn, { sm: true, icon: 'upload', label: busy === 'upload' ? 'Adding…' : 'Upload a folder…', disabled: !!busy || !c?.uploadSkill, onClick: () => folderRef.current?.click() }),
      h(Btn, { sm: true, kind: 'ghost', label: 'Upload a SKILL.md or zip…', disabled: !!busy || !c?.uploadSkill, onClick: () => fileRef.current?.click() }),
      picker(folderRef, { webkitdirectory: '', directory: '' }), picker(fileRef, { accept: '.md,.zip', multiple: false }),
      h('span', { style: { fontSize: 12, color: T.dim } }, 'Checked for hidden instructions; one that looks off is saved turned off.')),
    s && !s.skills?.length ? h('span', { style: { color: T.mut, fontSize: 12.5 } }, 'No skills yet: mods ship them in services/<id>/skills/, yours go in data/agent/skills/.') : null,
    ...groupSkills(s?.skills || []).map(g => h('div', { key: g.key, style: { display: 'flex', flexDirection: 'column', gap: 6 } },
      h('div', { style: { ...label11, fontSize: 10.5 } }, g.title), ...g.items.map(rowOf))),
    envs?.length ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, borderTop: '1px solid ' + T.bd, paddingTop: 10 } },
      h('div', { style: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' } },
        h('span', { style: { fontWeight: 500 } }, 'From a workspace'),
        h('select', { value: env, 'aria-label': 'Environment', onChange: e => setEnv(e.target.value), style: { ...inputSt, height: 28 } }, envs.map(e => h('option', { key: e.id, value: e.id }, e.name)))),
      ws && !ws.length ? h('span', { style: { color: T.mut, fontSize: 12.5 } }, 'No skills in this environment’s folders.') : null,
      ...(ws || []).map(k => h('div', { key: k.id, style: { display: 'flex', flexDirection: 'column', gap: 2, fontSize: 12.5 } },
        h('div', { style: { display: 'flex', gap: 8, alignItems: 'center' } },
          h('span', { style: { fontFamily: MONO, fontSize: 12, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, '/' + k.id),
          h(Badge, null, k.folder?.name || ''),
          own.some(o => o.name === k.name) ? h(Badge, { tone: 'dim' }, 'yours too') :
            h(Btn, { sm: true, kind: 'ghost', label: 'Copy', title: 'Copy to my skills', disabled: !!busy, onClick: () => act(k.id, () => c.copySkill({ id: k.id, environment: env }), `Copied ${k.name} to your skills`) })),
        h('span', { title: k.description, style: { color: T.mut, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' } }, k.description)))) : null);
}
/** The five modes, and how a call is decided. */
export function ModesCard() {
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10 } },
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } }, MODES.map(([k, l, d]) => h('div', { key: k, style: { display: 'flex', gap: 10, fontSize: 12.5, alignItems: 'baseline' } },
      h('span', { style: { minWidth: 130, fontWeight: 500 } }, l), h('span', { style: { color: T.mut } }, d)))),
    h('div', { style: { fontSize: 12, color: T.mut, display: 'flex', gap: 6, alignItems: 'flex-start' } }, h(Icon, { d: 'shield', size: 13, style: { marginTop: 2 } }),
      h('span', null, 'Each chat picks its mode in the header (new chats: Manual; a workspace folder’s level caps what any mode allows). Per-tool rules are name globs (Tool permissions; ', h('code', { style: { fontFamily: MONO } }, '[agent.permissions]'),
        ' in config.toml). A call is decided by the deny list, then the chat’s mode, then a mod’s own limits, then your grants, then the ask and allow lists, then its risk: reading runs; writing and generating ask unless the chat uses defaults; using the internet, running code and deleting ask, except in Auto, where the judge decides. Pending approvals from any client are in the header’s Approvals button.')));
}

/** The agent's own cards in one column (for anything that mounts the whole); the Settings page places them one by one. */
export function AgentSettings({ api, toast = () => {} }) {
  const p = { api, toast };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 14 } },
    h(AgentNotes, p), h(ModelsCard, p), h(DocumentsCard, p),
    h(InstructionsCard, p), h(MemoryCard, p), h(SkillsCard, p),
    section('Permissions', h(ModesCard), h(GrantsList, p)));   // the hub's values (learning, speech, the judge, screening…) are rows of web/settings/
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
export function GrantsList({ api, toast }) {
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
