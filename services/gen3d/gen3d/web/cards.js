// The thread: one turn per job (what was asked + a live job card), countdowns, results, actions.

import { S, on, action, upsertJob } from "./app.js";
import { continueFrom, prefill } from "./composer.js";
import { $, api, esc, fmtDur, fmtClock, fmtWhen, fmtNum, toast, store, rgb, ICON } from "./util.js";

const STAGE_LABEL = { shape: "Shape", parts: "Parts", rig: "Rig", preview: "Preview" };
const SUB_LABEL = {
  "worker.start": "Starting the GPU worker",
  "load.shape": "Loading Cube3D",
  "load.shape_fast": "Capturing HIP graphs",
  "shape.gpt": "Generating shape tokens",
  "shape.decode": "Decoding the mesh (marching cubes)",
  "shape.post": "Cleaning up the mesh",
  "load.parts": "Loading CubePart (first run compiles)",
  "parts.encode": "Encoding the input mesh",
  "parts.diffusion": "Separating parts (diffusion)",
  "parts.decode": "Decoding the part meshes",
  rig: "Adding joints and slides",
  preview: "Rendering the preview",
};

const now = () => Date.now() / 1000;
const url = (job, f) => `/v1/jobs/${job.id}/files/${f.split("/").map(encodeURIComponent).join("/")}`;

// ---- turn = user side + job card ------------------------------------------------------------

function userSide(job) {
  const r = job.request || {};
  const parent = r.parent_id ? S.jobs.get(r.parent_id) : null;
  let text = r.prompt?.trim();
  if (!text) {
    const bits = [];
    if (r.stages?.includes("parts")) bits.push(`Split into ${r.parts?.parts?.length || 0} parts`);
    if (r.stages?.includes("rig")) bits.push("rig for games");
    text = (bits.join(", ") || r.stages?.join(" + ") || "Job") + (job.input_mesh ? ` · ${job.title}` : "");
  }
  const chips = [];
  for (const s of r.stages || []) chips.push(`<span class="mchip${s === "parts" ? " accent" : s === "rig" ? " cyan" : ""}">${s}</span>`);
  if (r.stages?.includes("shape")) {
    chips.push(`<span class="mchip">res ${r.shape?.resolution_base}</span>`);
    chips.push(`<span class="mchip">${r.shape?.top_p == null ? "deterministic" : `seed ${r.shape?.seed}`}</span>`);
    if (r.shape?.bbox) chips.push(`<span class="mchip">bbox ${r.shape.bbox.join("×")}</span>`);
  }
  if (r.stages?.includes("parts")) chips.push(`<span class="mchip">${r.parts?.steps} steps</span>`);
  if (parent) chips.push(`<span class="mchip cyan">from “${esc(parent.title.slice(0, 30))}”</span>`);
  if (job.input_mesh) chips.push(`<span class="mchip accent">uploaded ${esc(job.input_mesh)}</span>`);
  const partsLine = r.stages?.includes("parts") && r.parts?.parts?.length
    ? `<div class="meta-chips">${r.parts.parts.map((p) => `<span class="mchip">${esc(p)}</span>`).join("")}</div>` : "";
  return `<div class="msg-user"><div class="bubble">${esc(text)}</div><div class="meta-chips">${chips.join("")}</div>${partsLine}</div>`;
}

function stageRows(job) {
  const by = job.eta?.by_stage || {};
  return `<div class="stages">${Object.entries(job.stages).map(([k, v]) => {
    const st = v.state || "pending";
    let detail = "", bar = "", time = "";
    if (st === "running") {
      const sub = v.sub ? (SUB_LABEL[v.sub] || v.sub) : "Starting";
      const pct = v.total ? Math.min(100, (100 * (v.step || 0)) / v.total) : null;
      detail = `<span class="sub">${esc(sub)}${v.total ? ` · ${v.step || 0}/${v.total}` : ""}</span>`;
      bar = `<div class="bar${pct == null ? " indet" : ""}"><i style="width:${pct ?? 30}%"></i></div>`;
      time = `<span data-elapsed="${v.started || now()}">${fmtDur(now() - (v.started || now()))}</span>${by[k] != null ? ` / ~${fmtDur((now() - (v.started || now())) + by[k])}` : ""}`;
    } else if (st === "done") {
      detail = `<span class="sub">${esc(stageSummary(job, k))}</span>`;
      bar = `<div class="bar"><i style="width:100%"></i></div>`;
      time = fmtDur(v.seconds);
    } else if (st === "pending") {
      detail = `<span class="sub">waiting</span>`;
      bar = `<div class="bar"><i style="width:0"></i></div>`;
      time = by[k] != null ? `~${fmtDur(by[k])}` : "";
    } else {
      detail = `<span class="sub">${st}${v.error ? ": " + esc(v.error) : ""}</span>`;
    }
    const ico = st === "done" ? ICON.check : "";
    return `<div class="stage ${st}"><span class="ico">${ico}</span><span class="name">${STAGE_LABEL[k] || k}</span>
      <span class="detail">${detail}${bar}</span><span class="time">${time}</span></div>`;
  }).join("")}</div>`;
}

function stageSummary(job, k) {
  const r = job.result?.[k] || {};
  if (k === "shape") return `${fmtNum(r.faces)} faces${r.peak_gpu_gb ? ` · ${r.peak_gpu_gb} GB peak` : ""}`;
  if (k === "parts") {
    const n = (r.parts || []).filter((p) => p.file).length;
    return `${n} part mesh${n === 1 ? "" : "es"}${r.faces != null ? ` · ${fmtNum(r.faces)} faces` : ""}${r.empty?.length ? ` · ${r.empty.length} empty` : ""}${r.peak_gpu_gb ? ` · ${r.peak_gpu_gb} GB peak` : ""}`;
  }
  if (k === "rig") return `${(r.joints || []).length} joints${r.faces != null ? ` · ${fmtNum(r.faces)} faces` : ""}${r.missing?.length ? ` · no ${r.missing.join(", ")}` : ""}`;
  if (k === "preview") return r.skipped || "4-view render";
  return "";
}

function etaLine(job) {
  const e = job.eta;
  if (!e) return "";
  const left = e.done_at - now();
  if (job.status === "queued") {
    return `<div class="eta-line"><span>Queued <b>${e.queue_position ? "#" + e.queue_position : "next"}</b> · starts in <span data-countdown="${now() + e.starts_in_s}">${fmtDur(e.starts_in_s)}</span></span>
      <span>done in <span class="big" data-countdown="${e.done_at}">${fmtDur(left)}</span></span><span class="at">~${fmtClock(e.done_at)}</span></div>`;
  }
  const started = job.started || now();
  const pct = Math.max(2, Math.min(99, (100 * (now() - started)) / Math.max(1, now() - started + left)));
  return `<div class="eta-line"><span class="big" data-countdown="${e.done_at}">${fmtDur(left)}</span><span>left</span>
      <span class="at">done ~${fmtClock(e.done_at)}</span><span>· running ${fmtDur(now() - started)}</span></div>
    <div class="overall"><i style="width:${pct}%" data-overall="${started}|${e.done_at}"></i></div>`;
}

function chainHas(job, key) {
  let j = job;
  for (let i = 0; j && i < 10; i++) {
    if (j.result?.[key] || (key === "shape" && j.input_mesh)) return true;
    j = j.parent_id ? S.jobs.get(j.parent_id) : null;
  }
  return false;
}

function resultBlock(job) {
  const files = new Set(job.files || []);
  const r = job.result || {};
  const show = files.has("rigged.glb") ? "rigged.glb" : files.has("parts.glb") ? "parts.glb" : files.has("mesh.glb") ? "mesh.glb" : null;
  const parts = (r.parts?.parts || []).filter((p) => p.file);
  const media = files.has("preview.png")
    ? `<img class="preview" src="${url(job, "preview.png")}?v=${job.finished || 0}" alt="Preview of ${esc(job.title)}" data-action="zoom" data-src="${url(job, "preview.png")}" data-title="${esc(job.title)}" loading="lazy">`
    : `<div class="viewer" style="height:180px"><div class="loading">no preview${show ? " · open the 3D viewer" : ""}</div></div>`;
  const openBtn = show ? `<button class="vbtn open-3d" data-action="open-3d" data-id="${job.id}">${ICON.box3d} Open 3D viewer</button>` : "";
  const links = [
    ["mesh.glb", "mesh"], ["parts.glb", "parts scene"], ["rigged.glb", "rigged"], ["rig.json", "rig.json"], ["input.glb", "input"],
  ].filter(([f]) => files.has(f)).map(([f, l]) => `<a href="${url(job, f)}" download>${ICON.download}${l}</a>`).join("");
  const stats = Object.entries(job.stages).filter(([, v]) => v.seconds != null)
    .map(([k, v]) => `<span>${STAGE_LABEL[k]} <b>${fmtDur(v.seconds)}</b></span>`).join("");
  const total = job.finished && job.started ? `<span>total <b>${fmtDur(job.finished - job.started)}</b></span>` : "";
  return `<div class="result">
      <div class="result-media" data-media="${job.id}">${media}${openBtn}</div>
      ${parts.length ? `<div class="parts-list" data-parts="${job.id}">${parts.map((p) => `<span class="part-chip" data-part="${p.index}" title="Click to hide / show in the viewer"><i style="background:${rgb(p.color)}"></i>${esc(p.name)}<small>${fmtNum(p.faces)}</small></span>`).join("")}</div>` : ""}
      ${r.parts?.empty?.length ? `<div class="warn-line">No geometry for: ${r.parts.empty.map(esc).join(", ")}. Try another seed or rename the part.</div>` : ""}
      <div class="stats">${stats}${total}</div>
      <div class="files-row">${links}<a href="/v1/jobs/${job.id}/download">${ICON.download}all files (.zip)</a></div>
    </div>`;
}

function actions(job) {
  const b = [];
  const act = (a, icon, label, cls = "") => `<button class="act ${cls}" data-action="${a}" data-id="${job.id}">${icon}${label}</button>`;
  if (["queued", "running"].includes(job.status)) b.push(act("cancel", ICON.stop, "Cancel"));
  if (job.status === "done") {
    const hasParts = chainHas(job, "parts"), hasRig = !!job.result?.rig;
    if (!hasParts && chainHas(job, "shape")) b.push(act("continue-parts", ICON.split, "Split into parts", "primary"));
    if (hasParts && !hasRig) b.push(act("continue-rig", ICON.rig, "Rig it", "primary"));
    if (hasParts) b.push(act("continue-reparts", ICON.split, "Re-split"));
  }
  if (["done", "failed", "canceled"].includes(job.status)) {
    b.push(act("retry", ICON.retry, "New seed"));
    b.push(act("edit", ICON.copy, "Edit & resend"));
  }
  b.push(`<button class="icon-btn" data-action="delete-job" data-id="${job.id}" title="Delete job and files" aria-label="Delete job">${ICON.trash}</button>`);
  return `<div class="job-actions">${b.join("")}</div>`;
}

function card(job) {
  const pill = `<span class="pill ${job.status}">${job.status}</span>`;
  let body = "";
  if (job.status === "queued" || job.status === "running") body = etaLine(job) + stageRows(job);
  else if (job.status === "done") body = resultBlock(job) + `<details class="help"><summary>Stages</summary>${stageRows(job)}</details>`;
  else if (job.status === "failed") body = `<div class="card error-card"><span>${esc(job.error || "failed")}</span></div>` + stageRows(job);
  else body = `<p class="muted small" style="margin:0">Canceled.</p>` + stageRows(job);
  return `<div class="job"><div class="avatar">${ICON.cube}</div><div class="job-body">
      <div class="job-head"><b>${esc(job.title || "Job")}</b>${pill}<span class="muted">${job.id} · ${fmtWhen(job.created)}</span></div>
      ${body}${actions(job)}</div></div>`;
}

// ---- rendering ------------------------------------------------------------------------------

function sorted() { return [...S.jobs.values()].sort((a, b) => a.created - b.created); }

function renderAll() {
  const jobs = sorted();
  $("empty").hidden = jobs.length > 0;
  $("turns").innerHTML = jobs.map((j) => `<div class="turn" data-job="${j.id}">${userSide(j)}<div class="job-slot">${card(j)}</div></div>`).join("");
  scrollBottom();
  autoView();
}

function renderOne(job) {
  const el = document.querySelector(`.turn[data-job="${job.id}"]`);
  if (!el) { renderAll(); return; }
  const slot = el.querySelector(".job-slot");
  const media = slot.querySelector(".result-media");
  if (media?.querySelector("canvas") && job.status === "done") return;  // keep a live viewer as is
  slot.innerHTML = card(job);
}

function scrollBottom() { const t = $("thread"); requestAnimationFrame(() => { t.scrollTop = t.scrollHeight; }); }

// countdowns tick locally between server updates
setInterval(() => {
  const t = now();
  document.querySelectorAll("[data-countdown]").forEach((el) => { el.textContent = fmtDur(Number(el.dataset.countdown) - t); });
  document.querySelectorAll("[data-elapsed]").forEach((el) => { el.textContent = fmtDur(t - Number(el.dataset.elapsed)); });
  document.querySelectorAll("[data-overall]").forEach((el) => {
    const [s, d] = el.dataset.overall.split("|").map(Number);
    el.style.width = `${Math.max(2, Math.min(99, (100 * (t - s)) / Math.max(1, d - s)))}%`;
  });
}, 1000);

// ---- 3D viewer (viewer.js, loaded on first use) ---------------------------------------------

let viewerMod = null;
async function openViewer(job) {
  const media = document.querySelector(`[data-media="${job.id}"]`);
  if (!media) return;
  try {
    viewerMod ||= await import("./viewer.js");
  } catch (e) { toast("3D viewer failed to load: " + e.message); return; }
  viewerMod.mount(media, job);
}

function autoView() {
  if (store("autoview") === false) return;
  const last = sorted().filter((j) => j.status === "done" && (j.files || []).some((f) => f.endsWith(".glb"))).pop();
  if (last && !document.querySelector(`[data-media="${last.id}"] canvas`)) openViewer(last);
}

// ---- actions --------------------------------------------------------------------------------

const job = (el) => S.jobs.get(el.dataset.id);
action("cancel", async (el) => { upsertJob(await api(`/v1/jobs/${el.dataset.id}/cancel`, { method: "POST" })); });
action("retry", async (el) => {
  const j = await api(`/v1/jobs/${el.dataset.id}/retry`, { method: "POST", body: { new_seed: true } });
  upsertJob(j); toast(`Queued with seed ${j.request.shape?.seed} · done ~${fmtClock(j.eta?.done_at || now())}`);
});
action("edit", (el) => prefill(job(el)));
action("continue-parts", (el) => continueFrom(job(el), ["parts", "preview"]));
action("continue-reparts", (el) => continueFrom(job(el), ["parts", "rig", "preview"]));
action("continue-rig", (el) => continueFrom(job(el), ["rig", "preview"]));
action("delete-job", async (el) => {
  if (!el.dataset.armed) {
    el.dataset.armed = "1"; el.style.color = "var(--red)"; toast("Click again to delete this job and its files");
    setTimeout(() => { delete el.dataset.armed; el.style.color = ""; }, 3000);
    return;
  }
  await api(`/v1/jobs/${el.dataset.id}`, { method: "DELETE" });
  S.jobs.delete(el.dataset.id);
  viewerMod?.unmountFor(el.dataset.id);
  renderAll();
});
action("open-3d", (el) => openViewer(job(el)));
action("zoom", (el) => { $("lightbox-img").src = el.dataset.src; $("lightbox-title").textContent = el.dataset.title; $("lightbox").showModal(); });

document.addEventListener("click", (e) => {
  const chip = e.target.closest(".parts-list .part-chip");
  if (!chip) return;
  const id = chip.closest("[data-parts]").dataset.parts;
  chip.classList.toggle("off");
  viewerMod?.togglePart(id, Number(chip.dataset.part), !chip.classList.contains("off"));
});

on("chatOpened", () => { viewerMod?.unmountAll(); renderAll(); });
on("jobChanged", (j, prev) => {
  if (j.deleted) { document.querySelector(`.turn[data-job="${j.id}"]`)?.remove(); return; }
  if (j.chat_id !== S.chat) return;
  if (!prev || !document.querySelector(`.turn[data-job="${j.id}"]`)) { renderAll(); return; }
  renderOne(j);
  if (prev.status !== "done" && j.status === "done") { autoView(); scrollBottom(); }
});
