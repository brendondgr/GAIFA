// The Set up dialog (plan capability-enablement 3.4): opens from any Set up button with one or more mod ids (a
// `gaifa:setup` window event, {detail: {ids}}). First two ways on, side by side: **Set it up here** (everything the plan
// says, nothing to decide hidden: what, where, sizes, downloads with source and licence, host problems with a command
// to copy and Check again, the questions; then Set up, the live lines, needs_you with I ran it, the test) and **Have your
// coding agent do it** (the prompt and Copy). Reopening while a job runs shows that job.
// Written by us, not Claude Design. Plain DOM over the page's own styles; installed once by the shell (Hub.dc.html).

import { h } from './mod-ui.js';

const GB = n => n == null ? '' : `${n < 1 ? n.toFixed(1) : n < 10 ? n.toFixed(1) : Math.round(n)} GB`;

/** The plan, in the sections the dialog shows: [{title, rows: [string], tone?}]. Pure, for the tests. */
export function planSections(plan) {
  if (!plan) return [];
  const out = [];
  const about = plan.about || [];
  if (about.length) out.push({ title: 'What you get', rows: about.map(a => `${a.name}: ${a.provides || a.description || a.id}` + (a.port ? ` (port ${a.port})` : '')) });
  const steps = (plan.steps || []).map(s => `${s.what}` + (s.run ? ` — ${s.run}` : '') + (s.interactive ? ' (you run this one yourself)' : ''));
  if (steps.length) out.push({ title: `What it installs and where (${about.map(a => a.folder).join(', ') || 'services/'})`, rows: steps });
  const dl = (plan.suggestions || []).map(s => `${s.name}, ${GB(s.size_gb)} from ${s.source || s.repo || 'its source'}` + (s.licence ? `, licence ${s.licence}` : '') + (s.required ? ' (needed)' : '') + (s.gated ? ' (accept its terms on Hugging Face first)' : ''));
  if (dl.length) out.push({ title: 'Downloads', rows: dl });
  const images = Object.entries(plan.images || {}).map(([k, v]) => `container image ${k} (${GB(v)})`);
  if (images.length) out.push({ title: 'Containers', rows: images });
  const size = [plan.disk_gb != null ? `${GB(plan.disk_gb)} on disk` : '', plan.required_models_gb ? `${GB(plan.required_models_gb)} of models` : ''].filter(Boolean);
  if (size.length) out.push({ title: 'Size', rows: [size.join(', ')] });
  const variants = (plan.variants || []).map(v => `${v.setup}: ${v.label}${v.untested ? ' (not tested on this kind of machine)' : ''}${v.note ? ` — ${v.note}` : ''}`);
  if (variants.length) out.push({ title: 'For this machine', rows: variants });
  const host = (plan.host || []).filter(x => x && x.ok === false && (!x.gpu || plan.gpu));
  if (host.length) out.push({ title: 'Fix on this machine first', tone: 'warn', rows: host.map(x => `${x.detail}${x.fix ? `: ${x.fix}` : ''}${x.needs_root ? ' (needs sudo: run it yourself)' : ''}`) });
  const un = (plan.unavailable || []).map(u => `${u.setup}: ${u.why}`);
  if (un.length) out.push({ title: "Can't run here", tone: 'warn', rows: un });
  return out;
}

/** The plan's questions as form fields: [{id, kind, text, choices, required}]. */
export function questions(plan) {
  return (plan?.questions || []).map(q => ({ id: q.id, kind: q.kind || (q.choices ? 'choice' : 'yes-no'), text: q.text || q.id,
    choices: Array.isArray(q.choices) ? q.choices : null, required: q.required || [], picked: q.default || q.required || [], find: q.find || [] }));
}

/** Does a host fix read as a command to run (something to copy), rather than advice? */
export function isCommand(fix) {
  return /^(sudo|dnf|apt|apt-get|zypper|pacman|brew|podman|docker|loginctl|usermod|systemctl|uv|curl|bash|git|gaifa|bin\/gaifa)\b/.test(String(fix || '').trim());
}

/** The answers object `gaifa setup --answers` takes, from the form's values: {accept, decline, models, values}. */
export function answersFrom(qs, values) {
  const out = { accept: [], decline: [], models: {}, values: {} };
  for (const q of qs) {
    const v = values[q.id];
    if (q.kind === 'models') { const [setup] = q.id.split('/'); out.models[setup] = Array.isArray(v) && v.length ? v : ((q.picked || q.required || []).length ? (q.picked || q.required) : ['none']); }
    else if (q.kind === 'yes-no' || q.kind === 'licence') (v === false ? out.decline : out.accept).push(q.id);
    else if (v != null && v !== '') out.values[q.id] = v;
  }
  return out;
}

/** The words for a finished job: {title, body, tone}. */
export function jobWords(job) {
  if (!job) return { title: '', body: '', tone: 'dim' };
  const names = (job.ids || []).join(', ');
  if (job.state === 'running') return { title: `Setting up ${names}…`, body: (job.lines || []).slice(-1)[0] || '', tone: 'accent' };
  if (job.state === 'done') {
    const bad = (job.started || []).filter(s => s.error);
    return bad.length ? { title: `${names} set up, but didn't start`, body: bad.map(s => `${s.id}: ${s.error}`).join(' · '), tone: 'warn' }
      : { title: `${names} ${job.ids.length > 1 ? 'are' : 'is'} set up`, body: 'Started and ready.', tone: 'green' };
  }
  if (job.state === 'needs_you') {
    const n = job.needs || {}, q = (n.questions || [])[0], i = (n.interactive || [])[0];
    return { title: 'It needs you', body: i ? `Run this yourself, then press I ran it: ${i.run || i.id}` : q ? q.text || q.id : 'A step is waiting for you.', tone: 'accent' };
  }
  if (job.state === 'cancelled') return { title: 'Stopped', body: '', tone: 'dim' };
  return { title: `Setting up ${names} failed`, body: job.error || 'See the setup log in data/state/setup/logs/.', tone: 'red' };
}

const BTN = p => `height:30px;padding:0 14px;border-radius:7px;font:inherit;font-size:12.5px;cursor:pointer;${p
  ? 'border:0;background:var(--acc,#FFB224);color:#1A1200;font-weight:600' : 'border:1px solid var(--bds,#2A3547);background:transparent;color:var(--tx,#E6EAF2)'}`;
const MUT = 'color:var(--mut,#8A94A6)';

/** Install the dialog once: `gaifa:setup` events open it. `env`: {api, toast, on(type, fn) → off, go(hash)}. */
export function install(env) {
  if (globalThis.GAIFA_SETUP_DIALOG) return;
  globalThis.GAIFA_SETUP_DIALOG = true;
  globalThis.addEventListener('gaifa:setup', ev => open(env, ev.detail?.ids || []));
}

export async function open(env, ids) {
  const { api, toast } = env;
  const back = h('div', { role: 'presentation', style: 'position:fixed;inset:0;z-index:9000;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;padding:16px' });
  const box = h('div', { role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Set up', style: 'width:min(720px,100%);max-height:calc(100vh - 32px);overflow:auto;background:var(--card,#11151D);border:1px solid var(--bds,#2A3547);border-radius:12px;padding:18px 20px;display:flex;flex-direction:column;gap:12px;color:var(--tx,#E6EAF2);font-size:13px' });
  back.append(box);
  const close = () => { off?.(); back.remove(); };
  back.addEventListener('click', e => { if (e.target === back) close(); });
  document.body.append(back);
  let off = null, plan = null, values = {};
  const head = title => h('div', { style: 'display:flex;align-items:center;gap:8px' }, h('h2', { style: 'margin:0;font-size:16px;flex:1' }, title),
    h('button', { type: 'button', 'aria-label': 'Close', onclick: close, style: 'background:none;border:0;color:var(--mut,#8A94A6);font-size:18px;cursor:pointer' }, '×'));
  const fail = e => toast?.(e?.detail || e?.message || String(e), 'error');

  const showJob = job => {
    const w = jobWords(job), pre = h('pre', { style: 'margin:0;max-height:220px;overflow:auto;font-size:11px;padding:8px 10px;border-radius:6px;background:var(--inset,#131926);white-space:pre-wrap' }, (job.lines || []).slice(-40).join('\n'));
    const acts = [];
    if (job.state === 'running') acts.push(h('button', { type: 'button', style: BTN(false), onclick: () => api.cancelSetup().then(showJob, fail) }, 'Stop'));
    if (job.state === 'needs_you') acts.push(h('button', { type: 'button', style: BTN(true), onclick: () => {
      const done = [...(job.needs?.interactive || []).map(i => i.id)].filter(Boolean);
      api.startSetup(job.ids, { done }).then(follow, fail); } }, 'I ran it'));
    if (job.state === 'done') {
      acts.push(h('button', { type: 'button', style: BTN(true), onclick: () => { close(); env.go?.(`#/s/${job.ids[0]}`); } }, `Open ${job.ids[0]}`));
      acts.push(h('button', { type: 'button', style: BTN(false), onclick: async () => {
        for (const id of job.ids) {
          try { const t = await api.testSetup(id); toast?.((t.sentence || `${id}: ${t.passed ? "passed" : "failed"} in ${t.seconds} s`) + ((t.advice || []).length ? ` · ${t.advice[0]}` : ""), t.passed ? "success" : "error"); }
          catch (e) { if (e?.code !== 'no_test') fail(e); }
        } } }, 'Test on this machine'));
    }
    if (job.state === 'failed') acts.push(h('button', { type: 'button', style: BTN(false), onclick: () => showAgent() }, 'Have your coding agent do it'));
    acts.push(h('button', { type: 'button', style: BTN(false), onclick: close }, 'Close'));
    box.replaceChildren(head(w.title), w.body ? h('p', { style: 'margin:0;' + MUT }, w.body) : '', pre, h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end' }, ...acts));
  };
  const follow = job => {
    showJob(job);
    off?.();
    off = env.on?.('setup', ev => { const j = ev.job; if (j && j.id === job.id) showJob(j); });
  };
  const showAgent = async () => {
    let text = '';
    try { text = await api.getSetupPrompt(ids); } catch (e) { fail(e); }
    const ta = h('textarea', { readonly: true, style: 'width:100%;min-height:220px;font:11.5px/1.5 ui-monospace,monospace;background:var(--inset,#131926);color:inherit;border:1px solid var(--bd,#1D2430);border-radius:6px;padding:8px' });
    ta.value = text;
    box.replaceChildren(head('Have your coding agent do it'),
      h('p', { style: 'margin:0;' + MUT }, 'Paste this into Claude Code or Codex. It reads the same setup docs, runs the same command, and can fix what goes wrong on your machine.'),
      ta, h('div', { style: 'display:flex;gap:8px;justify-content:flex-end' },
        h('button', { type: 'button', style: BTN(true), onclick: () => globalThis.navigator?.clipboard?.writeText(text).then(() => toast?.('Copied', 'success'), fail) }, 'Copy'),
        h('button', { type: 'button', style: BTN(false), onclick: () => choose() }, 'Back')));
  };
  const showHere = async () => {
    box.replaceChildren(head('Set it up here'), h('p', { style: 'margin:0;' + MUT }, 'Reading what it would do…'));
    try { plan = await api.getSetupPlan(ids); } catch (e) { fail(e); return choose(); }
    const qs = questions(plan);
    const secs = planSections(plan).map(s => h('section', { style: 'display:flex;flex-direction:column;gap:4px' },
      h('div', { style: `font-weight:600;font-size:12.5px;${s.tone === 'warn' ? 'color:var(--acct,#FFB224)' : ''}` }, s.title),
      ...s.rows.map(r => h('div', { style: 'font-size:12.5px;overflow-wrap:anywhere;' + MUT }, r))));
    const host = (plan.host || []).filter(x => x && x.ok === false && isCommand(x.fix));   // advice ("move the clone …") is read, not copied
    const fields = qs.map(q => {
      if (q.kind === 'models' && q.choices) return h('fieldset', { style: 'border:0;padding:0;margin:0;display:flex;flex-direction:column;gap:4px' },
        h('legend', { style: 'font-weight:600;font-size:12.5px;margin-bottom:4px' }, q.text),
        ...(q.find || []).map(f => h('div', { style: 'font-size:12px;' + MUT }, 'Compared: ', h('a', { href: f.url, target: '_blank', rel: 'noopener' }, f.label), f.note ? ` (${f.note})` : '')),   // capability-enablement 7.1
        ...q.choices.map(c => { const cb = h('input', { type: 'checkbox', checked: q.picked.includes(c) || undefined, onchange: e => {
          const cur = new Set(values[q.id] || q.picked); e.target.checked ? cur.add(c) : cur.delete(c); values[q.id] = [...cur]; } });
          if (q.picked.includes(c)) cb.checked = true;
          return h('label', { style: 'display:flex;gap:6px;align-items:center;font-size:12.5px' }, cb, c); }));
      if (q.choices) { const sel = h('select', { onchange: e => { values[q.id] = e.target.value; }, style: 'font:inherit' }, ...q.choices.map(c => h('option', { value: c }, c)));
        values[q.id] = q.choices[0]; return h('label', { style: 'display:flex;flex-direction:column;gap:4px;font-size:12.5px' }, q.text, sel); }
      const cb = h('input', { type: 'checkbox', onchange: e => { values[q.id] = e.target.checked; } });
      cb.checked = true; values[q.id] = true;
      return h('label', { style: 'display:flex;gap:6px;align-items:center;font-size:12.5px' }, cb, q.text);
    });
    const blocked = (plan.blocking || []).length > 0;
    box.replaceChildren(head(`Set up ${(plan.about || []).map(a => a.name).join(', ') || ids.join(', ')}`), ...secs,
      host.length ? h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' },
        ...host.map(x => h('button', { type: 'button', style: BTN(false), onclick: () => globalThis.navigator?.clipboard?.writeText(x.fix).then(() => toast?.('Copied: run it in a terminal', 'success'), fail) }, `Copy: ${x.fix}`)),
        h('button', { type: 'button', style: BTN(false), onclick: showHere }, 'Check again')) : '',
      ...fields,
      h('div', { style: 'display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap' },
        h('button', { type: 'button', style: BTN(false), onclick: () => choose() }, 'Back'),
        h('button', { type: 'button', disabled: blocked || undefined, style: BTN(true) + (blocked ? ';opacity:.5;cursor:default' : ''),
          onclick: () => api.startSetup(ids, answersFrom(qs, values)).then(follow, fail) }, 'Set up')));
  };
  const choose = () => {
    const card = (title, body, onclick, primary) => h('button', { type: 'button', onclick, style: `flex:1 1 240px;text-align:left;padding:14px;border-radius:10px;cursor:pointer;font:inherit;color:inherit;background:var(--inset,#131926);border:1px solid ${primary ? 'var(--acc,#FFB224)' : 'var(--bds,#2A3547)'}` },
      h('div', { style: 'font-weight:600;margin-bottom:4px' }, title), h('div', { style: 'font-size:12.5px;' + MUT }, body));
    box.replaceChildren(head(`Set up ${ids.join(', ')}`), h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap' },
      card('Set it up here', 'See what it installs, where and how big, answer its questions, and watch it run.', showHere, true),
      card('Have your coding agent do it', 'A prompt for Claude Code or Codex: it reads the same docs, runs the same command, and can fix what goes wrong on your machine.', showAgent, false)));
  };
  try {
    const job = await api.getSetupJob();
    if (job && job.state === 'running') return follow(job);
  } catch { /* no job yet */ }
  choose();
}
