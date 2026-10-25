// Settings → About → Hardware (plan 35.2, brief §11.7 `Hardware`): what this machine has, from
// `GET /api/system/hardware`: the system line, one row per GPU (memory, runtimes, what it can run,
// problems), and the accelerators GAIFA can use here. Written by us (web/PATCHES.md).

import { h, MONO, MUT, BD, TONE, fmtBytes, btnSt } from './chart-kit.js';

const R = () => globalThis.React;

// ---------- pure (tested in utils/tests/web/hardware.test.mjs) ----------
export const ACCEL_LABEL = { rocm: 'ROCm', cuda: 'CUDA', xpu: 'Intel XPU', mps: 'Apple MPS', vulkan: 'Vulkan', cpu: 'CPU' };
const RUNTIME_LABEL = { rocm: 'ROCm', cuda: 'CUDA', level_zero: 'Level Zero', vulkan: 'Vulkan', metal: 'Metal' };

export function hwView(m) {
  if (!m) return null;
  const os = m.os === 'darwin' ? (m.distro?.name || 'macOS') : (m.distro?.name || m.os) + (m.wsl ? ' (WSL2)' : '');
  const system = [os, m.cpu, `${m.cpus} CPUs`, fmtBytes(m.ram_bytes) + ' memory', m.container ? `inside ${m.container}` : ''].filter(Boolean).join(' · ');
  const gpus = (m.gpus || []).map(g => ({
    key: g.index, name: g.name + (g.arch ? ` (${g.arch})` : ''),
    memory: g.memory === 'unified' ? `shares the system's memory${g.vram_bytes ? ` · up to ${fmtBytes(g.vram_bytes)}` : ''}`
      : g.memory === 'dedicated' ? `${g.vram_bytes ? fmtBytes(g.vram_bytes) : 'its own'} VRAM` : 'memory unknown',
    runtimes: Object.entries(g.runtimes || {}).map(([k, v]) => (RUNTIME_LABEL[k] || k) + (v && v !== 'yes' ? ' ' + v : '')).join(', '),
    runs: (g.accels || []).map(a => ACCEL_LABEL[a] || a).join(', ') || 'nothing GAIFA can use yet',
    problems: g.problems || [],
  }));
  return { system, gpus, accels: (m.accels || []).map(a => ACCEL_LABEL[a] || a).join(' · '), none: !gpus.length };
}

// ---------- the card ----------
export function HardwareCard({ api }) {
  const React = R(), [m, setM] = React.useState(null), [err, setErr] = React.useState(null), [busy, setBusy] = React.useState(false);
  const load = async refresh => { setBusy(true); try { setM(await api.getHardware(refresh)); setErr(null); } catch (e) { setErr(e); } finally { setBusy(false); } };
  React.useEffect(() => { load(false); }, []);
  const v = hwView(m);
  const label = { fontSize: 11, fontWeight: 600, letterSpacing: '.07em', textTransform: 'uppercase', color: MUT, margin: 0 };
  return h('section', { 'aria-label': 'Hardware', style: { background: 'var(--card,#11151D)', border: `1px solid ${BD}`, borderRadius: 10, padding: 16, display: 'flex', flexDirection: 'column', gap: 10 } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 10 } },
      h('h2', { style: label }, 'Hardware'), h('span', { style: { flex: 1 } }),
      h('button', { onClick: () => load(true), disabled: busy, style: btnSt }, busy ? 'Reading…' : 'Read again')),
    err ? h('div', { role: 'alert', style: { fontSize: 13, color: TONE.red } }, err.detail || String(err))
      : !v ? h('div', { style: { fontSize: 13, color: MUT } }, 'Reading…')
        : [h('div', { key: 's', style: { fontSize: 13 } }, v.system),
          v.none ? h('div', { key: 'n', style: { fontSize: 13, color: MUT } }, 'No GPU found: GAIFA runs everything on the CPU here.') : null,
          ...v.gpus.map(g => h('div', { key: g.key, style: { display: 'flex', flexDirection: 'column', gap: 3, padding: '8px 10px', borderRadius: 7, background: 'var(--inset,#131926)' } },
            h('div', { style: { fontSize: 13, fontWeight: 500 } }, g.name),
            h('div', { style: { fontSize: 12, color: MUT } }, [g.memory, g.runtimes].filter(Boolean).join(' · ')),
            h('div', { style: { fontSize: 12 } }, h('span', { style: { color: MUT } }, 'Runs: '), g.runs),
            ...g.problems.map((p, i) => h('div', { key: i, style: { fontSize: 12, color: TONE.accent } }, p)))),
          h('div', { key: 'a', style: { fontSize: 12, color: MUT } }, 'GAIFA can use: ', h('span', { style: { fontFamily: MONO, color: 'var(--fg,#E6EDF3)' } }, v.accels))]);
}
