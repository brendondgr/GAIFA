// The Chat page (plan 14.1, Wire — Phase 14): thread list, thread view and composer for the agent
// mod. A plain ES module on the page's React; Hub.dc.html mounts `ChatPage` for #/chat and
// #/chat/<thread id>. Written by us (web/PATCHES.md).
//
// Extending the chat (the modularity contract, brief §11.13): import from this file
//   registerCard(kind, Component)     a card for an event type, or 'tool:<name>' / 'result:<name>'
//   registerAction({...})             a result button or a composer quick action
//   registerPreview(kind, Component)  how a result of a new output kind is shown
//   registerStep(name, words)         a tool's step words in the activity fold
// A mod gives its own with `[ui] chat = "ui/chat.js"` (plan 44.1, chat-mods.js): its setup(chat) gets these.

import { h, T, Icon, Btn, COL, useWidth, chipSt, label11 } from './chat-ui.js';
import { MD_CSS, installCopy } from './chat-md.js';
import { Card, CARD_CSS, TodoList } from './chat-cards.js';
import './chat-forms.js';
import './chat-results.js';
import { runAction } from './chat-actions.js';
import { buildView, applyTransient, settleLive, mergeEvents, todosOpen, threadOf } from './chat-thread.js';
import { groupTurns } from './chat-turn.js';
import { TurnView, ACTIVITY_CSS } from './chat-activity.js';
import { createChatClient } from './chat-api.js';
import { ThreadList, Item, LIST_CSS } from './chat-list.js';
import { GroupedChats, readView, saveView, loadEnvs } from './chat-groups.js';
import { ThreadHeader, bypassAllowed } from './chat-header.js';
import { decideFolder, lastEnv, rememberEnv, newChatSettings } from './chat-env.js';
import { ControlsRow, ModeMenu, ModelMenu, EnvMenu, CONTROLS_CSS } from './chat-controls.js';
import { Composer } from './chat-composer.js';
import { QUOTE_CSS } from './chat-quote.js';
import { QuoteReplyBox, QREPLY_CSS, addQuote, draftQuotes, quotesPayload, messageText } from './chat-quote-reply.js';
import * as chatUi from './chat-ui.js';
import { registerCard } from './chat-cards.js';
import { registerAction } from './chat-actions.js';
import { registerPreview, ActionBar, Model3DPreview } from './chat-results.js';
import { registerStep, nameOf } from './chat-steps.js';
import { loadChatModules } from './chat-mods.js';
import * as liveKit from '../live-kit.js';

export { registerCard } from './chat-cards.js';
export { registerAction, actionsFor } from './chat-actions.js';
export { registerPreview } from './chat-results.js';
export { registerStep } from './chat-steps.js';
export { ParamCard } from './chat-forms.js';

const R = () => globalThis.React;
const LIST_PAGE = 200;    // chats per page in the list (Show more adds a page)
const EMPTY_LIVE = { deltas: {}, progress: {}, meter: null };
const SUGGEST = ['Make me an image of a fox in the snow', 'Turn my last image into a 3D model', 'Say “Welcome to AIHub” in Hope’s voice', 'What can you do?'];
const PAGE_CSS = `.aichat-box:focus-within{border-color:var(--bdh,#3A4A63)!important}`;

let shared = null;
/** One client per page load, shared by the Chat page and Settings → Agent. */
export function getChatClient(api) {
  if (!shared) shared = createChatClient({ api, base: globalThis.AIHUB_API_BASE || '' });
  return shared;
}
function injectCss() {
  if (typeof document === 'undefined' || document.getElementById('aichat-css')) return;
  installCopy();
  const s = document.createElement('style');
  s.id = 'aichat-css'; s.textContent = MD_CSS + CARD_CSS + ACTIVITY_CSS + LIST_CSS + CONTROLS_CSS + QUOTE_CSS + QREPLY_CSS + PAGE_CSS;
  document.head.appendChild(s);
}
/** What a mod's chat module gets (plan 44.1). */
export function chatModuleApi(api) {
  return { registerCard, registerPreview, registerAction, registerStep, ui: chatUi, api, live: liveKit, parts: { ActionBar, nameOf, Model3DPreview } };
}
const DOWN = new Set(['service_not_running', 'service_not_found', 'service_failed', 'upstream_error', 'hub_error']);

export function ChatPage({ api, route, toast = () => {}, confirm, openOutput, openSessions, go = x => { location.hash = x; } }) {
  const React = R(), { useState, useEffect, useRef, useMemo, useLayoutEffect } = React;
  const c = getChatClient(api), tid = route?.parts?.[1] || null;
  const [rootRef, width] = useWidth(1000), narrow = width < 760;
  const [threads, setThreads] = useState([]), [listLoading, setListLoading] = useState(true), [q, setQ] = useState(''), [archived, setArchived] = useState(false), [limit, setLimit] = useState(LIST_PAGE);
  const [models, setModels] = useState(null), [settings, setSettings] = useState(null), [tools, setTools] = useState(null);
  const [thread, setThread] = useState(null), [events, setEvents] = useState([]), [live, setLive] = useState(EMPTY_LIVE), [running, setRunning] = useState(false), [conn, setConn] = useState('open'), [ready, setReady] = useState(false);
  const [quoteDrafts, setQuoteDrafts] = useState({});   // Select → Reply: the quote-reply cards waiting in each chat's composer
  const [drafts, setDrafts] = useState({}), [attachments, setAttachments] = useState([]), [toolForms, setToolForms] = useState([]);
  const [meterOpen, setMeterOpen] = useState(false), [drawer, setDrawer] = useState(false), [down, setDown] = useState(null);
  const [fresh, setFresh] = useState(() => ({ model: null, mode: 'manual', settings: newChatSettings({}, lastEnv()) }));   // a chat not created yet; its environment: the last one picked (plan 34)
  const [folders, setFolders] = useState(null);   // the workspace mod's folders, for Bypass (plan 27.4)
  const [judge, setJudge] = useState(null);       // GET /api/judge/status: Auto is offered while its model answers (plan 30.5)
  const [envs, setEnvs] = useState(null), [listView, setListViewState] = useState(readView), [listKey, setListKey] = useState(0);   // plan 41.2
  const setListView = v => { setListViewState(v); saveView(v); };
  const relist = () => setListKey(n => n + 1);
  const scrollRef = useRef(null), contentRef = useRef(null), stick = useRef(true), first = useRef(true), inputRef = useRef(null), loadRef = useRef(null), queue = useRef([]), flushT = useRef(0);
  const dkey = tid || 'new', draft = drafts[dkey] || '';
  const setDraft = v => setDrafts(d => ({ ...d, [dkey]: typeof v === 'function' ? v(d[dkey] || '') : v }));
  const quotes = quoteDrafts[dkey] || [], setQuotes = (v, k = dkey) => setQuoteDrafts(m => ({ ...m, [k]: typeof v === 'function' ? v(m[k] || []) : v || [] }));
  const fail = e => { if (c.live && (DOWN.has(e?.code) || e?.status === 502 || e?.status === 503)) setDown(e); else toast(e?.detail || String(e?.message || e), 'error'); };

  // ---- data ----
  const loadList = async () => {
    try { setThreads(await c.threads({ q, archived, limit, sort: listView.chatOrder })); setDown(null); } catch (e) { fail(e); }
    setListLoading(false);
  };
  loadRef.current = loadList;
  useEffect(() => { const t = setTimeout(loadList, q ? 220 : 0); return () => clearTimeout(t); }, [q, archived, limit, listView.chatOrder]);
  const loadEnvList = () => loadEnvs(api).then(setEnvs);
  useEffect(() => { loadEnvList(); }, []);
  useEffect(() => {
    injectCss();
    c.models().then(setModels).catch(fail);
    c.settings().then(setSettings).catch(() => {});
    api.listTools().then(setTools).catch(() => setTools([]));
    const judged = () => api.getJudgeStatus?.().then(setJudge).catch(() => setJudge(null));
    judged();
    const jt = setInterval(judged, 60000);
    return () => clearInterval(jt);
  }, []);

  const flush = () => {
    flushT.current = 0;
    const evs = queue.current; queue.current = [];
    if (!evs.length) return;
    const stored = evs.filter(e => e.seq != null);
    if (stored.length) setEvents(list => mergeEvents(list, stored));
    setLive(l => evs.reduce((acc, e) => (e.seq == null ? applyTransient(acc, e) : settleLive(acc, e)), l));
    for (const e of evs) {
      if (e.type === 'thread' && threadOf(e.payload)) { const t = threadOf(e.payload); setThread(x => (x && x.id === t.id ? { ...x, ...t } : x)); setThreads(l => l.map(x => (x.id === t.id ? { ...x, ...t } : x))); }
      if (e.type === 'state' && e.seq != null) {
        const st = e.payload.state;
        setRunning(st === 'running'); setThread(x => (x ? { ...x, state: st } : x));
        setThreads(l => l.map(x => (x.id === e.thread_id ? { ...x, state: st, running: st === 'running', updated: e.ts } : x)));
        if (st !== 'running') setTimeout(() => loadRef.current?.(), 300);
      }
    }
  };
  useEffect(() => {
    setEvents([]); setLive(EMPTY_LIVE); setThread(null); setReady(false); setRunning(false); setToolForms([]); setMeterOpen(false); setDrawer(false); setAttachments([]);
    first.current = true; stick.current = true; queue.current = [];
    if (!tid) return undefined;
    let alive = true;
    c.get(tid).then(t => { if (alive) { setThread(t); setRunning(!!t.running); } })
      .catch(e => { if (!alive) return; if (e.status === 404) { if (c.live) toast('That chat no longer exists', 'error'); go('#/chat'); } else fail(e); });
    c.context(tid).then(m => alive && setLive(l => ({ ...l, meter: m }))).catch(() => {});
    const s = c.stream(tid, 0, {
      onEvent: ev => { if (!alive) return; queue.current.push(ev); if (!flushT.current) flushT.current = setTimeout(flush, 30); },
      onReady: ev => { if (alive) { setRunning(!!ev.running); setReady(true); } },
      onState: st => alive && setConn(st),
    });
    return () => { alive = false; s.close(); clearTimeout(flushT.current); flushT.current = 0; };
  }, [tid]);

  const envId = (thread ? thread.settings?.environment : fresh.settings?.environment) || null;   // plan 34: the chat's environment
  useEffect(() => {      // its folders (and those allowed in this chat), for Bypass (plan 27.4)
    api.callService?.('workspace', 'GET', '/v1/folders', envId ? { query: { environment: envId } } : {}).then(r => setFolders(r.json?.folders || [])).catch(() => setFolders([]));
  }, [envId]);
  const [, setModTick] = useState(0);    // mods' chat modules (plan 44.1): draw again once they've registered
  useEffect(() => {
    let alive = true;
    Promise.resolve(api.listServices?.()).then(s => loadChatModules(s || [], chatModuleApi(api)))
      .then(r => { if (alive && r.some(x => x.ok)) setModTick(t => t + 1); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  const view = useMemo(() => buildView(events, live), [events, live]);
  const mods = useMemo(() => [...new Set((tools || []).map(t => t.mod))], [tools]);
  const [now, setNow] = useState(() => Date.now() / 1000);   // ticks while a turn runs, so the fold's timers count
  useEffect(() => { setNow(Date.now() / 1000); if (!running) return undefined; const t = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(t); }, [running]);
  const blocks = useMemo(() => groupTurns(view, { running, now, tools }), [view, running, now, tools]);
  useLayoutEffect(() => {
    const el = scrollRef.current; if (!el) return undefined;
    if (first.current && events.length) { el.scrollTop = el.scrollHeight; first.current = false; return undefined; }
    if (!stick.current) return undefined;
    el.scrollTop = el.scrollHeight;
    const f = requestAnimationFrame(() => { if (stick.current) el.scrollTop = el.scrollHeight; });  // after child effects (forms) mounted
    return () => cancelAnimationFrame(f);
  }, [view, toolForms]);
  useEffect(() => {  // content that grows later (an image loading, a form mounting) keeps the view at the bottom while it sticks there
    const el = scrollRef.current, inner = contentRef.current;
    if (!el || !inner || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(() => { if (stick.current) el.scrollTop = el.scrollHeight; });
    ro.observe(inner);
    return () => ro.disconnect();
  }, []);
  const onScroll = e => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 140; };

  // ---- actions ----
  const ensureThread = async () => {
    if (tid) return tid;
    const th = await c.create({ model: fresh.model || undefined, mode: fresh.mode, settings: fresh.settings });
    setThreads(l => [th, ...l]); relist();
    go('#/chat/' + th.id);
    return th.id;
  };
  const slash = async text => {
    const [cmd, ...rest] = text.slice(1).split(/\s+/), arg = rest.join(' ').trim();
    if (cmd === 'compact') { if (!tid) toast('Nothing to compact yet'); else c.compact(tid).then(() => toast('Compacted: earlier messages summarized', 'success'), fail); return null; }
    if (cmd === 'clear') { go('#/chat'); return null; }
    if (cmd === 'context') { setMeterOpen(true); return null; }
    if (cmd === 'clear-gpu') {      // plan 46.2: hub_free_gpu as your own step, drawn as its status card
      const services = arg ? arg.split(/[\s,]+/).filter(Boolean) : [];
      ensureThread().then(id => c.action(id, 'hub_free_gpu', services.length ? { services } : {})).catch(fail);
      return null;
    }
    if (cmd === 'model') {
      if (!arg) { toast('Usage: /model <id>. ' + (models?.models || []).map(m => m.id).join(', ')); return null; }
      if (models && !models.models.some(m => m.id === arg)) { toast(`No model “${arg}”`, 'error'); return null; }
      setModel(arg); toast(`Model: ${arg}`, 'success'); return null;
    }
    const skill = settings?.skills?.find(s => s.name === cmd);
    if (skill) return `Use the ${skill.id || skill.name} skill: ${arg}`.trim();
    return text;
  };
  const send = async (text, atts = [], qs = null) => {   // qs: the composer's quote-reply cards (null: a suggestion or a button)
    let t = text.trim();
    const k = dkey, cards = qs || [];
    if (t.startsWith('/')) { t = await slash(t); setDrafts(d => ({ ...d, [k]: '' })); if (t == null) return; }   // the cards stay for the next message
    t = messageText(t, atts, cards);
    if (!t && !cards.some(q => q.reply.trim())) return;
    setDrafts(d => ({ ...d, [k]: '' })); setAttachments([]); if (cards.length) setQuotes([], k); stick.current = true;
    try { const id = await ensureThread(); await c.send(id, t, atts.map(a => a.id), Object.fromEntries(atts.filter(a => a.mode).map(a => [a.id, a.mode])), quotesPayload(cards)); }
    catch (e) { setDrafts(d => ({ ...d, [k]: text })); if (cards.length) setQuotes(l => [...cards, ...l], k); fail(e); }
  };
  const setModel = m => { if (thread) c.patch(thread.id, { model: m }).then(t => { setThread(x => ({ ...x, ...t })); c.context(thread.id).then(mm => setLive(l => ({ ...l, meter: mm }))).catch(() => {}); }, fail); else setFresh(f => ({ ...f, model: m })); };
  const setMode = m => { if (thread) c.patch(thread.id, { mode: m }).then(t => setThread(x => ({ ...x, ...t })), fail); else setFresh(f => ({ ...f, mode: m })); };
  const setGroups = s => { if (thread) c.patch(thread.id, { settings: s }).then(t => setThread(x => ({ ...x, ...t })), fail); else setFresh(f => ({ ...f, settings: { ...f.settings, ...s } })); };
  const setEnv = id => { rememberEnv(id); setGroups({ ...(thread ? thread.settings || {} : {}), environment: id }); if (thread) setTimeout(relist, 300); };
  const rename = (t, title) => c.patch(t.id, { title }).then(n => { setThreads(l => l.map(x => (x.id === t.id ? { ...x, ...n } : x))); if (t.id === tid) setThread(x => ({ ...x, ...n })); }, fail);
  const archive = t => c.patch(t.id, { archived: !t.archived }).then(() => { setThreads(l => l.filter(x => x.id !== t.id)); relist(); toast(t.archived ? 'Moved back to chats' : 'Archived', 'success'); }, fail);
  const move = (t, env) => c.patch(t.id, { settings: { environment: env } }).then(n => {   // plan 41.2: Move to
    setThreads(l => l.map(x => (x.id === t.id ? { ...x, ...n } : x))); if (t.id === tid) setThread(x => ({ ...x, ...n })); relist();
    toast(`Moved to ${(envs || []).find(e => e.id === env)?.name || env}`, 'success');
  }, fail);
  const newIn = env => { rememberEnv(env); setFresh(f => ({ ...f, settings: { ...f.settings, environment: env } })); go('#/chat'); setDrawer(false); setTimeout(() => inputRef.current?.focus(), 50); };
  const envName = id => { const list = envs || []; return (list.find(e => e.id === id) || list.find(e => e.default))?.name || null; };
  const itemProps = (t, flat = false) => ({ moveTo: (envs || []).filter(e => e.id !== ((t.settings || {}).environment || (envs || []).find(x => x.default)?.id)),
    onMove: envs ? env => move(t, env) : null, where: flat && envs ? envName((t.settings || {}).environment) : null });
  const remove = async t => {
    const ok = confirm ? await confirm({ title: `Delete “${t.title || 'this chat'}”?`, body: 'The chat and its history are deleted. Its outputs stay in Outputs.', confirmLabel: 'Delete chat', danger: true }) : window.confirm('Delete this chat?');
    if (!ok) return;
    try { await c.remove(t.id); setThreads(l => l.filter(x => x.id !== t.id)); relist(); if (t.id === tid) go('#/chat'); toast('Chat deleted', 'success'); } catch (e) { fail(e); }
  };
  const forkAt = async (seq, text, qs = []) => {   // qs: the message's quote-replies, as cards to edit (their seqs are the same in the branch)
    try {
      if (seq < 1) { go('#/chat'); setDrafts(d => ({ ...d, new: text || '' })); if (qs.length) setQuotes(qs.map(({ seq: _s, ...q }) => q), 'new'); return; }
      const th = await c.fork(tid, seq);
      setThreads(l => [th, ...l]); relist();
      if (text != null) setDrafts(d => ({ ...d, [th.id]: text }));
      if (qs.length) setQuotes(qs, th.id);
      go('#/chat/' + th.id);
      toast(text != null ? 'Branched: edit the message and send it' : 'Branched into a new chat', 'success');
    } catch (e) { fail(e); }
  };
  const openTool = (name, args = {}, a) => {
    const tool = (tools || []).find(t => t.name === name);
    if (!tool) { toast(`${name} isn't available right now`, 'error'); return; }
    stick.current = true;
    setToolForms(f => [...f.filter(x => x.tool.name !== name), { key: 'tf' + name + Date.now(), kind: 'toolform', tool, args, label: a?.label && a.on === 'composer' ? a.label : a?.label ? `${a.label}` : null }]);
  };
  const attach = o => { setAttachments(l => (l.some(x => x.id === o.output_id) ? l : [...l, { id: o.output_id, kind: o.kind, title: o.title, preview: o.preview, n: o.n }])); inputRef.current?.focus(); };
  const ctx = {
    api, live: c.live, tid, thread, outputs: view.outputs, tools, mods, running, dock: true,
    answer: (qid, answers) => c.answer(tid, qid, answers),
    // o: {remember, confirm} when allowing (plan 25.3), {reason} when denying
    // plan 34: "Add to <environment>" adds the folder there first (chat-env.js), then allows the call once
    decide: async (a, approve, args, o = {}) => { if (approve && a.limits?.ask_folder) o = await decideFolder(api, a.limits.ask_folder, o);
      return c.approval(tid, { approval_id: a.approval_id, approve, ...(approve ? { arguments: args, remember: o.remember || 'once', ...(o.confirm ? { confirm: true } : {}) } : { reason: o.reason || 'Denied in the chat' }) }); },
    cancel: () => c.cancel(tid).catch(fail),
    branch: it => forkAt(it.ev.seq - 1, it.ev.payload.text, draftQuotes(it.ev.payload)),
    copy: text => navigator.clipboard?.writeText(text).then(() => toast('Copied', 'success'), () => {}),
    openOutput, runAction: (a, o) => runAction(a, o, { openTool, attach, sendPrompt: t => send(t) }),
    // plan 24.7: a citation in a reply (#n p.14, #n:88, output:<id> …) opens the viewer there
    openCite: ({ ref, page, line }) => {
      const id = String(ref).startsWith('output:') ? String(ref).slice(7) : view.outputs.find(o => o.n === +String(ref).replace('#', ''))?.output_id;
      if (!id) { toast(`${ref} isn't an output in this chat`, 'error'); return; }
      openOutput?.(id, page ? { page: +page } : line ? { line: +line } : null);
    },
    runTool: async (item, args) => { const id = await ensureThread(); await c.action(id, item.tool.name, args); setToolForms(f => f.filter(x => x.key !== item.key)); },
    closeTool: item => setToolForms(f => f.filter(x => x.key !== item.key)),
    feedback: tid && c.feedback ? body => c.feedback(tid, body) : null,         // plan 21.7
    // plan 27.7: "Undo this turn": each path is a hub route (/api/s/<mod>/…/undo) a tool result named
    undo: api.callService ? async paths => {
      let conflict = null;
      for (const p of paths) {
        const m = /^\/api\/s\/([^/]+)(\/.*)$/.exec(p);
        if (!m) continue;
        try { await api.callService(m[1], 'POST', m[2]); }
        catch (e) { if (e.status === 409) conflict = e; else { fail(e); throw e; } }
      }
      if (conflict) { toast(`${conflict.detail || 'A file changed since this turn; nothing was restored'}. The Workspace page (Activity) shows what changed.`, 'error'); throw conflict; }
      toast('Undone', 'success');
      return 'undone';
    } : null,
    decidePref: c.decidePref ? (pid, ok) => c.decidePref(pid, ok).then(r => { toast(ok ? 'Saved: it fills your cards from now on' : 'Not used', 'success'); return r; }, e => { fail(e); throw e; }) : null,
  };

  // ---- render ----
  const list = h(ThreadList, { threads, loading: listLoading, activeId: tid, q, onQ: v => { setQ(v); setLimit(LIST_PAGE); }, archived, onArchived: v => { setArchived(v); setLimit(LIST_PAGE); setListLoading(true); }, onMore: threads.length >= limit ? () => setLimit(n => n + LIST_PAGE) : null,
    onNew: () => { go('#/chat'); setDrawer(false); setTimeout(() => inputRef.current?.focus(), 50); }, onOpen: () => setDrawer(false), onRename: rename, onArchive: archive, onDelete: remove, onClose: narrow ? () => setDrawer(false) : null, onSessions: openSessions ? () => { setDrawer(false); openSessions(); } : null,
    view: listView, onView: setListView, canGroup: !!envs, itemProps,
    grouped: envs && listView.group === 'environment' && c.threadGroups ? h(GroupedChats, { c, api, envs, archived, view: listView, onView: setListView, known: threads, reloadKey: listKey,
      renderItem: t => h(Item, { key: t.id, t, active: t.id === tid, onOpen: () => setDrawer(false), onRename: v => rename(t, v), onArchive: () => archive(t), onDelete: () => remove(t), ...itemProps(t) }),
      onNewIn: newIn, onEnvsChanged: loadEnvList, onError: fail, go }) : null });
  const empty = !tid || (ready && !events.length && !running);
  const compacts = events.filter(e => e.type === 'compact').length;
  return h('div', { ref: rootRef, style: { display: 'flex', height: '100%', minHeight: 0, position: 'relative', overflow: 'hidden', background: T.bg } },
    narrow ? null : h('div', { style: { width: 248, flex: 'none', borderRight: '1px solid ' + T.bd, minHeight: 0 } }, list),
    narrow && drawer ? h(React.Fragment, null,
      h('div', { onClick: () => setDrawer(false), 'aria-hidden': true, style: { position: 'absolute', inset: 0, zIndex: 40, background: T.ov } }),
      h('div', { style: { position: 'absolute', top: 0, bottom: 0, left: 0, zIndex: 41, width: 'min(300px, 86%)', borderRight: '1px solid ' + T.bds, boxShadow: '0 0 40px rgba(0,0,0,.4)' } }, list)) : null,
    h('section', { 'aria-label': 'Chat', style: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 0 } },
      h(ThreadHeader, { thread,
        onRename: title => rename(thread, title), meter: live.meter, meterOpen, setMeterOpen, onCompact: () => c.compact(tid).then(() => toast('Compacted', 'success'), fail), compacts,
        learn: thread ? !(thread.settings || {}).no_learn : null, onLearn: thread ? on => setGroups({ ...(thread.settings || {}), no_learn: !on }) : null,
        running, state: thread?.state, onBranch: events.length ? () => forkAt(view.lastSeq, null) : null, onMenu: narrow ? () => setDrawer(true) : null, narrow: (narrow ? width : width - 248) < 700 }),
      down ? h('div', { role: 'alert', style: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', padding: '8px 14px', background: T.trd, borderBottom: '1px solid ' + T.rd, fontSize: 12.5 } },
        h('span', { style: { color: T.rd, display: 'flex' } }, h(Icon, { d: 'alert', size: 15 })),
        h('span', { style: { flex: 1, minWidth: 200 } }, h('strong', null, 'The agent isn’t running. '), down.detail || ''),
        h(Btn, { sm: true, kind: 'pri', label: 'Start Agent', onClick: () => api.startService('agent').then(() => { toast('Starting the agent…'); setTimeout(() => { setDown(null); loadList(); c.models().then(setModels).catch(fail); }, 2500); }, fail) }),
        h('a', { href: '?mock#/chat', style: { fontSize: 12.5 } }, 'Try the scripted demo')) : null,
      conn === 'reconnecting' ? h('div', { role: 'status', style: { padding: '4px 14px', fontSize: 12, color: T.acct, background: T.tacc } }, 'Reconnecting to the chat…') : null,
      h('div', { ref: scrollRef, onScroll, style: { flex: 1, minHeight: 0, overflowY: 'auto', overflowX: 'hidden', position: 'relative' } },
        view.todos && todosOpen(view.todos) ? h('div', { style: { position: 'sticky', top: 0, zIndex: 5, background: T.bg, borderBottom: '1px solid ' + T.bd, padding: '7px 16px' } },
          h('div', { style: { maxWidth: COL, margin: '0 auto', display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 } },
            h('span', { style: label11 }, 'Plan'), h('div', { style: { minWidth: 0, flex: 1 } }, h(TodoList, { items: view.todos, compact: true })))) : null,
        h('div', { ref: contentRef, style: { maxWidth: COL, margin: '0 auto', padding: '18px 16px 28px', display: 'flex', flexDirection: 'column', gap: 14, minWidth: 0 } },
          empty && !toolForms.length ? h(EmptyState, { onPick: t => send(t), tools }) : null,
          blocks.map(b => (b.kind === 'turn' ? h(TurnView, { key: b.key, turn: b, ctx }) : h(Card, { key: b.item.key, item: b.item, ctx }))))),
      h(Composer, { draft, setDraft, attachments, setAttachments, onOpen: openOutput, onSend: send, onStop: () => c.cancel(tid).catch(fail), running, tools, index: tools,
        dock: [...toolForms, ...view.pending].reverse().map(it => h(Card, { key: it.key, item: it, ctx })),
        settings: thread?.settings || fresh.settings, onSettings: setGroups, skills: settings?.skills || [], outputs: view.outputs, api, inputRef, quotes, setQuotes,
        onQuick: a => runAction(a, null, { openTool, attach, sendPrompt: t => send(t) }),
        controls: h(ControlsRow, {   // plan 42.3: the chat's environment, mode and model, under the box
          env: h(EnvMenu, { api, c, thread, envs, value: envId, onChange: setEnv, stamp: events.reduce((n, e) => n + (e.type === 'decision'), 0), onEnvsChanged: loadEnvList, confirm,
            onDeleted: (id, ids) => { setThreads(l => l.filter(x => !ids.includes(x.id))); relist(); if (tid && ids.includes(tid)) go('#/chat');
              toast(`Deleted the environment${ids.length ? ` and ${ids.length} chat${ids.length === 1 ? '' : 's'}` : ''}`, 'success'); } }),
          mode: h(ModeMenu, { value: thread?.mode || fresh.mode, onChange: setMode, bypass: bypassAllowed(folders, events), judge }),
          model: h(ModelMenu, { models, value: thread?.model || fresh.model || models?.default, onChange: setModel }) }) })),
    h(QuoteReplyBox, { scrollRef, resetKey: dkey, onAdd: q => setQuotes(l => addQuote(l, q)) }));
}

function EmptyState({ onPick }) {
  return h('div', { style: { padding: 'min(10vh, 72px) 0 12px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, textAlign: 'center' } },
    h('span', { style: { width: 40, height: 40, borderRadius: 10, display: 'grid', placeItems: 'center', background: T.tpu, color: T.pu } }, h(Icon, { d: 'chat', size: 20 })),
    h('h2', { style: { margin: 0, fontSize: 18, fontWeight: 600, letterSpacing: '-.01em' } }, 'What should we make?'),
    h('p', { style: { margin: 0, color: T.mut, maxWidth: 460 } }, 'Images, video, 3D models and speech, all on this machine. The agent asks before it runs anything that generates, and every result can be chained into the next.'),
    h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center', marginTop: 6, maxWidth: 560 } },
      SUGGEST.map(s => h('button', { key: s, type: 'button', onClick: () => onPick(s), style: { ...chipSt(false), height: 30, color: T.tx } }, s))));
}
