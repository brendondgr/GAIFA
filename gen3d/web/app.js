// 3DGenerate web UI: state, chats, live updates (SSE) and worker status. No build step.
// Modules: composer.js (prompt + settings menu), cards.js (job cards), viewer.js (three.js);
// main.js imports them all (they register hooks) and then calls boot().

import { $, api, esc, fmtDur, fmtClock, toast, store, ICON } from "./util.js";

export const S = {
  chats: [],
  chat: null,          // current chat id (null = a new, unsaved chat)
  jobs: new Map(),     // id -> job (current chat)
  allActive: new Map(),// id -> job for every queued/running job (queue dialog, badges)
  options: null,       // /v1/options
  health: null,
  hooks: { jobChanged: [], chatOpened: [], ready: [] },
};

const on = (name, fn) => S.hooks[name].push(fn);
const fire = (name, ...a) => S.hooks[name].forEach((fn) => fn(...a));
export { on };

// ---- chats ------------------------------------------------------------------------------------

export async function loadChats() {
  S.chats = (await api("/v1/chats")).chats;
  renderChats();
}

function renderChats() {
  const nav = $("chat-list");
  if (!S.chats.length) { nav.innerHTML = `<p class="muted small" style="padding:10px">No chats yet.</p>`; return; }
  const today = new Date().toDateString();
  const groups = {};
  for (const c of S.chats) {
    const d = new Date(c.updated * 1000);
    const g = d.toDateString() === today ? "Today"
      : Date.now() - d < 7 * 864e5 ? "This week" : "Earlier";
    (groups[g] ||= []).push(c);
  }
  nav.innerHTML = Object.entries(groups).map(([g, list]) => `<div class="chat-group">${g}</div>` + list.map((c) => {
    const live = [...S.allActive.values()].some((j) => j.chat_id === c.id);
    return `<div class="chat-item${c.id === S.chat ? " active" : ""}" data-chat="${c.id}">
      <button class="open" data-action="open-chat" data-id="${c.id}" title="${esc(c.title)}">${esc(c.title)}</button>
      ${live ? `<span class="badge-live" title="Job running or queued"></span>` : ""}
      <button class="icon-btn small del" data-action="delete-chat" data-id="${c.id}" title="Delete chat" aria-label="Delete chat">${ICON.trash}</button>
    </div>`;
  }).join("")).join("");
}

export async function openChat(id, { push = true } = {}) {
  S.chat = id;
  S.jobs.clear();
  if (push) history.replaceState(null, "", id ? `#${id}` : "#");
  $("app").classList.remove("side-open");
  let title = "New chat";
  if (id) {
    try {
      const chat = await api(`/v1/chats/${id}`);
      title = chat.title;
      for (const j of chat.jobs) S.jobs.set(j.id, j);
    } catch (e) {
      toast(e.message); S.chat = null; history.replaceState(null, "", "#");
    }
  }
  $("chat-title").textContent = title;
  renderChats();
  fire("chatOpened");
}

export async function ensureChat(titleHint) {
  if (S.chat) return S.chat;
  const chat = await api("/v1/chats", { method: "POST", body: { title: (titleHint || "New chat").slice(0, 60) } });
  S.chats.unshift(chat);
  S.chat = chat.id;
  history.replaceState(null, "", `#${chat.id}`);
  $("chat-title").textContent = chat.title;
  renderChats();
  return chat.id;
}

async function deleteChat(id) {
  const c = S.chats.find((x) => x.id === id);
  const btn = document.querySelector(`.chat-item[data-chat="${id}"] .del`);
  if (btn && !btn.dataset.armed) {  // two-step delete: no confirm() dialogs
    btn.dataset.armed = "1"; btn.style.color = "var(--red)"; btn.title = "Click again to delete";
    toast(`Click again to delete "${c?.title}" and its files`);
    setTimeout(() => { if (btn) { delete btn.dataset.armed; btn.style.color = ""; btn.title = "Delete chat"; } }, 3000);
    return;
  }
  await api(`/v1/chats/${id}`, { method: "DELETE" });
  S.chats = S.chats.filter((x) => x.id !== id);
  if (S.chat === id) await openChat(null);
  renderChats();
}

function startRename() {
  const h = $("chat-title");
  if (!S.chat || h.isContentEditable) return;
  h.contentEditable = "true"; h.focus();
  document.getSelection().selectAllChildren(h);
  const done = async (save) => {
    h.contentEditable = "false";
    const t = h.textContent.trim();
    const chat = S.chats.find((c) => c.id === S.chat);
    if (save && t && chat && t !== chat.title) {
      await api(`/v1/chats/${S.chat}`, { method: "PATCH", body: { title: t } });
      chat.title = t; renderChats();
    } else if (chat) h.textContent = chat.title;
  };
  h.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); h.blur(); } if (e.key === "Escape") { done(false); } };
  h.onblur = () => done(true);
}

// ---- jobs -------------------------------------------------------------------------------------

export function upsertJob(job) {
  const prev = S.jobs.get(job.id) || S.allActive.get(job.id);
  if (["queued", "running"].includes(job.status)) S.allActive.set(job.id, job);
  else S.allActive.delete(job.id);
  if (job.chat_id === S.chat) S.jobs.set(job.id, job);
  if (prev && prev.status !== job.status && ["done", "failed"].includes(job.status)) finished(job);
  fire("jobChanged", job, prev);
  renderChatsSoon();
  renderQueueBadge();
}

let chatsTimer;
function renderChatsSoon() { clearTimeout(chatsTimer); chatsTimer = setTimeout(renderChats, 200); }

// Tell the user when something finishes: toast, tab title, and (opt-in) a desktop notification.
let unseen = 0;
function finished(job) {
  const ok = job.status === "done";
  const took = job.finished && job.started ? ` in ${fmtDur(job.finished - job.started)}` : "";
  const msg = ok ? `Ready${took}: ${job.title}` : `Failed: ${job.title}`;
  toast(msg, 5000);
  if (document.hidden) { unseen++; document.title = `(${unseen}) 3DGenerate`; }
  if (store("notify") && "Notification" in window && Notification.permission === "granted" && document.hidden) {
    const n = new Notification(ok ? "3D model ready" : "3D job failed", { body: `${job.title}${took}`, icon: "icon.svg", tag: job.id });
    n.onclick = () => { window.focus(); if (job.chat_id) openChat(job.chat_id); };
  }
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) { unseen = 0; document.title = "3DGenerate"; } });

async function loadActive() {
  const { jobs } = await api("/v1/jobs?status=queued,running&limit=200");
  S.allActive = new Map(jobs.map((j) => [j.id, j]));
  renderQueueBadge();
}

function renderQueueBadge() {
  const n = S.allActive.size;
  $("queue-count").textContent = n ? String(n) : "";
  const last = [...S.allActive.values()].reduce((m, j) => Math.max(m, j.eta?.done_at || 0), 0);
  $("top-chips").innerHTML = n
    ? `<span class="chip"><span class="dot busy"></span><b>${n}</b> job${n > 1 ? "s" : ""} · all done ~<b>${fmtClock(last)}</b></span>`
    : "";
  if ($("queue-dialog").open) renderQueueDialog();
}

function renderQueueDialog() {
  const rows = [...S.allActive.values()].sort((a, b) => (a.eta?.queue_position ?? 99) - (b.eta?.queue_position ?? 99));
  $("queue-summary").textContent = rows.length ? `${rows.length} active` : "";
  $("queue-list").innerHTML = rows.length ? rows.map((j) => {
    const e = j.eta || {};
    const left = e.done_at ? e.done_at - Date.now() / 1000 : null;
    return `<div class="q-row">
      <span class="pos">${j.status === "running" ? "▶" : "#" + (e.queue_position ?? "?")}</span>
      <span class="t">${esc(j.title)}<small class="muted">${j.id} · ${j.stages ? Object.keys(j.stages).join(" → ") : ""}</small></span>
      <span class="when">${j.status === "running" ? "running" : "starts in " + fmtDur(e.starts_in_s)}<br>done ${fmtDur(left)} · ${e.done_at ? fmtClock(e.done_at) : "–"}</span>
      <span>${j.chat_id ? `<button class="icon-btn" data-action="open-chat" data-id="${j.chat_id}" title="Open chat">${ICON.continue}</button>` : ""}
        <button class="icon-btn" data-action="cancel-job" data-id="${j.id}" title="Cancel">${ICON.stop}</button></span>
    </div>`;
  }).join("") : `<p class="q-empty">Nothing queued. The GPU is free.</p>`;
}

// ---- live updates -----------------------------------------------------------------------------

let es;
function connectEvents() {
  es?.close();
  es = new EventSource("/v1/events");
  es.addEventListener("job", (e) => upsertJob(JSON.parse(e.data)));
  es.addEventListener("worker", () => refreshHealth());
  es.addEventListener("chat", (e) => {
    const c = JSON.parse(e.data);
    const i = S.chats.findIndex((x) => x.id === c.id);
    if (i >= 0) S.chats[i] = { ...S.chats[i], ...c }; else S.chats.unshift(c);
    if (c.id === S.chat) $("chat-title").textContent = c.title;
    renderChatsSoon();
  });
  es.addEventListener("deleted", (e) => {
    const d = JSON.parse(e.data);
    if (d.id) { S.jobs.delete(d.id); S.allActive.delete(d.id); fire("jobChanged", { id: d.id, deleted: true }); }
    if (d.chat_id && !d.id) { S.chats = S.chats.filter((c) => c.id !== d.chat_id); if (S.chat === d.chat_id) openChat(null); }
    renderChatsSoon(); renderQueueBadge();
  });
  es.onopen = () => refreshHealth();
  es.onerror = () => setWorker(null);  // EventSource reconnects by itself
}

export async function refreshHealth() {
  try {
    S.health = await api("/health");
    setWorker(S.health);
  } catch { setWorker(null); }
}

function setWorker(h) {
  const dot = $("worker-dot"), lab = $("worker-label"), dot2 = $("worker-dot2");
  if (!h) { dot.className = "dot err"; lab.textContent = "Offline"; dot2.className = "dot err"; $("worker-detail").textContent = "API not reachable"; return; }
  const w = h.worker;
  const cls = w.state === "busy" || w.state === "starting" ? "busy" : w.state === "ready" ? "ok" : "";
  dot.className = dot2.className = `dot ${cls}`;
  const models = w.loaded?.length ? w.loaded.map((m) => (m === "shape" ? "Cube3D" : "CubePart")).join(" + ") : "";
  lab.textContent = { stopped: "GPU idle", starting: "Worker starting", ready: models ? `Loaded: ${models}` : "Worker ready", busy: "Generating…" }[w.state] || w.state;
  if (h.fake_worker) lab.textContent += " (fake)";
  $("worker-detail").textContent = `${w.state}${models ? " · " + models : ""}${w.device ? " · " + w.device : ""}${w.unloads_in_s != null ? ` · unloads in ${fmtDur(w.unloads_in_s)}` : ""}`;
  $("idle-note").textContent = `unloads after ${fmtDur(h.idle_unload_s)} idle`;
  $("data-dir").textContent = h.data;
}

// ---- global UI --------------------------------------------------------------------------------

const ACTIONS = {
  "new-chat": () => openChat(null),
  "open-chat": (el) => { document.querySelectorAll("dialog[open]").forEach((d) => d.close()); openChat(el.dataset.id); },
  "delete-chat": (el) => deleteChat(el.dataset.id),
  "open-sidebar": () => $("app").classList.add("side-open"),
  "close-sidebar": () => $("app").classList.remove("side-open"),
  "open-queue": () => { renderQueueDialog(); $("queue-dialog").showModal(); },
  "open-settings": () => { refreshHealth(); $("settings-dialog").showModal(); },
  "close-dialog": (el) => el.closest("dialog").close(),
  "cancel-job": async (el) => { await api(`/v1/jobs/${el.dataset.id}/cancel`, { method: "POST" }); toast("Canceled"); },
};
export function action(name, fn) { ACTIONS[name] = fn; }

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-action]");
  if (!el || !ACTIONS[el.dataset.action]) return;
  e.preventDefault();
  Promise.resolve(ACTIONS[el.dataset.action](el, e)).catch((err) => toast(err.message));
});
document.querySelectorAll("dialog").forEach((d) => d.addEventListener("click", (e) => { if (e.target === d) d.close(); }));
$("chat-title").addEventListener("click", startRename);
window.addEventListener("hashchange", () => { const id = location.hash.slice(1) || null; if (id !== S.chat) openChat(id, { push: false }); });

// ---- boot -------------------------------------------------------------------------------------

export async function boot() {
  try {
    S.options = await api("/v1/options");
  } catch (e) { toast(e.message, 8000); }
  await Promise.all([loadChats().catch(() => {}), loadActive().catch(() => {}), refreshHealth()]);
  connectEvents();
  fire("ready");
  await openChat(location.hash.slice(1) || null, { push: false });
  setInterval(refreshHealth, 5000);
  setInterval(renderQueueBadge, 5000);
}
