// web/hardware.js (plan 35.2): the Hardware card's view of GET /api/system/hardware. The card is checked in the browser.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const hw = await import(pathToFileURL(path.join(root, 'web', 'hardware.js')).href);

const strix = { os: 'linux', wsl: false, container: '', distro: { name: 'Fedora Linux 44' }, cpu: 'AMD RYZEN AI MAX+ 395', cpus: 32, ram_bytes: 130446364672,
  gpus: [{ index: 0, vendor: 'amd', name: 'AMD Radeon 8060S Graphics', arch: 'gfx1151', memory: 'unified', vram_bytes: 130446364672,
    runtimes: { rocm: '7.1', vulkan: 'yes' }, accels: ['rocm', 'vulkan'], problems: [] }], accels: ['rocm', 'vulkan', 'cpu'] };

test('this machine: one unified GPU', () => {
  const v = hw.hwView(strix);
  assert.equal(v.system, 'Fedora Linux 44 · AMD RYZEN AI MAX+ 395 · 32 CPUs · 130 GB memory');
  assert.equal(v.gpus[0].name, 'AMD Radeon 8060S Graphics (gfx1151)');
  assert.equal(v.gpus[0].memory, "shares the system's memory · up to 130 GB");
  assert.equal(v.gpus[0].runtimes, 'ROCm 7.1, Vulkan');
  assert.equal(v.gpus[0].runs, 'ROCm, Vulkan');
  assert.equal(v.accels, 'ROCm · Vulkan · CPU');
});

test('WSL, a dedicated card, a GPU that runs nothing yet, no GPU', () => {
  const m = { ...strix, wsl: true, distro: { name: 'Ubuntu 24.04' }, gpus: [
    { index: 0, name: 'NVIDIA GeForce RTX 4070', arch: 'sm_89', memory: 'dedicated', vram_bytes: 12e9, runtimes: { cuda: '12.7' }, accels: ['cuda'], problems: [] },
    { index: 1, name: 'Intel GPU (through WSL)', arch: '', memory: 'unknown', vram_bytes: 0, runtimes: {}, accels: [], problems: ['no Level Zero'] }] };
  const v = hw.hwView(m);
  assert.ok(v.system.startsWith('Ubuntu 24.04 (WSL2) · '));
  assert.equal(v.gpus[0].memory, '12.0 GB VRAM');
  assert.equal(v.gpus[1].memory, 'memory unknown');
  assert.equal(v.gpus[1].runs, 'nothing AIHub can use yet');
  assert.deepEqual(v.gpus[1].problems, ['no Level Zero']);
  assert.equal(hw.hwView({ ...strix, gpus: [], accels: ['cpu'] }).none, true);
  assert.equal(hw.hwView(null), null);
});
