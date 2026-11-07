// One connection for every open chat's events (chat-split plan 3.2). The Chat page can show any number of chats side
// by side, and a browser keeps only about six connections to the hub; so the live client's `stream(tid, after,
// handlers)` subscribes to a pool that keeps one EventSource on the agent's `/v1/streams?threads=<tid>:<after>,…`,
// reopened (after `delay` ms) whenever the set of threads changes, each thread from the oldest seq a subscriber still
// needs. Each subscriber skips what it has already seen, so a reopen never repeats an event for it. Against an agent
// without the route (it answers 404) the pool hands every subscription to `single`, one stream per thread as before.
// chat-responsive 3.1: the agent names each shared stream (its first event, {type: 'stream', id}); with `control`, a chat
// opened or closed later is added to or removed from that connection (`POST /v1/streams/{id}/threads`) instead of
// reopening it for every chat, and the pool reopens only when that call fails (an older agent, or a stream that ended).
// Tested in utils/tests/web/chat-streams.test.mjs.
//
// createStreamPool({streamsUrl(spec), single(tid, after, handlers), probe() → Promise<boolean>, EventSource, delay,
//                   control(id, {add: [[tid, after]], remove: [tid]}) → Promise<boolean>})
//   → {stream(tid, after, {onEvent, onReady, onState}) → {close(), lastSeq}, get shared()}

export function createStreamPool({ streamsUrl, single, probe = () => Promise.resolve(true), EventSource: ES = globalThis.EventSource, delay = 40,
  setTimer = (f, ms) => setTimeout(f, ms), clearTimer = t => clearTimeout(t), control = null }) {
  const subs = new Set();        // {tid, last, h, inner (a single stream in fallback), sent (the connection carries it for this sub)}
  let es = null, timer = null, tries = 0, shared = null, probing = null, sid = null, carried = new Set();

  const spec = () => {
    const after = new Map();
    for (const s of subs) after.set(s.tid, Math.min(after.has(s.tid) ? after.get(s.tid) : Infinity, s.last));
    return [...after].map(([tid, a]) => `${encodeURIComponent(tid)}:${a}`).join(',');
  };
  const each = (tid, f) => { for (const s of [...subs]) if (tid == null || s.tid === tid) f(s); };
  const close = () => { if (es) { es.onopen = es.onmessage = es.onerror = null; es.close(); es = null; } sid = null; carried = new Set(); };
  const open = () => {
    timer = null;
    close();
    if (!subs.size || shared !== true) return;
    for (const s of subs) s.sent = true;
    carried = new Set([...subs].map(s => s.tid));
    es = new ES(streamsUrl(spec()));
    es.onopen = () => { tries = 0; each(null, s => s.h.onState?.('open')); };
    es.onmessage = m => {
      let ev;
      try { ev = JSON.parse(m.data); } catch { return; }
      if (ev.type === 'stream') { sid = ev.id; return; }
      if (ev.type === 'ready') { each(ev.thread_id, s => s.h.onReady?.(ev)); return; }
      if (ev.type === 'gone') return;      // the chat's own get() answers 404 and the pane says so
      each(ev.thread_id, s => {
        if (ev.seq != null) { if (ev.seq <= s.last) return; s.last = ev.seq; }
        s.h.onEvent?.(ev);
      });
    };
    es.onerror = () => {
      close();
      each(null, s => s.h.onState?.('reconnecting'));
      clearTimer(timer);
      timer = setTimer(open, Math.min(10000, 800 * 2 ** tries++));
    };
  };
  // A change in which chats are open: added to or removed from the open connection, or the connection (re)opened.
  const sync = () => {
    timer = null;
    if (!subs.size) { close(); return; }
    if (!es || !sid || !control) { open(); return; }
    const want = new Set([...subs].map(s => s.tid)), fresh = [...subs].filter(s => !s.sent);
    const add = new Map();
    for (const s of fresh) add.set(s.tid, Math.min(add.has(s.tid) ? add.get(s.tid) : Infinity, s.last));
    const remove = [...carried].filter(t => !want.has(t));
    if (!add.size && !remove.length) return;
    fresh.forEach(s => { s.sent = true; });
    const at = es;
    control(sid, { add: [...add], remove }).then(ok => {
      if (at !== es) return;                       // reopened meanwhile: that carries everything
      if (!ok) { open(); return; }
      add.forEach((_, t) => carried.add(t)); remove.forEach(t => carried.delete(t));
    }, () => { if (at === es) open(); });
  };
  const schedule = () => { clearTimer(timer); timer = setTimer(sync, delay); };
  const decided = () => {          // the agent has /v1/streams, or not: subscriptions made meanwhile follow
    if (shared === false) { for (const s of subs) if (!s.inner) s.inner = single(s.tid, s.last, s.h); return; }
    schedule();
  };

  function stream(tid, after = 0, h = {}) {
    const s = { tid, last: after, h, inner: null, sent: false };
    subs.add(s);
    if (shared === null && !probing) probing = Promise.resolve().then(probe).catch(() => true).then(ok => { shared = !!ok; probing = null; decided(); });
    else if (shared === false) s.inner = single(tid, after, h);
    else if (shared === true) schedule();
    return {
      close() {
        if (!subs.delete(s)) return;
        if (s.inner) { s.inner.close(); return; }
        if (shared === true) schedule();
      },
      get lastSeq() { return s.inner ? s.inner.lastSeq : s.last; },
    };
  }
  return { stream, get shared() { return shared !== false; }, get open() { return !!es; } };
}
