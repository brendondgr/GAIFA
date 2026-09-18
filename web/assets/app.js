/* lcpp — app: state/store, router (hash), components/*, views/*.
   Data access goes only through `api` (assets/api.js, assets/mock.js). */
import * as U from './utils.js';
import { ApiError, createHttpApi } from './api.js';
import { createMockApi } from './mock.js';
const { GB, MB, fmtGB, fmtBytes, fmtDur, ago, nowS, debounce, esc, shq, argvToCmd, clone, deepEq, NAME_RE, CTX_PRESETS, ctxLabel, modelNick, loadPref, savePref, download } = U;
const L = window.Lcpp;
const h = L.el, Icon = L.Icon;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
async function copyText(text, label) { try { await navigator.clipboard.writeText(text); toast(label || 'Copied to clipboard'); } catch { toast('Clipboard unavailable in this browser', 'error'); } }

/* ============================================================
   api selection — mock by default; live via window.LCPP_API_BASE or ?live
   ============================================================ */
const LIVE = !!window.LCPP_API_BASE || new URLSearchParams(location.search).has('live');
const BASE = window.LCPP_API_BASE || '';
const api = LIVE ? createHttpApi(BASE) : createMockApi();

/* ============================================================
   state / store
   ============================================================ */
const store = {
  state: { overview: null, loaded: false, daemonDown: false, downSince: 0, models: null, discovered: null, relay: null, settings: null, recent: [], layout: loadPref('lcpp.layout', 'grid'), theme: loadPref('lcpp.theme', 'system') },
  listeners: new Set(),
  subscribe(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); },
  set(patch) { Object.assign(this.state, patch); this.emit(); },
  emit() { this.listeners.forEach(fn => { try { fn(this.state); } catch (e) { console.error(e); } }); },
};
const instances = () => (store.state.overview && store.state.overview.instances) || [];
const findInst = name => instances().find(i => i.name === name);
const modelById = id => ((store.state.models && store.state.models.models) || []).find(m => m.id === id);
const modelLabel = id => { const m = modelById(id); return m ? { name: m.id, nick: modelNick(m) } : { name: id, nick: '' }; };

// ---- poller: only while visible; 2 s while anything is in flux, else 10 s ----
let pollTimer = null, inflight = null;
function pollInterval() { const s = store.state; if (s.daemonDown) return 3000; if (!s.overview) return 2000; const busy = s.overview.instances.some(i => i.state === 'starting' || i.state === 'stopping' || i.relay.state === 'pending' || (i.models || []).some(m => m.loading)); return busy ? 2000 : 10000; }
function schedulePoll() { clearTimeout(pollTimer); if (document.visibilityState !== 'visible') { console.debug('[poll] tab hidden, not scheduling'); return; } const ms = pollInterval(); console.debug('[poll] next overview in', ms, 'ms'); pollTimer = setTimeout(refreshOverview, ms); }
function refreshOverview() {
  if (inflight) return inflight;
  inflight = api.getOverview().then(ov => { store.set({ overview: ov, loaded: true, daemonDown: false }); }).catch(e => { if (e.status === 0) store.set({ daemonDown: true, loaded: true, downSince: store.state.downSince || Date.now() }); else toast(e.detail, 'error'); }).finally(() => { inflight = null; schedulePoll(); });
  return inflight;
}
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') refreshOverview(); else { clearTimeout(pollTimer); console.debug('[poll] paused: tab hidden'); } });

// optimistic patch of one instance, returns a rollback fn
function patchInstance(name, patch) { const ov = store.state.overview; if (!ov) return () => { }; const snap = clone(ov.instances); const i = ov.instances.find(x => x.name === name); if (i) Object.assign(i, patch); store.emit(); return () => { ov.instances = snap; store.emit(); }; }
function replaceInstance(inst) { const ov = store.state.overview; if (!ov) return; const k = ov.instances.findIndex(x => x.name === inst.name); if (k >= 0) ov.instances[k] = inst; else ov.instances.push(inst); store.emit(); }
async function loadModels() { try { const [m, d] = await Promise.all([api.listModels(), api.listDiscovered()]); store.set({ models: m, discovered: d }); } catch (e) { if (e.status !== 0) toast(e.detail, 'error'); } }
async function loadRelay() { try { store.set({ relay: await api.getRelay() }); } catch (e) { if (e.status !== 0) toast(e.detail, 'error'); } }
async function loadSettings() { try { store.set({ settings: await api.getSettings() }); } catch (e) { if (e.status !== 0) toast(e.detail, 'error'); } }
async function loadRecent() { try { store.set({ recent: await api.getRecent() }); } catch { /* optional */ } }

/* ============================================================
   components — toasts, dialogs, menus, editors
   ============================================================ */
function toast(message, kind = 'info') { const area = $('#toasts'); const t = L.Toast({ message, kind, onDismiss: el => el.remove() }); area.append(t); if (kind !== 'error') setTimeout(() => t.remove(), 4000); return t; }

let dialogDepth = 0;
function openDialog(d, { onClose } = {}) {
  const opener = document.activeElement; document.body.append(d); dialogDepth++;
  d.addEventListener('close', () => { dialogDepth--; d.remove(); onClose && onClose(d.returnValue); if (opener && opener.isConnected && opener.focus) opener.focus(); }, { once: true });
  d.addEventListener('click', e => { if (e.target === d) d.close('cancel'); });
  d.showModal();
  const first = d.querySelector('input:not([type=hidden]), select, textarea, button:not(.btn-ghost)'); if (first) first.focus();
  return d;
}
function confirmDialog({ title, html, label = 'Confirm', danger = true }) {
  return new Promise(resolve => {
    const ok = L.Button({ label, variant: danger ? 'danger' : 'primary', onClick: () => d.close('ok') });
    const d = L.Dialog({ title, body: h('div', { html }), actions: [L.Button({ label: 'Cancel', onClick: () => d.close('cancel') }), ok] });
    openDialog(d, { onClose: v => resolve(v === 'ok') }); ok.focus();
  });
}
let openMenu = null;
function showMenu(anchor, items) {
  closeMenu(); const m = h('div', { class: 'menu', role: 'menu' });
  items.forEach(it => { if (it === '-') { m.append(h('hr')); return; } const b = h('button', { type: 'button', role: 'menuitem', disabled: !!it.disabled, onClick: () => { closeMenu(); it.onClick && it.onClick(); } }, [it.icon ? Icon(it.icon) : null, it.label]); m.append(b); });
  document.body.append(m); const r = anchor.getBoundingClientRect(); const mw = m.offsetWidth; m.style.top = (r.bottom + window.scrollY + 4) + 'px'; m.style.left = Math.max(8, Math.min(r.right - mw, window.innerWidth - mw - 8)) + window.scrollX + 'px';
  openMenu = { m, anchor }; const first = m.querySelector('button:not(:disabled)'); if (first) first.focus();
  setTimeout(() => { document.addEventListener('click', onDoc); document.addEventListener('keydown', onKey); }, 0);
  function onDoc(e) { if (!m.contains(e.target)) closeMenu(); }
  function onKey(e) { if (e.key === 'Escape') { closeMenu(); anchor.focus(); } if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); const bs = $$('button:not(:disabled)', m); const k = bs.indexOf(document.activeElement); bs[(k + (e.key === 'ArrowDown' ? 1 : bs.length - 1)) % bs.length].focus(); } }
  openMenu.off = () => { document.removeEventListener('click', onDoc); document.removeEventListener('keydown', onKey); };
}
function closeMenu() { if (openMenu) { openMenu.off && openMenu.off(); openMenu.m.remove(); openMenu = null; } }

// key/value editor: rows of {key, value}; values may be empty for boolean flags
function kvEditor({ rows = [], onChange, keyPlaceholder = 'flag', valuePlaceholder = 'value (empty for a switch)' }) {
  const box = h('div', { class: 'kv' }); const list = h('div', { class: 'kv' });
  const data = rows.map(r => ({ ...r }));
  const emit = () => onChange && onChange(data.filter(r => r.key.trim()).map(r => ({ key: r.key.trim(), value: r.value })));
  const render = () => { list.replaceChildren(...data.map((r, k) => h('div', { class: 'kv-row' }, [h('input', { class: 'input mono', value: r.key, placeholder: keyPlaceholder, 'aria-label': 'key', onInput: e => { r.key = e.target.value; emit(); } }), h('input', { class: 'input mono', value: r.value, placeholder: valuePlaceholder, 'aria-label': 'value', onInput: e => { r.value = e.target.value; emit(); } }), L.Button({ icon: 'x', variant: 'ghost', size: 'sm', title: 'Remove', onClick: () => { data.splice(k, 1); render(); emit(); } })]))); };
  render(); box.append(list, h('div', {}, L.Button({ label: 'Add', icon: 'plus', size: 'sm', variant: 'ghost', onClick: () => { data.push({ key: '', value: '' }); render(); const last = list.lastElementChild; last && last.querySelector('input').focus(); } })));
  box.getRows = () => data.filter(r => r.key.trim()); box.setRows = rows => { data.splice(0, data.length, ...rows.map(r => ({ ...r }))); render(); };
  return box;
}
const paramsToRows = p => Object.entries(p || {}).map(([key, value]) => ({ key, value: value === true ? '' : String(value) }));
const rowsToParams = rows => Object.fromEntries(rows.map(r => [r.key, r.value === '' ? true : /^-?\d+(\.\d+)?$/.test(r.value) ? +r.value : r.value === 'true' ? true : r.value === 'false' ? false : r.value]));
function chipInput({ values = [], onChange, placeholder = 'add a nickname' }) {
  const box = h('div', { class: 'row', style: { alignItems: 'center' } }); const data = [...values];
  const render = () => { box.replaceChildren(...data.map((v, k) => L.Chip({ label: v, removable: true, onClick: () => { data.splice(k, 1); render(); onChange(data); } })), input); };
  const input = h('input', { class: 'input mono', placeholder, style: { width: '160px', height: '26px' }, 'aria-label': placeholder, onKeydown: e => { if ((e.key === 'Enter' || e.key === ',') && input.value.trim()) { e.preventDefault(); data.push(input.value.trim().replace(/,$/, '')); input.value = ''; render(); onChange(data); input.focus(); } if (e.key === 'Backspace' && !input.value && data.length) { data.pop(); render(); onChange(data); input.focus(); } }, onBlur: () => { if (input.value.trim()) { data.push(input.value.trim()); input.value = ''; render(); onChange(data); } } });
  render(); return box;
}
function skeletonCards(n = 3) { return h('div', { class: 'grid' }, Array.from({ length: n }, () => h('div', { class: 'card', style: { padding: '16px', display: 'flex', flexDirection: 'column', gap: '10px' } }, [L.Skeleton({ width: '55%', height: '16px' }), L.Skeleton({ width: '30%' }), L.Skeleton({ width: '80%' }), L.Skeleton({ width: '60%' }), h('div', { class: 'row' }, [L.Skeleton({ width: '64px', height: '20px' }), L.Skeleton({ width: '88px', height: '20px' })])]))); }
function sectionLabel(t) { return h('div', { class: 'section-label', text: t }); }
function instBadges(i) { const p = i.params || {}; const b = []; if (p['ctx-size']) b.push({ label: 'ctx ' + p['ctx-size'] }); if (p['cache-type-k'] || p['cache-type-v']) b.push({ label: 'kv ' + (p['cache-type-k'] || 'f16') + '/' + (p['cache-type-v'] || 'f16') }); if (i.capabilities && i.capabilities.vision) b.push({ label: 'vision', tone: 'cyan' }); if (i.capabilities && i.capabilities.speculative) b.push({ label: 'spec-decode', tone: 'cyan' }); if (i.kind === 'router') b.push({ label: 'max ' + (p['models-max'] || 1) + ' loaded', tone: 'purple' }); return b; }
const curlFor = (url, model) => `curl ${url}/chat/completions \\\n  -H 'Content-Type: application/json' \\\n  -d '{"model":"${model}","messages":[{"role":"user","content":"Hello"}],"stream":true}'`;

/* ============================================================
   router (hash)
   ============================================================ */
const VIEWS = ['instances', 'models', 'playground', 'relay', 'settings'];
let dirtyGuard = null; // fn → true when a view has unsaved changes
let currentHash = location.hash || '#/instances', suppressHash = false;
function parseHash(hash = location.hash) { const raw = hash.replace(/^#\/?/, ''); const [pathQ, qs] = raw.split('?'); const parts = pathQ.split('/').filter(Boolean); return { view: VIEWS.includes(parts[0]) ? parts[0] : 'instances', parts, q: Object.fromEntries(new URLSearchParams(qs || '')) }; }
function navigate(hash) { if (location.hash === hash) renderRoute(); else location.hash = hash; }
async function onHashChange() {
  if (suppressHash) { suppressHash = false; return; }
  const from = parseHash(currentHash), to = parseHash(location.hash);
  if (dirtyGuard && dirtyGuard() && from.view !== to.view) { const ok = await confirmDialog({ title: 'Discard unsaved changes?', html: 'The settings form has changes that have not been saved.', label: 'Discard' }); if (!ok) { suppressHash = true; location.hash = currentHash; return; } dirtyGuard = null; }
  currentHash = location.hash || '#/instances'; renderRoute();
}
window.addEventListener('hashchange', onHashChange);
/* ============================================================
   views/instances — cards or list, empty state, daemon banner
   ============================================================ */
function instanceVM(i) {
  const ml = i.model_id ? modelLabel(i.model_id) : { name: '', nick: '' }; const t = nowS();
  return { ...i, model_name: ml.name, nickname: ml.nick, uptime: i.state === 'ready' || i.state === 'stopping' ? fmtDur(t - i.started_ts) : i.state === 'starting' ? fmtDur(t - i.started_ts) : '—', rss: i.rss_bytes == null ? '—' : fmtGB(i.rss_bytes), elapsed: i.state === 'starting' ? Math.floor(t - i.started_ts) : null, badges: instBadges(i), relay: { ...i.relay, label: i.relay.state === 'pending' ? (store.state.overview && store.state.overview.relay.reachable ? (i.state === 'ready' ? 'pending · registering' : 'pending · registers when ready') : 'pending · relay unreachable, retrying') : undefined } };
}
function cardHandlers(i) {
  return {
    onLogs: () => openLogs(i.name), onTry: () => navigate(`#/playground?instance=${encodeURIComponent(i.name)}`),
    onRestart: async () => { if (!await confirmDialog({ title: `Restart ${i.name}?`, html: `The server on port <code class="mono">${i.port}</code> will be stopped and started again with the same settings.${i.relay.state === 'registered' ? ' Its Relay registration will be renewed.' : ''}`, label: 'Restart', danger: false })) return; const rb = patchInstance(i.name, { state: 'stopping' }); try { replaceInstance(await api.restart(i.name)); toast(`Restarting ${i.name}…`, 'success'); } catch (e) { rb(); toast(e.detail, 'error'); } refreshOverview(); },
    onStop: async () => { if (!await confirmDialog({ title: `Stop ${i.name}?`, html: `The server on port <code class="mono">${i.port}</code> will be stopped.${i.relay.state !== 'off' ? ' <b>It will also be removed from Relay.</b>' : ''}`, label: 'Stop' })) return; const rb = patchInstance(i.name, { state: 'stopping' }); try { await api.stop(i.name); toast(`Stopping ${i.name}…`, 'success'); } catch (e) { rb(); toast(e.detail, 'error'); } refreshOverview(); },
    onCopy: () => copyText(i.url, 'Copied endpoint URL'), onCopyCmd: () => copyText(argvToCmd(i.argv), 'Copied llama-server command'),
    onPublish: async on => { const snap = clone(i.relay); if (on) { const alias = await promptAlias(i); if (alias === null) { store.emit(); return; } patchInstance(i.name, { relay: { ...i.relay, state: 'pending', alias } }); try { replaceInstance(await api.publish(i.name, alias)); toast(`Publishing ${i.name} as "${alias}"`, 'success'); } catch (e) { patchInstance(i.name, { relay: snap }); toast(e.detail, 'error'); } } else { if (!await confirmDialog({ title: `Unpublish ${i.name}?`, html: `The registration <code class="mono">${i.relay.key}</code> (alias <code class="mono">${esc(i.relay.alias)}</code>) will be removed from Relay. The server keeps running.`, label: 'Unpublish' })) { store.emit(); return; } patchInstance(i.name, { relay: { state: 'off', key: null, alias: null, health: null, error: null } }); try { replaceInstance(await api.unpublish(i.name)); toast(`Unpublished ${i.name}`, 'success'); } catch (e) { patchInstance(i.name, { relay: snap }); toast(e.detail, 'error'); } } refreshOverview(); },
    onModel: async (id, load) => { const inst = findInst(i.name); const m = inst && inst.models.find(x => x.id === id); if (m) { if (load) m.loading = true; else m.loaded = false; store.emit(); } try { replaceInstance(await (load ? api.routerLoad(i.name, id) : api.routerUnload(i.name, id))); toast(`${load ? 'Loading' : 'Unloaded'} ${id}${load ? '…' : ''}`, 'success'); } catch (e) { toast(e.detail, 'error'); } refreshOverview(); },
    onRetry: async () => { try { replaceInstance(await api.restart(i.name)); toast(`Retrying ${i.name}…`, 'success'); } catch (e) { toast(e.detail, 'error'); } refreshOverview(); },
    onDismiss: async () => { const ov = store.state.overview; ov.instances = ov.instances.filter(x => x.name !== i.name); store.emit(); try { await api.dismiss(i.name); } catch (e) { toast(e.detail, 'error'); } refreshOverview(); },
    onMore: e => showMenu(e.currentTarget, [{ label: 'Copy endpoint URL', icon: 'copy', onClick: () => copyText(i.url, 'Copied endpoint URL') }, { label: 'Copy curl example', icon: 'copy', onClick: () => copyText(curlFor(i.url, i.relay.alias || i.model_id || (i.models[0] && i.models[0].id) || 'default'), 'Copied curl example') }, { label: 'Show details', icon: 'info', onClick: () => showDetails(i) }, '-', { label: 'Open in Relay', icon: 'external', disabled: i.relay.state !== 'registered', onClick: () => window.open(store.state.overview.relay.dashboard_url, '_blank', 'noopener') }]),
  };
}
function promptAlias(i) { return new Promise(resolve => { const f = L.Field({ label: 'Alias on Relay', mono: true, value: i.relay.alias || (i.model_id ? modelLabel(i.model_id).nick : i.name), help: 'The model name clients will use through Relay' }); const ok = L.Button({ label: 'Publish', variant: 'primary', onClick: () => d.close('ok') }); const d = L.Dialog({ title: `Publish ${i.name} to Relay`, body: f, actions: [L.Button({ label: 'Cancel', onClick: () => d.close('cancel') }), ok] }); f.control.addEventListener('keydown', e => { if (e.key === 'Enter') d.close('ok'); }); openDialog(d, { onClose: v => resolve(v === 'ok' ? f.control.value.trim() : null) }); }); }
function showDetails(i) { const d = L.Dialog({ title: `${i.name} — details`, body: h('div', { class: 'stack' }, [sectionLabel('Effective params'), h('pre', { class: 'code', text: JSON.stringify(i.params, null, 2) }), sectionLabel('argv'), h('pre', { class: 'code', text: argvToCmd(i.argv) }), sectionLabel('Instance JSON'), h('pre', { class: 'code', text: JSON.stringify(i, null, 2) })]), actions: [L.Button({ label: 'Copy command', icon: 'copy', onClick: () => copyText(argvToCmd(i.argv), 'Copied llama-server command') }), L.Button({ label: 'Close', onClick: () => d.close() })] }); d.style.width = 'min(760px, calc(100vw - 32px))'; openDialog(d); }

function renderInstances(root, route) {
  let lastKey = null, tick = null;
  const wrap = h('div', { class: 'view' }); root.replaceChildren(wrap);
  function draw() {
    const s = store.state; const list = instances();
    const key = JSON.stringify([list, s.layout, s.loaded, s.daemonDown, s.recent, s.models && s.models.models.map(m => m.id + m.nicknames.join()), list.some(i => i.state === 'starting') ? Math.floor(nowS()) : 0, Math.floor(nowS() / 60)]);
    if (key === lastKey) return; lastKey = key;
    const focused = document.activeElement && document.activeElement.closest('.inst-card, tr[data-name]'); const focusName = focused && focused.dataset.name;
    const head = h('div', { class: 'view-head' }, [h('h1', { class: 'title', text: 'Instances' }), h('span', { class: 'muted', text: list.length ? `${list.length} running` : '' }), L.Segmented({ label: 'Layout', size: 'sm', value: s.layout, options: [{ value: 'grid', label: 'Grid', icon: 'grid' }, { value: 'list', label: 'List', icon: 'list' }], onChange: v => { savePref('lcpp.layout', v); store.set({ layout: v }); } })]);
    let body;
    if (!s.loaded) body = skeletonCards(3);
    else if (!list.length) body = emptyState(s);
    else if (s.layout === 'list') body = listLayout(list);
    else { body = h('div', { class: 'grid' }); list.forEach(i => { const vm = instanceVM(i); const c = L.InstanceCard(vm, cardHandlers(i)); c.dataset.name = i.name; if (i.kind === 'router') $$('.models li', c).forEach((li, k) => { const m = i.models[k]; if (m && m.loading) { li.querySelector('.dot').className = 'dot dot-amber pulse'; li.querySelector('.muted').textContent = 'loading…'; li.querySelector('.btn').disabled = true; } }); body.append(c); }); }
    wrap.replaceChildren(head, body);
    if (focusName) { const el = wrap.querySelector(`[data-name="${CSS.escape(focusName)}"]`); if (el) el.focus({ preventScroll: true }); }
  }
  function emptyState(s) {
    const sys = s.overview && s.overview.system; const chips = (s.recent || []).slice(0, 3).map(r => L.Chip({ label: r.kind === 'router' ? `router · ${(r.model_ids || []).length || 'all'} models` : `${modelLabel(r.model_id).nick || r.model_id}${r.port ? ' · ' + r.port : ''}`, dot: 'off', onClick: () => openLaunch(r) }));
    return h('div', { class: 'stack' }, [L.EmptyState({ icon: 'box', title: 'No models running.', body: `lcpp is idle and using almost nothing${sys ? ' — ' + fmtBytes(sys.daemon.rss_bytes) : ''}.`, actions: [L.Button({ label: 'Launch a model', icon: 'plus', variant: 'primary', size: 'lg', onClick: () => openLaunch() })] }), chips.length ? h('div', { class: 'row', style: { justifyContent: 'center' } }, [sectionLabel('Recent'), ...chips]) : null]);
  }
  function listLayout(list) {
    const t = L.Table({ columns: [{ label: 'state', cell: i => L.StatusDot({ state: i.state, label: i.state + (i.state === 'starting' ? ' · ' + Math.floor(nowS() - i.started_ts) + 's' : '') }) }, { label: 'name', cell: i => h('div', { class: 'row' }, [h('span', { class: 'name', text: i.name }), L.Badge({ label: i.kind, tone: i.kind === 'router' ? 'purple' : null })]) }, { label: 'model', cell: i => i.kind === 'router' ? h('span', { class: 'mono small', text: i.models.filter(m => m.loaded).map(m => m.id).join(', ') || 'none loaded' }) : h('span', { text: modelLabel(i.model_id).nick || i.model_id }) }, { label: 'endpoint', cell: i => h('code', { class: 'mono', text: i.url }) }, { label: 'uptime', num: true, cell: i => i.state === 'failed' ? '—' : fmtDur(nowS() - i.started_ts) }, { label: 'rss', num: true, cell: i => fmtGB(i.rss_bytes) }, { label: 'relay', cell: i => L.StatusDot({ state: i.relay.state, label: i.relay.state === 'registered' ? i.relay.alias : i.relay.state }) }, { label: '', cell: i => { const hd = cardHandlers(i); return h('div', { class: 'row', style: { flexWrap: 'nowrap' } }, [L.Button({ icon: 'logs', size: 'sm', variant: 'ghost', title: 'Logs', onClick: hd.onLogs }), L.Button({ icon: 'chat', size: 'sm', variant: 'ghost', title: 'Try it', disabled: i.state !== 'ready', onClick: hd.onTry }), L.Button({ icon: 'square', size: 'sm', variant: 'ghost', title: 'Stop', onClick: hd.onStop }), L.Button({ icon: 'more', size: 'sm', variant: 'ghost', title: 'More', onClick: hd.onMore })]); } }], rows: list });
    $$('tbody tr', t).forEach((tr, k) => { tr.dataset.name = list[k].name; tr.tabIndex = 0; }); return h('div', { class: 'card' }, t);
  }
  const unsub = store.subscribe(draw); draw(); tick = setInterval(draw, 1000);
  if (route.parts[1] && route.parts[2] === 'logs') openLogs(decodeURIComponent(route.parts[1]), true);
  return { destroy() { unsub(); clearInterval(tick); } };
}

/* ============================================================
   views/launch — the Launch dialog
   ============================================================ */
function openLaunch(prefill = {}) {
  const models = (store.state.models && store.state.models.models) || []; const settings = store.state.settings; const relayOk = store.state.overview && store.state.overview.relay.reachable;
  const spec = { kind: prefill.kind || 'single', model_id: prefill.model_id || (models.find(m => m.ok) || {}).id, model_ids: prefill.model_ids || models.filter(m => m.ok).map(m => m.id), models_max: prefill.models_max || 1, port: prefill.port || null, name: prefill.name || '', params: { ...(prefill.params || {}) }, relay: { enabled: prefill.relay ? !!prefill.relay.enabled : !!(settings && settings.relay.auto_register), alias: (prefill.relay && prefill.relay.alias) || '' }, save_preset: null };
  let pf = null, busy = false, extra = paramsToRows(Object.fromEntries(Object.entries(spec.params).filter(([k]) => !['ctx-size', 'n-gpu-layers', 'cache-type-k', 'cache-type-v', 'flash-attn', 'batch-size', 'ubatch-size', 'parallel', 'threads'].includes(k))));
  const model = () => modelById(spec.model_id);
  const eff = () => { const m = model(); return { ...((store.state.models && store.state.models.defaults) || {}), ...((m && m.overrides) || {}) }; };
  // fields
  const modeSeg = L.Segmented({ label: 'Mode', value: spec.kind, options: [{ value: 'single', label: 'Single model' }, { value: 'router', label: 'Router (many models, load on demand)' }], onChange: v => { spec.kind = v; syncMode(); change(); } });
  const search = h('input', { class: 'input', placeholder: 'Search models…', 'aria-label': 'Search models', onInput: () => drawPicker() });
  const picker = h('div', { class: 'picker', role: 'listbox', 'aria-label': 'Model' });
  const maxField = L.Field({ label: 'Max loaded at once', type: 'number', value: spec.models_max, min: 1, mono: true, onInput: v => { spec.models_max = Math.max(1, +v || 1); change(); } });
  const portField = L.Field({ label: 'Port', type: 'number', value: spec.port || '', mono: true, placeholder: 'auto', trailing: L.Button({ label: 'Use next free', size: 'sm', variant: 'ghost', onClick: async () => { try { const r = await api.suggestPort(); spec.port = r.port; portField.control.value = r.port; change(); } catch (e) { toast(e.detail, 'error'); } } }), onInput: v => { spec.port = +v || null; change(); } });
  const nameField = L.Field({ label: 'Name', optional: true, mono: true, value: spec.name, placeholder: '', onInput: v => { spec.name = v.trim(); change(); } });
  const ctxField = L.Field({ label: 'Context size', type: 'select', options: [], onChange: v => { if (v === 'custom') { ctxCustom.hidden = false; ctxCustom.control.focus(); spec.params['ctx-size'] = +ctxCustom.control.value || eff()['ctx-size']; } else { ctxCustom.hidden = true; if (+v === +eff()['ctx-size']) delete spec.params['ctx-size']; else spec.params['ctx-size'] = +v; } change(); } });
  const ctxCustom = L.Field({ label: 'Custom context size', type: 'number', mono: true, min: 512, step: 512, onInput: v => { spec.params['ctx-size'] = +v || undefined; change(); } }); ctxCustom.hidden = true;
  const relayToggle = L.Toggle({ label: 'Publish to Relay', checked: spec.relay.enabled, tone: 'cyan', onChange: v => { spec.relay.enabled = v; aliasField.control.disabled = !v; change(); } });
  const aliasField = L.Field({ label: 'Alias', mono: true, value: spec.relay.alias, placeholder: '', disabled: !spec.relay.enabled, onInput: v => { spec.relay.alias = v.trim(); change(); } });
  const relayNote = h('div', { class: 'help', hidden: true });
  const adv = {}; const numOv = (key, label) => L.Field({ label, type: 'number', mono: true, value: spec.params[key] ?? '', onInput: v => { if (v === '') delete spec.params[key]; else spec.params[key] = +v; change(); } });
  adv.ngl = numOv('n-gpu-layers', 'n-gpu-layers'); adv.batch = numOv('batch-size', 'batch-size'); adv.ubatch = numOv('ubatch-size', 'ubatch-size'); adv.parallel = numOv('parallel', 'parallel (slots)'); adv.threads = numOv('threads', 'threads');
  const kvSel = (key, label) => L.Field({ label, type: 'select', options: [{ value: '', label: 'model default' }, { value: 'f16', label: 'f16' }, { value: 'q8_0', label: 'q8_0' }, { value: 'q4_0', label: 'q4_0' }], value: spec.params[key] || '', onChange: v => { if (v === '') delete spec.params[key]; else spec.params[key] = v; change(); } });
  adv.ctk = kvSel('cache-type-k', 'cache-type-k'); adv.ctv = kvSel('cache-type-v', 'cache-type-v');
  adv.fa = L.Toggle({ label: 'flash-attn', checked: spec.params['flash-attn'] ?? eff()['flash-attn'] ?? true, onChange: v => { if (v === !!eff()['flash-attn']) delete spec.params['flash-attn']; else spec.params['flash-attn'] = v; change(); } });
  const extraEd = kvEditor({ rows: extra, onChange: rows => { extra = rows; change(); } });
  const presetChk = h('input', { class: 'checkbox', type: 'checkbox', id: 'preset-chk', onChange: () => { presetName.hidden = !presetChk.checked; spec.save_preset = presetChk.checked ? (presetName.control.value.trim() || null) : null; } });
  const presetName = L.Field({ label: 'Preset name', mono: true, placeholder: 'e.g. gemma-long-ctx', onInput: v => { spec.save_preset = v.trim() || null; } }); presetName.hidden = true;
  const summary = h('div', { class: 'inset stack', style: { gap: '6px' } });
  const preview = h('pre', { class: 'code' }); const copyBtn = L.Button({ icon: 'copy', variant: 'ghost', size: 'sm', title: 'Copy command', onClick: () => copyText(preview.dataset.cmd || '', 'Copied llama-server command') });
  const launchBtn = L.Button({ label: 'Launch', variant: 'primary', icon: 'play', onClick: doLaunch });
  const modelSection = h('div', { class: 'field' }, [h('span', { class: 'label', text: 'Model' }), search, picker, h('div', { class: 'help', id: 'model-help' })]);
  const routerSection = h('div', { class: 'stack' }, [maxField]);
  const body = h('div', { class: 'stack', style: { gap: '16px' } }, [h('div', { class: 'field' }, [h('span', { class: 'label', text: 'Mode' }), modeSeg]), modelSection, routerSection, h('div', { class: 'form-grid' }, [portField, nameField]), h('div', { class: 'form-grid' }, [ctxField, ctxCustom]), h('div', { class: 'stack', style: { gap: '8px' } }, [relayToggle, aliasField, relayNote]), h('details', { class: 'adv' }, [h('summary', { text: 'Advanced' }), h('div', { class: 'stack' }, [h('div', { class: 'form-grid' }, [adv.ngl, adv.ctk, adv.ctv, adv.batch, adv.ubatch, adv.parallel, adv.threads]), adv.fa, sectionLabel('Extra flags'), extraEd, h('label', { class: 'check', for: 'preset-chk' }, [presetChk, 'Save as preset']), presetName])]), h('div', { class: 'stack', style: { gap: '6px' } }, [sectionLabel('Preflight'), summary]), h('div', { class: 'stack', style: { gap: '6px' } }, [h('div', { class: 'row', style: { justifyContent: 'space-between' } }, [sectionLabel('Command preview'), copyBtn]), preview])]);
  const d = L.Dialog({ title: 'Launch', body, actions: [L.Button({ label: 'Cancel', onClick: () => d.close('cancel') }), launchBtn] }); d.style.width = 'min(720px, calc(100vw - 32px))';
  d.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); doLaunch(); } });
  function drawPicker() {
    const q = search.value.trim().toLowerCase(); picker.replaceChildren();
    models.filter(m => !q || m.id.toLowerCase().includes(q) || m.nicknames.some(n => n.toLowerCase().includes(q))).forEach(m => {
      const running = m.running.length; const sel = spec.kind === 'single' ? spec.model_id === m.id : spec.model_ids.includes(m.id);
      const row = h('div', { class: 'picker-row', role: 'option', tabindex: m.ok ? '0' : '-1', 'aria-selected': String(sel), 'aria-disabled': String(!m.ok), title: m.ok ? '' : m.problems.join('; '), onClick: () => pick(m), onKeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(m); } } }, [spec.kind === 'router' ? h('input', { class: 'checkbox', type: 'checkbox', checked: sel, disabled: !m.ok, tabindex: '-1', 'aria-label': m.id }) : h('span', { class: 'dot ' + (sel ? 'dot-amber' : 'dot-off') }), h('div', { class: 'grow' }, [h('div', { class: 'id', text: m.id }), h('div', { class: 'muted', text: m.ok ? m.nicknames.join(', ') : m.problems[0] })]), h('span', { class: 'mono muted', text: fmtGB(m.size_bytes) }), m.capabilities.vision ? L.Badge({ label: 'vision', tone: 'cyan' }) : null, m.capabilities.speculative ? L.Badge({ label: 'spec-decode', tone: 'cyan' }) : null, running ? L.Badge({ label: running + ' running', tone: 'green' }) : null]);
      picker.append(row);
    });
    if (!picker.children.length) picker.append(h('div', { class: 'picker-row muted', text: 'No models match' }));
  }
  function pick(m) { if (!m.ok) return; if (spec.kind === 'single') { spec.model_id = m.id; syncDefaults(); } else { const k = spec.model_ids.indexOf(m.id); if (k >= 0) spec.model_ids.splice(k, 1); else spec.model_ids.push(m.id); } drawPicker(); change(); }
  function syncDefaults() { const e = eff(); const ctx = e['ctx-size'] || 4096; const opts = CTX_PRESETS.map(v => ({ value: String(v), label: ctxLabel(v) + (v === +ctx ? ' (model default)' : '') })); if (!CTX_PRESETS.includes(+ctx)) opts.push({ value: String(ctx), label: ctx + ' (model default)' }); opts.push({ value: 'custom', label: 'Custom…' }); ctxField.control.replaceChildren(...opts.map(o => h('option', { value: o.value, text: o.label }))); const cur = spec.params['ctx-size'] || ctx; if ([...ctxField.control.options].some(o => +o.value === +cur)) { ctxField.control.value = String(cur); ctxCustom.hidden = true; } else { ctxField.control.value = 'custom'; ctxCustom.hidden = false; ctxCustom.control.value = cur; } adv.ngl.control.placeholder = e['n-gpu-layers'] ?? ''; adv.batch.control.placeholder = e['batch-size'] ?? ''; adv.ubatch.control.placeholder = e['ubatch-size'] ?? ''; adv.parallel.control.placeholder = e.parallel ?? '1'; adv.threads.control.placeholder = e.threads ?? 'auto'; adv.ctk.control.options[0].text = 'model default (' + (e['cache-type-k'] || 'f16') + ')'; adv.ctv.control.options[0].text = 'model default (' + (e['cache-type-v'] || 'f16') + ')'; const m = model(); if (m && !aliasField.control.value) aliasField.control.placeholder = modelNick(m); }
  function syncMode() { const single = spec.kind === 'single'; routerSection.hidden = single; drawPicker(); $('#model-help', modelSection).textContent = single ? '' : `${spec.model_ids.length} of ${models.filter(m => m.ok).length} models selected; ${spec.models_max} loaded at once`; }
  function buildSpec() { const s = { kind: spec.kind, params: { ...spec.params, ...rowsToParams(extra) }, relay: { enabled: spec.relay.enabled, alias: spec.relay.alias || undefined }, save_preset: spec.save_preset }; if (spec.kind === 'single') s.model_id = spec.model_id; else { s.model_ids = spec.model_ids; s.models_max = spec.models_max; } if (spec.port) s.port = spec.port; if (spec.name) s.name = spec.name; return s; }
  const runPreflight = debounce(async () => { try { pf = await api.preflight(buildSpec()); applyPreflight(); } catch (e) { if (e.status !== 0) toast(e.detail, 'error'); } }, 300);
  function change() { syncMode(); relayNote.hidden = relayOk; relayNote.textContent = spec.relay.enabled ? 'Relay is unreachable — will register when Relay comes back.' : 'Relay is unreachable.'; relayNote.className = 'help help-warn'; runPreflight(); }
  function applyPreflight() {
    const errs = pf.errors; const fe = f => errs.find(e => e.field === f);
    portField.control.placeholder = pf.suggested_port; if (fe('port')) portField.setHelp('err', pf.port_reason || fe('port').detail); else portField.setHelp('ok', `${pf.port} free`);
    nameField.control.placeholder = pf.name; if (fe('name')) nameField.setHelp('err', pf.name_reason || fe('name').detail); else nameField.setHelp('ok', `${pf.name} is available`);
    const mh = $('#model-help', modelSection); const me = fe('model'); if (me) { mh.className = 'help help-err'; mh.textContent = '✗ ' + me.detail; } else if (spec.kind === 'single') { mh.className = 'help'; mh.textContent = ''; }
    summary.replaceChildren(h('div', { class: 'row' }, [h('span', { class: 'muted', text: 'Estimated memory' }), h('b', { class: 'mono', text: fmtGB(pf.estimated_bytes) }), h('span', { class: 'muted', text: '· available' }), h('b', { class: 'mono', text: fmtGB(pf.available_bytes) })]), ...pf.warnings.map(w => h('div', { class: 'status status-amber', style: { alignItems: 'flex-start' } }, [Icon('alert'), h('span', { text: w })])), ...errs.map(e => h('div', { class: 'status status-red', style: { alignItems: 'flex-start' } }, [Icon('alert'), h('span', { text: e.detail })])), !pf.warnings.length && !errs.length ? h('div', { class: 'status status-green' }, [Icon('check'), 'Ready to launch']) : null);
    preview.textContent = argvToCmd(pf.argv); preview.dataset.cmd = argvToCmd(pf.argv); launchBtn.disabled = errs.length > 0 || busy;
  }
  async function doLaunch() {
    if (busy || (pf && pf.errors.length)) return; busy = true; launchBtn.classList.add('is-loading'); launchBtn.disabled = true;
    try { const r = await api.launch(buildSpec()); replaceInstance(r.instance); r.warnings.forEach(w => toast(w)); toast(`Starting ${r.instance.name}…`, 'success'); d.close('ok'); navigate('#/instances'); loadRecent(); refreshOverview(); }
    catch (e) { toast(e.detail, 'error'); if (e.code === 'port_in_use' || e.code === 'port_reserved') portField.setHelp('err', e.detail); if (e.code === 'name_taken' || e.code === 'invalid_name') nameField.setHelp('err', e.detail); }
    finally { busy = false; launchBtn.classList.remove('is-loading'); launchBtn.disabled = !!(pf && pf.errors.length); }
  }
  syncDefaults(); syncMode(); change(); openDialog(d); search.focus();
}

/* ============================================================
   views/logs — the logs drawer
   ============================================================ */
let logsState = null;
function openLogs(name, fromRoute) {
  closeLogs(true); const drawer = $('#drawer'); drawer.hidden = false;
  const st = logsState = { name, lines: [], follow: true, filter: '', wrap: false, limit: +loadPref('lcpp.loglines', 200), unseen: 0, stream: null };
  const title = h('h2', {}); const logBox = h('div', { class: 'log', role: 'log', 'aria-label': 'Log tail' }); const jump = h('div', { class: 'jump', hidden: true }, L.Button({ label: '↓ Jump to latest', onClick: () => { st.follow = true; followT.control.checked = true; st.unseen = 0; scrollEnd(); jump.hidden = true; } }));
  const followT = L.Toggle({ label: 'Follow', checked: true, onChange: v => { st.follow = v; if (v) { st.unseen = 0; jump.hidden = true; scrollEnd(); } } });
  const filter = h('input', { class: 'input', placeholder: 'Filter…', 'aria-label': 'Filter log lines', onInput: () => { st.filter = filter.value.toLowerCase(); redraw(); } });
  const wrapT = L.Toggle({ label: 'Wrap', checked: false, onChange: v => { st.wrap = v; logBox.classList.toggle('wrap', v); } });
  const limitSel = h('select', { class: 'select', 'aria-label': 'Lines', onChange: () => { st.limit = +limitSel.value; savePref('lcpp.loglines', st.limit); redraw(); } }, [200, 1000, 5000].map(n => h('option', { value: n, selected: n === st.limit, text: n + ' lines' })));
  const tools = h('div', { class: 'drawer-tools' }, [followT, filter, wrapT, limitSel, L.Button({ label: 'Copy all', icon: 'copy', size: 'sm', onClick: () => copyText(visible().map(fmtLine).join('\n'), 'Copied log') }), L.Button({ label: 'Download .log', icon: 'download', size: 'sm', onClick: () => download(`${name}.log`, st.lines.map(fmtLine).join('\n')) })]);
  const head = h('div', { class: 'drawer-head' }, [title, L.Button({ icon: 'x', variant: 'ghost', title: 'Close logs', onClick: () => closeLogs() })]);
  const bodyEl = h('div', { class: 'drawer-body' }, [logBox, jump]);
  drawer.replaceChildren(head, tools, bodyEl); requestAnimationFrame(() => drawer.classList.add('open'));
  const fmtLine = l => `${new Date(l.ts * 1000).toISOString()} [${l.stream}] ${l.text}`;
  const visible = () => st.lines.slice(-st.limit).filter(l => !st.filter || l.text.toLowerCase().includes(st.filter));
  function scrollEnd() { logBox.scrollTop = logBox.scrollHeight; }
  function redraw() { const v = visible(); logBox.replaceChildren(...v.map(L.LogLine)); if (!v.length) logBox.append(h('div', { class: 'empty', style: { border: 0, padding: '32px' }, text: st.lines.length ? `No log lines match "${filter.value}"` : 'No log output yet' })); if (st.follow) scrollEnd(); }
  function push(l) { st.lines.push(l); if (st.lines.length > 5000) st.lines.shift(); if (st.filter && !l.text.toLowerCase().includes(st.filter)) return; if (st.follow) { logBox.append(L.LogLine(l)); while (logBox.children.length > st.limit) logBox.firstChild.remove(); scrollEnd(); } else { st.unseen++; jump.hidden = false; jump.querySelector('.btn').textContent = `↓ Jump to latest (${st.unseen} new)`; } }
  logBox.addEventListener('scroll', () => { const atEnd = logBox.scrollHeight - logBox.scrollTop - logBox.clientHeight < 8; if (!atEnd && st.follow) { st.follow = false; followT.control.checked = false; } else if (atEnd && !st.follow && st.unseen === 0) { /* stay paused until Follow is re-enabled */ } });
  function drawTitle() { const i = findInst(name); title.replaceChildren(h('span', { class: 'name', text: name }), i ? L.StatusDot({ state: i.state }) : h('span', { class: 'muted small', text: 'gone' })); }
  st.unsub = store.subscribe(drawTitle); drawTitle();
  api.getLogs(name, 5000).then(r => { st.lines = r.lines; redraw(); st.stream = api.streamLogs(name, push); }).catch(e => { logBox.append(h('div', { class: 'empty', style: { border: 0 }, text: e.detail })); });
  if (!fromRoute) { suppressHash = true; location.hash = `#/instances/${encodeURIComponent(name)}/logs`; currentHash = location.hash; }
  const onKey = e => { if (e.key === 'Escape' && !dialogDepth) closeLogs(); }; document.addEventListener('keydown', onKey); st.onKey = onKey;
}
function closeLogs(silent) { if (!logsState) return; const st = logsState; logsState = null; st.stream && st.stream.close(); st.unsub && st.unsub(); document.removeEventListener('keydown', st.onKey); const drawer = $('#drawer'); drawer.classList.remove('open'); setTimeout(() => { if (!logsState) { drawer.hidden = true; drawer.replaceChildren(); } }, 200); if (!silent && /\/logs$/.test(location.hash)) { suppressHash = true; location.hash = '#/instances'; currentHash = location.hash; } }
/* ============================================================
   views/models — catalog table, defaults, discovered, editor
   ============================================================ */
function renderModels(root) {
  const wrap = h('div', { class: 'view' }); root.replaceChildren(wrap); let lastKey = null; const expanded = new Set();
  const search = h('input', { class: 'input', id: 'model-search', placeholder: 'Search models  /', 'aria-label': 'Search models', style: { width: '220px' }, onInput: () => { lastKey = null; draw(); } });
  function draw() {
    const s = store.state; const key = JSON.stringify([s.models, s.discovered, instances().map(i => [i.name, i.model_id, i.models]), [...expanded], search.value]); if (key === lastKey) return; lastKey = key;
    const head = h('div', { class: 'view-head' }, [h('h1', { class: 'title', text: 'Models' }), search, L.Button({ label: 'Add model', icon: 'plus', onClick: () => openModelEditor() })]);
    if (!s.models) { wrap.replaceChildren(head, skeletonCards(2)); return; }
    const q = search.value.trim().toLowerCase(); const list = s.models.models.filter(m => !q || m.id.toLowerCase().includes(q) || m.nicknames.some(n => n.toLowerCase().includes(q)));
    const table = h('table', { class: 'table' }, [h('thead', {}, h('tr', {}, ['', 'id', 'nicknames', 'location', 'size', 'files', 'capabilities', 'ctx', 'running', ''].map(t => h('th', { scope: 'col', text: t })))), h('tbody', {}, list.flatMap(m => {
      const open = expanded.has(m.id); const running = m.running.length;
      const row = h('tr', { class: m.ok ? '' : 'is-dim' }, [h('td', {}, L.Button({ icon: open ? 'down' : 'chevron', variant: 'ghost', size: 'sm', title: open ? 'Collapse' : 'Expand files', onClick: () => { open ? expanded.delete(m.id) : expanded.add(m.id); lastKey = null; draw(); } })), h('td', {}, h('div', { class: 'row', style: { flexWrap: 'nowrap' } }, [h('span', { class: 'name', text: m.id }), m.ok ? null : L.Badge({ label: 'missing files', tone: 'red' })])), h('td', {}, h('div', { class: 'row' }, m.nicknames.map(n => L.Badge(n)))), h('td', {}, h('span', { class: 'mono small', text: m.location === 'models' ? 'models/' : m.path.slice(0, m.path.lastIndexOf('/') + 1) })), h('td', { class: 'num', text: fmtGB(m.size_bytes) }), h('td', { class: 'num', text: String(m.files.length) }), h('td', {}, h('div', { class: 'row' }, [m.capabilities.vision ? L.Badge({ label: 'vision', tone: 'cyan' }) : null, m.capabilities.speculative ? L.Badge({ label: 'spec-decode', tone: 'cyan' }) : null, m.capabilities.split ? L.Badge({ label: 'split', tone: 'purple' }) : null])), h('td', { class: 'num', text: String(m.effective['ctx-size'] || '') }), h('td', { class: 'num' }, running ? L.Badge({ label: String(running), tone: 'green' }) : h('span', { class: 'dim', text: '0' })), h('td', {}, h('div', { class: 'row', style: { flexWrap: 'nowrap', justifyContent: 'flex-end' } }, [L.Button({ label: 'Launch', icon: 'play', size: 'sm', variant: 'primary', disabled: !m.ok, title: m.ok ? '' : m.problems.join('; '), onClick: () => openLaunch({ kind: 'single', model_id: m.id }) }), L.Button({ icon: 'edit', size: 'sm', variant: 'ghost', title: 'Edit', onClick: () => openModelEditor(m) }), L.Button({ icon: 'trash', size: 'sm', variant: 'ghost', title: running ? `In use by ${m.running.join(', ')}` : 'Delete', disabled: !!running, onClick: () => deleteModel(m) })]))]);
      if (!open) return [row];
      const files = h('tr', { class: 'files' }, h('td', { colspan: '10' }, [h('div', { class: 'stack', style: { gap: '2px' } }, [...m.files.map(f => h('div', { class: 'file-row' }, [h('span', { class: 'role', text: f.role === 'split' ? `split ${f.part}` : f.role === 'model' && f.part ? `model ${f.part}` : f.role }), h('span', { text: f.path, style: { overflow: 'hidden', textOverflow: 'ellipsis' } }), h('span', { class: 'size muted', text: fmtBytes(f.size_bytes) }), h('span', { class: 'exists ' + (f.exists ? 'status-green' : 'status-red'), text: f.exists ? '✓ exists' : '✗ missing' })])), m.problems.length ? h('div', { class: 'help help-err', text: m.problems.join(' · ') }) : null, Object.keys(m.overrides).length ? h('div', { class: 'row', style: { marginTop: '6px' } }, [h('span', { class: 'section-label', text: 'overrides' }), ...Object.entries(m.overrides).map(([k, v]) => L.Badge(`${k} ${v === true ? '' : v}`.trim()))]) : null])]));
      return [row, files];
    }))]);
    const defaults = defaultsCard(s.models.defaults);
    const disc = h('section', { class: 'section' }, [h('div', { class: 'row' }, [h('h2', { class: 'card-head', style: { border: 0, padding: 0 }, text: 'Discovered GGUFs' }), h('span', { class: 'muted small', text: 'in the scan directories, not in the catalog' })]), !s.discovered ? L.Skeleton({ height: '60px' }) : !s.discovered.length ? h('div', { class: 'empty', style: { padding: '24px' }, text: 'Every GGUF in the scan directories is in the catalog.' }) : h('div', { class: 'card' }, L.Table({ columns: [{ label: 'path', cell: d => h('span', { class: 'mono small', text: d.path }) }, { label: 'size', num: true, cell: d => fmtGB(d.size_bytes) }, { label: 'suggested id', cell: d => h('code', { class: 'mono', text: d.suggested_id }) }, { label: '', cell: d => h('div', { style: { textAlign: 'right' } }, L.Button({ label: 'Add to catalog', icon: 'plus', size: 'sm', onClick: () => openModelEditor({ id: d.suggested_id, nicknames: [d.suggested_id], path: d.path, overrides: {}, files: [], isNew: true }) })) }], rows: s.discovered }))]);
    wrap.replaceChildren(head, h('div', { class: 'card table-wrap' }, list.length ? table : h('div', { class: 'empty', style: { border: 0 }, text: q ? `No models match "${search.value}"` : 'No models configured yet.' })), h('div', { class: 'grid-2', style: { alignItems: 'start' } }, [defaults, disc]));
  }
  function defaultsCard(defaults) {
    const form = { ...defaults }; let saving = false; const fields = [];
    const num = k => L.Field({ label: k, type: 'number', mono: true, value: form[k], onInput: v => { form[k] = +v; dirty(); } }); const sel = k => L.Field({ label: k, type: 'select', value: form[k], options: ['f16', 'q8_0', 'q4_0'].map(v => ({ value: v, label: v })), onChange: v => { form[k] = v; dirty(); } }); const tog = k => L.Toggle({ label: k, checked: !!form[k], onChange: v => { form[k] = v; dirty(); } });
    const saveBtn = L.Button({ label: 'Save', variant: 'primary', disabled: true, onClick: async () => { saving = true; saveBtn.classList.add('is-loading'); try { const p = await api.saveDefaults(form); store.state.models.defaults = p; toast('Model defaults saved', 'success'); lastKey = null; draw(); } catch (e) { toast(e.detail, 'error'); } finally { saving = false; saveBtn.classList.remove('is-loading'); } } });
    const revertBtn = L.Button({ label: 'Revert', disabled: true, onClick: () => { lastKey = null; draw(); } });
    const dirty = () => { const d = !deepEq(form, defaults); saveBtn.disabled = !d; revertBtn.disabled = !d; };
    return L.Card({ title: 'Model defaults', body: h('div', { class: 'stack' }, [h('p', { class: 'muted small', text: 'Applied to every model unless a per-model override says otherwise.' }), h('div', { class: 'form-grid' }, [num('ctx-size'), sel('cache-type-k'), sel('cache-type-v'), num('n-gpu-layers'), num('batch-size'), num('ubatch-size')]), h('div', { class: 'row', style: { gap: '20px' } }, [tog('flash-attn'), tog('no-mmap')])]), footer: [saveBtn, revertBtn] });
  }
  async function deleteModel(m) { if (!await confirmDialog({ title: `Delete ${m.id} from the catalog?`, html: `The entry and its nicknames (${m.nicknames.map(n => `<code class="mono">${esc(n)}</code>`).join(', ')}) are removed from lcpp. <b>The files stay on disk</b> (${fmtGB(m.size_bytes)} in ${esc(m.path.slice(0, m.path.lastIndexOf('/')))}).`, label: 'Delete' })) return; try { await api.deleteModel(m.id); toast(`Deleted ${m.id}`, 'success'); loadModels(); } catch (e) { toast(e.detail, 'error'); } }
  const unsub = store.subscribe(draw); draw(); if (!store.state.models) loadModels(); else loadModels();
  return { destroy() { unsub(); }, focusSearch() { search.focus(); search.select(); } };
}

function openModelEditor(m = null) {
  const isNew = !m || m.isNew; const disc = store.state.discovered || []; const known = [...new Set([...disc.map(d => d.path), ...((store.state.models && store.state.models.models) || []).flatMap(x => x.files.map(f => f.path))])];
  const input = { id: m ? m.id : '', nicknames: m ? [...m.nicknames] : [], path: m ? m.path : '', mmproj: m && m.overrides ? m.overrides.mmproj || '' : '', draft: m && m.overrides ? m.overrides['model-draft'] || '' : '', spec_type: m && m.overrides ? m.overrides['spec-type'] || '' : '', overrides: m && m.overrides ? Object.fromEntries(Object.entries(m.overrides).filter(([k]) => !['mmproj', 'model-draft', 'spec-type'].includes(k))) : {} };
  let result = null;
  const dl = h('datalist', { id: 'gguf-list' }, known.map(p => h('option', { value: p })));
  const idF = L.Field({ label: 'id', mono: true, value: input.id, disabled: !isNew, help: 'unique slug', onInput: v => { input.id = v.trim(); check(); } });
  const nickBox = h('div', { class: 'field' }, [h('span', { class: 'label', text: 'nicknames' }), chipInput({ values: input.nicknames, onChange: v => { input.nicknames = v; check(); } })]);
  const pathF = L.Field({ label: 'model file', mono: true, value: input.path, placeholder: 'models/…/model.gguf', onInput: v => { input.path = v.trim(); check(); } }); pathF.control.setAttribute('list', 'gguf-list');
  const mmF = L.Field({ label: 'mmproj file', optional: true, mono: true, value: input.mmproj, onInput: v => { input.mmproj = v.trim(); check(); } }); mmF.control.setAttribute('list', 'gguf-list');
  const draftF = L.Field({ label: 'draft model file', optional: true, mono: true, value: input.draft, onInput: v => { input.draft = v.trim(); check(); } }); draftF.control.setAttribute('list', 'gguf-list');
  const specF = L.Field({ label: 'speculative type', type: 'select', value: input.spec_type, options: [{ value: '', label: 'none' }, { value: 'draft-mtp', label: 'draft-mtp' }, { value: 'draft', label: 'draft' }], onChange: v => { input.spec_type = v; check(); } });
  const ov = kvEditor({ rows: paramsToRows(input.overrides), keyPlaceholder: 'param (ctx-size, n-gpu-layers…)', onChange: rows => { input.overrides = rowsToParams(rows); } });
  const filesBox = h('div', { class: 'stack', style: { gap: '2px' } }); const errBox = h('div', { class: 'help help-err' });
  const saveBtn = L.Button({ label: isNew ? 'Add model' : 'Save', variant: 'primary', onClick: save });
  const payload = () => ({ id: input.id, nicknames: input.nicknames, path: input.path, mmproj: input.mmproj || null, draft: input.draft || null, spec_type: input.draft ? (input.spec_type || 'draft') : null, overrides: input.overrides });
  const check = debounce(async () => { try { result = await api.validateModel(payload()); filesBox.replaceChildren(...result.files.map(f => h('div', { class: 'file-row' }, [h('span', { class: 'role', text: f.role === 'split' || (f.role === 'model' && f.part) ? `${f.role} ${f.part}` : f.role }), h('span', { text: f.path, style: { overflow: 'hidden', textOverflow: 'ellipsis' } }), h('span', { class: 'size muted', text: fmtBytes(f.size_bytes) }), h('span', { class: 'exists ' + (f.exists ? 'status-green' : 'status-red'), text: f.exists ? '✓ exists' : '✗ not found' })]))); const sp = result.files.filter(f => f.part); if (sp.length) filesBox.append(h('div', { class: 'help ' + (sp.every(f => f.exists) ? 'help-ok' : 'help-err'), text: `split 1 of ${sp.length} — ${sp.every(f => f.exists) ? 'all parts present' : sp.filter(f => !f.exists).length + ' part(s) missing'}` })); errBox.textContent = result.errors.join(' · '); pathF.setHelp(result.files[0] && result.files[0].exists ? 'ok' : input.path ? 'err' : '', result.files[0] && result.files[0].exists ? `exists, ${fmtBytes(result.files[0].size_bytes)}` : input.path ? 'not found' : ''); saveBtn.disabled = !result.ok; } catch (e) { if (e.status !== 0) toast(e.detail, 'error'); } }, 300);
  async function save() { saveBtn.classList.add('is-loading'); try { await api.saveModel(payload()); toast(`${isNew ? 'Added' : 'Saved'} ${input.id}`, 'success'); d.close('ok'); loadModels(); } catch (e) { toast(e.detail, 'error'); errBox.textContent = e.detail; } finally { saveBtn.classList.remove('is-loading'); } }
  const d = L.Dialog({ title: isNew ? 'Add model to catalog' : `Edit ${m.id}`, body: h('div', { class: 'stack', style: { gap: '14px' } }, [dl, h('div', { class: 'form-grid' }, [idF, specF]), nickBox, pathF, h('div', { class: 'form-grid' }, [mmF, draftF]), h('div', { class: 'stack', style: { gap: '6px' } }, [sectionLabel('Files'), h('div', { class: 'inset' }, filesBox), errBox]), h('div', { class: 'stack', style: { gap: '6px' } }, [sectionLabel('Per-model overrides'), ov])]), actions: [L.Button({ label: 'Cancel', onClick: () => d.close('cancel') }), saveBtn] }); d.style.width = 'min(720px, calc(100vw - 32px))';
  d.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); if (!saveBtn.disabled) save(); } });
  openDialog(d); check();
}
/* ============================================================
   views/playground — chat against an instance or via Relay
   ============================================================ */
function renderPlayground(root, route) {
  const wrap = h('div', { class: 'view' }); root.replaceChildren(wrap);
  const st = { target: null, messages: [], system: '', temp: 0.7, top_p: 0.95, max_tokens: 512, reasoning: false, ctrl: null, tab: 'chat' };
  const targetSel = h('select', { class: 'select', 'aria-label': 'Target', style: { width: 'auto', minWidth: '240px' }, onChange: () => { st.target = JSON.parse(targetSel.value || 'null'); drawSnippets(); } });
  const sysTA = h('textarea', { class: 'textarea', placeholder: 'System prompt (optional)', 'aria-label': 'System prompt', onInput: () => { st.system = sysTA.value; } });
  const msgs = h('div', { class: 'msgs', role: 'log', 'aria-live': 'polite' }); const composer = h('textarea', { class: 'textarea', placeholder: 'Message… (Enter to send, Shift+Enter for a new line)', 'aria-label': 'Message', rows: '1', onKeydown: e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } } });
  const sendBtn = L.Button({ label: 'Send', variant: 'primary', icon: 'play', onClick: send }); const stopBtn = L.Button({ label: 'Stop', variant: 'danger', icon: 'square', onClick: () => st.ctrl && st.ctrl.abort() }); stopBtn.hidden = true;
  const clearBtn = L.Button({ label: 'Clear', variant: 'ghost', size: 'sm', onClick: () => { st.messages = []; msgs.replaceChildren(); } });
  const tempF = L.Field({ label: 'temperature', type: 'number', mono: true, value: st.temp, step: 0.05, min: 0, max: 2, onInput: v => { st.temp = +v; drawSnippets(); } }); const topF = L.Field({ label: 'top_p', type: 'number', mono: true, value: st.top_p, step: 0.05, min: 0, max: 1, onInput: v => { st.top_p = +v; drawSnippets(); } }); const maxF = L.Field({ label: 'max_tokens', type: 'number', mono: true, value: st.max_tokens, min: 1, onInput: v => { st.max_tokens = +v; drawSnippets(); } }); const reasonT = L.Toggle({ label: 'Reasoning', checked: false, onChange: v => { st.reasoning = v; drawSnippets(); } });
  const snipTabs = L.Tabs({ value: 'curl', tabs: [{ value: 'curl', label: 'curl' }, { value: 'python', label: 'Python' }, { value: 'js', label: 'JavaScript' }], onChange: v => { st.snip = v; drawSnippets(); } }); st.snip = 'curl'; const snipCode = h('pre', { class: 'code' }); const snipCopy = L.Button({ icon: 'copy', variant: 'ghost', size: 'sm', title: 'Copy snippet', onClick: () => copyText(snipCode.textContent, 'Copied snippet') });
  const side = h('div', { class: 'stack' }, [L.Card({ title: 'Sampling', body: h('div', { class: 'stack' }, [tempF, topF, maxF, reasonT]) }), L.Card({ title: 'Code snippet', actions: [snipCopy], body: h('div', { class: 'stack' }, [snipTabs, snipCode]) })]);
  const sysDetails = h('details', { class: 'adv', style: { padding: '0 16px' } }, [h('summary', { text: 'System prompt' }), h('div', { class: 'stack' }, sysTA)]);
  const chat = h('div', { class: 'card chat' }, [h('div', { class: 'card-head' }, [h('div', { class: 'row' }, [h('span', { class: 'label', text: 'Target' }), targetSel]), clearBtn]), sysDetails, msgs, h('div', { class: 'composer' }, [composer, sendBtn, stopBtn])]);
  const emptyBox = h('div'); wrap.append(h('div', { class: 'view-head' }, [h('h1', { class: 'title', text: 'Playground' })]), emptyBox, h('div', { class: 'play' }, [chat, side]));
  function request(msgList) { const r = { model: st.target && st.target.type === 'relay' ? st.target.model : (st.target && (findInst(st.target.name) || {}).relay && findInst(st.target.name).relay.alias) || (st.target && (findInst(st.target.name) || {}).model_id) || 'default', messages: [...(st.system ? [{ role: 'system', content: st.system }] : []), ...msgList], temperature: st.temp, top_p: st.top_p, max_tokens: st.max_tokens, stream: true }; r.chat_template_kwargs = { enable_thinking: st.reasoning }; return r; }
  function targetUrl() { if (!st.target) return 'http://127.0.0.1:PORT/v1'; if (st.target.type === 'relay') return (store.state.overview && store.state.overview.relay.url) + '/v1'; const i = findInst(st.target.name); return i ? i.url : 'http://127.0.0.1:PORT/v1'; }
  function drawSnippets() { const url = targetUrl(); const body = request([{ role: 'user', content: 'Hello' }]); const j = JSON.stringify(body, null, 2); const s = st.snip === 'curl' ? `curl ${url}/chat/completions \\\n  -H 'Content-Type: application/json' \\\n  -d '${j.replace(/'/g, "'\\''")}'` : st.snip === 'python' ? `from openai import OpenAI\n\nclient = OpenAI(base_url="${url}", api_key="none")\nstream = client.chat.completions.create(\n    model=${JSON.stringify(body.model)},\n    messages=[{"role": "user", "content": "Hello"}],\n    temperature=${st.temp}, top_p=${st.top_p}, max_tokens=${st.max_tokens},\n    extra_body={"chat_template_kwargs": {"enable_thinking": ${st.reasoning ? 'True' : 'False'}}},\n    stream=True,\n)\nfor chunk in stream:\n    print(chunk.choices[0].delta.content or "", end="", flush=True)` : `const res = await fetch("${url}/chat/completions", {\n  method: "POST",\n  headers: { "Content-Type": "application/json" },\n  body: JSON.stringify(${j.replace(/\n/g, '\n  ')}),\n});\nconst reader = res.body.getReader();\nconst dec = new TextDecoder();\nfor (;;) {\n  const { done, value } = await reader.read();\n  if (done) break;\n  process.stdout.write(dec.decode(value));\n}`; snipCode.textContent = s; }
  function drawTargets() {
    const ready = instances().filter(i => i.state === 'ready'); const relay = store.state.relay; const relayOk = store.state.overview && store.state.overview.relay.reachable; const routable = relayOk && relay ? relay.routable_models : [];
    const cur = targetSel.value; targetSel.replaceChildren(h('optgroup', { label: 'Instances (direct)' }, ready.length ? ready.map(i => h('option', { value: JSON.stringify({ type: 'instance', name: i.name }), text: `${i.name} — 127.0.0.1:${i.port}` })) : [h('option', { value: '', disabled: true, text: 'no ready instances' })]), h('optgroup', { label: 'via Relay' }, routable.length ? routable.map(m => h('option', { value: JSON.stringify({ type: 'relay', model: m }), text: `${m} — via Relay` })) : [h('option', { value: '', disabled: true, text: relayOk ? 'no routable models' : 'Relay unreachable' })]));
    if ([...targetSel.options].some(o => o.value === cur)) targetSel.value = cur; else { const want = route.q.instance ? JSON.stringify({ type: 'instance', name: route.q.instance }) : null; const first = [...targetSel.options].find(o => o.value && (!want || o.value === want)) || [...targetSel.options].find(o => o.value); targetSel.value = first ? first.value : ''; }
    st.target = JSON.parse(targetSel.value || 'null');
    const none = !ready.length && !routable.length; chat.hidden = none; side.hidden = none; emptyBox.replaceChildren(...(none ? [L.EmptyState({ icon: 'chat', title: 'Nothing to talk to yet.', body: 'Launch a model and it will show up here once it is ready.', actions: [L.Button({ label: 'Launch a model', icon: 'plus', variant: 'primary', onClick: () => openLaunch() })] })] : [])); drawSnippets();
  }
  function bubble(role) { const b = h('div', { class: 'msg ' + role }); msgs.append(b); msgs.scrollTop = msgs.scrollHeight; return b; }
  async function send() {
    const text = composer.value.trim(); if (!text || st.ctrl || !st.target) return; composer.value = ''; st.messages.push({ role: 'user', content: text }); bubble('user').textContent = text;
    const b = bubble('assistant'); const think = h('details', { class: 'think' }, [h('summary', { text: 'Thinking' }), h('div', { class: 'body' })]); const body = h('span'); const caret = h('span', { class: 'caret', 'aria-hidden': 'true' }); b.append(body, caret);
    let content = '', reasoning = ''; st.ctrl = new AbortController(); sendBtn.hidden = true; stopBtn.hidden = false;
    try {
      const metrics = await api.chat(st.target, request(st.messages), chunk => { const d = (chunk.choices && chunk.choices[0] && chunk.choices[0].delta) || {}; if (d.reasoning_content) { if (!think.isConnected) b.prepend(think); reasoning += d.reasoning_content; think.querySelector('.body').textContent = reasoning; } if (d.content) { content += d.content; body.textContent = content; } msgs.scrollTop = msgs.scrollHeight; }, st.ctrl.signal);
      st.messages.push({ role: 'assistant', content }); if (metrics) b.append(h('div', { class: 'metrics' }, [h('span', { text: `ttft ${metrics.ttft_ms} ms` }), h('span', { text: `${metrics.tokens_per_s} tok/s` }), h('span', { text: `${metrics.prompt_tokens} prompt` }), h('span', { text: `${metrics.completion_tokens} completion` }), h('span', { text: `${(metrics.total_ms / 1000).toFixed(2)} s total` })]));
    } catch (e) { if (e.name === 'AbortError') { b.append(h('div', { class: 'metrics' }, h('span', { text: 'stopped' }))); if (content) st.messages.push({ role: 'assistant', content }); } else { b.classList.add('error'); b.append(h('div', { class: 'metrics status-red' }, h('span', { text: e.detail || String(e) }))); if (e.status !== 0) toast(e.detail, 'error'); } }
    finally { caret.remove(); st.ctrl = null; sendBtn.hidden = false; stopBtn.hidden = true; composer.focus(); }
  }
  const unsub = store.subscribe(drawTargets); drawTargets(); loadRelay(); if (!store.state.models) loadModels();
  return { destroy() { unsub(); st.ctrl && st.ctrl.abort(); } };
}
/* ============================================================
   views/relay — connection, registrations, orphans, others, publish
   ============================================================ */
function renderRelay(root) {
  const wrap = h('div', { class: 'view' }); root.replaceChildren(wrap); let lastKey = null; let editing = null;
  function draw() {
    const s = store.state; const r = s.relay; const ov = s.overview; const key = JSON.stringify([r, ov && ov.relay, instances().map(i => [i.name, i.state, i.relay]), editing]); if (key === lastKey) return; lastKey = key;
    const head = h('div', { class: 'view-head' }, [h('h1', { class: 'title', text: 'Relay' })]);
    if (!r) { wrap.replaceChildren(head, skeletonCards(2)); return; }
    const status = r.status; const testBtn = L.Button({ label: 'Test connection', icon: 'bolt', onClick: async () => { testBtn.classList.add('is-loading'); try { const st = await api.testRelay(); toast(st.reachable ? `Relay reachable in ${st.latency_ms} ms` : st.error, st.reachable ? 'success' : 'error'); loadRelay(); refreshOverview(); } catch (e) { toast(e.detail, 'error'); } finally { testBtn.classList.remove('is-loading'); } } });
    const conn = L.Card({ title: 'Connection', class: 'about', actions: [testBtn], body: h('dl', {}, [h('dt', { text: 'URL' }), h('dd', { text: status.url }), h('dt', { text: 'Reachability' }), h('dd', {}, L.StatusDot({ tone: status.reachable ? 'green' : 'red', pulse: false, label: status.reachable ? 'reachable' : 'unreachable' + (status.error ? ' · ' + status.error : '') })), h('dt', { text: 'Latency' }), h('dd', { text: status.latency_ms == null ? '—' : status.latency_ms + ' ms' }), h('dt', { text: 'Version' }), h('dd', { text: status.version || 'unknown' })]), footer: [h('a', { href: status.dashboard_url, target: '_blank', rel: 'noopener', text: 'Open Relay dashboard ↗' })] });
    const orphans = r.owned.filter(x => x.orphan);
    const regTable = L.Table({ columns: [{ label: 'key', cell: x => h('code', { class: 'mono', text: x.key }) }, { label: 'instance', cell: x => x.orphan ? h('span', { class: 'status status-amber' }, [Icon('alert'), 'orphan — instance gone']) : h('span', { class: 'name', text: x.instance }) }, { label: 'alias', cell: x => editing === x.key ? aliasEditor(x) : h('div', { class: 'row', style: { flexWrap: 'nowrap' } }, [L.Badge({ label: x.alias || '—', tone: 'cyan' }), x.orphan ? null : L.Button({ icon: 'edit', size: 'sm', variant: 'ghost', title: 'Change alias', onClick: () => { editing = x.key; lastKey = null; draw(); } })]) }, { label: 'models', cell: x => h('span', { class: 'mono small', text: x.models.join(', ') }) }, { label: 'health', cell: x => L.StatusDot({ state: x.health }) }, { label: 'registered', num: true, cell: x => ago(x.registered_ts) }, { label: '', cell: x => h('div', { style: { textAlign: 'right' } }, x.orphan ? L.Button({ label: 'Remove', icon: 'trash', size: 'sm', variant: 'danger', onClick: () => removeReg(x) }) : L.Button({ label: 'Unpublish', size: 'sm', variant: 'danger', onClick: () => unpublish(x) })) }], rows: r.owned });
    $$('tbody tr', regTable).forEach((tr, k) => { if (r.owned[k].orphan) tr.style.background = 'var(--accent-soft)'; });
    const regs = L.Card({ title: 'Registrations managed by lcpp', actions: orphans.length ? [L.Button({ label: `Clean up ${orphans.length} orphan${orphans.length > 1 ? 's' : ''}`, size: 'sm', variant: 'danger', onClick: cleanup })] : [], body: r.owned.length ? regTable : h('div', { class: 'empty', style: { border: 0, padding: '24px' }, text: 'No registrations. Publish an instance to make it routable through Relay.' }) }); regs.querySelector('.card-body').style.padding = r.owned.length ? '0' : '';
    const others = L.Card({ title: 'Other relay endpoints', body: r.others.length ? L.Table({ columns: [{ label: 'name', cell: o => h('span', { class: 'name', text: o.name }) }, { label: 'alias', cell: o => o.alias ? L.Badge(o.alias) : h('span', { class: 'dim', text: '—' }) }, { label: 'server type', cell: o => h('span', { class: 'mono small', text: o.server_type }) }, { label: 'health', cell: o => L.StatusDot({ state: o.health }) }, { label: 'base url', cell: o => h('code', { class: 'mono', text: o.base_url }) }], rows: r.others.map(o => ({ ...o, class: 'is-dim' })) }) : h('div', { class: 'empty', style: { border: 0, padding: '24px' }, text: 'Relay has no endpoints other than lcpp’s.' }) }); others.querySelector('.card-body').style.padding = r.others.length ? '0' : '';
    const cands = instances().filter(i => i.state === 'ready' && i.relay.state === 'off'); const pubSel = h('select', { class: 'select', 'aria-label': 'Instance', style: { width: 'auto', minWidth: '220px' } }, cands.length ? cands.map(i => h('option', { value: i.name, text: `${i.name} — ${i.model_id || 'router'}` })) : [h('option', { value: '', text: 'no unpublished ready instances' })]); const aliasIn = h('input', { class: 'input mono', placeholder: 'alias', 'aria-label': 'Alias', style: { width: '200px' } }); const syncAlias = () => { const i = findInst(pubSel.value); aliasIn.placeholder = i ? (i.model_id ? modelLabel(i.model_id).nick : i.name) : 'alias'; }; pubSel.addEventListener('change', syncAlias); syncAlias();
    const pubBtn = L.Button({ label: 'Publish', variant: 'primary', icon: 'relay', disabled: !cands.length || !status.reachable, title: status.reachable ? '' : 'Relay unreachable', onClick: async () => { const name = pubSel.value; const alias = aliasIn.value.trim() || aliasIn.placeholder; pubBtn.classList.add('is-loading'); try { replaceInstance(await api.publish(name, alias)); toast(`Publishing ${name} as "${alias}"`, 'success'); loadRelay(); refreshOverview(); } catch (e) { toast(e.detail, 'error'); } finally { pubBtn.classList.remove('is-loading'); } } });
    const publish = L.Card({ title: 'Publish an instance', body: h('div', { class: 'row' }, [pubSel, aliasIn, pubBtn]) });
    wrap.replaceChildren(head, h('div', { class: 'grid-2', style: { alignItems: 'start' } }, [conn, publish]), regs, others);
  }
  function aliasEditor(x) { const inp = h('input', { class: 'input mono', value: x.alias || '', 'aria-label': 'Alias', style: { width: '160px', height: '26px' }, onKeydown: e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') { editing = null; lastKey = null; draw(); } } }); async function commit() { const alias = inp.value.trim(); if (!alias || alias === x.alias) { editing = null; lastKey = null; draw(); return; } try { replaceInstance(await api.publish(x.instance, alias)); toast(`Alias changed to "${alias}"`, 'success'); } catch (e) { toast(e.detail, 'error'); } editing = null; loadRelay(); } const box = h('div', { class: 'row', style: { flexWrap: 'nowrap' } }, [inp, L.Button({ icon: 'check', size: 'sm', title: 'Save alias', onClick: commit }), L.Button({ icon: 'x', size: 'sm', variant: 'ghost', title: 'Cancel', onClick: () => { editing = null; lastKey = null; draw(); } })]); setTimeout(() => inp.focus(), 0); return box; }
  async function unpublish(x) { if (!await confirmDialog({ title: `Unpublish ${x.instance}?`, html: `Registration <code class="mono">${esc(x.key)}</code> (alias <code class="mono">${esc(x.alias)}</code>) will be removed from Relay. The server keeps running.`, label: 'Unpublish' })) return; try { await api.unpublish(x.instance); toast(`Unpublished ${x.instance}`, 'success'); } catch (e) { toast(e.detail, 'error'); } loadRelay(); refreshOverview(); }
  async function removeReg(x) { if (!await confirmDialog({ title: `Remove orphan ${x.key}?`, html: `The registration for alias <code class="mono">${esc(x.alias)}</code> has no running instance. It will be deleted from Relay.`, label: 'Remove' })) return; try { await api.removeRegistration(x.key); toast(`Removed ${x.key}`, 'success'); } catch (e) { toast(e.detail, 'error'); } loadRelay(); }
  async function cleanup() { const n = store.state.relay.owned.filter(x => x.orphan).length; if (!await confirmDialog({ title: `Clean up ${n} orphan registration${n > 1 ? 's' : ''}?`, html: 'Every lcpp registration on Relay whose instance no longer exists will be deleted.', label: 'Clean up' })) return; try { const r = await api.cleanupOrphans(); toast(`Removed ${r.removed.length} orphan${r.removed.length === 1 ? '' : 's'}`, 'success'); } catch (e) { toast(e.detail, 'error'); } loadRelay(); }
  const unsub = store.subscribe(draw); draw(); loadRelay(); if (!store.state.models) loadModels();
  return { destroy() { unsub(); } };
}

/* ============================================================
   views/settings — one form, Save / Revert, restart-required notes
   ============================================================ */
function renderSettings(root) {
  const wrap = h('div', { class: 'view' }); root.replaceChildren(wrap); let form = null, saved = null, note = null;
  function draw() {
    const s = store.state.settings; const sys = store.state.overview && store.state.overview.system;
    if (!s) { wrap.replaceChildren(h('div', { class: 'view-head' }, h('h1', { class: 'title', text: 'Settings' })), skeletonCards(2)); return; }
    if (!form) { form = clone(s); saved = clone(s); }
    const restart = h('span', { class: 'badge badge-accent', text: 'restart required', title: 'Takes effect after lcpp service restart' });
    const num = (label, get, set, extra = {}) => L.Field({ label, type: 'number', mono: true, value: get(), ...extra, onInput: v => { set(+v); dirty(); } });
    const txt = (label, get, set, extra = {}) => L.Field({ label, mono: true, value: get(), ...extra, onInput: v => { set(v.trim()); dirty(); } });
    const daemon = L.Card({ title: 'Daemon', body: h('div', { class: 'stack' }, [h('div', { class: 'form-grid' }, [(() => { const f = num('port', () => form.daemon.port, v => form.daemon.port = v, { min: 1024, max: 65535 }); f.querySelector('.label').append(restart); return f; })()]), h('p', { class: 'help', text: 'Bound to 127.0.0.1 — this machine only.' })]) });
    const envEd = kvEditor({ rows: Object.entries(form.llama.environment).map(([key, value]) => ({ key, value })), keyPlaceholder: 'VAR', valuePlaceholder: 'value', onChange: rows => { form.llama.environment = Object.fromEntries(rows.map(r => [r.key, r.value])); dirty(); } });
    const spEd = kvEditor({ rows: paramsToRows(form.llama.server_params), keyPlaceholder: 'param', onChange: rows => { form.llama.server_params = rowsToParams(rows); dirty(); } });
    const llama = L.Card({ title: 'llama.cpp', body: h('div', { class: 'stack', style: { gap: '14px' } }, [h('div', { class: 'form-grid' }, [(() => { const f = txt('binary path', () => form.llama.binary, v => form.llama.binary = v, { disabled: true }); f.setHelp(sys && sys.llama.binary_ok ? 'ok' : '', sys ? (sys.llama.binary_ok ? 'found' : 'not found') : ''); return f; })(), L.Field({ label: 'build', mono: true, value: sys ? sys.llama.build : '', disabled: true })]), h('div', { class: 'stack', style: { gap: '6px' } }, [h('div', { class: 'row' }, [sectionLabel('Environment variables'), restart.cloneNode(true)]), envEd]), h('div', { class: 'stack', style: { gap: '6px' } }, [sectionLabel('Server params applied to every instance'), h('p', { class: 'help', text: 'New instances pick these up; running ones keep theirs until restarted.' }), spEd])]) });
    const ports = L.Card({ title: 'Ports', body: h('div', { class: 'form-grid' }, [num('range start', () => form.ports.start, v => form.ports.start = v, { min: 1024, max: 65535 }), num('range end', () => form.ports.end, v => form.ports.end = v, { min: 1024, max: 65535 })]) });
    const testBtn = L.Button({ label: 'Test', icon: 'bolt', size: 'sm', onClick: async () => { testBtn.classList.add('is-loading'); try { const st = await api.testRelay(); toast(st.reachable ? `Relay reachable in ${st.latency_ms} ms` : st.error, st.reachable ? 'success' : 'error'); } catch (e) { toast(e.detail, 'error'); } finally { testBtn.classList.remove('is-loading'); } } });
    const relay = L.Card({ title: 'Relay', actions: [testBtn], body: h('div', { class: 'stack' }, [h('div', { class: 'form-grid' }, [txt('URL', () => form.relay.url, v => form.relay.url = v), txt('dashboard URL', () => form.relay.dashboard_url, v => form.relay.dashboard_url = v)]), L.Toggle({ label: 'Auto-publish new instances to Relay', checked: form.relay.auto_register, tone: 'cyan', onChange: v => { form.relay.auto_register = v; dirty(); } })]) });
    const dirs = h('div', { class: 'stack', style: { gap: '6px' } }); const drawDirs = () => dirs.replaceChildren(...form.scan_dirs.map((d, k) => h('div', { class: 'input-row' }, [h('input', { class: 'input mono', value: d, 'aria-label': 'Scan directory', onInput: e => { form.scan_dirs[k] = e.target.value; dirty(); } }), L.Button({ icon: 'x', variant: 'ghost', size: 'sm', title: 'Remove', onClick: () => { form.scan_dirs.splice(k, 1); drawDirs(); dirty(); } })])), L.Button({ label: 'Add directory', icon: 'plus', size: 'sm', variant: 'ghost', onClick: () => { form.scan_dirs.push(''); drawDirs(); dirty(); dirs.querySelector('.input-row:last-of-type input').focus(); } })); drawDirs();
    const scan = L.Card({ title: 'Scan directories', body: h('div', { class: 'stack' }, [h('p', { class: 'help', text: 'Folders searched for GGUF files to suggest in the Models view.' }), dirs]) });
    const iface = L.Card({ title: 'Interface', body: h('div', { class: 'stack' }, [h('div', { class: 'field' }, [h('span', { class: 'label', text: 'Theme' }), L.Segmented({ label: 'Theme', size: 'sm', value: store.state.theme, options: [{ value: 'system', label: 'System' }, { value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }], onChange: setTheme })]), h('div', { class: 'field' }, [h('span', { class: 'label', text: 'Default instances layout' }), L.Segmented({ label: 'Layout', size: 'sm', value: store.state.layout, options: [{ value: 'grid', label: 'Grid', icon: 'grid' }, { value: 'list', label: 'List', icon: 'list' }], onChange: v => { savePref('lcpp.layout', v); store.set({ layout: v }); } })]), h('div', { class: 'field' }, [h('span', { class: 'label', text: 'Poll interval' }), h('p', { class: 'help', text: '2 s while an instance is starting or stopping, otherwise 10 s; never while this tab is hidden.' })])]) });
    const about = L.Card({ title: 'About', class: 'about', body: h('div', { class: 'stack' }, [h('dl', {}, [h('dt', { text: 'lcpp' }), h('dd', { text: sys ? sys.daemon.version : '—' }), h('dt', { text: 'daemon pid' }), h('dd', { text: sys ? String(sys.daemon.pid) : '—' }), h('dt', { text: 'uptime' }), h('dd', { text: sys ? fmtDur(sys.daemon.uptime_s) : '—' }), h('dt', { text: 'daemon memory' }), h('dd', { text: sys ? fmtBytes(sys.daemon.rss_bytes) : '—' }), h('dt', { text: 'mode' }), h('dd', { text: LIVE ? 'live (' + (BASE || location.origin) + ')' : 'mock' })]), sectionLabel('CLI equivalents'), h('pre', { class: 'code', text: 'lcpp status\nlcpp start <model> --port N\nlcpp stop <name|port|all>\nlcpp logs <name> -f\nlcpp service start' })]) });
    const saveBtn = L.Button({ label: 'Save', variant: 'primary', disabled: true, onClick: save }); const revertBtn = L.Button({ label: 'Revert', disabled: true, onClick: () => { form = clone(saved); dirtyGuard = null; note = null; draw(); } });
    const bar = h('div', { class: 'row', style: { justifyContent: 'flex-end' } }, [note ? L.Banner({ kind: 'info', message: note }) : null, h('span', { class: 'spacer', style: { flex: 1 } }), revertBtn, saveBtn]);
    wrap.replaceChildren(h('div', { class: 'view-head' }, [h('h1', { class: 'title', text: 'Settings' }), h('span', { class: 'muted small', text: 'data/lcpp.json' })]), bar, h('div', { class: 'grid-2', style: { alignItems: 'start' } }, [daemon, ports, relay, scan, llama, iface, about]));
    function dirty() { const d = !deepEq(form, saved); saveBtn.disabled = !d; revertBtn.disabled = !d; dirtyGuard = d ? () => true : null; }
    async function save() { saveBtn.classList.add('is-loading'); try { const r = await api.saveSettings(form); saved = clone(r.settings); form = clone(r.settings); store.state.settings = clone(r.settings); dirtyGuard = null; note = r.restart_required ? 'Saved. The daemon port change takes effect after `lcpp service restart`.' : null; toast('Settings saved', 'success'); draw(); } catch (e) { toast(e.detail, 'error'); } finally { saveBtn.classList.remove('is-loading'); } }
  }
  const unsub = store.subscribe(() => { if (!form) draw(); }); draw(); if (!store.state.settings) loadSettings();
  return { destroy() { unsub(); dirtyGuard = null; } };
}
/* ============================================================
   app — shell, header, nav, theme, shortcuts, help, dev panel
   ============================================================ */
const NAV = [{ view: 'instances', label: 'Instances', icon: 'cpu', key: 'i' }, { view: 'models', label: 'Models', icon: 'box', key: 'm' }, { view: 'playground', label: 'Playground', icon: 'chat', key: 'p' }, { view: 'relay', label: 'Relay', icon: 'relay', key: 'r' }, { view: 'settings', label: 'Settings', icon: 'settings', key: 's' }];
const RENDER = { instances: renderInstances, models: renderModels, playground: renderPlayground, relay: renderRelay, settings: renderSettings };
let current = null, currentView = null;
const mq = window.matchMedia('(prefers-color-scheme: dark)');
function applyTheme() { const t = store.state.theme; const dark = t === 'dark' || (t === 'system' && mq.matches); document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light'); }
function setTheme(t) { savePref('lcpp.theme', t); store.set({ theme: t }); applyTheme(); }
mq.addEventListener('change', applyTheme);

function renderRoute() {
  const r = parseHash(); closeMenu(); $('#app').classList.remove('nav-open'); $('#menu-btn').setAttribute('aria-expanded', 'false');
  if (r.view !== 'instances') closeLogs(true);
  if (currentView !== r.view) { current && current.destroy && current.destroy(); current = RENDER[r.view]($('#view'), r); currentView = r.view; document.title = `${NAV.find(n => n.view === r.view).label} · lcpp`; window.scrollTo(0, 0); }
  else if (r.view === 'instances' && r.parts[2] === 'logs') openLogs(decodeURIComponent(r.parts[1]), true);
  else if (r.view === 'instances' && logsState && !r.parts[2]) closeLogs(true);
  drawNav();
}
function drawNav() { const r = parseHash(); const n = $('#nav'); n.replaceChildren(...NAV.map(x => L.NavItem({ label: x.label, href: '#/' + x.view, icon: x.icon, current: r.view === x.view, count: x.view === 'instances' ? (instances().length || null) : x.view === 'models' ? ((store.state.models && store.state.models.models.length) || null) : null }))); }
let headerKey = null;
function drawHeader() {
  const s = store.state; const ov = s.overview; const hd = $('#header'); const running = instances().filter(i => i.state !== 'failed').length;
  const key = JSON.stringify([ov && ov.system.memory, ov && ov.system.gpu, ov && ov.relay, ov && ov.system.daemon.version, running, s.daemonDown, s.loaded]); if (key === headerKey) return; headerKey = key;
  const stopAll = L.Button({ label: 'Stop all', icon: 'square', variant: 'danger', disabled: !running, onClick: async () => { const names = instances().filter(i => i.state !== 'failed').map(i => i.name); if (!await confirmDialog({ title: `Stop all ${names.length} instance${names.length > 1 ? 's' : ''}?`, html: `<code class="mono">${names.map(esc).join('</code>, <code class="mono">')}</code> will be stopped. Every Relay registration they hold will be removed.`, label: 'Stop all' })) return; const rb = names.map(n => patchInstance(n, { state: 'stopping' })); try { await api.stopAll(); toast('Stopping all instances…', 'success'); } catch (e) { rb.forEach(f => f()); toast(e.detail, 'error'); } refreshOverview(); } });
  stopAll.querySelector('svg').after(h('span', { class: 'lbl' })); stopAll.lastChild.remove(); stopAll.append(h('span', { class: 'lbl', text: 'Stop all' }));
  const launch = L.Button({ icon: 'plus', variant: 'primary', title: 'Launch (n)', onClick: () => openLaunch() }); launch.append(h('span', { class: 'lbl', text: 'Launch' })); launch.classList.remove('btn-icon');
  const meters = ov ? [L.MemoryMeter({ label: 'RAM', used: ov.system.memory.used_bytes, total: ov.system.memory.total_bytes }), ov.system.gpu ? L.MemoryMeter({ label: 'GTT', used: ov.system.gpu.gtt_used_bytes, total: ov.system.gpu.gtt_total_bytes }) : null] : [L.Skeleton({ height: '16px' }), L.Skeleton({ height: '16px' })];
  hd.replaceChildren(h('div', { class: 'meters' }, meters), h('div', { class: 'stats' }, [h('span', { class: 'running' }, [Icon('cpu'), h('b', { text: String(running) }), h('span', { class: 'lbl', text: running === 1 ? 'instance running' : 'instances running' })]), ov ? L.RelayPill({ reachable: ov.relay.reachable, title: ov.relay.reachable ? `${ov.relay.url} · ${ov.relay.latency_ms} ms` : ov.relay.error || 'unreachable' }) : null]), h('span', { class: 'spacer' }), h('div', { class: 'actions' }, [launch, stopAll]));
  const ds = $('#daemon-status'); if (ov) ds.replaceChildren(h('span', { class: 'dot dot-green' }), h('span', { text: 'daemon' }), h('span', { class: 'mono', text: 'v' + ov.system.daemon.version + ' · ' + ov.system.llama.build })); else if (s.daemonDown) ds.replaceChildren(h('span', { class: 'dot dot-red' }), h('span', { text: 'daemon unreachable' })); else ds.replaceChildren(h('span', { class: 'dot dot-off' }), h('span', { text: 'connecting…' }));
  $('#ver').textContent = ov ? 'v' + ov.system.daemon.version : ''; if (ov) $('#relay-link').href = ov.relay.dashboard_url;
  $('#foot-badges').replaceChildren(LIVE ? h('span', { class: 'badge', text: 'LIVE' }) : h('span', { class: 'mock-badge', text: 'MOCK', title: 'Mock API — Shift+D for scenarios' }), L.Button({ label: '?', size: 'sm', variant: 'ghost', title: 'Keyboard shortcuts (?)', onClick: openHelp }));
}
let bannerTick = null;
function drawBanner() {
  const s = store.state; const b = $('#banner'); clearInterval(bannerTick);
  if (!s.daemonDown) { b.replaceChildren(); return; }
  const port = (s.settings && s.settings.daemon.port) || (s.overview && s.overview.system.daemon.port) || 7700; const count = h('span', { class: 'mono' });
  const tick = () => { const left = Math.max(0, Math.ceil((3000 - (Date.now() - (s.downTick || Date.now()))) / 1000)); count.textContent = left + 's'; };
  s.downTick = Date.now(); tick(); bannerTick = setInterval(() => { tick(); }, 250);
  b.replaceChildren(h('div', { style: { padding: '12px 24px 0' } }, L.Banner({ html: `<b>lcpp daemon not responding at 127.0.0.1:${port}.</b> Retrying in <span id="retry-in"></span> · start it with <code class="mono">lcpp service start</code>`, actions: [L.Button({ label: 'Retry now', size: 'sm', onClick: () => refreshOverview() })] })));
  $('#retry-in').replaceWith(count);
}
function openHelp() { const rows = [['n', 'Launch a model'], ['g i', 'Go to Instances'], ['g m', 'Go to Models'], ['g p', 'Go to Playground'], ['g r', 'Go to Relay'], ['g s', 'Go to Settings'], ['/', 'Search in the Models view'], ['l', 'Logs for the focused instance card'], ['Esc', 'Close dialog, drawer or menu'], ['Ctrl+Enter', 'Launch from the Launch dialog'], ['?', 'This help'], ...(LIVE ? [] : [['Shift+D', 'Mock scenario panel']])]; const d = L.Dialog({ title: 'Keyboard shortcuts', body: h('div', { class: 'shortcut-list' }, rows.flatMap(([k, t]) => [h('div', { class: 'row', style: { flexWrap: 'nowrap' } }, k.split(/[ +]/).map(L.Kbd)), h('span', { text: t })])), actions: [L.Button({ label: 'Close', onClick: () => d.close() })] }); openDialog(d); }
function toggleDev() { const box = $('#dev'); if (box.firstChild) { box.replaceChildren(); return; } const m = api.mock; const speedSeg = L.Segmented({ label: 'Speed', size: 'sm', value: String(m.speed), options: [{ value: '1', label: '×1' }, { value: '5', label: '×5' }], onChange: v => { m.speed = +v; } }); box.append(L.Card({ class: 'dev', title: 'Mock scenarios', actions: [L.Button({ icon: 'x', variant: 'ghost', size: 'sm', title: 'Close', onClick: toggleDev })], body: h('div', {}, [L.Toggle({ label: 'Relay reachable', checked: m.relayReachable, tone: 'cyan', onChange: v => { m.relayReachable = v; refreshOverview(); loadRelay(); } }), L.Toggle({ label: 'Daemon down', checked: m.daemonDown, onChange: v => { m.daemonDown = v; refreshOverview(); } }), h('div', { class: 'row' }, [h('span', { class: 'muted', text: 'Reset' }), ...['seed', 'empty', 'busy'].map(k => L.Button({ label: k[0].toUpperCase() + k.slice(1), size: 'sm', onClick: () => { m.reset(k); toast(`Mock reset to ${k}`, 'success'); refreshOverview(); loadModels(); loadRelay(); loadRecent(); } }))]), h('div', { class: 'row' }, [h('span', { class: 'muted', text: 'Speed' }), speedSeg]), h('p', { class: 'help', text: 'Failure paths: launch on port 4000 (reserved) or 5432 (in use); launch ornith1-35B while gemma4-26B and another large model are ready.' })]) })); }
// keyboard shortcuts
let gPending = 0;
document.addEventListener('keydown', e => {
  const t = e.target; const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
  if (e.key === 'D' && e.shiftKey && !LIVE && !typing) { e.preventDefault(); toggleDev(); return; }
  if (typing || dialogDepth || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === '?') { e.preventDefault(); openHelp(); return; }
  if (gPending && Date.now() - gPending < 900) { gPending = 0; const n = NAV.find(x => x.key === e.key); if (n) { e.preventDefault(); navigate('#/' + n.view); } return; }
  if (e.key === 'g') { gPending = Date.now(); return; }
  if (e.key === 'n') { e.preventDefault(); openLaunch(); }
  else if (e.key === '/') { e.preventDefault(); if (currentView !== 'models') { navigate('#/models'); setTimeout(() => current && current.focusSearch && current.focusSearch(), 50); } else current.focusSearch && current.focusSearch(); }
  else if (e.key === 'l') { const c = document.activeElement && document.activeElement.closest('[data-name]'); if (c) { e.preventDefault(); openLogs(c.dataset.name); } }
  else if (e.key === 'Escape') { closeMenu(); $('#app').classList.remove('nav-open'); }
});
// init
$('#logo').append(L.Logo(22)); $('#logo2').append(L.Logo(22)); $('#menu-btn').append(Icon('menu'));
$('#menu-btn').addEventListener('click', () => { const open = $('#app').classList.toggle('nav-open'); $('#menu-btn').setAttribute('aria-expanded', String(open)); });
$('#scrim').addEventListener('click', () => { $('#app').classList.remove('nav-open'); $('#menu-btn').setAttribute('aria-expanded', 'false'); });
applyTheme();
store.subscribe(() => { drawHeader(); drawNav(); });
store.subscribe((() => { let last = null; return s => { if (s.daemonDown !== last) { last = s.daemonDown; drawBanner(); } }; })());
drawHeader(); drawNav(); drawBanner();
if (!location.hash) { suppressHash = false; history.replaceState(null, '', '#/instances'); }
currentHash = location.hash;
Promise.all([loadModels(), loadSettings(), loadRecent()]).then(() => { renderRoute(); });
renderRoute(); refreshOverview();
