// Composer: prompt, stage toggles, preset, parts editor, the full settings menu, mesh upload,
// "continue from job" context, live ETA hint, and submit.

import { S, on, action, ensureChat, upsertJob } from "./app.js";
import { $, api, esc, fmtDur, fmtClock, toast, store, rgb, ICON } from "./util.js";

const STAGES = [
  { key: "shape", label: "Shape", help: "Cube3D: prompt → mesh" },
  { key: "parts", label: "Parts", help: "CubePart: mesh → named parts" },
  { key: "rig", label: "Rig", help: "joints + telescoping slides per limb" },
  { key: "preview", label: "Preview", help: "Blender render" },
];
const PALETTE = [[242, 109, 109], [242, 208, 109], [175, 242, 109], [109, 242, 142], [109, 242, 242], [109, 142, 242], [175, 109, 242], [242, 109, 208]];

// C = what the next job will be. Remembered across reloads (except parent/upload).
const C = {
  stages: { shape: true, parts: false, rig: false, preview: true },
  preset: "balanced",
  parts: [],
  shape: {}, partsOpts: {}, rig: {},
  parent: null,   // job to continue from
  upload: null,   // File
};

function defaults() {
  const d = S.options?.defaults || {};
  C.shape = { ...(d.shape || {}) };
  const { parts, ...po } = d.parts || {};
  C.partsOpts = po;
  C.rig = { ...(d.rig || {}) };
}

function save() {
  store("compose", { stages: C.stages, preset: C.preset, parts: C.parts, shape: C.shape, partsOpts: C.partsOpts, rig: C.rig });
}

function restore() {
  defaults();
  const s = store("compose");
  if (!s) return;
  Object.assign(C.stages, s.stages || {});
  C.preset = s.preset ?? "balanced";
  C.parts = s.parts || [];
  Object.assign(C.shape, s.shape || {});
  Object.assign(C.partsOpts, s.partsOpts || {});
  Object.assign(C.rig, s.rig || {});
}

// ---- availability rules --------------------------------------------------------------------

const parentHas = (k) => !!C.parent?.result?.[k] || (k === "mesh" && !!C.parent?.input_mesh);
const hasMeshSource = () => !!C.upload || parentHas("shape") || parentHas("mesh") || !!C.parent?.result?.parts;
function allowed(stage) {
  if (stage === "shape") return !C.upload && !C.parent;
  if (stage === "parts") return true;
  if (stage === "rig") return C.stages.parts || parentHas("parts");
  return true;
}
function activeStages() {
  return STAGES.map((s) => s.key).filter((k) => C.stages[k] && allowed(k));
}
function problem() {
  const st = activeStages();
  if (!st.length) return "Pick at least one stage";
  if (st.includes("shape") && !$("prompt").value.trim()) return "Describe the object";
  if (st.includes("parts") && !C.parts.length) return "Add at least one part name";
  if (st.includes("parts") && !st.includes("shape") && !hasMeshSource()) return "Parts needs a mesh: turn on Shape, upload one, or continue from a result";
  if (!st.some((s) => s !== "preview") && !C.parent) return "Preview needs something to render";
  return null;
}

// ---- request --------------------------------------------------------------------------------

export function buildRequest() {
  const stages = activeStages();
  return {
    prompt: $("prompt").value.trim(),
    stages,
    preset: null,
    shape: { ...C.shape },
    parts: { ...C.partsOpts, parts: C.parts },
    rig: { ...C.rig },
    parent_id: C.parent?.id || null,
  };
}

// ---- rendering ------------------------------------------------------------------------------

function renderStages() {
  $("stage-toggles").innerHTML = STAGES.map((s) => {
    const ok = allowed(s.key);
    return `<button type="button" data-action="toggle-stage" data-stage="${s.key}" aria-pressed="${C.stages[s.key] && ok}"
      ${ok ? "" : "disabled"} title="${esc(s.help)}${ok ? "" : " (not available here)"}"><i></i><span>${s.label}</span></button>`;
  }).join("");
  const n = C.parts.length;
  $("parts-label").textContent = n ? `${n} part${n > 1 ? "s" : ""}` : "Parts";
  $("btn-parts").classList.toggle("on", C.stages.parts && allowed("parts"));
}

function renderPreset() {
  const p = S.options?.presets || {};
  $("preset").innerHTML = Object.entries(p).map(([k, v]) => `<option value="${k}" title="${esc(v.help)}">${esc(v.label)}</option>`).join("")
    + `<option value="custom">Custom</option>`;
  $("preset").value = C.preset || "custom";
}

function applyPreset(name) {
  const p = S.options?.presets?.[name];
  if (!p) return;
  Object.assign(C.shape, p.shape || {});
  Object.assign(C.partsOpts, p.parts || {});
}

function presetMatches() {
  for (const [k, v] of Object.entries(S.options?.presets || {})) {
    const ok = Object.entries(v.shape || {}).every(([f, x]) => C.shape[f] === x)
      && Object.entries(v.parts || {}).every(([f, x]) => C.partsOpts[f] === x);
    if (ok) return k;
  }
  return "custom";
}

function renderContext() {
  const row = $("context-row");
  const bits = [];
  if (C.parent) {
    const what = C.parent.result?.parts ? "its parts" : "its mesh";
    bits.push(`<span class="ctx" title="New stages read ${what}">${ICON.continue}<span>Continue from “${esc(C.parent.title)}” (${what})</span>
      <button type="button" class="icon-btn" data-action="clear-parent" aria-label="Stop continuing">${ICON.x}</button></span>`);
  }
  if (C.upload) {
    bits.push(`<span class="ctx upload">${ICON.file}<span>${esc(C.upload.name)} · ${(C.upload.size / 1e6).toFixed(1)} MB</span>
      <button type="button" class="icon-btn" data-action="clear-upload" aria-label="Remove file">${ICON.x}</button></span>`);
  }
  row.innerHTML = bits.join("");
  row.hidden = !bits.length;
  $("prompt").placeholder = C.parent || C.upload ? "Optional note (the mesh comes from above)…" : "Describe a 3D object…";
}

function renderPartsMenu() {
  const t = S.options?.part_templates || {};
  const max = S.options?.max_parts || 8;
  $("parts-menu").innerHTML = `
    ${menuHead("Part names", "CubePart makes one mesh per name")}
    <div class="part-chips" id="part-chips">
      ${C.parts.map((p, i) => `<span class="part-chip"><i style="background:${rgb(PALETTE[i % 8])}"></i>${esc(p)}
        <button type="button" data-action="remove-part" data-i="${i}" aria-label="Remove ${esc(p)}">×</button></span>`).join("")}
      ${C.parts.length < max ? `<input id="part-input" placeholder="${C.parts.length ? "add another…" : "e.g. seat, backrest, legs"}" maxlength="60">` : ""}
    </div>
    <div class="parts-foot"><span>${C.parts.length}/${max} · Enter or comma to add</span>
      <button type="button" class="btn" data-action="clear-parts" style="padding:2px 8px">Clear</button></div>
    <h5 style="margin-top:10px">Templates</h5>
    <div class="templates">${Object.keys(t).map((k) => `<button type="button" data-action="use-template" data-name="${esc(k)}">${esc(k)}</button>`).join("")}</div>
    <p class="muted small" style="margin:8px 2px 0">Name only parts that exist in the mesh. Left/right is the object's own left (it faces you). The rig understands <code>left arm …</code>, <code>right leg …</code>, <code>head …</code>, <code>strap …</code>, <code>base …</code>.</p>`;
  const inp = $("part-input");
  if (inp) {
    inp.addEventListener("keydown", (e) => {
      if ((e.key === "Enter" || e.key === ",") && inp.value.trim()) { e.preventDefault(); addParts(inp.value); }
      else if (e.key === "Backspace" && !inp.value && C.parts.length) { C.parts.pop(); changed(); renderPartsMenu(); $("part-input")?.focus(); }
    });
    inp.addEventListener("paste", (e) => { const t = e.clipboardData.getData("text"); if (t.includes(",")) { e.preventDefault(); addParts(t); } });
  }
}

function addParts(text) {
  const max = S.options?.max_parts || 8;
  for (const p of text.split(",").map((x) => x.trim()).filter(Boolean)) {
    if (C.parts.length >= max) { toast(`CubePart supports at most ${max} parts`); break; }
    if (!C.parts.includes(p)) C.parts.push(p);
  }
  C.stages.parts = true;
  changed(); renderPartsMenu(); $("part-input")?.focus();
}

function fieldRow(f) {
  const g = f.group === "parts" ? C.partsOpts : C[f.group];
  const v = g[f.key];
  const id = `opt-${f.group}-${f.key}`;
  const label = `<span>${esc(f.label)}${f.help ? `<small>${esc(f.help)}</small>` : ""}</span>`;
  const num = (val, extra = "") => `<input type="number" id="${id}" data-group="${f.group}" data-key="${f.key}" data-kind="${f.type}"
      ${f.min != null ? `min="${f.min}"` : ""} ${f.max != null ? `max="${f.max}"` : ""} step="${f.step ?? (f.type === "integer" ? 1 : "any")}" value="${val ?? ""}" ${extra}>`;
  if (f.type === "boolean") {
    return `<label class="row switch">${label}<input type="checkbox" id="${id}" data-group="${f.group}" data-key="${f.key}" data-kind="boolean" ${v ? "checked" : ""}><i></i></label>`;
  }
  if (f.type === "choice" || (f.choices && f.type === "number")) {
    const opts = f.choices.map((c) => `<option value="${c}" ${String(c) === String(v) ? "selected" : ""}>${c}</option>`).join("");
    const kind = f.type === "choice" ? "choice" : "number";
    return `<label class="row">${label}<select id="${id}" data-group="${f.group}" data-key="${f.key}" data-kind="${kind}">${opts}</select></label>`;
  }
  if (f.type === "bbox") {
    const on = Array.isArray(v);
    const b = on ? v : [1, 1, 1];
    const presets = S.options?.bbox_presets || {};
    return `<label class="row switch"><span>${esc(f.label)}<small>aspect ratio W × H × D (Y up); off = model decides</small></span>
        <input type="checkbox" data-action-change="bbox-on" ${on ? "checked" : ""}><i></i></label>
      ${on ? `<div class="row bbox-row">${["W", "H", "D"].map((a, i) => `<label class="nullbox">${a}
        <input type="number" step="0.1" min="0.1" data-bbox="${i}" value="${b[i]}"></label>`).join("")}</div>
      <div class="bbox-presets">${Object.entries(presets).map(([k, p]) =>
        `<button type="button" data-action="bbox-preset" data-v="${p.join(",")}" class="${p.join() === b.join() ? "on" : ""}">${esc(k)}</button>`).join("")}</div>` : ""}`;
  }
  if (f.nullable) {
    const isNull = v === null;
    return `<label class="row">${label}<span class="pair">${num(isNull ? "" : v, isNull ? "disabled" : "")}
      <label class="nullbox"><input type="checkbox" data-null-for="${id}" ${isNull ? "checked" : ""}> ${esc(f.null_label || "none")}</label></span></label>`;
  }
  return `<label class="row">${label}${num(v)}</label>`;
}

function renderOptions() {
  const fields = (S.options?.fields || []).filter((f) => f.type !== "parts");
  const groups = [["shape", "Shape · Cube3D"], ["parts", "Parts · CubePart"], ["rig", "Rig"]];
  $("options-menu").innerHTML = menuHead("All settings", "saved in this browser") + groups.map(([g, title]) => {
    const on = C.stages[g] && allowed(g);
    return `<div class="opt-group${on ? "" : " disabled"}"><h5>${title}${on ? "" : `<span class="off">stage off</span>`}</h5>
      ${fields.filter((f) => f.group === g).map(fieldRow).join("")}</div>`;
  }).join("") + `<div class="opt-actions"><button type="button" data-action="reset-options">Reset to defaults</button>
      <a href="/docs" target="_blank" rel="noopener" class="small">API reference</a></div>`;
}

// ---- ETA hint -------------------------------------------------------------------------------

let etaTimer, etaSeq = 0;
function updateEta() {
  clearTimeout(etaTimer);
  etaTimer = setTimeout(async () => {
    const why = problem();
    const hint = $("eta-hint");
    $("btn-send").disabled = !!why && !(why === "Describe the object" && !$("prompt").value);
    $("btn-send").title = why || "Generate (Enter)";
    if (why) { hint.textContent = ""; return; }
    const seq = ++etaSeq;
    try {
      const body = buildRequest();
      if (C.upload) body.stages = body.stages.filter((s) => s !== "shape");
      if ((body.stages.includes("parts") && !body.stages.includes("shape")) && !body.parent_id) body.prompt = body.prompt || "x";
      const e = await api("/v1/estimate", { method: "POST", body: { ...body, prompt: body.prompt || "x", parent_id: null } });
      if (seq !== etaSeq) return;
      hint.innerHTML = e.wait_s > 1
        ? `≈ <b>${fmtDur(e.own_s)}</b> +${fmtDur(e.wait_s)} queue · ~${fmtClock(e.done_at)}`
        : `≈ <b>${fmtDur(e.own_s)}</b> · ~${fmtClock(e.done_at)}`;
      hint.title = e.plan.map((p) => `${p.sub}: ${fmtDur(p.seconds)}`).join("\n");
    } catch { hint.textContent = ""; }
  }, 250);
}

function changed() {
  C.preset = presetMatches();
  save();
  renderStages();
  renderContext();
  if (!$("options-menu").hidden) renderOptions();
  $("preset").value = C.preset;
  updateEta();
}

// ---- submit ---------------------------------------------------------------------------------

async function submit() {
  const why = problem();
  if (why) { toast(why); return; }
  const req = buildRequest();
  const btn = $("btn-send");
  btn.disabled = true;
  try {
    const title = req.prompt || C.upload?.name || (C.parent ? `${req.stages.join(" + ")} of ${C.parent.title}` : "Job");
    req.chat_id = await ensureChat(title);
    if (!req.prompt) delete req.prompt;
    let job;
    if (C.upload) {
      const form = new FormData();
      form.append("mesh", C.upload);
      req.stages = req.stages.filter((s) => s !== "shape");
      form.append("job", JSON.stringify(req));
      job = await api("/v1/jobs/upload", { method: "POST", form });
    } else {
      job = await api("/v1/jobs", { method: "POST", body: req });
    }
    upsertJob(job);
    $("prompt").value = ""; autosize();
    C.parent = null; C.upload = null; $("mesh-file").value = "";
    if (!C.stages.shape && !allowed("shape")) C.stages.shape = true;
    changed();
    const e = job.eta;
    toast(e?.queue_position ? `Queued #${e.queue_position} · done ~${fmtClock(e.done_at)}` : `Started · done ~${fmtClock(e?.done_at || Date.now() / 1000)}`);
  } catch (e) {
    toast(e.message, 6000);
  } finally {
    btn.disabled = false; updateEta();
  }
}

// ---- external API for cards -----------------------------------------------------------------

export function continueFrom(job, stages) {
  C.parent = job;
  C.upload = null;
  C.stages = { shape: false, parts: stages.includes("parts"), rig: stages.includes("rig"), preview: true };
  changed();
  if (stages.includes("parts")) openMenu("parts-menu");
  $("prompt").focus();
}

export function prefill(job) {
  const r = job.request || {};
  $("prompt").value = r.prompt || ""; autosize();
  C.stages = { shape: false, parts: false, rig: false, preview: false };
  for (const s of r.stages || []) C.stages[s] = true;
  Object.assign(C.shape, r.shape || {});
  const { parts, ...po } = r.parts || {};
  Object.assign(C.partsOpts, po);
  if (parts?.length) C.parts = [...parts];
  Object.assign(C.rig, r.rig || {});
  C.parent = r.parent_id ? (S.jobs.get(r.parent_id) || null) : null;
  changed();
  $("prompt").focus();
}

// ---- menus ----------------------------------------------------------------------------------

function openMenu(id) {
  for (const m of ["parts-menu", "options-menu"]) if (m !== id) $(m).hidden = true;
  const el = $(id);
  el.hidden = !el.hidden;
  if (!el.hidden) { id === "parts-menu" ? renderPartsMenu() : renderOptions(); if (id === "parts-menu") $("part-input")?.focus(); }
}
// Menus stay open until closed on purpose (their button, the × in the header, or Esc): clicking
// elsewhere, or on an item inside (which re-renders the menu), never closes them.
function closeMenus() { $("parts-menu").hidden = true; $("options-menu").hidden = true; }
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && (!$("parts-menu").hidden || !$("options-menu").hidden)) { e.preventDefault(); closeMenus(); }
});
action("close-menus", closeMenus);
const menuHead = (title, sub) => `<div class="menu-head"><h5>${title}${sub ? ` <small>${sub}</small>` : ""}</h5>
  <button type="button" class="icon-btn small" data-action="close-menus" title="Close (Esc)" aria-label="Close">${ICON.x}</button></div>`;

action("toggle-stage", (el) => { const k = el.dataset.stage; C.stages[k] = !C.stages[k]; if (k === "parts" && C.stages.parts && !C.parts.length) openMenu("parts-menu"); changed(); });
action("toggle-parts", () => openMenu("parts-menu"));
action("toggle-options", () => openMenu("options-menu"));
action("remove-part", (el) => { C.parts.splice(+el.dataset.i, 1); changed(); renderPartsMenu(); });
action("clear-parts", () => { C.parts = []; changed(); renderPartsMenu(); });
action("use-template", (el) => { C.parts = [...S.options.part_templates[el.dataset.name]]; C.stages.parts = true; changed(); renderPartsMenu(); });
action("reset-options", () => { defaults(); C.preset = "balanced"; applyPreset("balanced"); changed(); renderOptions(); });
action("bbox-preset", (el) => { C.shape.bbox = el.dataset.v.split(",").map(Number); changed(); renderOptions(); });
action("clear-parent", () => { C.parent = null; C.stages.shape = true; changed(); });
action("clear-upload", () => { C.upload = null; $("mesh-file").value = ""; C.stages.shape = true; changed(); });
action("attach", () => $("mesh-file").click());
action("suggest", (el) => {
  const s = SUGGESTIONS[+el.dataset.i];
  $("prompt").value = s.prompt; autosize();
  C.stages = { shape: true, parts: !!s.parts, rig: !!s.rig, preview: true };
  if (s.parts) C.parts = [...s.parts];
  if (s.bbox) C.shape.bbox = s.bbox;
  changed(); $("prompt").focus();
});

$("options-menu").addEventListener("change", (e) => {
  const t = e.target;
  if (t.dataset.nullFor) {
    const inp = $(t.dataset.nullFor);
    const g = inp.dataset.group === "parts" ? C.partsOpts : C[inp.dataset.group];
    g[inp.dataset.key] = t.checked ? null : (Number(inp.value) || Number(inp.defaultValue) || (inp.dataset.key === "top_p" ? 0.9 : 1.8));
    changed(); renderOptions(); return;
  }
  if (t.dataset.actionChange === "bbox-on") { C.shape.bbox = t.checked ? [1, 1, 1] : null; changed(); renderOptions(); return; }
  if (t.dataset.bbox != null) {
    const b = [...(C.shape.bbox || [1, 1, 1])]; b[+t.dataset.bbox] = Math.max(0.1, Number(t.value) || 1); C.shape.bbox = b; changed(); return;
  }
  const { group, key, kind } = t.dataset;
  if (!group) return;
  const g = group === "parts" ? C.partsOpts : C[group];
  if (kind === "boolean") g[key] = t.checked;
  else if (kind === "choice") g[key] = t.value;
  else if (t.value !== "") {
    let v = Number(t.value);
    if (t.min !== "" && v < Number(t.min)) v = Number(t.min);
    if (t.max !== "" && v > Number(t.max)) v = Number(t.max);
    g[key] = kind === "integer" ? Math.round(v) : v;
    t.value = g[key];
  }
  changed();
});

$("preset").addEventListener("change", (e) => { C.preset = e.target.value; applyPreset(C.preset); changed(); });
$("mesh-file").addEventListener("change", (e) => { if (e.target.files[0]) takeFile(e.target.files[0]); });

function takeFile(f) {
  if (!/\.(glb|gltf|obj|ply|stl|off)$/i.test(f.name)) { toast("Use a .glb, .gltf, .obj, .ply, .stl or .off mesh"); return; }
  C.upload = f; C.parent = null;
  C.stages.shape = false;
  if (!C.stages.parts && !C.stages.rig) C.stages.parts = true;
  changed();
  if (!C.parts.length) openMenu("parts-menu");
}
const box = $("composer");
box.addEventListener("dragover", (e) => { if (e.dataTransfer?.types?.includes("Files")) { e.preventDefault(); $("drop-box").classList.add("over"); } });
box.addEventListener("dragleave", () => $("drop-box").classList.remove("over"));
box.addEventListener("drop", (e) => { e.preventDefault(); $("drop-box").classList.remove("over"); if (e.dataTransfer.files[0]) takeFile(e.dataTransfer.files[0]); });

const prompt = $("prompt");
function autosize() { prompt.style.height = "auto"; prompt.style.height = Math.min(prompt.scrollHeight, innerHeight * 0.4) + "px"; }
prompt.addEventListener("input", () => { autosize(); updateEta(); });
prompt.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); } });
$("composer").addEventListener("submit", (e) => { e.preventDefault(); submit(); });

// ---- empty-state suggestions ----------------------------------------------------------------

const SUGGESTIONS = [
  { title: "Knight, rigged for games", prompt: "stylized low-poly knight in armor standing in a T-pose",
    parts: ["head", "torso", "left arm", "right arm", "left leg", "right leg"], rig: true, bbox: [1.6, 1.8, 0.6] },
  { title: "Hover bike, split", prompt: "futuristic hover motorcycle with twin jet thrusters and a long padded seat",
    parts: ["main body", "front thruster", "rear thruster", "seat", "handlebars"], bbox: [0.8, 0.9, 2.0] },
  { title: "Loot crate, split", prompt: "sci-fi loot crate with a hinged lid, glowing panels and side handles", parts: ["lid", "box body", "handles", "glowing panels"] },
  { title: "Brass lantern", prompt: "ornate brass hanging lantern with glass panels and a ring on top", bbox: [1, 1.8, 1] },
];

function renderSuggestions() {
  $("suggestions").innerHTML = SUGGESTIONS.map((s, i) => `<button class="suggestion" data-action="suggest" data-i="${i}">
    <b>${esc(s.title)}</b>${esc(s.prompt.slice(0, 90))}${s.prompt.length > 90 ? "…" : ""}
    <span class="meta-chips" style="justify-content:flex-start;margin-top:6px"><span class="mchip">shape</span>${s.parts ? `<span class="mchip accent">${s.parts.length} parts</span>` : ""}${s.rig ? `<span class="mchip cyan">rig</span>` : ""}</span></button>`).join("");
}

on("ready", () => { restore(); renderPreset(); renderSuggestions(); changed(); });
on("chatOpened", () => { if (C.parent && C.parent.chat_id !== S.chat) { C.parent = null; C.stages.shape = true; changed(); } updateEta(); });
on("jobChanged", () => updateEta());
