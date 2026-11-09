// The Chat page (plan 14.1, Wire — Phase 14): thread list, thread view and composer for the agent
// mod. A plain ES module on the page's React; Hub.dc.html mounts `ChatPage` for #/chat and
// #/chat/<thread id>. Written by us (web/PATCHES.md). The page keeps the list and what every chat shares;
// each open chat is a `ChatPane` (chat-pane.js, chat-split plan 1.2).
//
// Extending the chat (the modularity contract, brief §11.13): import from this file
//   registerCard(kind, Component)     a card for an event type, or 'tool:<name>' / 'result:<name>'
//   registerAction({...})             a result button or a composer quick action
//   registerPreview(kind, Component)  how a result of a new output kind is shown
//   registerStep(name, words)         a tool's step words in the activity fold
// A mod gives its own with `[ui] chat = "ui/chat.js"` (plan 44.1, chat-mods.js): its setup(chat) gets these.

import { h, T, Icon, Btn, useWidth } from './chat-ui.js';
import { MD_CSS, installCopy } from './chat-md.js';
import { CARD_CSS } from './chat-cards.js';
import './chat-forms.js';
import './chat-results.js';
import './chat-status.js';
import './chat-show.js';
import './chat-save.js';
import { ACTIVITY_CSS } from './chat-activity.js';
import { createChatClient } from './chat-api.js';
import { ThreadList, Item, LIST_CSS } from './chat-list.js';
import { GroupedChats, readView, saveView, viewOfUi, loadEnvs } from './chat-groups.js';
import { useUiPref } from '../ui-prefs.js';
import { ChatPane } from './chat-pane.js';
import { SplitView, SPLIT_CSS } from './chat-split.js';
import { single, panes, activePane, setTid, setActive, dropTids, loadLayout, saveLayout } from './chat-layout.js';
import { CONTROLS_CSS } from './chat-controls.js';
import { QUOTE_CSS } from './chat-quote.js';
import { QREPLY_CSS } from './chat-quote-reply.js';
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
const PAGE_CSS = `.aichat-box:focus-within{border-color:var(--bdh,#3A4A63)!important}`;

let shared = null;
/** One client per page load, shared by the Chat page and Settings → Agent. */
export function getChatClient(api) {
  if (!shared) shared = createChatClient({ api, base: globalThis.GAIFA_API_BASE || '' });
  return shared;
}
function injectCss() {
  if (typeof document === 'undefined' || document.getElementById('aichat-css')) return;
  installCopy();
  const s = document.createElement('style');
  s.id = 'aichat-css'; s.textContent = MD_CSS + CARD_CSS + ACTIVITY_CSS + LIST_CSS + CONTROLS_CSS + QUOTE_CSS + QREPLY_CSS + SPLIT_CSS + PAGE_CSS;
  document.head.appendChild(s);
}
/** What a mod's chat module gets (plan 44.1). */
export function chatModuleApi(api) {
  return { registerCard, registerPreview, registerAction, registerStep, ui: chatUi, api, live: liveKit, parts: { ActionBar, nameOf, Model3DPreview } };
}
/** The layout with chat `tid` in view: the pane already showing it becomes active, else the active pane shows it. */
function withRoute(L, tid) {
  if (!tid) return L;
  const open = panes(L.root).find(p => p.tid === tid);
  return open ? setActive(L, open.id) : setTid(L, activePane(L).id, tid);
}
const MAX_PANES = 4;   // while each pane opens its own stream: a browser keeps about six connections to the hub (plan chat-split 2.3)
const DOWN = new Set(['service_not_running', 'service_not_found', 'service_failed', 'upstream_error', 'hub_error']);

export function ChatPage({ api, route, toast = () => {}, confirm, openOutput, openSessions, go = x => { location.hash = x; } }) {
  const React = R(), { useState, useEffect, useRef, useMemo } = React;
  const c = getChatClient(api), tid = route?.parts?.[1] || null;
  const [rootRef, width] = useWidth(1000), narrow = width < 760;
  const [threads, setThreads] = useState([]), [listLoading, setListLoading] = useState(true), [q, setQ] = useState(''), [archived, setArchived] = useState(false), [limit, setLimit] = useState(LIST_PAGE);
  const [models, setModels] = useState(null), [settings, setSettings] = useState(null), [tools, setTools] = useState(null);
  const [drawer, setDrawer] = useState(false), [down, setDown] = useState(null);
  const [judge, setJudge] = useState(null);       // GET /api/judge/status: Auto is offered while its model answers (plan 30.5)
  const [envs, setEnvs] = useState(null), [listKey, setListKey] = useState(0);   // plan 41.2
  const [listUi] = useUiPref('chat.list', null), listView = readView(listUi ? viewOfUi(listUi) : undefined);   // settings-that-stick 3.3: config.toml [ui.chat.list]
  const [cmd, setCmd] = useState(null);           // the page's New chat, for the active pane
  // chat-split plan 2.2: the open chats' layout, saved in this browser; the URL follows the active pane
  const [layout, setLayout] = useState(() => withRoute(loadLayout() || single(tid), tid));
  const lref = useRef(layout); lref.current = layout;
  useEffect(() => { saveLayout(layout); }, [layout]);
  const mounted = useRef(false);
  useEffect(() => {      // a link, the list or Back: that chat in view (#/chat: the active pane becomes a new chat)
    if (!mounted.current) { mounted.current = true; return; }
    setLayout(L => (tid ? withRoute(L, tid) : setTid(L, activePane(L).id, null)));
  }, [tid]);
  const act = activePane(layout);
  useEffect(() => { if ((act.tid || null) !== tid) go(act.tid ? '#/chat/' + act.tid : '#/chat'); }, [act.id, act.tid]);
  const bus = useRef(null); if (!bus.current) bus.current = new EventTarget();
  const setListView = v => saveView(v);
  const relist = () => setListKey(n => n + 1);
  const loadRef = useRef(null);
  const fail = e => { if (c.live && (DOWN.has(e?.code) || e?.status === 502 || e?.status === 503)) setDown(e); else toast(e?.detail || String(e?.message || e), 'error'); };
  const openIn = (paneId, id) => setLayout(L => setActive(setTid(L, paneId, id), paneId));
  const newChat = env => { setCmd(x => ({ n: (x?.n || 0) + 1, type: 'new', env, pane: lref.current.active })); setDrawer(false); };

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
  const [speechOut, setSpeechOut] = useState(null);   // plan 49.1: the voice that reads replies (hub settings' speech_output)
  useEffect(() => { api.getSettings?.().then(s => setSpeechOut(s.speech_output || null)).catch(() => {}); }, []);
  const [, setModTick] = useState(0);    // mods' chat modules (plan 44.1): draw again once they've registered
  useEffect(() => {
    let alive = true;
    Promise.resolve(api.listServices?.()).then(s => loadChatModules(s || [], chatModuleApi(api)))
      .then(r => { if (alive && r.some(x => x.ok)) setModTick(t => t + 1); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    const on = e => openOutput?.(e.detail);
    document.addEventListener('gaifa:open-output', on);
    return () => document.removeEventListener('gaifa:open-output', on);
  }, [openOutput]);
  const mods = useMemo(() => [...new Set((tools || []).map(t => t.mod))], [tools]);

  // ---- the list's actions ----
  const listPatch = (id, p) => setThreads(l => l.map(x => (x.id === id ? { ...x, ...p } : x)));
  const patched = t => { if (!t?.id) return; listPatch(t.id, t); bus.current.dispatchEvent(new CustomEvent('patched', { detail: t })); };   // every pane showing it
  const rename = (t, title) => c.patch(t.id, { title }).then(patched, fail);
  const archive = t => c.patch(t.id, { archived: !t.archived }).then(() => { setThreads(l => l.filter(x => x.id !== t.id)); relist(); toast(t.archived ? 'Moved back to chats' : 'Archived', 'success'); }, fail);
  const move = (t, env) => c.patch(t.id, { settings: { environment: env } }).then(n => {   // plan 41.2: Move to
    patched(n); relist();
    toast(`Moved to ${(envs || []).find(e => e.id === env)?.name || env}`, 'success');
  }, fail);
  const newIn = env => newChat(env);
  const itemProps = t => ({ moveTo: (envs || []).filter(e => e.id !== ((t.settings || {}).environment || (envs || []).find(x => x.default)?.id)),
    onMove: envs ? env => move(t, env) : null });
  const remove = async t => {
    const ok = confirm ? await confirm({ title: `Delete “${t.title || 'this chat'}”?`, body: 'The chat and its history are deleted. Its outputs stay in Outputs.', confirmLabel: 'Delete chat', danger: true }) : window.confirm('Delete this chat?');
    if (!ok) return;
    try { await c.remove(t.id); setThreads(l => l.filter(x => x.id !== t.id)); relist(); setLayout(L => dropTids(L, [t.id])); toast('Chat deleted', 'success'); } catch (e) { fail(e); }
  };
  const sh = {
    api, c, toast, confirm, openOutput, fail, models, reloadModels: () => c.models().then(m => { setModels(m); return m; }, fail), settings, tools, mods, judge, speechOut, envs, loadEnvList, relist, bus: bus.current, rename, patched, listPatch,
    reloadList: () => loadRef.current?.(),
    addThread: th => { setThreads(l => [th, ...l]); relist(); },
    envDeleted: ids => { setThreads(l => l.filter(x => !ids.includes(x.id))); relist(); setLayout(L => dropTids(L, ids)); },
    onMenu: narrow ? () => setDrawer(true) : null,
    banner: down ? h('div', { role: 'alert', style: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', padding: '8px 14px', background: T.trd, borderBottom: '1px solid ' + T.rd, fontSize: 12.5 } },
      h('span', { style: { color: T.rd, display: 'flex' } }, h(Icon, { d: 'alert', size: 15 })),
      h('span', { style: { flex: 1, minWidth: 200 } }, h('strong', null, 'The agent isn’t running. '), down.detail || ''),
      h(Btn, { sm: true, kind: 'pri', label: 'Start Agent', onClick: () => api.startService('agent').then(() => { toast('Starting the agent…'); setTimeout(() => { setDown(null); loadList(); c.models().then(setModels).catch(fail); }, 2500); }, fail) }),
      h('a', { href: '?mock#/chat', style: { fontSize: 12.5 } }, 'Try the scripted demo')) : null,
  };

  // ---- render ----
  const list = h(ThreadList, { threads, loading: listLoading, activeId: tid, q, onQ: v => { setQ(v); setLimit(LIST_PAGE); }, archived, onArchived: v => { setArchived(v); setLimit(LIST_PAGE); setListLoading(true); }, onMore: threads.length >= limit ? () => setLimit(n => n + LIST_PAGE) : null,
    onNew: () => newChat(), onOpen: () => setDrawer(false), onRename: rename, onArchive: archive, onDelete: remove, onClose: narrow ? () => setDrawer(false) : null, onSessions: openSessions ? () => { setDrawer(false); openSessions(); } : null,
    view: listView, onView: setListView, canGroup: !!envs, itemProps,
    grouped: envs && listView.group === 'environment' && c.threadGroups ? h(GroupedChats, { c, api, envs, archived, view: listView, onView: setListView, known: threads, reloadKey: listKey,
      renderItem: t => h(Item, { key: t.id, t, active: t.id === tid, onOpen: () => setDrawer(false), onRename: v => rename(t, v), onArchive: () => archive(t), onDelete: () => remove(t), ...itemProps(t) }),
      onNewIn: newIn, onEnvsChanged: loadEnvList, onError: fail, go }) : null });
  return h('div', { ref: rootRef, style: { display: 'flex', height: '100%', minHeight: 0, position: 'relative', overflow: 'hidden', background: T.bg } },
    narrow ? null : h('div', { style: { width: 248, flex: 'none', borderRight: '1px solid ' + T.bd, minHeight: 0 } }, list),
    narrow && drawer ? h(React.Fragment, null,
      h('div', { onClick: () => setDrawer(false), 'aria-hidden': true, style: { position: 'absolute', inset: 0, zIndex: 40, background: T.ov } }),
      h('div', { style: { position: 'absolute', top: 0, bottom: 0, left: 0, zIndex: 41, width: 'min(300px, 86%)', borderRight: '1px solid ' + T.bds, boxShadow: '0 0 40px rgba(0,0,0,.4)' } }, list)) : null,
    h(SplitView, { layout, setLayout, narrow, maxPanes: c.live && !c.sharedStream ? MAX_PANES : Infinity, onRefuse: m => toast(m, 'error'),
      titleOf: id => threads.find(t => t.id === id)?.title || null,
      renderPane: (p, { active, tools, grip }) => h(ChatPane, { shared: sh, tid: p.tid, paneId: p.id, cmd, grip, paneTools: tools,
        onOpen: id => openIn(p.id, id), onFocus: active ? null : () => setLayout(L => setActive(L, p.id)) }) }));
}
