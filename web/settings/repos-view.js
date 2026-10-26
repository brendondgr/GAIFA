// Settings → Services → Repositories, the pure parts (plan mod-repos 3.5; tested in
// utils/tests/web/settings-repos.test.mjs): the group's summary, each mod's line and badges, and what
// the Update confirmation says. The data is `GET /api/repos` (brief §6.4 `Repos`). Written by us.

const plural = (k, w) => `${k} ${w}${k === 1 ? '' : 's'}`;
const short = sha => (sha ? sha.slice(0, 10) : '—');

/** "4 repositories · 1 update · 1 warning" (an error counts as a warning here; it's red in the list). */
export function repoSummary(body) {
  const list = body?.repos;
  if (!list) return 'Mods that are their own repositories';
  if (!list.length) return 'No mod is its own repository';
  const updates = list.filter(r => r.behind > 0).length;
  const warnings = list.filter(r => r.level === 'warn' || r.level === 'error').length;
  return [list.length === 1 ? '1 repository' : `${list.length} repositories`, updates ? plural(updates, 'update') : '',
    warnings ? plural(warnings, 'warning') : ''].filter(Boolean).join(' · ');
}

/** Where the checkout is: "4716ca0401 on main", "detached at …", "not checked out". */
export function checkoutText(r) {
  if (!r.initialized) return 'not checked out';
  return r.on_branch ? `${short(r.head)} on ${r.on_branch}` : `${short(r.head)} detached`;
}

/** The badges after a mod's name: its problems (red, amber, cyan) or "up to date". */
export function repoBadges(r) {
  const tone = { error: 'red', warn: 'accent', info: 'cyan' };
  const out = (r.problems || []).map(p => ({ code: p.code, tone: tone[p.level] || 'dim',
    text: p.code === 'updates_available' ? plural(r.behind, 'new commit') : LABEL[p.code] || p.code.replace(/_/g, ' '), title: `${p.title}. ${p.fix ? 'Fix: ' + p.fix : ''}`.trim() }));
  if (r.staged_pin) out.push({ code: 'staged', tone: 'purple', text: 'pin staged', title: `GAIFA's index pins ${short(r.staged_pin)}; commit GAIFA to keep it` });
  return out.length ? out : [{ code: 'ok', tone: 'green', text: 'at its pin', title: `pinned at ${short(r.pinned)}` }];
}
const LABEL = { not_checked_out: 'not checked out', dirty: 'changed files', untracked: 'untracked files', unpushed: 'not pushed',
  pin_not_on_remote: 'pin not on GitHub', checkout_behind_pin: 'behind the pin', checkout_ahead_of_pin: 'not pinned yet',
  diverged: 'split from the pin', fetch_failed: "couldn't check", wrong_remote: 'other origin', git_error: 'git failed' };

/** What a mod's Update button does now: null when it can't (with why), else the confirmation's text. */
export function updatePlan(r, incoming) {
  const blocking = (r.problems || []).find(p => ['not_checked_out', 'dirty', 'unpushed', 'diverged', 'git_error'].includes(p.code));
  if (blocking) return { can: false, why: `${blocking.title}. Fix: ${blocking.fix}` };
  if (!r.behind && !(incoming && incoming.length)) return { can: false, why: 'Up to date as of the last check (Check now asks GitHub again)' };
  const n = incoming ? incoming.length : r.behind;
  return { can: true, text: `Update ${r.id} to ${r.branch} on GitHub (${plural(n, 'new commit')}). It installs what changed, restarts ${r.id} if it's running and checks it; `
    + 'if anything fails it goes back. The new pin is staged in GAIFA for you to commit.' };
}

/** The last update's outcome as one line. */
export function updateLine(job) {
  if (!job) return null;
  if (job.running) return { tone: 'cyan', text: `Updating ${job.id}: ${job.steps.length ? job.steps[job.steps.length - 1].text : 'starting'}…` };
  const r = job.result || {};
  return { tone: r.ok ? 'green' : 'red', text: `${job.id}: ${r.message || (r.ok ? 'updated' : 'failed')}` };
}

/** "checked 3h ago", "never checked". */
export function fetchedText(ts, now = Date.now() / 1000) {
  if (!ts) return 'never checked';
  const d = Math.max(0, now - ts);
  return 'checked ' + (d < 90 ? 'just now' : d < 5400 ? `${Math.round(d / 60)} min ago` : d < 172800 ? `${Math.round(d / 3600)} h ago` : `${Math.round(d / 86400)} days ago`);
}
