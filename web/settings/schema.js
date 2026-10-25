// The Settings page as data (plan settings-redesign 1.1, regrouped in 2.1): sections → groups → rows. A row is
// one `config.toml` key with its label, hint, control and keywords, or a `block` (anything that isn't a plain
// value: a chart, a table, a card from the agent). Pure: no React and no DOM, so the page (settings.js), the
// search (search.js) and the tests (utils/tests/web/settings-schema.test.mjs) all read the same list. Blocks
// are named here and drawn by blocks-hub.js / blocks-agent.js. Written by us (web/PATCHES.md).

import { checkCommandRule, checkToolGlob } from '../chat/chat-rules.js';

// Section → the api areas its data comes from: the "Mock data" note (GAIFA patch 5, PATCHES.md).
export const SETTINGS_AREAS = { general: ['settings', 'system'], machine: ['settings', 'memory', 'system'], services: ['settings', 'services'],
  agent: [], permissions: ['settings', 'tools'], speech: ['settings'], sessions: ['sessions'], about: ['services', 'system'] };

// ---------- paths into the Settings object ----------
export function getPath(o, path) { return String(path).split('.').reduce((x, k) => (x == null ? undefined : x[k]), o); }
export function setPath(o, path, v) {
  const ks = String(path).split('.'), last = ks.pop();
  let x = o;
  for (const k of ks) { if (x[k] == null || typeof x[k] !== 'object') x[k] = {}; x = x[k]; }
  x[last] = v;
  return o;
}
// The Settings sections that live under [agent] in config.toml (utils/settings.py save()).
const AGENT_TABLES = new Set(['judge', 'screen', 'permissions', 'web']);
/** A Settings path → its dotted config.toml key (`judge.threshold` → `agent.judge.threshold`). */
export function configKey(path) { const top = String(path).split('.')[0]; return AGENT_TABLES.has(top) ? 'agent.' + path : String(path); }

const between = (min, max, unit = '') => v => (String(v ?? '').trim() !== '' && !isNaN(Number(v)) && Number(v) >= min && Number(v) <= max ? null : `Between ${min} and ${max}${unit ? ' ' + unit : ''}`);
/** A row bound to one Settings path: reads and writes the page draft. A number row with min/max checks its range. */
export function field(id, path, o = {}) {
  const r = { id, path, key: o.key === undefined ? configKey(path) : o.key, keywords: [], get: d => getPath(d, path), set: (d, v) => setPath(d, path, v), ...o };
  if (r.control === 'number' && !r.validate && r.min != null && r.max != null) r.validate = between(r.min, r.max, r.unit);
  return r;
}
/** A row whose value applies at once outside the draft (theme, density, the sidebar): `read(ctx)`, `apply(ctx, v)`. */
export function instant(id, path, o = {}) { return { ...field(id, path, o), instant: true }; }
/** A block: drawn by the component named `block`, from blocks-hub.js or blocks-agent.js. */
export function block(id, name, o = {}) { return { id, control: 'block', block: name, key: null, keywords: [], ...o }; }

const knownMods = ctx => (ctx.services || []).filter(s => !(s.manifest_errors || []).length);
const hasMod = (ctx, ...ids) => (ctx.services || []).some(s => ids.includes(s.id));
const n = (k, word) => `${k} ${word}${k === 1 ? '' : 's'}`;
const onOff = v => (v ? 'on' : 'off');

// ---------- validation (the rules vmSettings had) ----------
export const PORT_MSG = 'Use a port between 1024 and 65535';
export const RESERVE_MSG = 'Between 0 and 64 GB';
const checkPort = v => (!/^\d+$/.test(String(v)) || Number(v) < 1024 || Number(v) > 65535 ? PORT_MSG : null);
const checkReserve = v => between(0, 64)(v) && RESERVE_MSG;
const checkDays = v => (/^\d+(\.\d+)?$/.test(String(v ?? '').trim()) && Number(v) <= 3650 ? null : 'A number of days, 0 to 3650');

// ---------- choices ----------
export const JUDGE_CONTEXTS = [{ value: 'none', label: 'Your words and the call' }, { value: 'trail', label: '+ earlier calls' }, { value: 'full', label: '+ their results' }];
export const RELEVANCE = [{ value: 'auto', label: 'Automatic' }, { value: 'decide', label: 'A decision model' }, { value: 'lexical', label: 'Words in common' }, { value: 'off', label: 'Off' }];

// ---------- the sections ----------
/** Every section, group and row. `ctx` carries what choices and summaries depend on (`services`, `draft`, `reading`); nothing here fetches. */
export function sections(ctx = {}) {
  const mods = knownMods(ctx), d = ctx.draft || {};
  const svcName = id => (ctx.services || []).find(s => s.id === id)?.name || id;
  const agentOn = !ctx.services || hasMod(ctx, 'agent');
  const secs = [
    { id: 'general', label: 'General', icon: 'gear', areas: SETTINGS_AREAS.general, groups: [
      { id: 'hub', label: 'Hub', summary: () => `Port ${d.hub?.port ?? '—'}${ctx.system ? ` · v${ctx.system.hub.version}` : ''}`, rows: [
        field('port', 'hub.port', { label: 'GAIFA port', hint: 'Bound to 127.0.0.1 — this machine only. Default 7000.', control: 'number', inputMode: 'numeric',
          restart: true, validate: checkPort, keywords: ['address', 'listen', 'localhost', '127.0.0.1'] }),
        block('process', 'ProcessCard', { label: 'GAIFA process', card: true, keywords: ['version', 'pid', 'uptime', 'rss'] }),
      ] },
      { id: 'interface', label: 'Interface', summary: c => `${cap(c.theme || 'system')} theme · ${c.density || 'compact'} · sidebar ${c.nav?.services || 'list'}`, rows: [
        instant('theme', 'ui.theme', { label: 'Theme', hint: 'System follows your OS setting. Applied immediately.', control: 'segmented',
          choices: [{ value: 'system', label: 'System' }, { value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }],
          read: c => c.theme, apply: (c, v) => c.setTheme?.(v), keywords: ['dark mode', 'light mode', 'colors'] }),
        instant('density', 'ui.density', { label: 'Density', hint: 'Compact tightens tables.', control: 'segmented',
          choices: [{ value: 'comfortable', label: 'Comfortable' }, { value: 'compact', label: 'Compact' }],
          read: c => c.density, apply: (c, v) => c.setDensity?.(v), keywords: ['compact', 'spacing'] }),
        instant('navServices', 'ui.nav.services', { label: 'Services in the sidebar', hint: 'Each mod listed, one Services button, or counts by state. Applied immediately.', control: 'segmented',
          choices: [{ value: 'list', label: 'List' }, { value: 'button', label: 'Button' }, { value: 'counts', label: 'Counts' }],
          read: c => c.nav?.services || 'list', apply: (c, v) => c.setNav?.(x => ({ collapsed: false, hidden: [], folded: false, ...(x || {}), services: v })), keywords: ['sidebar', 'nav'] }),
        instant('navFolded', 'ui.nav.folded', { label: 'Fold the services list', hint: 'The list folded under its SERVICES header.', control: 'toggle',
          read: c => !!c.nav?.folded, apply: (c, v) => c.setNav?.(x => ({ collapsed: false, services: 'list', hidden: [], ...(x || {}), folded: v })), keywords: ['sidebar', 'collapse'] }),
        block('dashboard', 'DashboardReset', { label: 'Reset the dashboard layout', key: 'ui.dashboard', keywords: ['overview', 'widgets', 'customize'] }),
      ] },
      { id: 'outputs', label: 'Outputs', summary: () => (Number(d.outputs?.hidden_keep_days) ? `Saved web pages kept ${d.outputs.hidden_keep_days} days` : 'Saved web pages kept'), rows: [
        field('hiddenDays', 'outputs.hidden_keep_days', { label: 'Saved web pages', hint: 'Pages the agent read are kept as hidden outputs (for citations and rereading). Delete them after this many days; 0 keeps them.',
          control: 'number', unit: 'days', width: 90, validate: checkDays, keywords: ['trash', 'clean up', 'hidden outputs'] }),
      ] }] },
    { id: 'machine', label: 'Machine', icon: 'chart', areas: SETTINGS_AREAS.machine, groups: [
      { id: 'memory', label: 'Memory', summary: () => `Reserve ${d.memory?.reserve_gb ?? '—'} GB · auto make room ${onOff(d.memory?.auto_make_room)} · ${(d.memory?.never_unload || []).length} never unloaded`, rows: [
        block('history', 'MemoryHistory', { label: 'Last 24 hours', keywords: ['chart', 'usage'] }),
        field('reserve', 'memory.reserve_gb', { label: 'Reserve', hint: 'GB of unified memory GAIFA always keeps free for the OS and desktop.', control: 'number',
          min: 0, max: 64, unit: 'GB', validate: checkReserve, keywords: ['RAM', 'unified', 'free memory', 'headroom'] }),
        field('auto', 'memory.auto_make_room', { label: 'Automatically make room when a service needs memory', hint: 'When off, GAIFA shows you the plan and asks first.',
          control: 'toggle', aria: 'Automatically make room', keywords: ['unload', 'make room'] }),
        field('never', 'memory.never_unload', { label: 'Never auto-unload', hint: 'These services are never part of a make-room plan.', control: 'chips',
          choices: mods.map(s => ({ value: s.id, label: s.name })), keywords: ['pin', 'keep loaded'] }),
        field('priority', 'memory.priority', { label: 'Unload order', hint: 'Top of the list is unloaded first.', control: 'order',
          items: dd => (getPath(dd, 'memory.priority') || []).filter(id => mods.some(s => s.id === id)).map(id => ({ id, label: svcName(id), note: (dd.memory?.never_unload || []).includes(id) ? 'never unloaded' : '' })),
          keywords: ['priority', 'unload first'] }),
      ] },
      { id: 'storage', label: 'Storage', summary: c => (c.system ? `${fb(c.system.disk.free_bytes)} free of ${fb(c.system.disk.total_bytes)}` : 'Folders and disk'), rows: [
        block('folders', 'PathsList', { label: 'Folders', keywords: ['paths', 'disk', 'models', 'databases', 'outputs', 'logs', 'state', 'root'] }),
      ] },
      { id: 'hardware', label: 'Hardware', summary: () => 'GPUs, runtimes and what GAIFA can use here', rows: [
        block('hardware', 'HardwareCard', { label: 'Hardware', card: true, keywords: ['GPU', 'VRAM', 'CPU', 'accelerator', 'ROCm', 'CUDA'] }),
      ] }] },
    { id: 'services', label: 'Services', icon: 'puzzle', areas: SETTINGS_AREAS.services, groups: [
      { id: 'services', label: 'Services', summary: () => { const en = Object.values(d.services?.enabled || {}); return `${n(en.length, 'mod')} · ${en.filter(Boolean).length} enabled`; }, rows: [
        block('table', 'ServicesTable', { label: 'Folders in services/', keys: ['services.order', 'services.enabled', 'services.autostart'], card: true,
          keywords: ['mods', 'enabled', 'autostart', 'order', 'sidebar', 'tools'] }),
        block('add', 'AddModCard', { label: 'Add a mod', card: true, keywords: ['new mod', 'template', 'gaifa new'] }),
      ] }] },
    { id: 'agent', label: 'Agent', icon: 'chat', areas: SETTINGS_AREAS.agent, when: () => agentOn, groups: [
      { id: 'model', label: 'Model', summary: () => 'The chat model, fallback and steps (the agent’s own settings)', rows: [
        block('notes', 'AgentNotes', { label: 'The agent' }),
        block('models', 'ModelsCard', { label: 'Models', keywords: ['chat model', 'fallback', 'max steps', 'relay'] }),
      ] },
      { id: 'documents', label: 'Documents', summary: () => 'Whole documents and the reply reserve', rows: [
        block('documents', 'DocumentsCard', { label: 'Documents', card: true, keywords: ['whole documents', 'reply reserve', 'tokens'] }),
      ] },
      { id: 'web', label: 'Reading web pages', summary: () => `Long pages: ${(RELEVANCE.find(x => x.value === d.web?.relevance) || {}).label || '—'}`, rows: [
        field('relevance', 'web.relevance', { label: 'Long pages', hint: 'A page longer than the agent asked for comes back as its passages most relevant to the question, most relevant first, with line numbers to cite.',
          control: 'select', choices: RELEVANCE, keywords: ['web_fetch', 'passages'] }),
        field('relevanceModel', 'web.model', { label: 'Relevance model', hint: 'The decision model that scores passages.', control: 'select',
          choices: c => (c.reading?.choices?.decide || []).map(x => ({ value: x, label: x })), when: () => ['auto', 'decide'].includes(d.web?.relevance), keywords: ['decide'] }),
      ] },
      { id: 'instructions', label: 'Instructions', summary: () => 'AGENT.md', rows: [block('instructions', 'InstructionsCard', { label: 'Instructions', card: true, keywords: ['AGENT.md', 'standing instructions'] })] },
      { id: 'memory', label: 'Memory', summary: () => 'MEMORY.md and its topics', rows: [block('memory', 'MemoryCard', { label: 'Memory', card: true, keywords: ['MEMORY.md', 'remember', 'topics'] })] },
      { id: 'skills', label: 'Skills', summary: () => 'Loaded when needed; each is a slash command', rows: [block('skills', 'SkillsCard', { label: 'Skills', card: true, keywords: ['slash commands', 'SKILL.md'] })] },
      { id: 'learning', label: 'Learning', summary: () => `Learn from chats ${onOff(d.learning?.enabled)} · nightly at ${d.learning?.nightly_at || '—'}`, rows: [
        block('learning', 'LearningSection', { label: 'Learning', card: true, keys: ['learning.enabled', 'learning.infer_after', 'learning.fade_days', 'learning.nightly_at'], keywords: ['preferences', 'nightly', 'learner'] }),
      ] }] },
    { id: 'permissions', label: 'Permissions', icon: 'shield', areas: SETTINGS_AREAS.permissions, when: () => agentOn, groups: [
      { id: 'modes', label: 'Modes', summary: () => 'Plan · Manual · Accept edits · Auto · Bypass', rows: [block('modes', 'ModesCard', { label: 'Modes', keywords: ['plan', 'manual', 'accept edits', 'auto', 'bypass'] })] },
      { id: 'rules', label: 'Tool rules', summary: () => { const p = d.permissions || {}; return `${(p.deny || []).length} never · ${(p.ask || []).length} ask · ${(p.allow || []).length} allow`; }, rows: [
        field('deny', 'permissions.deny', { label: 'Never run', hint: 'Tool names or globs (comfy_*). Never run wins over everything.', control: 'list', check: checkToolGlob, placeholder: 'tts_delete_voice', keywords: ['deny', 'block'] }),
        field('ask', 'permissions.ask', { label: 'Always ask', hint: 'Asks in every mode unless you granted the tool.', control: 'list', check: checkToolGlob, placeholder: 'hub_set_preference' }),
        field('allow', 'permissions.allow', { label: 'Run without asking', hint: 'Never skips the card of a tool that runs code.', control: 'list', check: checkToolGlob, placeholder: 'hub_start_service' }),
      ] },
      { id: 'grants', label: 'Grants', summary: () => 'What you allowed in a chat or always', rows: [block('grants', 'GrantsList', { label: 'Grants', keywords: ['always allow', 'revoke'] })] },
      { id: 'judge', label: 'Auto judge', summary: () => { const j = d.judge || {}; return `${j.model || '—'} via ${j.backend || '—'} · ${n((j.allow_commands || []).length + (j.ask_commands || []).length, 'command rule')}`; }, rows: [
        block('judgeModel', 'JudgeModelBlock', { label: 'Judge model', keys: ['judge.backend', 'judge.model', 'judge.url'], keywords: ['decide', 'relay', 'auto mode'] }),
        field('context', 'judge.context', { label: 'The judge reads', hint: 'What it reads of the turn besides your words and the call.', control: 'segmented', choices: JUDGE_CONTEXTS }),
        field('threshold', 'judge.threshold', { label: 'Threshold', hint: 'A decision model: every answer must clear it.', control: 'number', min: 0.01, max: 1, step: 0.01, width: 90 }),
        field('timeout', 'judge.timeout_s', { label: 'Time limit', hint: 'Slower than this, the call asks you.', control: 'number', min: 0.1, max: 60, step: 0.5, unit: 's', width: 90 }),
        field('allowCommands', 'judge.allow_commands', { label: 'Always allow these commands in Auto', hint: 'They run without asking unless a fixed rule asks (secrets, sudo, removing a tree, piping into a shell, git push…). * matches any text in a word, a last * any further words.',
          control: 'list', check: checkCommandRule, placeholder: 'pytest *', keywords: ['command rules'] }),
        field('askCommands', 'judge.ask_commands', { label: 'Always ask before these', hint: 'They ask in Auto even when the fixed rules or the model would run them.', control: 'list', check: checkCommandRule, placeholder: 'git checkout *' }),
      ] },
      { id: 'screening', label: 'Screening', summary: () => { const s = d.screen || {}; return `Pages ${onOff(s.pages)} · documents ${onOff(s.documents)} · ${s.model || 'the judge’s model'}`; }, rows: [
        field('pages', 'screen.pages', { label: 'Screen fetched pages', hint: 'Before the chat model reads a page, fixed patterns and a model remove passages that try to instruct an AI. The full page stays an output.', control: 'toggle', keywords: ['prompt injection'] }),
        field('documents', 'screen.documents', { label: 'Screen your documents', hint: 'Uploads and files you attach.', control: 'toggle' }),
        field('transcripts', 'screen.transcripts', { label: 'Screen transcripts', control: 'toggle' }),
        block('screenModel', 'ScreenModelBlock', { label: 'Screen pages with', keys: ['screen.backend', 'screen.model', 'screen.threshold', 'screen.confirm'], keywords: ['decide', 'judge'] }),
        field('windowChars', 'screen.window_chars', { label: 'Text per model call', hint: 'Characters of passages in one screening call (800 suits a small model, 6000 a large one).', control: 'number', min: 200, max: 20000, step: 200, unit: 'chars', width: 100 }),
        field('parallel', 'screen.parallel', { label: 'Calls at once', control: 'number', min: 1, max: 32, width: 80 }),
      ] },
      { id: 'judged', label: 'Judged calls', summary: () => 'What the judge ran and asked, newest first', rows: [block('judged', 'JudgedList', { label: 'Judged calls', keywords: ['auto', 'verdicts'] })] },
    ] },
    { id: 'speech', label: 'Speech', icon: 'mic', areas: SETTINGS_AREAS.speech, when: () => !ctx.services || hasMod(ctx, 'stt', 'tts'), groups: [
      { id: 'dictation', label: 'Dictation', summary: () => `${d.speech_input?.preset || 'balanced'} · ${n((d.speech_input?.mics || []).length, 'microphone')} ranked`, rows: [
        block('dictation', 'SpeechInputSection', { label: 'Speech input', card: true, keys: ['speech_input.mics', 'speech_input.language', 'speech_input.preset', 'speech_input.mode'], keywords: ['microphone', 'dictation', 'stt', 'whisper'] }),
      ] },
      { id: 'voice', label: 'Voice', summary: () => `${d.speech_output?.voice || 'the default voice'} · read every reply ${onOff(d.speech_output?.auto_read)}`, rows: [
        block('voice', 'SpeechOutputSection', { label: 'Voice', card: true, keys: ['speech_output.voice', 'speech_output.speed', 'speech_output.auto_read', 'speech_output.pause_ms'], keywords: ['read aloud', 'tts', 'voice mode'] }),
      ] }] },
    { id: 'sessions', label: 'Sessions', icon: 'refresh', areas: SETTINGS_AREAS.sessions, when: () => ctx.hasSessions !== false, groups: [
      { id: 'sessions', label: 'Sessions', summary: () => 'Save the current setup, switch between them', rows: [
        block('sessions', 'SessionsPanel', { label: 'Sessions', card: true, keywords: ['save session', 'restore', 'switch', 'MCP'] }),
      ] }] },
    { id: 'about', label: 'About', icon: 'info', areas: SETTINGS_AREAS.about, groups: [
      { id: 'versions', label: 'Versions', summary: c => `GAIFA v${c.system?.hub?.version || '0.1.0'}`, rows: [block('versions', 'Versions', { label: 'Versions', card: true, keywords: ['version', 'GAIFA'] })] },
      { id: 'cli', label: 'Command line', summary: () => 'gaifa status, start, logs, new, doctor', rows: [block('cli', 'CliList', { label: 'Command line', card: true, keywords: ['CLI', 'terminal', 'gaifa status'] })] },
      { id: 'doctor', label: 'Doctor', summary: () => 'The install checked, as gaifa doctor', rows: [block('doctor', 'DoctorPanel', { label: 'Doctor', card: true, keywords: ['checks', 'problems', 'gaifa doctor'] })] },
    ] },
  ];
  return secs.filter(s => !s.when || s.when(ctx));
}
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
const fb = b => { if (b == null || isNaN(b)) return '—'; const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0, v = b; while (v >= 1000 && i < 4) { v /= 1000; i++; } return (i === 0 ? v : v.toFixed(v >= 100 ? 0 : 1)) + ' ' + u[i]; };

// ---------- pure helpers ----------
/** Every row, flat, with its section and group ids and `ref` = 'section/group/row'. */
export function rowsOf(secs) {
  const out = [];
  for (const s of secs) for (const g of s.groups) for (const r of g.rows) out.push({ ...r, section: s.id, group: g.id, ref: `${s.id}/${g.id}/${r.id}` });
  return out;
}
/** The row at 'section/group/row', or null. */
export function rowAt(secs, ref) { return rowsOf(secs).find(r => r.ref === ref) || null; }
/** The row editing a Settings path (`memory.reserve_gb`), or null. */
export function rowFor(secs, path) { return rowsOf(secs).find(r => r.path === path) || null; }
/** A group's one-line summary for its closed state. */
export function summaryOf(group, ctx) { try { return group.summary ? group.summary(ctx) : ''; } catch { return ''; } }

/** The draft's problems: {path: message}, from each row's `validate`. Instant rows and blocks aren't in the draft. */
export function validateDraft(secs, draft) {
  const out = {};
  if (!draft) return out;
  for (const r of rowsOf(secs)) {
    if (!r.validate || r.instant || r.control === 'block') continue;
    const v = r.get(draft);
    if (v === undefined) continue;   // a section this hub doesn't send
    const m = r.validate(v, draft);
    if (m) out[r.path] = m;
  }
  return out;
}

const NUMERIC = ['hub.port', 'memory.reserve_gb'];
/** What Save sends: the keys that changed from `orig` (a whole section's value per key), numbers as numbers, never `ui`
 *  (its rows apply at once and save themselves), so a save never overwrites what another card saved meanwhile. */
export function saveBody(draft, orig = null, secs = null) {
  const d = JSON.parse(JSON.stringify(draft));
  delete d.ui;
  const nums = new Set([...NUMERIC, ...(secs ? rowsOf(secs).filter(r => r.control === 'number' && r.path).map(r => r.path) : [])]);
  for (const p of nums) { const v = getPath(d, p); if (v != null && String(v).trim() !== '' && !isNaN(Number(v))) setPath(d, p, Number(v)); }
  if (!orig) return d;
  const out = {};
  for (const [sec, vals] of Object.entries(d)) {
    if (!vals || typeof vals !== 'object') continue;
    for (const [k, v] of Object.entries(vals)) if (JSON.stringify(v) !== JSON.stringify(orig[sec]?.[k])) (out[sec] ||= {})[k] = v;
  }
  return out;
}
/** Whether the draft differs from what was loaded (the `ui` rows apply at once, so they never make it dirty). */
export function isDirty(orig, draft) {
  if (!orig || !draft) return false;
  const strip = x => { const y = { ...x }; delete y.ui; return JSON.stringify(y); };
  return strip(orig) !== strip(draft);
}
