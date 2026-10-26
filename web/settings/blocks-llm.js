// Settings → LLMs (plan llm-servers 4.1): every language-model server in one place. Servers: the relay's
// endpoints by where they run, with health, key, and their own model lists (hide what you don't want in the
// Chat picker). Add a server: a provider and its key, or any OpenAI-compatible URL. On this machine: the
// [llm] engines (lcpp, vLLM) with Load and Unload. Defaults: the agent's chat model and fallback.
// The relay is reached through the hub's proxy (/api/s/relay/admin/…); keys go to the relay only and come
// back as their last four characters. Written by us (web/PATCHES.md); the pure parts are in llm-view.js.

import { h, T, MONO, Btn, Badge, inputSt } from '../chat/chat-ui.js';
import { useAgent } from '../chat/chat-settings.js';
import { PRESETS, addBody, grouped, groupOf, healthState, keyState, modelFacts } from './llm-view.js';

const R = () => globalThis.React;
export const llmEvents = new EventTarget();          // "changed": a server was added or removed
const relay = (api, method, path, json) => api.callService('relay', method, path, json !== undefined ? { json } : {}).then(r => r.json);
const msg = e => String(e?.detail || e?.message || e);
const small = { fontSize: 12, color: T.mut };
const row = (...kids) => h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } }, ...kids);

function ModelList({ api, ep, toast }) {
  const React = R(), [body, setBody] = React.useState(null), [busy, setBusy] = React.useState(false);
  const load = React.useCallback(refresh => relay(api, 'GET', `/admin/endpoints/${ep.id}/models${refresh ? '?refresh=1' : ''}`)
    .then(setBody, e => setBody({ error: msg(e), models: [] })), [api, ep.id]);
  React.useEffect(() => { load(false); }, [load]);
  if (!body) return h('div', { style: small }, 'Asking the server…');
  const hidden = new Set(ep.hidden_models || []);
  const patch = async json => { setBusy(true); try { await relay(api, 'PATCH', `/admin/endpoints/${ep.id}/models`, json); await load(false); llmEvents.dispatchEvent(new Event('changed')); } catch (e) { toast?.(msg(e), 'error'); } finally { setBusy(false); } };
  const toggle = m => { m.hidden ? hidden.delete(m.id) : hidden.add(m.id); patch({ hidden: [...hidden] }); };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 0 2px 2px' } },
    row(h('span', { style: small }, `${body.models.length} model${body.models.length === 1 ? '' : 's'}${ep.alias ? `, picked as ${ep.alias}/<model>` : ''}`),
      h(Btn, { sm: true, kind: 'ghost', label: 'Refresh', disabled: busy, onClick: () => load(true) }),
      groupOf(ep) === 'cloud' && ep.protocol === 'openai' ? h('label', { style: { ...small, display: 'flex', gap: 5, alignItems: 'center' } },
        h('input', { type: 'checkbox', checked: body.hide_filter, disabled: busy, onChange: e => patch({ hide_filter: e.target.checked }) }), 'hide embedding, speech and image models') : null),
    body.error ? h('div', { role: 'alert', style: { fontSize: 12, color: T.rd } }, body.error) : null,
    ...body.models.map(m => h('label', { key: m.id, style: { display: 'flex', gap: 8, alignItems: 'center', fontSize: 12.5, opacity: m.hidden ? 0.55 : 1 } },
      h('input', { type: 'checkbox', checked: !m.hidden, disabled: busy, onChange: () => toggle(m), 'aria-label': `Show ${m.id} in the Chat picker` }),
      h('span', { style: { fontFamily: MONO } }, m.id),
      h('span', { style: { color: T.dim, fontSize: 11.5 } }, [m.context_length ? `${Math.round(m.context_length / 1000)}k` : '', m.vision ? 'vision' : '', m.reasoning ? 'thinks' : ''].filter(Boolean).join(' · ')))));
}

function ServerCard({ api, ep, toast, onChange }) {
  const React = R(), [open, setOpen] = React.useState(false), [keyOpen, setKeyOpen] = React.useState(false);
  const [key, setKey] = React.useState(''), [busy, setBusy] = React.useState(false), [sure, setSure] = React.useState(false);
  const act = async fn => { setBusy(true); try { await fn(); await onChange(); } catch (e) { toast?.(msg(e), 'error'); } finally { setBusy(false); } };
  const hs = healthState(ep), ks = keyState(ep);
  return h('div', { style: { padding: '10px 0', borderBottom: '1px solid ' + T.bd } },
    row(h('span', { style: { fontWeight: 600 } }, ep.name),
      ep.alias ? h('span', { style: { fontFamily: MONO, fontSize: 12, color: T.mut } }, ep.alias) : null,
      h(Badge, { tone: hs.tone }, hs.text), h(Badge, { tone: ks.tone }, ks.text),
      ep.owner ? h(Badge, { tone: 'dim', title: `${ep.owner} manages it` }, ep.owner) : null,
      h('span', { style: { flex: 1 } }),
      h(Btn, { sm: true, kind: 'ghost', label: open ? 'Hide models' : 'Models', onClick: () => setOpen(!open) }),
      ep.owner ? null : h(Btn, { sm: true, kind: 'ghost', label: ep.has_key ? 'Key…' : 'Add key', onClick: () => setKeyOpen(!keyOpen) }),
      h(Btn, { sm: true, kind: 'ghost', label: ep.enabled === false ? 'Turn on' : 'Turn off', disabled: busy,
        onClick: () => act(() => relay(api, 'PATCH', `/admin/endpoints/${ep.id}`, { enabled: ep.enabled === false })) }),
      ep.owner ? null : h(Btn, { sm: true, kind: sure ? 'pri' : 'ghost', label: sure ? 'Remove it' : 'Remove', disabled: busy,
        onClick: () => (sure ? act(() => relay(api, 'DELETE', `/admin/endpoints/${ep.id}`)) : setSure(true)) })),
    h('div', { style: { ...small, fontFamily: MONO, fontSize: 11.5, marginTop: 2 } }, ep.base_url),
    keyOpen ? row(h('input', { type: 'password', autoComplete: 'off', value: key, placeholder: 'the provider’s API key', 'aria-label': `API key for ${ep.name}`,
        onChange: e => setKey(e.target.value), style: { ...inputSt, width: 300 } }),
      h(Btn, { sm: true, kind: 'pri', label: 'Save key', disabled: busy || !key.trim(),
        onClick: () => act(async () => { await relay(api, 'PATCH', `/admin/endpoints/${ep.id}`, { upstream_key: key.trim() }); setKey(''); setKeyOpen(false); }) }),
      ep.has_key ? h(Btn, { sm: true, kind: 'ghost', label: 'Remove key', disabled: busy,
        onClick: () => act(() => relay(api, 'PATCH', `/admin/endpoints/${ep.id}`, { upstream_key: '' })) }) : null,
      h('span', { style: { ...small, fontSize: 11.5 } }, 'Kept by the relay only (relay.db, in backups); never shown again.')) : null,
    open ? h(ModelList, { api, ep, toast }) : null);
}

export function LlmServers({ ctx }) {
  const React = R(), api = ctx.api, [eps, setEps] = React.useState(null), [err, setErr] = React.useState(null);
  const load = React.useCallback(() => relay(api, 'GET', '/admin/endpoints').then(x => { setEps(x); setErr(null); ctx.onLlm?.({ endpoints: x }); }, setErr), [api]);
  React.useEffect(() => { load(); const f = () => load(); llmEvents.addEventListener('changed', f); return () => llmEvents.removeEventListener('changed', f); }, [load]);
  if (err) return h('div', { role: 'alert', style: { padding: '12px 0', color: T.rd, fontSize: 12.5 } }, `The relay didn’t answer: ${msg(err)}. Start LLM Relay (Services).`);
  if (!eps) return h('div', { style: { padding: '12px 0', ...small } }, 'Loading…');
  if (!eps.length) return h('div', { style: { padding: '12px 0', ...small } }, 'No servers yet: add one below.');
  return h('div', { style: { padding: '4px 0 10px' } }, ...grouped(eps).map(g => h('div', { key: g.id, style: { marginTop: 8 } },
    h('div', { style: { fontSize: 11, fontWeight: 600, letterSpacing: '.07em', textTransform: 'uppercase', color: T.mut } }, g.label,
      h('span', { style: { fontWeight: 400, textTransform: 'none', letterSpacing: 0, color: T.dim } }, ' · ' + g.hint)),
    ...g.items.map(ep => h(ServerCard, { key: ep.id, api, ep, toast: ctx.toast, onChange: load })))));
}

export function AddLlmServer({ ctx }) {
  const React = R(), [f, setF] = React.useState({ preset: 'anthropic' }), [busy, setBusy] = React.useState(false), [err, setErr] = React.useState(null);
  const set = k => e => setF(x => ({ ...x, [k]: e.target.value }));
  const p = PRESETS.find(x => x.id === f.preset) || PRESETS[0];
  const add = async () => {
    const { body, error } = addBody(f);
    if (error) return setErr(error);
    setBusy(true); setErr(null);
    try { await relay(ctx.api, 'POST', '/admin/endpoints', body); setF({ preset: f.preset }); llmEvents.dispatchEvent(new Event('changed')); ctx.toast?.(`Added ${body.name}`); }
    catch (e) { setErr(msg(e)); } finally { setBusy(false); }
  };
  const input = (k, ph, o = {}) => h('input', { value: f[k] || '', placeholder: ph, onChange: set(k), 'aria-label': o.label || ph, type: o.type || 'text', autoComplete: 'off',
    style: { ...inputSt, width: o.width || 220 } });
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8, padding: '10px 0 14px' } },
    row(h('select', { value: f.preset, onChange: set('preset'), 'aria-label': 'Provider', style: { ...inputSt, width: 260 } },
      PRESETS.map(x => h('option', { key: x.id, value: x.id }, x.label))),
      f.preset === 'url' ? input('url', 'http://10.0.0.4:8000/v1', { label: 'URL', width: 260 }) : null,
      input('key', p.keyHint, { label: 'API key', type: 'password', width: 240 })),
    row(input('name', f.preset === 'url' ? 'A name (optional)' : p.label, { label: 'Name' }),
      input('alias', p.alias ? `short name: ${p.alias}` : 'short name (optional)', { label: 'Short name', width: 180 }),
      h(Btn, { sm: true, kind: 'pri', label: busy ? 'Adding…' : 'Add server', disabled: busy, onClick: add })),
    h('div', { style: small }, f.preset === 'url' ? 'Its models are read from its /models list.'
      : `Its models are read from ${p.label} with this key, and picked as ${(f.alias || p.alias)}/<model>. Cloud models answer chats only, never the judge or background work.`),
    err ? h('div', { role: 'alert', style: { fontSize: 12.5, color: T.rd } }, err) : null);
}

function EngineModel({ ctx, engine, m, reload }) {
  const React = R(), [busy, setBusy] = React.useState(false), [room, setRoom] = React.useState(null);
  const run = async fn => { setBusy(true); try { await fn(); await reload(); } catch (e) {
    if (e?.code === 'needs_room') setRoom(e.data?.plan || {}); else ctx.toast?.(msg(e), 'error'); } finally { setBusy(false); } };
  const unloads = (room?.unload || []).map(u => u.name || u.id).join(', ');
  return h('div', { style: { padding: '6px 0' } },
    row(h('span', { style: { fontFamily: MONO, fontSize: 12.5 } }, m.name || m.id),
      m.loaded ? h(Badge, { tone: 'green' }, 'loaded') : m.downloaded === false ? h(Badge, { tone: 'dim' }, 'not downloaded') : null,
      h('span', { style: { ...small, fontSize: 11.5 } }, modelFacts(m)),
      m.relay_model ? h('span', { style: { ...small, fontSize: 11.5 } }, '→ ' + m.relay_model) : null,
      h('span', { style: { flex: 1 } }),
      m.loaded ? h(Btn, { sm: true, kind: 'ghost', label: 'Unload', disabled: busy, onClick: () => run(() => ctx.api.unloadLlm(engine.id, m.id)) })
        : h(Btn, { sm: true, label: busy ? 'Loading…' : 'Load', disabled: busy, onClick: () => run(() => ctx.api.loadLlm(engine.id, m.id)) })),
    room ? row(h('span', { style: { fontSize: 12, color: T.acct } }, `Not enough free memory${unloads ? `: GAIFA can unload ${unloads}` : ''}.`),
      h(Btn, { sm: true, kind: 'pri', label: 'Unload & load', onClick: () => { setRoom(null); run(() => ctx.api.loadLlm(engine.id, m.id, true)); } }),
      h(Btn, { sm: true, kind: 'ghost', label: 'Cancel', onClick: () => setRoom(null) })) : null);
}

export function LlmEngines({ ctx }) {
  const React = R(), api = ctx.api, [engines, setEngines] = React.useState(null), [err, setErr] = React.useState(null);
  const load = React.useCallback(() => (api.getLlmEngines ? api.getLlmEngines().then(x => { setEngines(x); setErr(null); ctx.onLlm?.({ engines: x }); }, setErr) : Promise.resolve()), [api]);
  React.useEffect(() => { load(); }, [load]);
  if (!api.getLlmEngines) return h('div', { style: { padding: '12px 0', ...small } }, 'This hub doesn’t serve /api/llm yet.');
  if (err) return h('div', { role: 'alert', style: { padding: '12px 0', color: T.rd, fontSize: 12.5 } }, msg(err));
  if (!engines) return h('div', { style: { padding: '12px 0', ...small } }, 'Loading…');
  if (!engines.length) return h('div', { style: { padding: '12px 0', ...small } }, 'No engine mods (lcpp, vllm) here.');
  return h('div', { style: { padding: '4px 0 10px' } }, ...engines.map(e => h('div', { key: e.id, style: { padding: '8px 0', borderBottom: '1px solid ' + T.bd } },
    row(h('span', { style: { fontWeight: 600 } }, e.name), h(Badge, { tone: e.running ? 'green' : 'dim' }, e.running ? (e.engine?.state || 'running') : e.state),
      h('span', { style: { flex: 1 } }),
      e.running ? h(Btn, { sm: true, kind: 'ghost', label: 'Refresh', onClick: load })
        : h(Btn, { sm: true, label: 'Start', onClick: () => api.startService(e.id).then(() => setTimeout(load, 1500), x => ctx.toast?.(msg(x), 'error')) })),
    e.error ? h('div', { role: 'alert', style: { fontSize: 12, color: T.rd } }, e.error) : null,
    e.running && !e.models.length ? h('div', { style: small }, 'No models in its catalog yet: add them on its page.') : null,
    ...e.models.map(m => h(EngineModel, { key: m.id, ctx, engine: e, m, reload: load })))));
}

export function LlmDefaults({ ctx }) {
  const React = R(), api = ctx.api, a = useAgent(api, ctx.toast);
  const [pick, setPick] = React.useState(null), [busy, setBusy] = React.useState(false);
  if (!a.s) return h('div', { style: { padding: '12px 0', ...small } }, a.err ? 'The agent isn’t running.' : 'Loading…');
  const v = pick || { model: a.s.model || '', fallback: a.s.fallback || '' };
  const models = (a.models?.models || []).map(m => m.id);
  const dirty = v.model !== (a.s.model || '') || v.fallback !== (a.s.fallback || '');
  const sel = (k, opts) => h('select', { value: v[k], 'aria-label': k === 'model' ? 'Chat model' : 'Fallback model', onChange: e => setPick({ ...v, [k]: e.target.value }),
    style: { ...inputSt, width: 280 } }, opts.map(o => h('option', { key: o.value, value: o.value }, o.label)));
  const save = async () => {
    setBusy(true);
    try {
      const svc = await api.getService('agent');
      await api.saveServiceConfig('agent', { env: { ...(svc.config?.env || {}), AGENT_MODEL: v.model, AGENT_FALLBACK_MODEL: v.fallback } });
      await api.restartService('agent');
      ctx.toast?.('Saved; the agent restarted with them');
      setPick(null); setTimeout(() => a.reload?.(), 2500);
    } catch (e) { ctx.toast?.(msg(e), 'error'); } finally { setBusy(false); }
  };
  const opt = id => ({ value: id, label: id });
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8, padding: '10px 0 14px' } },
    row(h('span', { style: { width: 110, fontSize: 12.5 } }, 'Chat model'), sel('model', [...new Set([v.model, ...models])].filter(Boolean).map(opt))),
    row(h('span', { style: { width: 110, fontSize: 12.5 } }, 'Fallback'), sel('fallback', [{ value: '', label: 'none' }, ...[...new Set([v.fallback, ...models])].filter(Boolean).map(opt)])),
    row(h(Btn, { sm: true, kind: 'pri', label: busy ? 'Saving…' : 'Save and restart the agent', disabled: !dirty || busy, onClick: save }),
      h('span', { style: small }, 'New chats start on the chat model; each chat can switch in its model menu. The fallback answers when a chat’s model fails.')));
}

// Agent → Model points here: the servers, their keys and the default models live in LLMs.
export function LlmLink() {
  return h('div', { style: { padding: '4px 0 10px', ...small } }, 'The servers, their keys and the default chat model are in ',
    h('a', { href: '#/settings/llms', style: { color: T.acc } }, 'Settings → LLMs'), '.');
}

export const LLM_BLOCKS = { LlmServers, AddLlmServer, LlmEngines, LlmDefaults, LlmLink };
