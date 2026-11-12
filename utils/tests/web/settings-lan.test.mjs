// web/settings/blocks-lan.js (plan lan-access 2.2): Settings → General → Network, its words and steps.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const B = await import(pathToFileURL(path.join(root, 'web/settings/blocks-lan.js')).href).catch(e => ({ skip: e }));
const si = globalThis.setInterval;                 // the mock's 1 s ticker must not keep the test process alive
globalThis.setInterval = (...a) => { const t = si(...a); t.unref?.(); return t; };
const M = await import(pathToFileURL(path.join(root, 'web/mock.js')).href);

test('where it stands, and what is left to do', { skip: B.skip && 'needs the page modules' }, () => {
  const off = { enabled: false, has_password: false, listening: false, devices: [] };
  assert.equal(B.lanSummary(null), 'Other devices on your network');
  assert.equal(B.lanSummary(off), 'Off: GAIFA answers this machine only');
  assert.equal(B.lanSteps(off), 'password');
  assert.equal(B.lanSteps({ ...off, has_password: true }), 'switch');
  assert.equal(B.lanSteps({ ...off, has_password: true, enabled: true }), 'restart');
  assert.equal(B.lanSteps({ ...off, has_password: true, enabled: false, listening: true }), 'restart');     // turned off, still listening
  assert.equal(B.lanSummary({ ...off, listening: true }), 'Off: restart GAIFA to close it');
  const open = { enabled: true, has_password: true, listening: true, devices: [{ id: 'a' }], port: 7000, https: 'off' };
  assert.equal(B.lanSteps(open), null);
  assert.equal(B.lanSummary(open), 'Open to your network · 1 device signed in');
  assert.equal(B.lanSummary({ remote: true }), 'You are signed in from another device');
  assert.equal(B.firewallCommand(open), 'sudo firewall-cmd --permanent --add-port=7000/tcp && sudo firewall-cmd --reload');
  assert.match(B.firewallCommand({ ...open, https: 'also', https_port: 7443 }), /--add-port=7000\/tcp --add-port=7443\/tcp/);
});

test('the mock: a password first, then on, and a restart to open it', async () => {
  const api = M.createMockApi();
  let st = await api.getLan();
  assert.equal(st.enabled, false);
  await assert.rejects(api.saveLan({ enabled: true }), e => e.code === 'no_password');
  await assert.rejects(api.setLanPassword('short'));
  await api.setLanPassword('a long enough password');
  st = await api.saveLan({ enabled: true });
  assert.equal(st.restart_required, true);
  assert.deepEqual((await api.restartHub()), { restarting: true });
});
