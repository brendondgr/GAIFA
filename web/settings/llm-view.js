// Settings → LLMs, the pure parts (plan llm-servers 4.1; tested in utils/tests/web/settings-llm.test.mjs):
// the relay's endpoints grouped by where they run, a key's state, what "Add a server" sends, the engines'
// rows, and the section's summaries. The data: the relay's GET /admin/endpoints (through the hub's proxy),
// its GET /admin/endpoints/{id}/models, and the hub's GET /api/llm/engines. Written by us.

export const GROUPS = [
  { id: 'local', label: 'On this machine', hint: 'llama.cpp, vLLM and other servers on 127.0.0.1' },
  { id: 'remote', label: 'Remote', hint: 'Servers on other machines, directly or through an SSH tunnel' },
  { id: 'cloud', label: 'Cloud', hint: 'Paid providers: for chats only' },
  { id: 'agent', label: 'Agents', hint: 'Agent servers such as OpenCode (their own keys)' },
];

export const PRESETS = [
  { id: 'anthropic', label: 'Anthropic (Claude)', keyHint: 'sk-ant-…', alias: 'claude' },
  { id: 'openai', label: 'OpenAI', keyHint: 'sk-…', alias: 'openai' },
  { id: 'gemini', label: 'Google Gemini', keyHint: 'AIza…', alias: 'gemini' },
  { id: 'url', label: 'Any OpenAI-compatible server (URL)', keyHint: 'optional', alias: '' },
];

/** Where an endpoint runs (the relay's catalog group). */
export function groupOf(ep) {
  if ((ep.protocol || 'openai') === 'opencode') return 'agent';
  if (ep.kind === 'cloud') return 'cloud';
  return ep.kind === 'local' ? 'local' : 'remote';
}

/** Endpoints by group, in GROUPS order, empty groups left out. */
export function grouped(endpoints) {
  return GROUPS.map(g => ({ ...g, items: (endpoints || []).filter(e => groupOf(e) === g.id) })).filter(g => g.items.length);
}

/** A key's state for the card: `{tone, text}`. */
export function keyState(ep) {
  if (ep.has_key) return { tone: 'green', text: `key ${ep.key_hint || 'set'}` };
  if (groupOf(ep) === 'cloud') return { tone: 'red', text: 'no key' };
  return { tone: 'dim', text: 'no key needed' };
}

/** The health badge. */
export function healthState(ep) {
  return { healthy: { tone: 'green', text: 'healthy' }, degraded: { tone: 'accent', text: 'degraded' }, failed: { tone: 'red', text: 'failing' } }[ep.health]
    || { tone: 'dim', text: ep.enabled === false ? 'off' : 'not checked yet' };
}

/** What "Add a server" sends to POST /admin/endpoints, or an error to show. */
export function addBody(form) {
  const f = form || {};
  const name = (f.name || '').trim();
  const key = (f.key || '').trim();
  if (f.preset === 'url') {
    const url = (f.url || '').trim();
    if (!/^https?:\/\/\S+$/.test(url)) return { error: 'An http:// or https:// URL, e.g. http://10.0.0.4:8000/v1' };
    const alias = (f.alias || '').trim() || null;
    if (alias && !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(alias)) return { error: 'The short name: letters, digits, . _ - (no spaces or /)' };
    return { body: { name: name || url.replace(/^https?:\/\//, ''), base_url: url, alias, list_models: true, ...(key ? { upstream_key: key } : {}) } };
  }
  const p = PRESETS.find(x => x.id === f.preset);
  if (!p) return { error: 'Pick a provider' };
  if (!key) return { error: `${p.label} needs an API key` };
  return { body: { name: name || p.label, preset: p.id, upstream_key: key, ...((f.alias || '').trim() ? { alias: f.alias.trim() } : {}) } };
}

/** "3 servers · 1 cloud · 2 failing". */
export function serversSummary(endpoints) {
  if (!endpoints) return 'The relay’s servers';
  const n = endpoints.length, cloud = endpoints.filter(e => groupOf(e) === 'cloud').length, bad = endpoints.filter(e => e.health === 'failed').length;
  return [`${n} server${n === 1 ? '' : 's'}`, cloud ? `${cloud} cloud` : '', bad ? `${bad} failing` : ''].filter(Boolean).join(' · ');
}

/** "2 engines · 1 model loaded". */
export function enginesSummary(engines) {
  if (!engines) return 'llama.cpp, vLLM';
  if (!engines.length) return 'No engine mods';
  const loaded = engines.reduce((n, e) => n + (e.models || []).filter(m => m.loaded).length, 0);
  return `${engines.length} engine${engines.length === 1 ? '' : 's'} · ${loaded} model${loaded === 1 ? '' : 's'} loaded`;
}

/** A model row's facts: "17 GB · 262k context · GGUF". */
export function modelFacts(m) {
  const ctx = m.context ? (m.context >= 1000 ? `${Math.round(m.context / 1000)}k` : m.context) + ' context' : '';
  return [m.size_gb ? `${m.size_gb >= 10 ? Math.round(m.size_gb) : m.size_gb} GB` : '', m.memory_gb ? `needs ${m.memory_gb} GB` : '', ctx,
    m.format ? m.format.toUpperCase() : ''].filter(Boolean).join(' · ');
}
