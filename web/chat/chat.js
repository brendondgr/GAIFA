// The Chat page (plan 14.1, Wire — Phase 14): thread list, thread view and composer for the agent
// mod. A plain ES module on the page's React; Hub.dc.html mounts `ChatPage` for #/chat,
// #/chat/<thread id>, #/chat/all (every chat, chat-all.js), #/chat/projects (the projects grid, chat-projects.js; plan
// projects 5.1), #/chat/projects/<id> (a project's page, chat-project.js), #/chat/tasks (the scheduled tasks, chat-tasks.js; plan
// scheduled-tasks 4.2) and #/chat/tasks/<id> (a task's page, chat-task.js); all but the chats are drawn in the main area
// instead of the panes (thread ids start with t_, so they never clash). Written by us (web/PATCHES.md). The page keeps the list and what every chat shares;
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
import { DateSections } from './chat-dates.js';
import { AllChats } from './chat-all.js';
import { GroupedChats, readView, saveView, viewOfUi, loadEnvs, archivedParam, groupOf, showAllOf } from './chat-groups.js';
import { useUiPref } from '../ui-prefs.js';
import { ChatPane } from './chat-pane.js';
import { SplitView, SPLIT_CSS } from './chat-split.js';
import { ProjectsPage, ProjectsEntry, PROJECTS_CSS } from './chat-projects.js';
import { ProjectChats } from './chat-project-groups.js';
import { ProjectPage } from './chat-project.js';
import { TasksPage, TasksEntry } from './chat-tasks.js';
import { TaskPage } from './chat-task.js';
import { single, panes, activePane, setTid, setActive, dropTids, loadLayout, saveLayout, splitPane } from './chat-layout.js';
import './chat-agents.js';
import { CONTROLS_CSS } from './chat-controls.js';
import { QUOTE_CSS } from './chat-quote.js';
import { QREPLY_CSS } from './chat-quote-reply.js';
import * as chatUi from './chat-ui.js';
import { registerCard } from './chat-cards.js';
import { registerAction } from './chat-actions.js';
import { registerPreview, ActionBar, Model3DPreview } from './chat-results.js';
import { registerStep, nameOf } from './chat-steps.js';
import { loadChatModules } from './chat-mods.js';
import { ChatPanels } from './chat-panel.js';
import * as liveKit from '../live-kit.js';

export { registerCard } from './chat-cards.js';
export { registerAction, actionsFor } from './chat-actions.js';
export { registerPreview } from './chat-results.js';
export { registerStep } from './chat-steps.js';
export { ParamCard } from './chat-forms.js';

const R = () => globalThis.React;
const LIST_PAGE = 20;     // chats in the list, flat or by date, before Show all (plan chat-history 2.4)
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
  s.id = 'aichat-css'; s.textContent = MD_CSS + CARD_CSS + ACTIVITY_CSS + LIST_CSS + CONTROLS_CSS + QUOTE_CSS + QREPLY_CSS + SPLIT_CSS + PROJECTS_CSS + PAGE_CSS;
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
/** What the route draws in the main area: a page of its own (`{page: 'all'}`, chat-history 3.1; `{page: 'projects'}`,
 * `{page: 'project', pid}`, plan projects 5.1–5.2; `{page: 'tasks'}`, `{page: 'task', kid}`, scheduled-tasks 4.2), or null for the
 * chats' panes. Thread ids start with t_, so they never clash. */
export function subPage(route) {
  const p = route?.parts || [];
  if (p[1] === 'all') return { page: 'all' };
  if (p[1] === 'tasks') return p[2] ? { page: 'task', kid: decodeURIComponent(p[2]) } : { page: 'tasks' };
  if (p[1] !== 'projects') return null;
  return p[2] ? { page: 'project', pid: decodeURIComponent(p[2]) } : { page: 'projects' };
}
const MAX_PANES = 4;   // while each pane opens its own stream: a browser keeps about six connections to the hub (plan chat-split 2.3)
const DOWN = new Set(['service_not_running', 'service_not_found', 'service_failed', 'upstream_error', 'hub_error']);

export function ChatPage({ api, route, toast = () => {}, confirm, openOutput, openSessions, go = x => { location.hash = x; } }) {
  const React = R(), { useState, useEffect, useRef, useMemo } = React;
  const c = getChatClient(api), sub = subPage(route), allPage = sub?.page === 'all', tid = sub ? null : route?.parts?.[1] || null;   // chat-history 3.1, projects 5.1
  const [rootRef, width] = useWidth(1000), narrow = width < 760;
  const narrowRef = useRef(narrow); narrowRef.current = narrow;
  const [threads, setThreads] = useState([]), [listLoading, setListLoading] = useState(true), [q, setQ] = useState(''), [total, setTotal] = useState(null);
  const [models, setModels] = useState(null), [settings, setSettings] = useState(null), [tools, setTools] = useState(null);
  const [drawer, setDrawer] = useState(false), [down, setDown] = useState(null);
  const [judge, setJudge] = useState(null);       // GET /api/judge/status: Auto is offered while its model answers (plan 30.5)
  const [envs, setEnvs] = useState(null), [listKey, setListKey] = useState(0);   // plan 41.2
  const [listUi] = useUiPref('chat.list', null), listView = readView(listUi ? viewOfUi(listUi) : undefined);   // settings-that-stick 3.3: config.toml [ui.chat.list]
  const archived = archivedParam(listView.show);   // Show: Chats, Archived or Both (chat-history 2.2)
  const [cmd, setCmd] = useState(null);           // the page's New chat, for the active pane
  // chat-split plan 2.2: the open chats' layout, saved in this browser; the URL follows the active pane
  const [layout, setLayout] = useState(() => withRoute(loadLayout() || single(tid), tid));
  const lref = useRef(layout); lref.current = layout;
  useEffect(() => { saveLayout(layout); }, [layout]);
  const mounted = useRef(false), wasSub = useRef(!!sub);
  useEffect(() => {      // a link, the list or Back: that chat in view (#/chat: the active pane becomes a new chat)
    const back = wasSub.current; wasSub.current = !!sub;
    if (!mounted.current) { mounted.current = true; return; }
    if (sub || (back && !tid)) return;   // a page in the main area (Show all, projects), and back from it: the panes stay as they were
    setLayout(L => (tid ? withRoute(L, tid) : setTid(L, activePane(L).id, null)));
  }, [tid, sub?.page]);
  const act = activePane(layout);
  useEffect(() => { if (!sub && (act.tid || null) !== tid) go(act.tid ? '#/chat/' + act.tid : '#/chat'); }, [act.id, act.tid]);   // not on a page: leaving it is the route's
  const bus = useRef(null); if (!bus.current) bus.current = new EventTarget();
  const setListView = v => saveView(v);
  const relist = () => setListKey(n => n + 1);
  const loadRef = useRef(null);
  const fail = e => { if (c.live && (DOWN.has(e?.code) || e?.status === 502 || e?.status === 503)) setDown(e); else toast(e?.detail || String(e?.message || e), 'error'); };
  const openIn = (paneId, id) => setLayout(L => setActive(setTid(L, paneId, id), paneId));
  const newChat = env => { setCmd(x => ({ n: (x?.n || 0) + 1, type: 'new', env, pane: lref.current.active })); setDrawer(false); };

  // ---- data ----
  const loadList = async () => {
    try {
      const [list, n] = await Promise.all([c.threads({ q, archived, limit: LIST_PAGE, sort: listView.chatOrder }),
        c.threadCount ? c.threadCount({ q, archived }).then(r => r.count, () => null) : null]);   // an older agent: no count
      setThreads(list); setTotal(n); setDown(null);
    } catch (e) { fail(e); }
    setListLoading(false);
  };
  loadRef.current = loadList;
  useEffect(() => { const t = setTimeout(loadList, q ? 220 : 0); return () => clearTimeout(t); }, [q, listView.show, listView.chatOrder, listKey]);
  const shown = useRef(listView.show);
  useEffect(() => { if (shown.current !== listView.show) { shown.current = listView.show; setListLoading(true); } }, [listView.show]);
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
  const [svcList, setSvcList] = useState(null);   // calendar 7.1: the mods' side panels
  useEffect(() => {
    let alive = true;
    Promise.resolve(api.listServices?.()).then(s => { if (alive) setSvcList(s || []); return loadChatModules(s || [], chatModuleApi(api)); })
      .then(r => { if (alive && r.some(x => x.ok)) setModTick(t => t + 1); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    const on = e => openOutput?.(e.detail);
    document.addEventListener('gaifa:open-output', on);
    return () => document.removeEventListener('gaifa:open-output', on);
  }, [openOutput]);
  useEffect(() => {       // agent-workflows 3.3: a sub-agent's Open puts it in a pane beside the chat that asked (narrow: in its place)
    const on = e => {
      const { tid: id, pane } = e.detail || {};
      if (!id) return;
      if (narrowRef.current) { go('#/chat/' + id); return; }
      setLayout(L => { const open = panes(L.root).find(p => p.tid === id);
        if (open) return setActive(L, open.id);
        const full = c.live && !c.sharedStream && panes(L.root).length >= MAX_PANES;   // each pane its own stream: as the split's limit
        return full ? setTid(L, activePane(L).id, id) : splitPane(L, pane || L.active, 'right', id); });
    };
    document.addEventListener('gaifa:open-chat-beside', on);
    return () => document.removeEventListener('gaifa:open-chat-beside', on);
  }, []);
  // capability-enablement 3.6: the mods a chat can use (the catalog lists the rest too: not set up, turned off, …), so
  // Read aloud, the mic and the side panels show only for a mod that can run
  const mods = useMemo(() => [...new Set((tools || []).filter(t => !t.state || t.state === 'on' || t.state === 'starts_on_use' || t.state === 'off_by_mod').map(t => t.mod))], [tools]);

  // ---- the list's actions ----
  const listPatch = (id, p) => setThreads(l => l.map(x => (x.id === id ? { ...x, ...p } : x)));
  const patched = t => { if (!t?.id) return; listPatch(t.id, t); bus.current.dispatchEvent(new CustomEvent('patched', { detail: t })); };   // every pane showing it
  const rename = (t, title) => c.patch(t.id, { title }).then(patched, fail);
  const archive = t => c.patch(t.id, { archived: !t.archived }).then(() => {   // with Show: Both the row stays, dimmed or not
    setThreads(l => (archived === 'all' ? l.map(x => (x.id === t.id ? { ...x, archived: !t.archived } : x)) : l.filter(x => x.id !== t.id))); relist();
    const kids = t.children > 0 ? ` with its ${t.children === 1 ? 'sub-agent' : `${t.children} sub-agents`}` : '';   // agent-workflows 3.5
    toast((t.archived ? 'Moved back to chats' : 'Archived') + kids, 'success'); }, fail);
  const move = (t, env) => c.patch(t.id, { settings: { environment: env } }).then(n => {   // plan 41.2: Move to
    patched(n); relist();
    toast(`Moved to ${(envs || []).find(e => e.id === env)?.name || env}`, 'success');
  }, fail);
  const newIn = env => { newChat(env); if (sub) go('#/chat'); };
  const [projects, setProjects] = useState([]);       // plan projects 5.3: Move to… lists them
  const loadProjects = () => c.projects?.().then(setProjects, () => setProjects([]));
  useEffect(() => { loadProjects(); const w = c.watchProjects?.(() => loadProjects()); return () => w?.close(); }, []);
  const [tasks, setTasks] = useState([]);             // scheduled-tasks 4.2: the Scheduled row
  const loadTasks = () => c.tasks?.().then(setTasks, () => setTasks([]));
  useEffect(() => { loadTasks(); const w = c.watchTasks?.(() => loadTasks()); return () => w?.close(); }, []);
  useEffect(() => {          // agent-workflows 3.2: sub-agents started, changed or ended; the trees follow, a parent's row counts them
    const known = new Set();
    const w = c.watchWorkflows?.(ev => {
      bus.current.dispatchEvent(new CustomEvent('agent_child', { detail: ev }));
      if (!ev.child || known.has(ev.child.id) || !ev.parent) return;
      known.add(ev.child.id);                // the first time the page hears of one: its parent's row, with its count
      c.get(ev.parent).then(p => patched(p), () => {});
    });
    return () => w?.close();
  }, []);
  const newInProject = p => { setCmd(x => ({ n: (x?.n || 0) + 1, type: 'new', project: p || null, pane: lref.current.active })); setDrawer(false); if (sub) go('#/chat'); };   // 5.4
  const moveProject = (t, pid) => c.patch(t.id, { settings: { project: pid } }).then(n => {
    patched(n); relist();
    toast(pid ? `Moved to the project ${projects.find(p => p.id === pid)?.name || ''}` : 'Removed from the project', 'success');
  }, fail);
  const itemProps = t => ({ moveTo: (envs || []).filter(e => e.id !== ((t.settings || {}).environment || (envs || []).find(x => x.default)?.id)),
    onMove: envs ? env => move(t, env) : null, projects, onProject: c.projects ? pid => moveProject(t, pid) : null,
    tree: c.tree ? { c, bus: bus.current, activeId: tid, onOpen: () => setDrawer(false) } : null });   // agent-workflows 3.2
  const remove = async t => {
    const kids = t.children > 0 ? ` and its ${t.children === 1 ? 'sub-agent' : `${t.children} sub-agents`}` : '';   // agent-workflows 3.5: they go with it
    const ok = confirm ? await confirm({ title: `Delete “${t.title || 'this chat'}”?`, body: `The chat${kids} and ${kids ? 'their histories are' : 'its history is'} deleted. Its outputs stay in Outputs.`, confirmLabel: 'Delete chat', danger: true }) : window.confirm('Delete this chat?');
    if (!ok) return;
    try { await c.remove(t.id); setThreads(l => l.filter(x => x.id !== t.id)); relist(); setLayout(L => dropTids(L, [t.id])); toast('Chat deleted', 'success'); } catch (e) { fail(e); }
  };
  const sh = {
    api, c, toast, confirm, openOutput, fail, models, projects, reloadModels: () => c.models().then(m => { setModels(m); return m; }, fail), settings, tools, mods, judge, speechOut, envs, loadEnvList, relist, bus: bus.current, rename, patched, listPatch,
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
  const renderItem = t => h(Item, { key: t.id, t, active: t.id === tid, onOpen: () => setDrawer(false), onRename: v => rename(t, v), onArchive: () => archive(t), onDelete: () => remove(t), ...itemProps(t) });
  const grouping = groupOf(listView, { envs: !!envs && !!c.threadGroups, projects: !!c.threadGroups && projects.length > 0 });   // Environment needs the workspace mod, Project some projects; else Date or None
  const list = h(ThreadList, { threads, loading: listLoading, activeId: tid, q, onQ: setQ,
    showAll: !['environment', 'project'].includes(grouping) || q.trim() ? showAllOf(threads.length, total, LIST_PAGE) : null,   // chat-history 2.4: 20, then Show all
    onShowAll: () => { setDrawer(false); go('#/chat/all' + (q.trim() ? '?q=' + encodeURIComponent(q.trim()) : '')); },
    onNew: () => newChat(), onOpen: () => setDrawer(false), onRename: rename, onArchive: archive, onDelete: remove, onClose: narrow ? () => setDrawer(false) : null, onSessions: openSessions ? () => { setDrawer(false); openSessions(); } : null,
    view: listView, onView: setListView, canGroup: !!envs, canProjects: projects.length > 0, itemProps,
    projectsRow: c.projects ? h(ProjectsEntry, { projects, active: sub?.page === 'projects' || sub?.page === 'project', current: sub?.page === 'project' ? sub.pid : null, go, onGo: () => setDrawer(false) }) : null,   // plan projects 5.4
    tasksRow: c.tasks ? h(TasksEntry, { tasks, active: sub?.page === 'tasks' || sub?.page === 'task', current: sub?.page === 'task' ? sub.kid : null, onGo: () => setDrawer(false) }) : null,   // scheduled-tasks 4.2
    groupLabel: grouping === 'date' ? 'Chats by date' : grouping === 'project' ? 'Chats by project' : 'Chats by environment',
    grouped: grouping === 'environment' ? h(GroupedChats, { c, api, envs, view: listView, onView: setListView, known: threads, reloadKey: listKey,
      renderItem, onNewIn: newIn, onEnvsChanged: loadEnvList, onError: fail, go })
      : grouping === 'project' ? h(ProjectChats, { c, projects, view: listView, onView: setListView, known: threads, reloadKey: listKey,   // plan projects 5.4
        renderItem, onNewIn: newInProject, onError: fail, go })
      : grouping === 'date' && threads.length ? h(DateSections, { threads, view: listView, renderItem }) : null });   // chat-history 2.3
  return h('div', { ref: rootRef, style: { display: 'flex', height: '100%', minHeight: 0, position: 'relative', overflow: 'hidden', background: T.bg } },
    narrow ? null : h('div', { style: { width: 248, flex: 'none', borderRight: '1px solid ' + T.bd, minHeight: 0 } }, list),
    narrow && drawer ? h(React.Fragment, null,
      h('div', { onClick: () => setDrawer(false), 'aria-hidden': true, style: { position: 'absolute', inset: 0, zIndex: 40, background: T.ov } }),
      h('div', { style: { position: 'absolute', top: 0, bottom: 0, left: 0, zIndex: 41, width: 'min(300px, 86%)', borderRight: '1px solid ' + T.bds, boxShadow: '0 0 40px rgba(0,0,0,.4)' } }, list)) : null,
    allPage ? h(AllChats, { c, view: listView, onView: setListView, envs, projects, project0: route?.params?.project || '', q0: route?.params?.q || '', reloadKey: listKey, bus: bus.current, itemProps,
      actions: { rename, archive, remove }, onError: fail, onMenu: narrow ? () => setDrawer(true) : null,
      onBack: () => go(act.tid ? '#/chat/' + act.tid : '#/chat') }) :
    sub?.page === 'projects' ? h(ProjectsPage, { c, toast, go, onMenu: narrow ? () => setDrawer(true) : null }) :
    sub?.page === 'project' ? h(ProjectPage, { key: sub.pid, shared: sh, pid: sub.pid, go }) :
    sub?.page === 'tasks' ? h(TasksPage, { shared: sh, go }) :
    sub?.page === 'task' ? h(TaskPage, { key: sub.kid, shared: sh, kid: sub.kid, go }) :
    h(SplitView, { layout, setLayout, narrow, maxPanes: c.live && !c.sharedStream ? MAX_PANES : Infinity, onRefuse: m => toast(m, 'error'),
      titleOf: id => threads.find(t => t.id === id)?.title || null,
      renderPane: (p, { active, tools, grip }) => h(ChatPane, { shared: sh, tid: p.tid, paneId: p.id, cmd, grip, paneTools: tools,
        onOpen: id => openIn(p.id, id), onFocus: active ? null : () => setLayout(L => setActive(L, p.id)) }) }),
    h(ChatPanels, { services: svcList, narrow, api, go, toast }));   // calendar 7.1: mods' side panels (the Calendar's)
}
