// Settings dialog: GPU worker load/unload, notifications, viewer preference, API example, history.

import { S, on, action, openChat, loadChats, refreshHealth } from "./app.js";
import { $, api, toast, store } from "./util.js";

function status(msg, cls = "") { const el = $("worker-status"); el.textContent = msg; el.className = `status small ${cls}`; }

action("load-worker", async (el) => {
  el.disabled = true; status("Starting the worker and loading Cube3D + CubePart (~1 min the first time)…");
  try {
    const w = await api("/v1/load?models=shape,parts", { method: "POST" });
    status(`Loaded: ${w.loaded.join(", ")}`, "ok");
  } catch (e) { status(e.message, "err"); } finally { el.disabled = false; refreshHealth(); }
});

action("unload-worker", async (el) => {
  const busy = S.health?.queue?.running;
  if (busy && !el.dataset.armed) {
    el.dataset.armed = "1"; status("A job is running. Click again to cancel it and free the GPU.", "err");
    setTimeout(() => delete el.dataset.armed, 4000);
    return;
  }
  el.disabled = true;
  try {
    const r = await api(`/v1/unload${busy ? "?force=true" : ""}`, { method: "POST" });
    status(r.stopped ? "Worker stopped; GPU memory released." : "The worker was not running.", "ok");
  } catch (e) { status(e.message, "err"); } finally { el.disabled = false; refreshHealth(); }
});

action("clear-history", async (el) => {
  if (!el.dataset.armed) {
    el.dataset.armed = "1"; el.textContent = "Click again: this deletes every chat, job and file";
    setTimeout(() => { delete el.dataset.armed; el.textContent = "Delete all chats and files"; }, 4000);
    return;
  }
  const { chats } = await api("/v1/chats");
  for (const c of chats) await api(`/v1/chats/${c.id}`, { method: "DELETE" });
  const { jobs } = await api("/v1/jobs?limit=1000");   // jobs made through the API without a chat
  for (const j of jobs) await api(`/v1/jobs/${j.id}`, { method: "DELETE" });
  $("history-status").textContent = `Deleted ${chats.length} chat(s) and ${jobs.length} loose job(s).`;
  delete el.dataset.armed; el.textContent = "Delete all chats and files";
  await loadChats(); await openChat(null);
});

$("opt-notify").addEventListener("change", async (e) => {
  if (e.target.checked && "Notification" in window && Notification.permission !== "granted") {
    const p = await Notification.requestPermission().catch(() => "denied");
    if (p !== "granted") { e.target.checked = false; toast("The browser blocked notifications for this page"); }
  }
  store("notify", e.target.checked);
});
$("opt-autoview").addEventListener("change", (e) => store("autoview", e.target.checked));

on("ready", () => {
  $("opt-notify").checked = !!store("notify") && "Notification" in window && Notification.permission === "granted";
  $("opt-autoview").checked = store("autoview") !== false;
  const base = location.origin;
  $("api-example").textContent =
`curl ${base}/v1/jobs -H 'content-type: application/json' -d '{
  "prompt": "sci-fi crate with a hinged lid", "chat_id": "new",
  "stages": ["shape", "parts", "preview"],
  "parts": {"parts": ["lid", "box", "handles"]}, "preset": "fast"}'

curl ${base}/v1/jobs/<id>            # status, stage progress, eta.done_at
curl -N ${base}/v1/jobs/<id>/events  # live progress (SSE)
curl -OJ ${base}/v1/jobs/<id>/download`;
});
