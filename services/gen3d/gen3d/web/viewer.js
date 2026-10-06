// Inline 3D viewer (three.js, vendored). One live viewer at a time (WebGL contexts are limited);
// mounting another restores the previous card's preview image.
//
// Rigged models follow the rig.json contract written by workers/rig.py: every limb has a
// `<limb>_joint` node (rotate: swing = local Z, lift = local X) and a `<limb>_slide` child
// (translate along local +Y); `recline_joint` and `head_joint` rotate about local X.

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { esc, fmtDur, ICON } from "./util.js";

const LIMBS = [
  { key: "arm_L", tag: "M1", name: "Left arm", swing: "Raise" },
  { key: "arm_R", tag: "M2", name: "Right arm", swing: "Raise" },
  { key: "leg_L", tag: "M3", name: "Left leg", swing: "Spread" },
  { key: "leg_R", tag: "M4", name: "Right leg", swing: "Spread" },
];
const X = new THREE.Vector3(1, 0, 0), Z = new THREE.Vector3(0, 0, 1);
const loader = new GLTFLoader();

let V = null; // the live viewer

const fileUrl = (job, f) => `/v1/jobs/${job.id}/files/${f}?v=${job.finished || 0}`;

export function unmountAll() {
  if (!V) return;
  cancelAnimationFrame(V.raf);
  V.ro.disconnect();
  V.controls.dispose();
  V.scene.traverse((o) => { o.geometry?.dispose(); (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m?.dispose()); });
  V.renderer.dispose();
  V.renderer.forceContextLoss();
  if (V.el.isConnected) V.el.innerHTML = V.restore;
  V = null;
}

export function unmountFor(id) { if (V?.job.id === id) unmountAll(); }

export function togglePart(id, index, visible) {
  if (!V || V.job.id !== id) return;
  V.hiddenParts[visible ? "delete" : "add"](index);
  applyPartVisibility();
}

export async function mount(el, job) {
  if (V?.el === el) return;
  unmountAll();
  const files = new Set(job.files || []);
  const tabs = [["rigged.glb", "Rigged"], ["parts.glb", "Parts"], ["mesh.glb", "Mesh"], ["input.glb", "Input"]].filter(([f]) => files.has(f));
  if (!tabs.length) return;
  const restore = el.innerHTML;
  el.innerHTML = `<div class="viewer"><canvas tabindex="0" aria-label="3D view: drag to orbit, scroll to zoom, right-drag to pan"></canvas>
      <div class="viewer-bar">
        <div class="tabs" role="tablist">${tabs.map(([f, l], i) => `<button class="tab${i === 0 ? " active" : ""}" data-file="${f}">${l}</button>`).join("")}</div>
        <span class="grow"></span>
        <button class="vbtn" data-v="wire" title="Wireframe">wire</button>
        <button class="vbtn" data-v="reset" title="Reset view">reset</button>
        ${files.has("preview.png") ? `<button class="vbtn" data-v="close" title="Back to the preview image">${ICON.x}</button>` : ""}
      </div>
      <div class="loading">loading…</div></div><div class="motors" hidden></div>`;
  const canvas = el.querySelector("canvas");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0e1219);
  const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 200);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xdfe8ee, 0x1a1f23, 1.3));
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(3, 5, 4); key.castShadow = true; key.shadow.mapSize.set(2048, 2048);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xffb224, 0.7); rim.position.set(-3, 2, -3); scene.add(rim);
  const floor = new THREE.Mesh(new THREE.CircleGeometry(1, 64), new THREE.MeshStandardMaterial({ color: 0x151a22, roughness: 0.95 }));
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
  const grid = new THREE.PolarGridHelper(1, 12, 6, 64, 0x2a3547, 0x1d2430); scene.add(grid);

  V = { el, job, restore, renderer, scene, camera, controls, floor, grid, root: null, file: null, wire: false,
        hiddenParts: new Set(), rig: null, joints: {}, state: {}, anim: false, raf: 0,
        ro: new ResizeObserver(() => resize()) };
  V.ro.observe(canvas);
  resize();

  el.querySelector(".viewer-bar").addEventListener("click", (e) => {
    const t = e.target.closest("button");
    if (!t) return;
    if (t.dataset.file) {
      el.querySelectorAll(".viewer-bar .tab").forEach((b) => b.classList.toggle("active", b === t));
      load(t.dataset.file);
    } else if (t.dataset.v === "wire") {
      V.wire = !V.wire; t.classList.toggle("on", V.wire);
      V.root?.traverse((o) => { if (o.isMesh) o.material.wireframe = V.wire; });
    } else if (t.dataset.v === "reset") frame();
    else if (t.dataset.v === "close") unmountAll();
  });

  const tick = (t) => {
    if (!V) return;
    if (V.anim) animate(t / 1000);
    controls.update();
    renderer.render(scene, camera);
    V.raf = requestAnimationFrame(tick);
  };
  V.raf = requestAnimationFrame(tick);
  await load(tabs[0][0]);
}

function resize() {
  if (!V) return;
  const r = V.renderer.domElement.getBoundingClientRect();
  V.renderer.setSize(r.width, r.height, false);
  V.camera.aspect = r.width / Math.max(r.height, 1);
  V.camera.updateProjectionMatrix();
}

async function load(file) {
  const v = V;
  const busy = v.el.querySelector(".loading");
  busy.hidden = false; busy.textContent = "loading…";
  let gltf;
  try { gltf = await loader.loadAsync(fileUrl(v.job, file)); }
  catch (e) { busy.textContent = "could not load " + file; return; }
  if (V !== v) return;
  if (v.root) v.scene.remove(v.root);
  v.root = gltf.scene;
  v.file = file;
  v.root.traverse((o) => {
    if (!o.isMesh) return;
    o.castShadow = o.receiveShadow = true;
    const hasColor = !!o.geometry.attributes.color;
    const base = o.material?.color && !hasColor ? o.material.color.clone() : new THREE.Color(hasColor ? 0xffffff : 0xb8b2a8);
    o.material = new THREE.MeshStandardMaterial({ color: base, vertexColors: hasColor, roughness: 0.55, metalness: 0.12, wireframe: v.wire });
    if (!o.geometry.attributes.normal) o.geometry.computeVertexNormals();
  });
  // stand it on the floor, centered
  const box = new THREE.Box3().setFromObject(v.root);
  const c = box.getCenter(new THREE.Vector3());
  v.root.position.x -= c.x; v.root.position.z -= c.z; v.root.position.y -= box.min.y;
  v.scene.add(v.root);
  busy.hidden = true;
  frame();
  applyPartVisibility();
  await setupRig(file);
}

function frame() {
  const v = V;
  if (!v?.root) return;
  const size = new THREE.Box3().setFromObject(v.root).getSize(new THREE.Vector3());
  const h = Math.max(size.x, size.y, size.z) || 1;
  v.floor.scale.setScalar(h * 0.75); v.grid.scale.setScalar(h * 0.7);
  v.controls.target.set(0, size.y * 0.45, 0);
  v.camera.position.set(h * 1.1, size.y * 0.85, h * 2.4);
  v.camera.near = h / 100; v.camera.far = h * 50; v.camera.updateProjectionMatrix();
  v.controls.update();
}

function applyPartVisibility() {
  if (!V?.root || V.file !== "parts.glb") return;
  V.root.traverse((o) => {
    const m = /^part_(\d+)_/.exec(o.name || "");
    if (m && (o.isMesh || o.children.length)) o.visible = !V.hiddenParts.has(Number(m[1]));
  });
}

// ---- rig ------------------------------------------------------------------------------------

async function setupRig(file) {
  const v = V;
  const panel = v.el.querySelector(".motors");
  v.joints = {}; v.anim = false;
  if (file !== "rigged.glb" || !(v.job.files || []).includes("rig.json")) { panel.hidden = true; return; }
  try { v.rig = await (await fetch(fileUrl(v.job, "rig.json"))).json(); } catch { panel.hidden = true; return; }
  if (V !== v) return;
  const units = v.rig.units === "m";
  for (const l of LIMBS) {
    const j = v.rig.joints?.[l.key];
    const joint = j && v.root.getObjectByName(j.joint_node), slide = j && v.root.getObjectByName(j.slide_node);
    if (!joint || !slide) continue;
    v.joints[l.key] = { joint, slide, q0: joint.quaternion.clone(), p0: slide.position.clone(),
      side: Math.sign(j.extend_dir_world[0]) || 1, max: j.limits?.extend?.[1] ?? 0.2, units };
  }
  const grab = (n) => { const o = n && v.root.getObjectByName(n); return o ? { o, q0: o.quaternion.clone() } : null; };
  v.head = grab(v.rig.joints?.head?.node);
  v.recline = grab(v.rig.joints?.recline?.node);
  reset();
  const limbs = LIMBS.filter((l) => v.joints[l.key]);
  if (!limbs.length && !v.head && !v.recline) { panel.hidden = true; return; }
  panel.hidden = false;
  const ch = (id, label, min, max, step) => `<div class="ch"><label for="${id}">${label}</label>
    <input type="range" id="${id}" min="${min}" max="${max}" step="${step}" value="0"><output data-out="${id}"></output></div>`;
  panel.innerHTML = `<div class="motors-head"><h5>Motors</h5>
      <button class="vbtn" data-pose="rest">rest</button><button class="vbtn" data-pose="spread">spread</button>
      <button class="vbtn" data-pose="reach">reach + extend</button><button class="vbtn" data-pose="random">random</button>
      <button class="vbtn" data-pose="cycle">cycle motors</button>
      <span class="muted small">swing is mirrored per side: + raises / spreads outward</span></div>
    <div class="motor-grid">
      ${limbs.map((l) => `<div class="motor"><header><span class="tag">${l.tag}</span>${l.name}</header>
        ${ch(`${l.key}-swing`, l.swing, -90, 90, 1)}${ch(`${l.key}-lift`, "Lift", -45, 80, 1)}${ch(`${l.key}-extend`, "Extend", 0, 1, 0.01)}</div>`).join("")}
      ${v.head || v.recline ? `<div class="motor"><header><span class="tag">M5</span>Head + recline</header>
        ${v.head ? ch("head", "Head", -25, 25, 1) : ""}${v.recline ? ch("recline", "Recline", -30, 60, 1) : ""}</div>` : ""}
    </div>`;
  panel.oninput = (e) => {
    const t = e.target; if (t.type !== "range") return;
    v.anim = false; panel.querySelector('[data-pose="cycle"]')?.classList.remove("on");
    const [k, c] = t.id.split("-");
    if (c) v.state[k][c] = Number(t.value); else v.state[k] = Number(t.value);
    apply();
  };
  panel.onclick = (e) => {
    const p = e.target.closest("[data-pose]")?.dataset.pose;
    if (!p) return;
    if (p === "cycle") { v.anim = !v.anim; e.target.classList.toggle("on", v.anim); return; }
    v.anim = false; panel.querySelector('[data-pose="cycle"]')?.classList.remove("on");
    reset();
    const s = v.state, r = (a, b) => a + Math.random() * (b - a);
    if (p === "spread") { for (const k of ["arm_L", "arm_R", "leg_L", "leg_R"]) if (s[k]) s[k].swing = 14; }
    if (p === "reach") {
      if (s.arm_L) Object.assign(s.arm_L, { swing: 45, extend: 1 });
      if (s.arm_R) Object.assign(s.arm_R, { swing: -20, extend: 0.5 });
      if (s.leg_L) s.leg_L.extend = 0.8;
      if (s.leg_R) s.leg_R.lift = 30;
      s.recline = 25;
    }
    if (p === "random") {
      for (const l of LIMBS) if (s[l.key]) s[l.key] = { swing: Math.round(r(-60, 60)), lift: Math.round(r(-20, 50)), extend: +r(0, 1).toFixed(2) };
      s.head = Math.round(r(-15, 15)); s.recline = Math.round(r(0, 40));
    }
    apply();
  };
  apply();
}

function reset() {
  V.state = { head: 0, recline: 0 };
  for (const k of Object.keys(V.joints)) V.state[k] = { swing: 0, lift: 0, extend: 0 };
}

const qa = new THREE.Quaternion(), qb = new THREE.Quaternion();
function apply() {
  const v = V;
  for (const [k, J] of Object.entries(v.joints)) {
    const s = v.state[k];
    qa.setFromAxisAngle(Z, THREE.MathUtils.degToRad(s.swing * J.side));
    qb.setFromAxisAngle(X, THREE.MathUtils.degToRad(s.lift));
    J.joint.quaternion.copy(J.q0).multiply(qa).multiply(qb);
    J.slide.position.copy(J.p0).add(new THREE.Vector3(0, s.extend * J.max, 0));
  }
  if (v.head) v.head.o.quaternion.copy(v.head.q0).multiply(qa.setFromAxisAngle(X, THREE.MathUtils.degToRad(v.state.head)));
  if (v.recline) v.recline.o.quaternion.copy(v.recline.q0).multiply(qa.setFromAxisAngle(X, THREE.MathUtils.degToRad(-v.state.recline)));
  syncUI();
}

function syncUI() {
  const panel = V.el.querySelector(".motors");
  const set = (id, val, text) => {
    const inp = panel.querySelector(`#${CSS.escape(id)}`), out = panel.querySelector(`[data-out="${id}"]`);
    if (inp && Number(inp.value) !== val) inp.value = val;
    if (out) out.textContent = text;
  };
  const deg = (x) => `${x > 0 ? "+" : ""}${Math.round(x)}°`;
  for (const [k, J] of Object.entries(V.joints)) {
    const s = V.state[k];
    set(`${k}-swing`, s.swing, deg(s.swing));
    set(`${k}-lift`, s.lift, deg(s.lift));
    set(`${k}-extend`, s.extend, J.units ? `${(s.extend * J.max * 100).toFixed(1)} cm` : `${Math.round(s.extend * 100)}%`);
  }
  set("head", V.state.head, deg(V.state.head));
  set("recline", V.state.recline, deg(V.state.recline));
}

function animate(t) {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches ? 0.3 : 1;
  t *= reduced;
  LIMBS.forEach((l, i) => {
    const s = V.state[l.key]; if (!s) return;
    s.swing = 50 * Math.sin(t * 0.9 + i * 1.6);
    s.lift = 20 * Math.sin(t * 0.6 + i);
    s.extend = 0.5 + 0.5 * Math.sin(t * 1.3 + i * 0.8);
  });
  V.state.recline = 20 + 20 * Math.sin(t * 0.4);
  apply();
}
