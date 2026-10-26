// One chat on the Chat page (chat-split plan 1.2): its stream, events and live state, the header, the thread and the
// composer. `ChatPage` (chat.js) keeps the chat list and what every pane shares (`shared`: the client, models, tools,
// settings, environments, the list's updates) and draws one `ChatPane` per open chat; a pane never changes the URL
// itself, it asks with `onOpen(tid | null)`.
//
// shared: {api, c, toast, confirm, openOutput, fail, models, settings, tools, mods, judge, speechOut, envs, folders?,
//          loadEnvList, relist, reloadList, addThread(th), listPatch(id, partial), patched(t), rename(t, title),
//          envDeleted(ids), bus (EventTarget: 'patched' {detail: thread}), banner (an element or null), onMenu}
// cmd: {n, type: 'new', env?, pane} from the page, acted on when `n` changes by the pane it names (New chat, New chat in
// an environment). grip, paneTools: the split view's handle and buttons, drawn in the header.

import { h, T, Icon, COL, useWidth, chipSt, label11 } from './chat-ui.js';
import { Card, TodoList } from './chat-cards.js';
import { runAction } from './chat-actions.js';
import { buildView, applyTransient, settleLive, mergeEvents, todosOpen, threadOf } from './chat-thread.js';
import { groupTurns } from './chat-turn.js';
import { TurnView } from './chat-activity.js';
import { ThreadHeader, bypassAllowed } from './chat-header.js';
import { decideFolder, lastEnv, rememberEnv, newChatSettings } from './chat-env.js';
import { ControlsRow, ModeMenu, ModelMenu, EnvMenu } from './chat-controls.js';
import { Composer, chatSkills, typeInto } from './chat-composer.js';
import { VoiceButton, lastAnswer } from './chat-voice.js';
import { scrollToReply } from './chat-quote.js';
import { QuoteReplyBox, addQuote, draftQuotes, quotesPayload, messageText } from './chat-quote-reply.js';
import { speak, speakable } from './chat-speak.js';

const R = () => globalThis.React;
const EMPTY_LIVE = { deltas: {}, progress: {}, meter: null };
const SUGGEST = ['Make me an image of a fox in the snow', 'Turn my last image into a 3D model', 'Say “Welcome to GAIFA” in Hope’s voice', 'What can you do?'];

export function ChatPane({ shared, tid = null, paneId = null, cmd = null, onOpen = () => {}, onFocus = null, grip = null, paneTools = null, style = null }) {
  const React = R(), { useState, useEffect, useRef, useMemo, useLayoutEffect } = React;
  const { api, c, toast, confirm, openOutput, fail, models, settings, tools, mods, judge, speechOut, envs } = shared;
  const [rootRef, width] = useWidth(800);
  const [thread, setThread] = useState(null), [events, setEvents] = useState([]), [live, setLive] = useState(EMPTY_LIVE), [running, setRunning] = useState(false), [conn, setConn] = useState('open'), [ready, setReady] = useState(false);
  const [quoteDrafts, setQuoteDrafts] = useState({});   // Select → Reply: the quote-reply cards waiting in each chat's composer
  const [drafts, setDrafts] = useState({}), [attachments, setAttachments] = useState([]), [toolForms, setToolForms] = useState([]);
  const [meterOpen, setMeterOpen] = useState(false);
  const [fresh, setFresh] = useState(() => ({ model: null, mode: 'manual', settings: newChatSettings({}, lastEnv()) }));   // a chat not created yet; its environment: the last one picked (plan 34)
  const [folders, setFolders] = useState(null);   // the workspace mod's folders, for Bypass (plan 27.4)
  const scrollRef = useRef(null), contentRef = useRef(null), stick = useRef(true), first = useRef(true), inputRef = useRef(null), queue = useRef([]), flushT = useRef(0);
  const dkey = tid || 'new', draft = drafts[dkey] || '';
  const setDraft = v => setDrafts(d => ({ ...d, [dkey]: typeof v === 'function' ? v(d[dkey] || '') : v }));
  const quotes = quoteDrafts[dkey] || [], setQuotes = (v, k = dkey) => setQuoteDrafts(m => ({ ...m, [k]: typeof v === 'function' ? v(m[k] || []) : v || [] }));

  // ---- data ----
  const flush = () => {
    flushT.current = 0;
    const evs = queue.current; queue.current = [];
    if (!evs.length) return;
    const stored = evs.filter(e => e.seq != null);
    if (stored.length) setEvents(list => mergeEvents(list, stored));
    setLive(l => evs.reduce((acc, e) => (e.seq == null ? applyTransient(acc, e) : settleLive(acc, e)), l));
    for (const e of evs) {
      if (e.type === 'thread' && threadOf(e.payload)) { const t = threadOf(e.payload); setThread(x => (x && x.id === t.id ? { ...x, ...t } : x)); shared.listPatch(t.id, t); }
      if (e.type === 'state' && e.seq != null) {
        const st = e.payload.state;
        setRunning(st === 'running'); setThread(x => (x ? { ...x, state: st } : x));
        shared.listPatch(e.thread_id, { state: st, running: st === 'running', updated: e.ts });
        if (st !== 'running') setTimeout(() => shared.reloadList(), 300);
      }
    }
  };
  useEffect(() => {
    setEvents([]); setLive(EMPTY_LIVE); setThread(null); setReady(false); setRunning(false); setToolForms([]); setMeterOpen(false); setAttachments([]);
    first.current = true; stick.current = true; queue.current = [];
    if (!tid) return undefined;
    let alive = true;
    c.get(tid).then(t => { if (alive) { setThread(t); setRunning(!!t.running); } })
      .catch(e => { if (!alive) return; if (e.status === 404) { if (c.live) toast('That chat no longer exists', 'error'); onOpen(null); } else fail(e); });
    c.context(tid).then(m => alive && setLive(l => ({ ...l, meter: m }))).catch(() => {});
    const s = c.stream(tid, 0, {
      onEvent: ev => { if (!alive) return; queue.current.push(ev); if (!flushT.current) flushT.current = setTimeout(flush, 30); },
      onReady: ev => { if (alive) { setRunning(!!ev.running); setReady(true); } },
      onState: st => alive && setConn(st),
    });
    return () => { alive = false; s.close(); clearTimeout(flushT.current); flushT.current = 0; };
  }, [tid]);
  useEffect(() => {      // a rename, model or mode change made elsewhere (the list, another pane): the agent doesn't stream it
    const on = e => { const t = e.detail; if (t?.id) setThread(x => (x && x.id === t.id ? { ...x, ...t } : x)); };
    shared.bus.addEventListener('patched', on);
    return () => shared.bus.removeEventListener('patched', on);
  }, [shared.bus]);
  const seenCmd = useRef(cmd?.n);
  useEffect(() => {      // the page's New chat (in an environment): this pane is the active one
    if (!cmd || cmd.n === seenCmd.current) return;
    seenCmd.current = cmd.n;
    if (cmd.pane && cmd.pane !== paneId) return;
    if (cmd.type === 'new') {
      if (cmd.env) { rememberEnv(cmd.env); setFresh(f => ({ ...f, settings: { ...f.settings, environment: cmd.env } })); }
      onOpen(null);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [cmd?.n]);

  const envId = (thread ? thread.settings?.environment : fresh.settings?.environment) || null;   // plan 34: the chat's environment
  useEffect(() => {      // its folders (and those allowed in this chat), for Bypass (plan 27.4)
    api.callService?.('workspace', 'GET', '/v1/folders', envId ? { query: { environment: envId } } : {}).then(r => setFolders(r.json?.folders || [])).catch(() => setFolders([]));
  }, [envId]);
  const wsOff = (thread?.settings?.disabled || []).includes('workspace');
  const [wsSkills, setWsSkills] = useState([]);
  useEffect(() => {      // skill-sources 2.3: the skills other agents keep in this chat's folders, for its `/` menu
    if (wsOff) { setWsSkills([]); return; }
    api.callService?.('workspace', 'GET', '/v1/skills', envId ? { query: { environment: envId } } : {}).then(r => setWsSkills(r.json?.skills || [])).catch(() => setWsSkills([]));
  }, [envId, wsOff]);
  const skills = useMemo(() => chatSkills(settings?.skills || [], wsSkills), [settings?.skills, wsSkills]);
  const wasRunning = useRef(false), reading = useRef(null), voiceOn = useRef(false);
  useEffect(() => {      // read every reply aloud (auto_read): when a turn ends, its last message
    if (wasRunning.current && !running && speechOut?.auto_read && c.live && !voiceOn.current) {   // voice mode reads its own
      const words = speakable(lastAnswer(events).text);
      if (words) { reading.current?.stop(); reading.current = speak(words, speechOut); reading.current.done.catch(() => {}); }
    }
    wasRunning.current = running;
  }, [running]);
  useEffect(() => () => reading.current?.stop(), [tid]);
  const view = useMemo(() => buildView(events, live), [events, live]);
  const [now, setNow] = useState(() => Date.now() / 1000);   // ticks while a turn runs, so the fold's timers count
  useEffect(() => { setNow(Date.now() / 1000); if (!running) return undefined; const t = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(t); }, [running]);
  const blocks = useMemo(() => {
    const b = groupTurns(view, { running, now, tools }), last = b.findLast(x => x.kind === 'turn');
    if (last) last.latest = true;   // fix-it cards show on the newest turn only (chat-fix.js)
    return b;
  }, [view, running, now, tools]);
  // what this chat's tools made: shown at the top of the turn that made it, never drawn again in a reply or by show
  const madeKey = blocks.flatMap(b => (b.outputs || []).map(o => o.output_id)).join(',');
  const made = useMemo(() => new Set(madeKey ? madeKey.split(',') : []), [madeKey]);
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
    shared.addThread(th);
    onOpen(th.id);
    return th.id;
  };
  const slash = async text => {
    const [cmdName, ...rest] = text.slice(1).split(/\s+/), arg = rest.join(' ').trim();
    if (cmdName === 'compact') { if (!tid) toast('Nothing to compact yet'); else c.compact(tid).then(() => toast('Compacted: earlier messages summarized', 'success'), fail); return null; }
    if (cmdName === 'clear') { onOpen(null); return null; }
    if (cmdName === 'context') { setMeterOpen(true); return null; }
    if (cmdName === 'clear-gpu') {      // plan 46.2: hub_free_gpu as your own step, drawn as its status card
      const services = arg ? arg.split(/[\s,]+/).filter(Boolean) : [];
      ensureThread().then(id => c.action(id, 'hub_free_gpu', services.length ? { services } : {})).catch(fail);
      return null;
    }
    if (cmdName === 'model') {
      if (!arg) { toast('Usage: /model <id>. ' + (models?.models || []).map(m => m.id).join(', ')); return null; }
      if (models && !models.models.some(m => m.id === arg)) { toast(`No model “${arg}”`, 'error'); return null; }
      setModel(arg); toast(`Model: ${arg}`, 'success'); return null;
    }
    const skill = skills.find(s => (s.folder ? s.id : s.name) === cmdName);
    if (skill) return `Use the ${skill.id || skill.name} skill: ${arg}`.trim();
    return text;
  };
  const send = async (text, atts = [], qs = null, mentions = []) => {   // qs: the composer's quote-reply cards (null: a suggestion or a button); mentions: plan 48.2
    let t = text.trim();
    const k = dkey, cards = qs || [];
    if (t.startsWith('/')) { t = await slash(t); setDrafts(d => ({ ...d, [k]: '' })); if (t == null) return; }   // the cards stay for the next message
    t = messageText(t, atts, cards);
    if (!t && !cards.some(q => q.reply.trim())) return;
    setDrafts(d => ({ ...d, [k]: '' })); setAttachments([]); if (cards.length) setQuotes([], k); stick.current = true;
    try { const id = await ensureThread(); await c.send(id, t, atts.map(a => a.id), Object.fromEntries(atts.filter(a => a.mode).map(a => [a.id, a.mode])), quotesPayload(cards), mentions); }
    catch (e) { setDrafts(d => ({ ...d, [k]: text })); if (cards.length) setQuotes(l => [...cards, ...l], k); fail(e); }
  };
  const setModel = m => { if (thread) c.patch(thread.id, { model: m }).then(t => { shared.patched(t); c.context(thread.id).then(mm => setLive(l => ({ ...l, meter: mm }))).catch(() => {}); }, fail); else setFresh(f => ({ ...f, model: m })); };
  const setMode = m => { if (thread) c.patch(thread.id, { mode: m }).then(shared.patched, fail); else setFresh(f => ({ ...f, mode: m })); };
  const setGroups = s => { if (thread) c.patch(thread.id, { settings: s }).then(shared.patched, fail); else setFresh(f => ({ ...f, settings: { ...f.settings, ...s } })); };
  const setEnv = id => { rememberEnv(id); setGroups({ ...(thread ? thread.settings || {} : {}), environment: id }); if (thread) setTimeout(shared.relist, 300); };
  const forkAt = async (seq, text, qs = []) => {   // qs: the message's quote-replies, as cards to edit (their seqs are the same in the branch)
    try {
      if (seq < 1) { onOpen(null); setDrafts(d => ({ ...d, new: text || '' })); if (qs.length) setQuotes(qs.map(({ seq: _s, ...q }) => q), 'new'); return; }
      const th = await c.fork(tid, seq);
      shared.addThread(th);
      if (text != null) setDrafts(d => ({ ...d, [th.id]: text }));
      if (qs.length) setQuotes(qs, th.id);
      onOpen(th.id);
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
    api, live: c.live, tid, thread, outputs: view.outputs, made, tools, mods, running, dock: true, confirm, toast, speechOutput: speechOut,
    act: (tool, args) => ensureThread().then(id => c.action(id, tool, args)),   // plan 46.5: a fix runs as your own step
    answer: (qid, answers) => c.answer(tid, qid, answers),
    // o: {remember, confirm} when allowing (plan 25.3), {reason} when denying
    // plan 34: "Add to <environment>" adds the folder there first (chat-env.js), then allows the call once
    decide: async (a, approve, args, o = {}) => { if (approve && a.limits?.ask_folder) o = await decideFolder(api, a.limits.ask_folder, o);
      return c.approval(tid, { approval_id: a.approval_id, approve, ...(approve ? { arguments: args, remember: o.remember || 'once', ...(o.confirm ? { confirm: true } : {}) } : { reason: o.reason || 'Denied in the chat' }) }); },
    cancel: () => c.cancel(tid).catch(fail),
    branch: it => forkAt(it.ev.seq - 1, it.ev.payload.text, draftQuotes(it.ev.payload)),
    copy: text => navigator.clipboard?.writeText(text).then(() => toast('Copied', 'success'), () => {}),
    scrollToReply: seq => scrollToReply(seq, rootRef.current || undefined),   // the reply in this pane, not another chat's
    openOutput, runAction: (a, o) => runAction(a, o, { openTool, attach, sendPrompt: t => send(t), api, toast, environment: envId, thread: tid }),   // api…thread: Save to… (plan 48.4)
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
  const empty = !tid || (ready && !events.length && !running);
  const compacts = events.filter(e => e.type === 'compact').length;
  return h('section', { ref: rootRef, 'aria-label': thread?.title ? `Chat: ${thread.title}` : 'Chat', 'data-chat-pane': tid || 'new', onMouseDownCapture: onFocus || undefined, onFocusCapture: onFocus || undefined,
    tabIndex: -1, onKeyDown: e => typeInto(e, inputRef.current),   // a click on the chat, then typing: the letters go into the box
    style: { outline: 'none', flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 0, position: 'relative', background: T.bg, ...style } },
    h(ThreadHeader, { thread,
      onRename: title => shared.rename(thread, title), meter: live.meter, meterOpen, setMeterOpen, onCompact: () => c.compact(tid).then(() => toast('Compacted', 'success'), fail), compacts,
      learn: thread ? !(thread.settings || {}).no_learn : null, onLearn: thread ? on => setGroups({ ...(thread.settings || {}), no_learn: !on }) : null,
      running, state: thread?.state, onBranch: events.length ? () => forkAt(view.lastSeq, null) : null, onMenu: shared.onMenu, narrow: width < 700, grip, tools: paneTools }),
    shared.banner || null,
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
      voice: h(VoiceButton, { api, onSend: t => send(t), running, waiting: view.pending.length > 0, answer: lastAnswer(events), speechOutput: speechOut, onMode: m => { voiceOn.current = m !== 'off'; } }),
      settings: thread?.settings || fresh.settings, onSettings: setGroups, skills, outputs: view.outputs, api, inputRef, quotes, setQuotes, folders,
      onQuick: a => runAction(a, null, { openTool, attach, sendPrompt: t => send(t) }),
      controls: h(ControlsRow, {   // plan 42.3: the chat's environment, mode and model, under the box
        env: h(EnvMenu, { api, c, thread, envs, value: envId, onChange: setEnv, stamp: events.reduce((n, e) => n + (e.type === 'decision'), 0), onEnvsChanged: shared.loadEnvList, confirm,
          onDeleted: (id, ids) => { shared.envDeleted(ids); if (tid && ids.includes(tid)) onOpen(null);
            toast(`Deleted the environment${ids.length ? ` and ${ids.length} chat${ids.length === 1 ? '' : 's'}` : ''}`, 'success'); } }),
        mode: h(ModeMenu, { value: thread?.mode || fresh.mode, onChange: setMode, bypass: bypassAllowed(folders, events), judge }),
        model: h(ModelMenu, { models, value: thread?.model || fresh.model || models?.default, onChange: setModel }) }) }),
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
