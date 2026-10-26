// Settings → Services → Repositories (plan mod-repos 3.5): the summary, the badges per state, the Update
// confirmation, the table drawn from GET /api/repos, and the [repos] rows in the schema.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { render, all, text, find } from './tinyreact.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const V = await load('settings/repos-view.js');
const RB = await load('settings/blocks-repos.js');
const S = await load('settings/schema.js');

const row = (id, o = {}) => ({ id, path: `services/${id}`, url: `git@github.com:brendondgr/${id}.git`, branch: 'main', initialized: true,
  pinned: 'a'.repeat(40), staged_pin: null, head: 'a'.repeat(40), on_branch: 'main', dirty: 0, untracked: 0, ahead: 0, behind: 0, unpushed: 0,
  pinned_on_remote: true, checkout_vs_pin: 'same', remote_url: null, last_fetch_ts: null, fetch_error: null, problems: [], level: null, ...o });
const prob = (code, level, title = code, fix = 'do it') => ({ code, level, title, detail: '', fix });
const BODY = { settings: { fetch_every_h: 24, notify: 'warnings', check_on_start: true }, last_fetch_ts: null, update: null, repos: [
  row('gen3d'),
  row('lcpp', { dirty: 1, level: 'warn', problems: [prob('dirty', 'warn', 'lcpp has 1 changed file not committed', 'commit them in services/lcpp')] }),
  row('relay', { behind: 2, level: 'info', problems: [prob('updates_available', 'info', 'relay: 2 new commits on main', 'gaifa repos update relay')] }),
  row('tts', { initialized: false, head: null, level: 'error', checkout_vs_pin: 'unknown', problems: [prob('not_checked_out', 'error', "tts isn't checked out", 'gaifa repos sync tts')] }),
] };

test('the summary', () => {
  assert.equal(V.repoSummary(BODY), '4 repositories · 1 update · 2 warnings');
  assert.equal(V.repoSummary({ repos: [row('a')] }), '1 repository');
  assert.equal(V.repoSummary({ repos: [] }), 'No mod is its own repository');
  assert.equal(V.repoSummary(null), 'Mods that are their own repositories');
});

test('badges per state', () => {
  const [gen3d, lcpp, relay, tts] = BODY.repos.map(V.repoBadges);
  assert.deepEqual(gen3d.map(b => [b.text, b.tone]), [['at its pin', 'green']]);
  assert.deepEqual(lcpp.map(b => [b.text, b.tone]), [['changed files', 'accent']]);
  assert.deepEqual(relay.map(b => [b.text, b.tone]), [['2 new commits', 'cyan']]);
  assert.deepEqual(tts.map(b => [b.text, b.tone]), [['not checked out', 'red']]);
  assert.match(lcpp[0].title, /Fix: commit them in services\/lcpp/);
  assert.deepEqual(V.repoBadges(row('x', { staged_pin: 'b'.repeat(40) })).map(b => b.text), ['pin staged']);
  assert.equal(V.checkoutText(row('x', { on_branch: null })), 'aaaaaaaaaa detached');
  assert.equal(V.checkoutText(BODY.repos[3]), 'not checked out');
});

test('what Update says and when it can', () => {
  const [gen3d, lcpp, relay] = BODY.repos;
  assert.equal(V.updatePlan(lcpp).can, false);
  assert.match(V.updatePlan(lcpp).why, /changed file.*Fix: commit them/);
  assert.match(V.updatePlan(gen3d).why, /Up to date/);
  const p = V.updatePlan(relay, ['9f1c2ab Anthropic adapter', '77d0e3c Live model lists']);
  assert.ok(p.can);
  assert.match(p.text, /^Update relay to main on GitHub \(2 new commits\)\. It installs what changed, restarts relay.*goes back\. The new pin is staged/);
  assert.equal(V.updateLine({ id: 'relay', running: true, steps: [{ ts: 1, text: 'checking' }] }).text, 'Updating relay: checking…');
  assert.deepEqual(V.updateLine({ id: 'relay', running: false, steps: [], result: { ok: false, message: 'gaifa check failed; relay is back at abc' } }),
    { tone: 'red', text: 'relay: gaifa check failed; relay is back at abc' });
  assert.equal(V.fetchedText(null), 'never checked');
  assert.equal(V.fetchedText(1000, 1000 + 3 * 3600), 'checked 3 h ago');
});

test('the table', () => {
  const api = { getRepos: async () => BODY, fetchRepos: async () => BODY, repoIncoming: async () => ({ commits: [] }), updateRepo: async () => ({}), pinRepo: async () => ({}) };
  const t = render(RB.RepositoriesTable({ ctx: { api, repos: BODY } }));
  const s = text(t);
  for (const id of ['gen3d', 'lcpp', 'relay', 'tts']) assert.ok(s.includes(id), id);
  assert.match(s, /pinned aaaaaaaaaa · checkout aaaaaaaaaa on main/);
  assert.match(s, /lcpp has 1 changed file not committed\. commit them in services\/lcpp/);
  assert.match(s, /gaifa repos update <id>/);
  const updates = all(t, n => n.type === 'button' && text(n) === 'Update…');
  assert.equal(updates.length, 4);
  assert.deepEqual(updates.map(b => !!b.props.disabled), [true, true, false, true]);   // only relay has something new and nothing in the way
  assert.ok(find(t, n => n.type === 'a' && n.props.href === 'https://github.com/brendondgr/relay'));
  assert.ok(find(t, n => n.type === 'button' && text(n) === 'Check now'));
  const none = render(RB.RepositoriesTable({ ctx: { api: {} } }));
  assert.match(text(none), /doesn’t serve \/api\/repos/);
});

test('the rows in the schema', () => {
  const secs = S.sections({ services: [], repos: BODY });
  const g = secs.find(s => s.id === 'services').groups.find(x => x.id === 'repositories');
  assert.equal(g.summary({}), '4 repositories · 1 update · 2 warnings');
  assert.deepEqual(g.rows.map(r => r.key), [null, 'repos.fetch_every_h', 'repos.notify', 'repos.check_on_start']);
  const fetch = g.rows[1];
  assert.equal(fetch.validate(721), 'Between 0 and 720 hours');
  assert.equal(fetch.validate(0), null);
  assert.deepEqual(g.rows[2].choices.map(c => c.value), ['warnings', 'all', 'off']);
});
