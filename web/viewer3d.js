// Viewer3D (design brief §2.1, Part B4): an orbitable GLB viewer with file tabs, wireframe, part
// visibility and rig sliders. Adapted from 3DGenerate's own viewer (services/gen3d/gen3d/web/viewer.js);
// three.js is vendored in web/vendor/three/. Written by us, not Claude Design.
//
//   const v = await mountViewer(el, { files: ['rigged.glb', 'parts.glb', 'mesh.glb'],
//     url: file => Promise<string>,            // a URL the loader can fetch (e.g. ctx.call(...).url)
//     rig: () => Promise<object|null> });       // rig.json, when the job has one
//   v.setPartVisible(index, bool); v.dispose();
//
// Rigged models follow the rig.json contract written by gen3d's workers/rig.py: every limb has a
// `<limb>_joint` node (swing = local Z, lift = local X) and a `<limb>_slide` child (+Y);
// `recline_joint` and `head_joint` rotate about local X.

import * as THREE from './vendor/three/three.module.min.js';
import { GLTFLoader } from './vendor/three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from './vendor/three/addons/controls/OrbitControls.js';

const LIMBS = [
  { key: 'arm_L', name: 'Left arm', swing: 'Raise' }, { key: 'arm_R', name: 'Right arm', swing: 'Raise' },
  { key: 'leg_L', name: 'Left leg', swing: 'Spread' }, { key: 'leg_R', name: 'Right leg', swing: 'Spread' },
];
const LABEL = { 'rigged.glb': 'Rigged', 'parts.glb': 'Parts', 'mesh.glb': 'Mesh' };
const X = new THREE.Vector3(1, 0, 0), Z = new THREE.Vector3(0, 0, 1);
const BTN = 'height:24px;padding:0 9px;border-radius:5px;border:1px solid var(--bds,#2A3547);background:var(--inset,#131926);color:var(--tx,#E6EAF2);font:inherit;font-size:11.5px;cursor:pointer';
const css = (el, s) => { el.style.cssText = s; return el; };
const mk = (tag, s, text) => { const e = css(document.createElement(tag), s || ''); if (text != null) e.textContent = text; return e; };

let live = null;  // one WebGL viewer at a time: contexts are limited

export async function mountViewer(el, { files, url, rig, height = 360 }) {
  live?.dispose();
  const tabs = files.filter(f => /\.(glb|gltf)$/i.test(f));
  if (!tabs.length) throw new Error('nothing to show: no GLB files');
  const wrap = mk('div', 'display:flex;flex-direction:column;gap:8px;min-width:0');
  const stage = mk('div', `position:relative;height:${height}px;border-radius:8px;overflow:hidden;background:#0e1219;border:1px solid var(--bd,#1D2430)`);
  const canvas = mk('canvas', 'width:100%;height:100%;display:block;outline:none');
  canvas.tabIndex = 0;
  canvas.setAttribute('aria-label', '3D view: drag to orbit, scroll to zoom, right-drag to pan');
  const bar = mk('div', 'position:absolute;left:8px;right:8px;top:8px;display:flex;gap:6px;align-items:center;flex-wrap:wrap');
  const busy = mk('div', 'position:absolute;inset:0;display:grid;place-items:center;color:var(--mut,#8A94A6);font-size:12px;pointer-events:none', 'loading…');
  stage.append(canvas, bar, busy);
  const motors = mk('div', 'display:none;flex-direction:column;gap:8px');
  wrap.append(stage, motors);
  el.replaceChildren(wrap);

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
  key.position.set(3, 5, 4); key.castShadow = true; key.shadow.mapSize.set(2048, 2048); scene.add(key);
  const rim = new THREE.DirectionalLight(0xffb224, 0.7); rim.position.set(-3, 2, -3); scene.add(rim);
  const floor = new THREE.Mesh(new THREE.CircleGeometry(1, 64), new THREE.MeshStandardMaterial({ color: 0x151a22, roughness: 0.95 }));
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
  const grid = new THREE.PolarGridHelper(1, 12, 6, 64, 0x2a3547, 0x1d2430); scene.add(grid);
  const loader = new GLTFLoader();

  const V = { root: null, file: null, wire: false, hidden: new Set(), joints: {}, state: {}, anim: false, raf: 0, head: null, recline: null, dead: false };
  const ro = new ResizeObserver(resize); ro.observe(canvas);
  function resize() {
    const r = canvas.getBoundingClientRect();
    renderer.setSize(r.width, r.height, false);
    camera.aspect = r.width / Math.max(r.height, 1); camera.updateProjectionMatrix();
  }
  resize();

  const tabBtns = tabs.map(f => { const b = mk('button', BTN, LABEL[f] || f); b.type = 'button'; b.onclick = () => load(f); return [f, b]; });
  const wireBtn = mk('button', BTN, 'wire'); wireBtn.type = 'button';
  wireBtn.onclick = () => { V.wire = !V.wire; wireBtn.style.borderColor = V.wire ? 'var(--acc,#FFB224)' : ''; V.root?.traverse(o => { if (o.isMesh) o.material.wireframe = V.wire; }); };
  const resetBtn = mk('button', BTN, 'reset view'); resetBtn.type = 'button'; resetBtn.onclick = frame;
  bar.append(...tabBtns.map(([, b]) => b), mk('span', 'flex:1'), wireBtn, resetBtn);

  const tick = t => {
    if (V.dead) return;
    if (V.anim) animate(t / 1000);
    controls.update(); renderer.render(scene, camera);
    V.raf = requestAnimationFrame(tick);
  };
  V.raf = requestAnimationFrame(tick);

  async function load(file) {
    tabBtns.forEach(([f, b]) => { b.style.background = f === file ? 'var(--acc,#FFB224)' : 'var(--inset,#131926)'; b.style.color = f === file ? '#1A1200' : 'var(--tx,#E6EAF2)'; });
    busy.style.display = 'grid'; busy.textContent = 'loading…';
    let gltf;
    try { gltf = await loader.loadAsync(await url(file)); } catch (e) { busy.textContent = `could not load ${file}`; return; }
    if (V.dead) return;
    if (V.root) scene.remove(V.root);
    V.root = gltf.scene; V.file = file;
    V.root.traverse(o => {
      if (!o.isMesh) return;
      o.castShadow = o.receiveShadow = true;
      const hasColor = !!o.geometry.attributes.color;
      const base = o.material?.color && !hasColor ? o.material.color.clone() : new THREE.Color(hasColor ? 0xffffff : 0xb8b2a8);
      o.material = new THREE.MeshStandardMaterial({ color: base, vertexColors: hasColor, roughness: 0.55, metalness: 0.12, wireframe: V.wire });
      if (!o.geometry.attributes.normal) o.geometry.computeVertexNormals();
    });
    const box = new THREE.Box3().setFromObject(V.root), c = box.getCenter(new THREE.Vector3());
    V.root.position.x -= c.x; V.root.position.z -= c.z; V.root.position.y -= box.min.y;
    scene.add(V.root);
    busy.style.display = 'none';
    frame(); applyParts();
    await setupRig(file);
  }

  function frame() {
    if (!V.root) return;
    const size = new THREE.Box3().setFromObject(V.root).getSize(new THREE.Vector3()), h = Math.max(size.x, size.y, size.z) || 1;
    floor.scale.setScalar(h * 0.75); grid.scale.setScalar(h * 0.7);
    controls.target.set(0, size.y * 0.45, 0);
    camera.position.set(h * 1.1, size.y * 0.85, h * 2.4);
    camera.near = h / 100; camera.far = h * 50; camera.updateProjectionMatrix(); controls.update();
  }

  function applyParts() {
    if (!V.root || V.file !== 'parts.glb') return;
    V.root.traverse(o => { const m = /^part_(\d+)_/.exec(o.name || ''); if (m && (o.isMesh || o.children.length)) o.visible = !V.hidden.has(Number(m[1])); });
  }

  // ---- rig sliders ------------------------------------------------------------------------
  async function setupRig(file) {
    V.joints = {}; V.anim = false; V.head = V.recline = null;
    motors.style.display = 'none'; motors.replaceChildren();
    if (file !== 'rigged.glb' || !rig) return;
    let r = null;
    try { r = await rig(); } catch { r = null; }
    if (!r || V.dead) return;
    const units = r.units === 'm';
    for (const l of LIMBS) {
      const j = r.joints?.[l.key], joint = j && V.root.getObjectByName(j.joint_node), slide = j && V.root.getObjectByName(j.slide_node);
      if (joint && slide) V.joints[l.key] = { joint, slide, q0: joint.quaternion.clone(), p0: slide.position.clone(), side: Math.sign(j.extend_dir_world?.[0]) || 1, max: j.limits?.extend?.[1] ?? 0.2, units };
    }
    const grab = n => { const o = n && V.root.getObjectByName(n); return o ? { o, q0: o.quaternion.clone() } : null; };
    V.head = grab(r.joints?.head?.node); V.recline = grab(r.joints?.recline?.node);
    reset();
    const limbs = LIMBS.filter(l => V.joints[l.key]);
    if (!limbs.length && !V.head && !V.recline) return;
    const sliders = {};
    const slider = (id, label, min, max, step) => {
      const inp = mk('input', 'flex:1;min-width:0'); Object.assign(inp, { type: 'range', min, max, step, value: 0 }); inp.setAttribute('aria-label', label);
      const out = mk('output', "font-family:'JetBrains Mono',monospace;font-size:11px;min-width:52px;text-align:right");
      inp.oninput = () => { V.anim = false; const [k, c] = id.split('-'); if (c) V.state[k][c] = Number(inp.value); else V.state[k] = Number(inp.value); apply(); };
      sliders[id] = [inp, out];
      const row = mk('label', 'display:flex;gap:6px;align-items:center;font-size:11.5px'); row.append(mk('span', 'width:52px;color:var(--mut,#8A94A6)', label), inp, out);
      return row;
    };
    const group = (title, ...rows) => { const g = mk('div', 'border:1px solid var(--bd,#1D2430);border-radius:7px;padding:8px;display:flex;flex-direction:column;gap:4px;min-width:0'); g.append(mk('strong', 'font-size:11.5px', title), ...rows); return g; };
    const poses = mk('div', 'display:flex;gap:6px;flex-wrap:wrap;align-items:center');
    for (const [p, label] of [['rest', 'rest'], ['spread', 'spread'], ['reach', 'reach + extend'], ['random', 'random'], ['cycle', 'cycle motors']]) {
      const b = mk('button', BTN, label); b.type = 'button';
      b.onclick = () => pose(p, b); poses.append(b);
    }
    const gridEl = mk('div', 'display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px');
    limbs.forEach(l => gridEl.append(group(l.name, slider(`${l.key}-swing`, l.swing, -90, 90, 1), slider(`${l.key}-lift`, 'Lift', -45, 80, 1), slider(`${l.key}-extend`, 'Extend', 0, 1, 0.01))));
    if (V.head || V.recline) gridEl.append(group('Head + recline', V.head ? slider('head', 'Head', -25, 25, 1) : '', V.recline ? slider('recline', 'Recline', -30, 60, 1) : ''));
    motors.append(poses, gridEl);
    motors.style.display = 'flex';
    V.sync = () => {
      const deg = x => `${x > 0 ? '+' : ''}${Math.round(x)}°`, set = (id, val, text) => { const s = sliders[id]; if (!s) return; if (Number(s[0].value) !== val) s[0].value = val; s[1].textContent = text; };
      for (const [k, J] of Object.entries(V.joints)) { const s = V.state[k]; set(`${k}-swing`, s.swing, deg(s.swing)); set(`${k}-lift`, s.lift, deg(s.lift)); set(`${k}-extend`, s.extend, J.units ? `${(s.extend * J.max * 100).toFixed(1)} cm` : `${Math.round(s.extend * 100)}%`); }
      set('head', V.state.head, deg(V.state.head)); set('recline', V.state.recline, deg(V.state.recline));
    };
    apply();
  }
  function pose(p, btn) {
    if (p === 'cycle') { V.anim = !V.anim; btn.style.borderColor = V.anim ? 'var(--acc,#FFB224)' : ''; return; }
    V.anim = false; reset();
    const s = V.state, r = (a, b) => a + Math.random() * (b - a);
    if (p === 'spread') for (const k of ['arm_L', 'arm_R', 'leg_L', 'leg_R']) if (s[k]) s[k].swing = 14;
    if (p === 'reach') { if (s.arm_L) Object.assign(s.arm_L, { swing: 45, extend: 1 }); if (s.arm_R) Object.assign(s.arm_R, { swing: -20, extend: 0.5 }); if (s.leg_L) s.leg_L.extend = 0.8; if (s.leg_R) s.leg_R.lift = 30; s.recline = 25; }
    if (p === 'random') { for (const l of LIMBS) if (s[l.key]) s[l.key] = { swing: Math.round(r(-60, 60)), lift: Math.round(r(-20, 50)), extend: +r(0, 1).toFixed(2) }; s.head = Math.round(r(-15, 15)); s.recline = Math.round(r(0, 40)); }
    apply();
  }
  function reset() { V.state = { head: 0, recline: 0 }; for (const k of Object.keys(V.joints)) V.state[k] = { swing: 0, lift: 0, extend: 0 }; }
  const qa = new THREE.Quaternion(), qb = new THREE.Quaternion();
  function apply() {
    for (const [k, J] of Object.entries(V.joints)) {
      const s = V.state[k];
      qa.setFromAxisAngle(Z, THREE.MathUtils.degToRad(s.swing * J.side)); qb.setFromAxisAngle(X, THREE.MathUtils.degToRad(s.lift));
      J.joint.quaternion.copy(J.q0).multiply(qa).multiply(qb);
      J.slide.position.copy(J.p0).add(new THREE.Vector3(0, s.extend * J.max, 0));
    }
    if (V.head) V.head.o.quaternion.copy(V.head.q0).multiply(qa.setFromAxisAngle(X, THREE.MathUtils.degToRad(V.state.head)));
    if (V.recline) V.recline.o.quaternion.copy(V.recline.q0).multiply(qa.setFromAxisAngle(X, THREE.MathUtils.degToRad(-V.state.recline)));
    V.sync?.();
  }
  function animate(t) {
    t *= matchMedia('(prefers-reduced-motion: reduce)').matches ? 0.3 : 1;
    LIMBS.forEach((l, i) => { const s = V.state[l.key]; if (!s) return; s.swing = 50 * Math.sin(t * 0.9 + i * 1.6); s.lift = 20 * Math.sin(t * 0.6 + i); s.extend = 0.5 + 0.5 * Math.sin(t * 1.3 + i * 0.8); });
    V.state.recline = 20 + 20 * Math.sin(t * 0.4);
    apply();
  }

  const api = {
    setPartVisible(index, visible) { V.hidden[visible ? 'delete' : 'add'](index); applyParts(); },
    show: load,
    dispose() {
      if (V.dead) return;
      V.dead = true; cancelAnimationFrame(V.raf); ro.disconnect(); controls.dispose();
      scene.traverse(o => { o.geometry?.dispose(); (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => m?.dispose()); });
      renderer.dispose(); renderer.forceContextLoss();
      if (live === api) live = null;
    },
  };
  live = api;
  await load(tabs[0]);
  return api;
}
