// capability-enablement 3.3: the box for a mod that isn't on (web/mod-off.js): each status's words and buttons, the
// small-setup rule, and the page mounting again when the status changes (ModPage's key).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const m = await import(pathToFileURL(path.join(root, 'web/mod-off.js')).href);

const cal = (status, o = {}) => ({ id: 'calendar', name: 'Calendar', state: 'stopped', provides: 'keep your calendar, to-dos and reminders',
  manifest_errors: [], availability: { status, why: '', fix: {} }, ...o });
const ids = v => v.buttons.map(b => b.id);

test('each status has its words and buttons', () => {
  const plan = { disk_gb: 0.1, steps: [{ what: 'makes .venv/ (0.1 GB)' }], questions: [], host: [] };
  let v = m.offView(cal('not_set_up'), 'the calendar', plan);
  assert.equal(v.title, "Calendar isn't set up on this machine");
  assert.match(v.body, /It lets GAIFA keep your calendar, to-dos and reminders\. Setting it up: makes \.venv\/ \(0\.1 GB\) · about 0\.1 GB in all\./);
  assert.deepEqual(ids(v), ['setup']) ; assert.equal(v.buttons[0].label, 'Set up Calendar'); assert.ok(v.agent && v.small);
  v = m.offView(cal('off'), 'the calendar');
  assert.equal(v.title, 'Calendar is turned off'); assert.deepEqual(ids(v), ['enable']); assert.equal(v.buttons[0].label, 'Turn on Calendar');
  v = m.offView(cal('starts_on_use'), 'the calendar');
  assert.equal(v.title, 'Calendar is not running'); assert.equal(v.body, 'Start it to use the calendar.'); assert.deepEqual(ids(v), ['start']);
  v = m.offView(cal('on', { state: 'starting' }));
  assert.equal(v.title, 'Calendar is starting…'); assert.deepEqual(v.buttons, []);
  v = m.offView(cal('failed', { state: 'failed', last_error: "exited with status 1 while starting\n\nLast log lines:\nTraceback" }));
  assert.equal(v.body, 'exited with status 1 while starting'); assert.deepEqual(ids(v), ['start', 'logs']);
  v = m.offView(cal('cant_run', { availability: { status: 'cant_run', why: 'Calendar can\'t run on this machine: its variant (cuda) needs a GPU' } }));
  assert.match(v.title, /can't run on this machine/); assert.match(v.body, /cuda/);
  v = m.offView(cal('broken', { manifest_errors: ['service.toml: missing [run].port'] }));
  assert.match(v.title, /problem in its service.toml/); assert.equal(v.body, 'service.toml: missing [run].port');
});

test('the status without an availability (an older hub)', () => {
  assert.equal(m.statusOf({ state: 'failed', manifest_errors: [] }), 'failed');
  assert.equal(m.statusOf({ state: 'stopped', enabled: false, manifest_errors: [] }), 'off');
  assert.equal(m.statusOf({ state: 'stopped', manifest_errors: ['x'] }), 'broken');
  assert.equal(m.statusOf({ state: 'stopped', manifest_errors: [] }), 'starts_on_use');
});

test('a small setup runs from the button; anything else asks first', () => {
  assert.equal(m.isSmall({ disk_gb: 0.2, questions: [], host: [] }), true);
  assert.equal(m.isSmall({ disk_gb: 6.7, questions: [], host: [] }), false, '0.5 GB and more');
  assert.equal(m.isSmall({ disk_gb: 0.1, questions: [{ id: 'x' }], host: [] }), false, 'a question');
  assert.equal(m.isSmall({ disk_gb: 0.1, questions: [], host: [{ id: 'podman', ok: false }] }), false, 'a host problem');
  assert.equal(m.isSmall(null), false, 'no plan yet');
});

test('the page mounts again when the status changes, and the five pages use the shared box', () => {
  const src = fs.readFileSync(path.join(root, 'web/ModPage.dc.html'), 'utf8');
  assert.match(src, /keyOf\(m\) \{[^\n]*availability\?\.status/);
  const kit = fs.readFileSync(path.join(root, 'web/mod-kit.js'), 'utf8');
  assert.match(kit, /modOff\(el, ctx, what\)/);
  for (const id of ['agent', 'mcp', 'searxng', 'web']) {
    const page = fs.readFileSync(path.join(root, `services/${id}/ui/page.js`), 'utf8');
    assert.ok(page.includes('requireRunning') && !page.includes('is not running`'), id);
  }
});

test('a GPU-only host check does not matter to a mod without the GPU', () => {
  assert.equal(m.isSmall({ disk_gb: 0.1, gpu: false, questions: [], host: [{ id: 'clone-under-home', ok: false, gpu: true }] }), true);
  assert.equal(m.isSmall({ disk_gb: 0.1, gpu: true, questions: [], host: [{ id: 'clone-under-home', ok: false, gpu: true }] }), false);
});
