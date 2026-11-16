// capability-enablement 3.4: the Set up dialog's pure parts (web/setup-dialog.js): the plan in sections with nothing to
// decide hidden, its questions as fields, the answers gaifa setup takes, and a job's words.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const d = await import(pathToFileURL(path.join(root, 'web/setup-dialog.js')).href);

const PLAN = {
  stage: 'plan', disk_gb: 6.7, gpu: true, required_models_gb: 1.73, images: { 'docker.io/searxng/searxng@sha256:x': 0.3 },
  about: [{ id: 'decide', name: 'Decisions', provides: 'judge tool calls in Auto mode', folder: 'services/decide', port: 5107, recommended: true, installed: false }],
  steps: [{ id: 'decide/1', what: 'makes .venv/ with PyTorch (6.6 GB)', run: 'gaifa install decide' }],
  suggestions: [{ name: 'd3-lite', size_gb: 1.73, source: 'vllm-sr/d3-lite', licence: 'Apache-2.0', required: true }],
  questions: [{ id: 'decide/models', kind: 'models', text: 'Which models for Decisions?', choices: ['d3-lite'], required: ['d3-lite'] },
              { id: 'decide/licence', kind: 'yes-no', text: 'Accept the licence?' }],
  host: [{ id: 'podman', ok: false, detail: 'podman is missing', fix: 'sudo dnf install podman', needs_root: true, gpu: false },
         { id: 'iommu-on', ok: true, detail: 'the IOMMU is on', fix: '' }],
  variants: [{ setup: 'decide', label: 'ROCm', untested: false }],
  unavailable: [],
};

test('the plan in sections: what, where, sizes, downloads with source and licence, containers, host problems', () => {
  const s = Object.fromEntries(d.planSections(PLAN).map(x => [x.title, x]));
  assert.deepEqual(s['What you get'].rows, ['Decisions: judge tool calls in Auto mode (port 5107)']);
  assert.deepEqual(s['What it installs and where (services/decide)'].rows, ['makes .venv/ with PyTorch (6.6 GB) — gaifa install decide']);
  assert.deepEqual(s.Downloads.rows, ['d3-lite, 1.7 GB from vllm-sr/d3-lite, licence Apache-2.0 (needed)']);
  assert.deepEqual(s.Containers.rows, ['container image docker.io/searxng/searxng@sha256:x (0.3 GB)']);
  assert.deepEqual(s.Size.rows, ['6.7 GB on disk, 1.7 GB of models']);
  assert.deepEqual(s['For this machine'].rows, ['decide: ROCm']);
  assert.equal(s['Fix on this machine first'].tone, 'warn');
  assert.deepEqual(s['Fix on this machine first'].rows, ['podman is missing: sudo dnf install podman (needs sudo: run it yourself)']);
  assert.deepEqual(d.planSections(null), []);
});

test('questions become fields, and fields the answers gaifa setup takes', () => {
  const qs = d.questions(PLAN);
  assert.deepEqual(qs.map(q => [q.id, q.kind]), [['decide/models', 'models'], ['decide/licence', 'yes-no']]);
  assert.deepEqual(d.answersFrom(qs, {}), { accept: ['decide/licence'], decline: [], models: { decide: ['d3-lite'] }, values: {} });
  assert.deepEqual(d.answersFrom(qs, { 'decide/licence': false, 'decide/models': [] }).decline, ['decide/licence']);
  assert.deepEqual(d.answersFrom([{ id: 'agent/config:AGENT_MODEL', kind: 'choice', choices: ['a', 'b'], required: [] }], { 'agent/config:AGENT_MODEL': 'b' }).values,
    { 'agent/config:AGENT_MODEL': 'b' });
});

test("a job's words", () => {
  assert.match(d.jobWords({ ids: ['web'], state: 'running', lines: ['==> web: makes .venv/'] }).body, /makes \.venv/);
  assert.equal(d.jobWords({ ids: ['web'], state: 'done', started: [{ id: 'web', state: 'ready' }] }).title, 'web is set up');
  assert.match(d.jobWords({ ids: ['web'], state: 'done', started: [{ id: 'web', state: 'failed', error: 'port 5102 in use' }] }).title, /didn't start/);
  assert.match(d.jobWords({ ids: ['web'], state: 'needs_you', needs: { interactive: [{ id: 'web/2', run: 'sudo usermod -aG docker me' }] } }).body, /sudo usermod/);
  assert.match(d.jobWords({ ids: ['web'], state: 'failed', error: 'web: web/1 failed' }).body, /web\/1 failed/);
});

test('only a command gets a Copy button', () => {
  assert.equal(d.isCommand('sudo dnf install podman'), true);
  assert.equal(d.isCommand('loginctl enable-linger me'), true);
  assert.equal(d.isCommand('move the clone under your home folder: the ComfyUI toolbox only sees $HOME'), false);
});

test('capability-enablement 7.1: a model question carries where such models are compared', () => {
  const qs = d.questions({ questions: [{ id: 'embed/models', kind: 'models', text: 'Which?', choices: ['a'], required: [], find: [{ label: 'MTEB', url: 'https://huggingface.co/spaces/mteb/leaderboard' }] }] });
  assert.equal(qs[0].find[0].label, 'MTEB');
});
