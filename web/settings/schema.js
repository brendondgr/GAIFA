// The Settings page as data (plan settings-redesign 1.1, regrouped in 2.1): sections → groups → rows. A row is
// one `config.toml` key with its label, hint, control and keywords, or a `block` (anything that isn't a plain
// value: a chart, a table, a card from the agent). Pure: no React and no DOM, so the page (settings.js), the
// search (search.js) and the tests (utils/tests/web/settings-schema.test.mjs) all read the same list. Blocks
// are named here and drawn by blocks-hub.js / blocks-agent.js. Written by us (web/PATCHES.md).

import { checkCommandRule, checkToolGlob } from '../chat/chat-rules.js';
import { mergeValue, Conflict } from '../settings-merge.js';
import { uiPrefs } from '../ui-prefs.js';
import { repoSummary } from './repos-view.js';
import { enginesSummary, serversSummary } from './llm-view.js';

// Section → the api areas its data comes from: the "Mock data" note (GAIFA patch 5, PATCHES.md).
export const SETTINGS_AREAS = { general: ['settings', 'system'], machine: ['settings', 'memory', 'system'], services: ['settings', 'services', 'repos'], llms: ['services', 'llm'],
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
const AGENT_TABLES = new Set(['judge', 'screen', 'permissions', 'web', 'workflows']);
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
/** Settings → Agent → Model's sub-agent rows (`[agent.workflows]`, plan agent-workflows 3.6). `d`: the draft. */
export function subAgentRows(d) {
  const on = () => d.workflows?.enabled !== false, kw = ['sub-agents', 'agent tool', 'workflow'];
  return [
    field('wfOn', 'workflows.enabled', { label: 'Sub-agents', hint: 'A chat may start sub-agents (the agent tool) for independent parts of its task: each a chat of its own, nested under it in the list.', control: 'toggle', keywords: [...kw, 'parallel'] }),
    field('wfLocal', 'workflows.parallel_local', { label: 'Sub-agents at once on this machine', hint: 'On one GPU they only queue; more may not be faster.', control: 'number', min: 1, max: 16, width: 80, when: on, keywords: kw }),
    field('wfRemote', 'workflows.parallel_remote', { label: 'Sub-agents at once on remote and cloud models', control: 'number', min: 1, max: 32, width: 80, when: on, keywords: kw }),
    field('wfChildren', 'workflows.max_children', { label: 'Sub-agents per turn', hint: 'How many one turn of a chat may start.', control: 'number', min: 0, max: 64, width: 80, when: on, keywords: kw }),
    field('wfDepth', 'workflows.max_depth', { label: 'Sub-agent depth', hint: '1: a sub-agent can’t start sub-agents of its own.', control: 'number', min: 1, max: 3, width: 80, when: on, keywords: kw }),
    field('wfSteps', 'workflows.child_max_steps', { label: 'A sub-agent’s steps', control: 'number', min: 1, max: 200, width: 80, when: on, keywords: kw }),
    field('wfTokens', 'workflows.workflow_tokens', { label: 'Sub-agents’ tokens per turn', hint: 'Every sub-agent of one turn together; past it they are stopped.', control: 'number', min: 1000, max: 100000000, step: 10000, unit: 'tokens', width: 120, when: on, keywords: [...kw, 'budget'] }),
    field('wfWindow', 'workflows.min_window', { label: 'Sub-agents need a window of', hint: 'Models with a smaller context window don’t get the agent tool.', control: 'number', min: 0, max: 10000000, step: 1024, unit: 'tokens', width: 120, when: on, keywords: kw }),
  ];
}

const knownMods = ctx => (ctx.services || []).filter(s => !(s.manifest_errors || []).length);
/** Settings → Speech → Voice mode (plan voice-speech-model 3.2, 6.3): the engine of Chat's voice mode, and with the speech model, who answers. */
export const VOICE_SIZES = [{ value: 'q4_k_m', label: 'Q4_K_M (smaller, faster)' }, { value: 'q8_0', label: 'Q8_0 (closer to the original)' }];
/** Tools the speech model may be given (plan voice-speech-model 5.1): read-only ones, plus the web search. */
export const VOICE_TOOLS = [{ value: 'calendar_agenda', label: 'Calendar: your day' }, { value: 'calendar_search', label: 'Calendar: find' },
  { value: 'calendar_free', label: 'Calendar: free time' }, { value: 'web_search', label: 'Web search' }, { value: 'time_now', label: 'The time' }];
/** Push to talk's keys (plan voice-mute 2.2): `KeyboardEvent.code`s that type nothing in the page's shortcuts. */
export const PUSH_KEYS = [{ value: 'Space', label: 'Space' }, { value: 'Backquote', label: '` (backquote)' }, { value: 'F2', label: 'F2' },
  { value: 'F8', label: 'F8' }, { value: 'ControlRight', label: 'Right Ctrl' }];
export function voiceModeGroup(d, ctx) {
  const speech = () => d.voice_mode?.engine === 'speech', own = () => speech() && d.voice_mode?.answers === 'speech', has = c => !c.services || hasMod(c, 'voice');
  const kw = ['voice mode', 'speech to speech', 'LFM3', 'omni', 'local'];
  return { id: 'voiceMode', label: 'Voice mode', when: () => !ctx.services || hasMod(ctx, 'voice', 'stt', 'tts'),
    summary: () => (speech() ? `Speech model (LFM3-Omni-2B ${(VOICE_SIZES.find(s => s.value === d.voice_mode?.quant)?.label || 'Q4_K_M').split(' ')[0]}, ${d.voice_mode?.voice || 'female'} voice) · ${own() ? 'it answers itself' : 'the chat’s agent answers'}` : 'The chat’s model, read aloud'),
    rows: [
      field('vmEngine', 'voice_mode.engine', { label: 'Voice mode uses', control: 'segmented', keywords: kw,
        hint: 'Chat model: your words are written down, the chat’s model answers, and the answer is read aloud. Speech model: a small model on this machine hears you and speaks; who answers is the next choice.',
        choices: c => [{ value: 'chat', label: 'Chat model, read aloud' },
          { value: 'speech', label: 'Speech model (local)', disabled: !has(c) && d.voice_mode?.engine !== 'speech', title: has(c) ? undefined : 'Install the Voice mod: gaifa setup voice' }] }),
      field('vmAnswers', 'voice_mode.answers', { label: 'Who answers', control: 'segmented', when: speech, keywords: [...kw, 'agent', 'harness', 'tools', 'apps', 'talk to the speech model'],
        hint: 'The chat’s agent: what you say is sent to the chat as a message, so the chat’s own model answers with its tools, apps, memory and cards, exactly as when you type, and the speech model says each step. The speech model itself: it answers on its own in a fraction of a second, without the chat’s model. The voice bar has the same switch.',
        choices: [{ value: 'agent', label: 'The chat’s agent' }, { value: 'speech', label: 'The speech model itself' }] }),
      field('vmQuant', 'voice_mode.quant', { label: 'Size', hint: 'Both are compared in docs/voice-eval.md.', control: 'segmented', choices: VOICE_SIZES, when: speech, keywords: [...kw, 'quant', 'Q4', 'Q8'] }),
      field('vmVoice', 'voice_mode.voice', { label: 'Voice', hint: 'The speech model has two voices; the voices above are for reading replies aloud.', control: 'segmented',
        choices: [{ value: 'female', label: 'Female' }, { value: 'male', label: 'Male' }], when: speech, keywords: kw }),
      field('vmTools', 'voice_mode.tools', { label: 'Tools it may use', control: 'chips', choices: VOICE_TOOLS, when: own, keywords: [...kw, 'tools', 'calendar', 'web search'],
        hint: 'Off by default. A call runs only when this chat’s permissions allow it without asking; anything that would show a card is refused, and it says so. It is a small model: it won’t always call the right tool.' }),
      field('vmAskChat', 'voice_mode.ask_chat', { label: 'Let it ask the chat’s model', control: 'toggle', when: own, keywords: [...kw, 'hand off', 'ask chat'],
        hint: 'For questions it can’t answer itself (a file, a long task), it sends your words to the chat’s own model and tells you the answer. That turn runs like a typed message, with its tools and cards.' }),
      field('vmTalk', 'voice_mode.talk', { label: 'Microphone', control: 'segmented', keywords: [...kw, 'push to talk', 'hold to talk', 'walkie', 'microphone', 'background noise'],
        hint: 'Always listening: it hears you whenever you talk and finds the end of your turn by the pause. Push to talk: it hears you only while you hold the key below or the bar’s Hold to talk button, and letting go sends what you said at once, so noise in the room can’t start a turn or stop a reply. The voice bar has the same switch.',
        choices: [{ value: 'open', label: 'Always listening' }, { value: 'push', label: 'Push to talk' }] }),
      field('vmPushKey', 'voice_mode.push_key', { label: 'Key', control: 'select', choices: PUSH_KEYS, when: () => d.voice_mode?.talk === 'push', keywords: [...kw, 'push to talk', 'key', 'shortcut'],
        hint: 'Hold it to talk while voice mode is on. It does nothing while you are typing in a text field (Space types a space there).' }),
      field('vmInterrupt', 'voice_mode.interrupt', { label: 'Talking over it', control: 'segmented', when: () => d.voice_mode?.talk !== 'push', keywords: [...kw, 'interrupt', 'barge in', 'background noise'],
        hint: 'Your voice stops a reply: the speech model listens for a voice, so a fan, a keyboard or music don’t (a TV can). When the chat’s agent answers and what interrupted held no words, the answer goes on from the sentence it stopped in. Off: only Stop, Mute and Esc end a reply. The chat-model loop goes by loudness.',
        choices: [{ value: 'speech', label: 'Your voice stops it' }, { value: 'off', label: 'Off' }] }),
      field('vmStartMuted', 'voice_mode.start_muted', { label: 'Start muted', control: 'toggle', when: () => d.voice_mode?.talk !== 'push', keywords: [...kw, 'mute', 'microphone', 'background noise'],
        hint: 'Voice mode starts with the microphone muted: nothing is heard until you unmute with the bar’s microphone button or M. Muted, noise in the room can’t start a turn or stop a reply.' }),
      block('vmStatus', 'VoiceModelStatus', { label: 'The speech model', when: speech, keywords: kw }),
    ] };
}
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
        field('port', 'hub.port', { label: 'GAIFA port', hint: 'On 127.0.0.1 for this machine; other devices only when you open it to your network (Network, below). Default 7000.', control: 'number', inputMode: 'numeric',
          restart: true, validate: checkPort, keywords: ['address', 'listen', 'localhost', '127.0.0.1'] }),
        block('overrides', 'OverridesCard', { label: 'Set on this machine', card: true, keywords: ['config.toml', 'overrides', 'changed', 'differs from the defaults', 'TOML'] }),
        block('process', 'ProcessCard', { label: 'GAIFA process', card: true, keywords: ['version', 'pid', 'uptime', 'rss'] }),
      ] },
      { id: 'network', label: 'Network', summary: () => 'Other devices on your network: off unless you open it', rows: [
        block('lan', 'NetworkCard', { label: 'Other devices on your network', card: true,
          keywords: ['network', 'LAN', 'wifi', 'phone', 'other devices', 'remote', 'access', 'password', 'sign in', 'firewall', '0.0.0.0', 'tailscale'] }),
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
      ] },
      // plan mod-repos 3.5: relay, lcpp, tts and gen3d are their own repositories (git submodules)
      { id: 'repositories', label: 'Repositories', summary: () => repoSummary(ctx.repos), rows: [
        block('repos', 'RepositoriesTable', { label: 'Mods with their own repository', card: true,
          keywords: ['git', 'submodule', 'GitHub', 'update', 'pin', 'relay', 'lcpp', 'tts', 'gen3d', 'gaifa repos'] }),
        field('reposFetch', 'repos.fetch_every_h', { label: 'Check GitHub every', hint: 'How often GAIFA asks GitHub what’s new in them. 0: never (Check now still does).',
          control: 'number', min: 0, max: 720, unit: 'hours', width: 90, keywords: ['fetch', 'network', 'updates'] }),
        field('reposNotify', 'repos.notify', { label: 'Alerts', hint: 'Warnings: changed files, unpushed commits and the like. All: new commits too.', control: 'select',
          choices: [{ value: 'warnings', label: 'Warnings' }, { value: 'all', label: 'All, updates too' }, { value: 'off', label: 'Off' }], keywords: ['notify', 'warnings'] }),
        field('reposStart', 'repos.check_on_start', { label: 'Check when GAIFA starts', hint: 'Reads their state from git on this machine (no network).', control: 'toggle' }),
      ] }] },
    // plan llm-servers 4.1: every language-model server in one place (the relay's endpoints, the [llm] engines)
    { id: 'llms', label: 'LLMs', icon: 'cpu', areas: SETTINGS_AREAS.llms, when: () => !ctx.services || hasMod(ctx, 'relay'), groups: [
      { id: 'servers', label: 'Servers', summary: () => serversSummary(ctx.llm?.endpoints), rows: [
        block('servers', 'LlmServers', { label: 'The relay’s servers', card: true,
          keywords: ['relay', 'endpoint', 'Claude', 'Anthropic', 'OpenAI', 'ChatGPT', 'Gemini', 'API key', 'key', 'cloud', 'models', 'hide', 'skynet', 'tunnel'] }),
      ] },
      { id: 'add', label: 'Add a server', summary: () => 'Anthropic, OpenAI, Gemini or any OpenAI-compatible URL', rows: [
        block('add', 'AddLlmServer', { label: 'Add a server', card: true, keywords: ['add', 'provider', 'API key', 'Claude', 'OpenAI', 'Gemini', 'vLLM', 'llama.cpp', 'Ollama', 'URL'] }),
      ] },
      { id: 'engines', label: 'On this machine', summary: () => enginesSummary(ctx.llm?.engines), rows: [
        block('engines', 'LlmEngines', { label: 'Local engines', card: true, keywords: ['llama.cpp', 'lcpp', 'vLLM', 'load', 'unload', 'GGUF', 'engine', 'local models'] }),
      ] },
      { id: 'defaults', label: 'Defaults', summary: () => 'The chat model and its fallback', when: () => agentOn, rows: [
        block('defaults', 'LlmDefaults', { label: 'Chat model and fallback', card: true, keywords: ['default model', 'chat model', 'fallback', 'AGENT_MODEL'] }),
      ] }] },
    { id: 'agent', label: 'Agent', icon: 'chat', areas: SETTINGS_AREAS.agent, when: () => agentOn, groups: [
      { id: 'model', label: 'Model', summary: () => 'The chat model, fallback and steps (the agent’s own settings)', rows: [
        block('notes', 'AgentNotes', { label: 'The agent' }),
        block('models', 'ModelsCard', { label: 'Models', keywords: ['chat model', 'fallback', 'max steps', 'relay'] }),
        instant('steps', 'ui.chat.steps', { label: 'Steps between messages', hint: 'One fold per turn ("Ran 2 tools"), or each thing the agent says between steps as a message of its own, with a fold for the steps before it. Applied immediately, in every browser.',
          control: 'segmented', choices: [{ value: 'fold', label: 'One fold per turn' }, { value: 'split', label: 'Split at each message' }],
          read: () => uiPrefs.get('chat.steps', 'fold'), apply: (c, v) => uiPrefs.set('chat.steps', v), keywords: ['split at each message', 'one fold per turn', 'layout', 'activity fold'] }),   // settings-that-stick 3.3
        block('llms', 'LlmLink', { label: 'Servers and keys', keywords: ['servers', 'API key', 'cloud'] }),   // llm-servers 4.1
        ...subAgentRows(d),          // agent-workflows 3.6: in this group (a section has at most 7)
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
      { id: 'memory', label: 'Memory', summary: () => 'What the agent knows, recall and fading', rows: [block('memory', 'MemoryCard', { label: 'Memory', card: true, keywords: ['remember', 'recall', 'facts', 'projects', 'fade'] })] },
      { id: 'skills', label: 'Skills', summary: () => 'Loaded when needed; each is a slash command', rows: [block('skills', 'SkillsCard', { label: 'Skills', card: true, keywords: ['slash commands', 'SKILL.md'] })] },
      { id: 'learning', label: 'Learning', summary: () => `Learn from chats ${onOff(d.learning?.enabled)} · nightly at ${d.learning?.nightly_at || '—'}`, rows: [
        field('learn', 'learning.enabled', { label: 'Learn from chats', hint: 'Card edits, answers and thumbs become preferences that fill your cards; each chat can turn it off in its header.', control: 'toggle', keywords: ['preferences', 'learner'] }),
        field('inferAfter', 'learning.infer_after', { label: 'Propose after', hint: 'An inferred preference is proposed once you chose it this many times, in as many chats.', control: 'number', min: 1, max: 100, width: 80 }),
        field('fadeDays', 'learning.fade_days', { label: 'Fade after', hint: 'Inferred preferences unused this long are retired; ones you stated never fade.', control: 'number', min: 1, max: 3650, unit: 'days', width: 90 }),
        field('nightly', 'learning.nightly_at', { label: 'Nightly run', hint: 'When the learner improves its instructions, plus after an hour without a chat.', control: 'time', keywords: ['schedule', 'harness'] }),
        block('learningPage', 'LearningLink', { label: 'The Learning page', keywords: ['preferences', 'review'] }),
      ] }] },
    { id: 'permissions', label: 'Permissions', icon: 'shield', areas: SETTINGS_AREAS.permissions, when: () => agentOn, groups: [
      { id: 'modes', label: 'Modes', summary: () => 'Plan · Manual · Accept edits · Auto · Bypass', rows: [block('modes', 'ModesCard', { label: 'Modes', keywords: ['plan', 'manual', 'accept edits', 'auto', 'bypass'] })] },
      { id: 'rules', label: 'Tool rules', summary: () => { const p = d.permissions || {}; return `${(p.deny || []).length} never · ${(p.ask || []).length} ask · ${(p.allow || []).length} allow`; }, rows: [
        field('deny', 'permissions.deny', { label: 'Never run', hint: 'Tool names or globs (comfy_*). Never run wins over everything.', control: 'list', check: checkToolGlob, placeholder: 'tts_delete_voice', keywords: ['deny', 'block'] }),
        field('ask', 'permissions.ask', { label: 'Always ask', hint: 'Asks in every mode unless you granted the tool.', control: 'list', check: checkToolGlob, placeholder: 'hub_set_preference' }),
        field('allow', 'permissions.allow', { label: 'Run without asking', hint: 'Never skips the card of a tool that runs code.', control: 'list', check: checkToolGlob, placeholder: 'hub_start_service' }),
      ] },
      { id: 'grants', label: 'Grants', summary: () => 'What you allowed in a chat or always', rows: [block('grants', 'GrantsList', { label: 'Grants', keywords: ['always allow', 'revoke'] })] },
      { id: 'judge', label: 'Auto judge', summary: () => { const j = d.judge || {}; return `${j.model || '—'} (decision model) · ${n((j.allow_commands || []).length + (j.ask_commands || []).length, 'command rule')}`; }, rows: [
        block('judgeModel', 'JudgeModelBlock', { label: 'Judge model', keys: ['judge.backend', 'judge.model', 'judge.url'], keywords: ['decide', 'decision model', 'd3-lite', 'auto mode'] }),
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
    { id: 'speech', label: 'Speech', icon: 'mic', areas: SETTINGS_AREAS.speech, when: () => !ctx.services || hasMod(ctx, 'stt', 'tts', 'voice'), groups: [
      { id: 'dictation', label: 'Dictation', when: () => !ctx.services || hasMod(ctx, 'stt'), summary: () => `${d.speech_input?.preset || 'balanced'} · ${n((d.speech_input?.mics || []).length, 'microphone')} ranked`, rows: [
        block('mics', 'MicsBlock', { label: 'Microphones', keys: ['speech_input.mics'], keywords: ['microphone', 'dictation', 'stt', 'level'] }),
        field('language', 'speech_input.language', { label: 'Language', hint: 'An ISO code such as en or de; empty detects it.', control: 'text', placeholder: 'detect', maxLength: 3, width: 90,
          validate: v => (/^([a-z]{2,3})?$/.test(String(v ?? '')) ? null : 'Two or three lowercase letters, or empty'), keywords: ['whisper'] }),
        field('preset', 'speech_input.preset', { label: 'Model', hint: 'Balanced (small) keeps up live; Accurate is slower to commit.', control: 'select',
          choices: [{ value: 'fast', label: 'Fast' }, { value: 'balanced', label: 'Balanced (default)' }, { value: 'accurate', label: 'Accurate' }, { value: 'best', label: 'Best' }], keywords: ['stt', 'whisper'] }),
        field('mode', 'speech_input.mode', { label: 'The microphone button', control: 'segmented',
          choices: [{ value: 'both', label: 'Click or hold' }, { value: 'toggle', label: 'Click' }, { value: 'hold', label: 'Hold' }], keywords: ['push to talk'] }),
      ] },
      { id: 'voice', label: 'Voice', when: () => !ctx.services || hasMod(ctx, 'tts'), summary: () => `${d.speech_output?.voice || 'the default voice'} · read every reply ${onOff(d.speech_output?.auto_read)}`, rows: [
        field('voice', 'speech_output.voice', { label: 'Read replies in', hint: 'The voice under each reply’s speaker, and voice mode’s answers.', control: 'select',
          choices: c => c.voiceChoices || [{ value: '', label: 'The speech mod’s default' }], keywords: ['read aloud', 'tts', 'kokoro'] }),
        field('speed', 'speech_output.speed', { label: 'Speed', hint: 'Built-in (Kokoro) voices only.', control: 'number', min: 0.5, max: 2, step: 0.1, width: 80 }),
        field('autoRead', 'speech_output.auto_read', { label: 'Read every reply aloud', hint: 'When a reply is finished. With a model on this GPU it waits for the reply to end.', control: 'toggle' }),
        field('pause', 'speech_output.pause_ms', { label: 'Voice mode: end of what you said', hint: 'The quiet that sends your message.', control: 'segmented',
          choices: [800, 1200, 1600, 2400].map(ms => ({ value: ms, label: ms / 1000 + ' s' })), keywords: ['voice mode', 'silence'] }),
      ] },
      voiceModeGroup(d, ctx)] },
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
  return secs.filter(s => !s.when || s.when(ctx)).map(s => ({ ...s, groups: s.groups.filter(g => !g.when || g.when(ctx)) }));
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

// ---------- settings-that-stick 2.3: another page or tab saved ----------
const sameJ = (a, b) => JSON.stringify(a) === JSON.stringify(b);
/** Fresh settings into an open page: a key the user hasn't touched takes the saved value (in `orig` and the draft). A
 *  touched list or table merges both sides' changes into the draft (as the hub would on Save). A touched plain value
 *  saved differently elsewhere keeps the draft and its old `orig`, and is listed in `elsewhere` (dotted key → the saved
 *  value) for Use theirs / Keep mine. `ui` applies at once, so it simply takes the saved values. */
export function mergeReload(orig, draft, fresh, elsewhere = {}) {
  const o = JSON.parse(JSON.stringify(orig)), d = JSON.parse(JSON.stringify(draft)), el = { ...elsewhere };
  for (const [sec, vals] of Object.entries(fresh || {})) {
    if (sec === 'ui') { o.ui = JSON.parse(JSON.stringify(vals)); d.ui = JSON.parse(JSON.stringify(vals)); continue; }   // applied at once: just the saved values
    if (!vals || typeof vals !== 'object') continue;
    o[sec] ||= {}; d[sec] ||= {};
    for (const [k, f] of Object.entries(vals)) {
      const was = o[sec][k], mine = d[sec][k], key = `${sec}.${k}`;
      if (sameJ(mine, was)) { o[sec][k] = f; d[sec][k] = JSON.parse(JSON.stringify(f)); delete el[key]; }
      else if (sameJ(f, mine)) { o[sec][k] = f; delete el[key]; }
      else if (!sameJ(f, was)) {
        try { d[sec][k] = mergeValue(key, f, was, mine); o[sec][k] = f; delete el[key]; } catch (e) { if (!(e instanceof Conflict)) throw e; el[key] = f; }
      }
    }
  }
  return { orig: o, draft: d, elsewhere: el };
}
/** Resolve one key changed elsewhere: `theirs` takes the saved value; `mine` keeps the draft and saves over it. */
export function resolveElsewhere(st, key, pick) {
  const [sec, k] = key.split('.'), f = st.elsewhere[key], el = { ...st.elsewhere };
  delete el[key];
  const orig = { ...st.orig, [sec]: { ...st.orig[sec], [k]: f } };
  const draft = pick === 'theirs' ? { ...st.draft, [sec]: { ...st.draft[sec], [k]: JSON.parse(JSON.stringify(f)) } } : st.draft;
  return { orig, draft, elsewhere: el };
}

// ---------- 4.2: defaults, changes ----------
const norm = (row, v) => {
  if (v == null) return null;
  if (row.control === 'number' && String(v).trim() !== '' && !isNaN(Number(v))) return Number(v);
  if (row.control === 'chips' && Array.isArray(v)) return [...v].sort();   // a set: the order doesn't matter
  return v;   // order and list rows keep their order
};
/** Whether a row's value equals another (numbers as numbers, chips as sets, lists and orders in order). */
export function sameValue(row, a, b) { return JSON.stringify(norm(row, a)) === JSON.stringify(norm(row, b)); }

/** The rows whose value differs from the default: [{ref, section, group, row, path, key, value, default}]. Instant rows
 *  read `ctx` (theme, density, the sidebar); blocks have no single value and are left out. */
export function changedRows(secs, draft, defaults, ctx = {}) {
  if (!draft || !defaults) return [];
  const out = [];
  for (const r of rowsOf(secs)) {
    if (r.control === 'block' || !r.path || (r.when && !r.when(ctx))) continue;
    const def = getPath(defaults, r.path);
    if (def === undefined) continue;
    const value = r.instant && r.read ? r.read(ctx) : r.get(draft);
    if (value === undefined || sameValue(r, value, def)) continue;
    out.push({ ref: r.ref, section: r.section, group: r.group, row: r.id, path: r.path, key: r.key, value, default: def });
  }
  return out;
}
/** `changedRows` counted per section and group, in the shape `matches` gives (the list's counts, the Changed filter). */
export function changedMatch(changed) {
  const m = { rows: [], perSection: {}, perGroup: {}, ids: new Set(), query: '' };
  for (const c of changed) {
    m.rows.push({ id: c.ref, section: c.section, group: c.group, kind: 'row' }); m.ids.add(c.ref);
    m.perSection[c.section] = (m.perSection[c.section] || 0) + 1;
    const g = `${c.section}/${c.group}`; m.perGroup[g] = (m.perGroup[g] || 0) + 1;
  }
  return m;
}
/** A value as the Reset link and the overrides say it: a choice's label, on/off, a list joined, "none". */
export function showValue(row, v) {
  if (v == null || v === '') return row?.control === 'list' || row?.control === 'chips' ? 'none' : '—';
  if (typeof v === 'boolean') return v ? 'on' : 'off';
  const ch = Array.isArray(row?.choices) ? row.choices : null;
  if (Array.isArray(v)) return v.length ? v.map(x => ch?.find(c => c.value === x)?.label || x).join(', ') : 'none';
  const c = ch?.find(x => x.value === v);
  return c ? c.label : String(v) + (row?.unit && row.control === 'number' ? ' ' + row.unit : '');
}

// ---------- 5.1: what this machine sets ----------
const tomlValue = v => (typeof v === 'string' ? JSON.stringify(v) : Array.isArray(v) ? '[' + v.map(tomlValue).join(', ') + ']' : typeof v === 'boolean' || typeof v === 'number' ? String(v) : JSON.stringify(v));
/** `changedRows` (over what is saved) as config.toml text: one [table] per key's table, in order, `key = value`. */
export function overrideLines(changed) {
  const tables = new Map();
  for (const c of changed) {
    if (!c.key) continue;
    const ks = String(c.key).split('.'), name = ks.pop(), table = ks.join('.');
    if (!tables.has(table)) tables.set(table, []);
    tables.get(table).push(`${name} = ${tomlValue(c.value)}`);
  }
  return [...tables].map(([table, lines]) => `[${table}]\n${lines.join('\n')}`).join('\n\n') + (tables.size ? '\n' : '');
}
