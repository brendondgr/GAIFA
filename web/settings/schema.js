// The Settings page as data (plan settings-redesign 1.1): sections → groups → rows. A row is one
// `config.toml` key with its label, hint, control and keywords, or a `block` (anything that isn't a
// plain value: a chart, a table, a card from the agent). Pure: no React and no DOM, so the page
// (settings.js), the search (search.js) and the tests (utils/tests/web/settings-schema.test.mjs)
// all read the same list. Blocks are named here and drawn by blocks-hub.js / blocks-agent.js.
// Written by us (web/PATCHES.md).

// Section → the api areas its data comes from: the "Mock data" note (GAIFA patch 5, PATCHES.md).
export const SETTINGS_AREAS = { general: ['settings', 'system'], paths: ['system'], memory: ['settings', 'memory'], services: ['settings', 'services'],
  interface: ['settings'], agent: [], sessions: ['sessions'], about: ['services', 'system'] };

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

/** A row bound to one Settings path: reads and writes the page draft. */
export function field(id, path, o = {}) {
  return { id, path, key: o.key === undefined ? configKey(path) : o.key, keywords: [], get: d => getPath(d, path), set: (d, v) => setPath(d, path, v), ...o };
}
/** A row whose value applies at once outside the draft (theme, density, the sidebar): `read(ctx)`, `apply(ctx, v)`. */
export function instant(id, path, o = {}) {
  return { ...field(id, path, o), instant: true };
}
/** A block: drawn by the component named `block`, from blocks-hub.js or blocks-agent.js. */
export function block(id, name, o = {}) { return { id, control: 'block', block: name, key: null, keywords: [], ...o }; }

const knownMods = ctx => (ctx.services || []).filter(s => !(s.manifest_errors || []).length);
const isNum = v => String(v ?? '').trim() !== '' && !isNaN(Number(v));

// ---------- validation (the rules vmSettings had) ----------
export const PORT_MSG = 'Use a port between 1024 and 65535';
export const RESERVE_MSG = 'Between 0 and 64 GB';
const checkPort = v => (!/^\d+$/.test(String(v)) || Number(v) < 1024 || Number(v) > 65535 ? PORT_MSG : null);
const checkReserve = v => (isNum(v) && Number(v) >= 0 && Number(v) <= 64 ? null : RESERVE_MSG);

// ---------- the sections ----------
/** Every section, group and row. `ctx` carries what choices depend on (`services`); nothing here fetches. */
export function sections(ctx = {}) {
  const mods = knownMods(ctx);
  const svcName = id => (ctx.services || []).find(s => s.id === id)?.name || id;
  return [
    { id: 'general', label: 'General', icon: 'gear', areas: SETTINGS_AREAS.general, groups: [
      { id: 'hub', label: 'Hub', rows: [
        field('port', 'hub.port', { label: 'GAIFA port', hint: 'Bound to 127.0.0.1 — this machine only. Default 7000.', control: 'number', inputMode: 'numeric',
          restart: true, validate: checkPort, keywords: ['address', 'listen', 'localhost', '127.0.0.1'] }),
        block('process', 'ProcessCard', { label: 'GAIFA process', card: true, keywords: ['version', 'pid', 'uptime', 'rss'] }),
      ] }] },
    { id: 'paths', label: 'Paths', icon: 'folder', areas: SETTINGS_AREAS.paths, groups: [
      { id: 'paths', label: 'Paths', rows: [
        block('folders', 'PathsList', { label: 'Folders', keywords: ['disk', 'storage', 'models', 'databases', 'outputs', 'logs', 'state', 'root'] }),
      ] }] },
    { id: 'memory', label: 'Memory', icon: 'chart', areas: SETTINGS_AREAS.memory, groups: [
      { id: 'memory', label: 'Memory', rows: [
        block('history', 'MemoryHistory', { label: 'Last 24 hours', keywords: ['chart', 'usage'] }),
        field('reserve', 'memory.reserve_gb', { label: 'Reserve', hint: 'GB of unified memory GAIFA always keeps free for the OS and desktop.', control: 'number',
          min: 0, max: 64, unit: 'GB', validate: checkReserve, keywords: ['RAM', 'unified', 'free memory', 'headroom'] }),
        field('auto', 'memory.auto_make_room', { label: 'Automatically make room when a service needs memory', hint: 'When off, GAIFA shows you the plan and asks first.',
          control: 'toggle', aria: 'Automatically make room', keywords: ['unload', 'make room'] }),
        field('never', 'memory.never_unload', { label: 'Never auto-unload', hint: 'These services are never part of a make-room plan.', control: 'chips',
          choices: mods.map(s => ({ value: s.id, label: s.name })), keywords: ['pin', 'keep loaded'] }),
        field('priority', 'memory.priority', { label: 'Unload order', hint: 'Top of the list is unloaded first.', control: 'order',
          items: d => (getPath(d, 'memory.priority') || []).filter(id => mods.some(s => s.id === id)).map(id => ({ id, label: svcName(id), note: (d.memory?.never_unload || []).includes(id) ? 'never unloaded' : '' })),
          keywords: ['priority', 'unload first'] }),
      ] }] },
    { id: 'services', label: 'Services', icon: 'puzzle', areas: SETTINGS_AREAS.services, groups: [
      { id: 'services', label: 'Services', rows: [
        block('table', 'ServicesTable', { label: 'Folders in services/', keys: ['services.order', 'services.enabled', 'services.autostart'], card: true,
          keywords: ['mods', 'enabled', 'autostart', 'order', 'sidebar'] }),
        block('add', 'AddModCard', { label: 'Add a mod', card: true, keywords: ['new mod', 'template', 'gaifa new'] }),
      ] }] },
    { id: 'interface', label: 'Interface', icon: 'sliders', areas: SETTINGS_AREAS.interface, groups: [
      { id: 'interface', label: 'Interface', rows: [
        instant('theme', 'ui.theme', { label: 'Theme', hint: 'System follows your OS setting. Applied immediately.', control: 'segmented',
          choices: [{ value: 'system', label: 'System' }, { value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }],
          read: c => c.theme, apply: (c, v) => c.setTheme?.(v), keywords: ['dark mode', 'light mode', 'colors'] }),
        instant('density', 'ui.density', { label: 'Density', hint: 'Compact tightens tables.', control: 'segmented',
          choices: [{ value: 'comfortable', label: 'Comfortable' }, { value: 'compact', label: 'Compact' }],
          read: c => c.density, apply: (c, v) => c.setDensity?.(v), keywords: ['compact', 'spacing'] }),
      ] }] },
    { id: 'agent', label: 'Agent', icon: 'chat', areas: SETTINGS_AREAS.agent, groups: [
      { id: 'agent', label: 'Agent', rows: [
        block('notes', 'AgentNotes', { label: 'The agent', card: true }),
        block('models', 'ModelsCard', { label: 'Models', card: true, keywords: ['chat model', 'fallback', 'max steps', 'relay'] }),
        block('documents', 'DocumentsCard', { label: 'Documents', card: true, keywords: ['whole documents', 'reply reserve', 'tokens'] }),
        block('web', 'WebReadingSection', { label: 'Reading web pages', card: true, keywords: ['screening', 'relevance', 'saved web pages', 'web_fetch'] }),
        block('instructions', 'InstructionsCard', { label: 'Instructions', card: true, keywords: ['AGENT.md', 'standing instructions'] }),
        block('memory', 'MemoryCard', { label: 'Memory', card: true, keywords: ['MEMORY.md', 'remember', 'topics'] }),
        block('skills', 'SkillsCard', { label: 'Skills', card: true, keywords: ['slash commands', 'SKILL.md'] }),
        block('learning', 'LearningSection', { label: 'Learning', card: true, keywords: ['preferences', 'nightly', 'learner'] }),
        block('dictation', 'SpeechInputSection', { label: 'Speech input', card: true, keywords: ['microphone', 'dictation', 'stt', 'whisper'] }),
        block('voice', 'SpeechOutputSection', { label: 'Voice', card: true, keywords: ['read aloud', 'tts', 'voice mode'] }),
        block('permissions', 'PermissionsCard', { label: 'Permissions', card: true, keywords: ['modes', 'tool rules', 'grants', 'judge', 'auto', 'approvals'] }),
      ] }] },
    { id: 'sessions', label: 'Sessions', icon: 'refresh', areas: SETTINGS_AREAS.sessions, groups: [
      { id: 'sessions', label: 'Sessions', rows: [
        block('sessions', 'SessionsPanel', { label: 'Sessions', card: true, keywords: ['save session', 'restore', 'switch', 'MCP'] }),
      ] }] },
    { id: 'about', label: 'About', icon: 'info', areas: SETTINGS_AREAS.about, groups: [
      { id: 'about', label: 'About', rows: [
        block('versions', 'Versions', { label: 'Versions', card: true, keywords: ['version', 'GAIFA'] }),
        block('hardware', 'HardwareCard', { label: 'Hardware', card: true, keywords: ['GPU', 'VRAM', 'CPU', 'accelerator', 'ROCm', 'CUDA'] }),
        block('doctor', 'DoctorPanel', { label: 'Doctor', card: true, keywords: ['checks', 'problems', 'gaifa doctor'] }),
        block('cli', 'CliList', { label: 'Command line', card: true, keywords: ['CLI', 'terminal', 'gaifa status'] }),
      ] }] },
  ];
}

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

/** The draft's problems: {path: message}, from each row's `validate`. Instant rows and blocks aren't in the draft. */
export function validateDraft(secs, draft) {
  const out = {};
  if (!draft) return out;
  for (const r of rowsOf(secs)) {
    if (!r.validate || r.instant || r.control === 'block') continue;
    const m = r.validate(r.get(draft), draft);
    if (m) out[r.path] = m;
  }
  return out;
}

/** What Save sends: the draft with numbers as numbers and without `ui` (its rows apply at once and save themselves). */
export function saveBody(draft) {
  const d = JSON.parse(JSON.stringify(draft));
  delete d.ui;
  if (d.hub) d.hub.port = Number(d.hub.port);
  if (d.memory) d.memory.reserve_gb = Number(d.memory.reserve_gb);
  return d;
}
/** Whether the draft differs from what was loaded (the `ui` rows apply at once, so they never make it dirty). */
export function isDirty(orig, draft) {
  if (!orig || !draft) return false;
  const strip = x => { const y = { ...x }; delete y.ui; return JSON.stringify(y); };
  return strip(orig) !== strip(draft);
}
