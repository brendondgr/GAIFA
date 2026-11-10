// A scheduled task's editor (plan scheduled-tasks 4.3): a dialog for a new task or a task's settings. Name and
// instructions; the schedule (Hourly: every N hours at :MM, an optional window and weekdays only; Every day, Weekdays: a
// time; Weekly: a day and a time; Monthly: a day of the month and a time) with its words and next run; the project (and
// "only its own folders"); model and mode (Bypass warns); skills always on; pre-allows (tools or globs, sites or every
// site, MCP servers); Use profile, Use project memory; how long its run chats stay before they're archived. Saving
// runs the agent's check: a new task with problems is saved turned off and stays open with them; an edit answers its
// problems the same way. Pure helpers first (tested in utils/tests/web/chat-tasks.test.mjs). Written by us (web/PATCHES.md).

import { h, T, Btn, inputSt, label11, SHADOW, ON_ACC, MONO } from './chat-ui.js';
import { KINDS, DAYS, check, describe, nextAfter, whenWords } from './chat-when.js';

const R = () => globalThis.React;
export const MODES = [['plan', 'Plan (reads only)'], ['accept_edits', 'Accept edits'], ['auto', 'Auto (the judge decides)'], ['bypass', 'Bypass (no judge)']];
export const BYPASS_WARNING = 'Bypass: the judge isn’t asked, so only the folders’ levels limit what a run does. No one is watching.';

/** "a, b  c" → ["a", "b", "c"], without repeats. */
export const splitList = s => [...new Set(String(s || '').split(/[\s,]+/).map(x => x.trim()).filter(Boolean))];

/** The editor's fields from a task (or the defaults for a new one, `preset` on top: a project's page passes its id). */
export function formOf(t = null, preset = {}) {
  const s = t?.schedule || { kind: 'daily', time: '07:00' };
  return {
    name: t?.name || '', instructions: t?.instructions || '', kind: t ? s.kind : preset.kind || s.kind, time: s.time || '07:00', day: s.day ?? (s.kind === 'monthly' ? 1 : 0),
    at: s.at || preset.at || '', event: s.kind === 'event' ? s : null,   // calendar 6.1–6.2: once's time; an event schedule kept as it is
    every: s.every || 1, minute: s.minute || 0, windowOn: !!(s.from && s.to), from: s.from || '08:00', to: s.to || '18:00', weekdays: !!s.weekdays,
    project_id: t?.project_id || preset.project_id || '', only_own: !!t?.only_own, model: t?.model || '', mode: t?.mode || 'auto',
    skills: [...(t?.skills || [])], tools: (t?.allow?.tools || []).join(', '), sites: (t?.allow?.sites || []).filter(x => x !== '*').join(', '),
    anySite: (t?.allow?.sites || []).includes('*'), mcp: [...(t?.allow?.mcp || [])], use_profile: t ? !!t.use_profile : true,
    use_project_memory: t ? !!t.use_project_memory : true, keep_days: t?.keep_days || 30,
  };
}
/** Once's default time: the next whole hour. */
export function defaultAt(now = new Date()) {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours() + 1, 0);
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:00`;
}
/** The schedule the fields describe. */
export function scheduleOf(f) {
  if (f.kind === 'hourly') {
    return { kind: 'hourly', every: +f.every || 1, minute: +f.minute || 0, ...(f.windowOn ? { from: f.from, to: f.to } : {}), ...(f.weekdays ? { weekdays: true } : {}) };
  }
  if (f.kind === 'once') return { kind: 'once', at: f.at };
  if (f.kind === 'event' && f.event) return f.event;
  if (f.kind === 'weekly') return { kind: 'weekly', day: +f.day || 0, time: f.time };
  if (f.kind === 'monthly') return { kind: 'monthly', day: Math.min(31, Math.max(1, +f.day || 1)), time: f.time };
  return { kind: f.kind, time: f.time };
}
/** What saving sends, or an error to show. */
export function taskBody(f) {
  const name = String(f.name || '').trim().replace(/\s+/g, ' ');
  if (!name) return { error: 'A task needs a name.' };
  if (!String(f.instructions || '').trim()) return { error: 'Say what each run should do: the instructions are its first message.' };
  const schedule = scheduleOf(f), bad = check(schedule);
  if (bad.length) return { error: `The schedule: ${bad[0]}.` };
  const sites = [...splitList(f.sites).map(s => s.replace(/^https?:\/\//, '').replace(/\/.*$/, '').toLowerCase()), ...(f.anySite ? ['*'] : [])];
  return { body: {
    name, instructions: String(f.instructions).trim(), schedule, project_id: f.project_id || null, only_own: !!(f.project_id && f.only_own),
    model: f.model || null, mode: f.mode, skills: f.skills, allow: { tools: splitList(f.tools), sites, mcp: f.mcp },
    use_profile: !!f.use_profile, use_project_memory: !!f.use_project_memory, keep_days: Math.min(3650, Math.max(1, +f.keep_days || 30)),
  } };
}
/** The schedule's words and its next run, for the picker's preview. */
export function preview(f, now = Date.now() / 1000) {
  const s = scheduleOf(f), bad = check(s);
  if (bad.length) return { error: bad[0] };
  if (s.kind === 'event') return { words: describe(s), next: 'from the calendar' };
  const nxt = nextAfter(s, now);
  return nxt ? { words: describe(s), next: whenWords(nxt, now) } : { error: 'that time has passed' };
}

export function TaskEditor({ shared, task = null, preset = {}, onClose, onSaved }) {
  const React = R(), { useState } = React;
  const { c, models, settings, tools, projects } = shared;
  const [f, setF] = useState(() => formOf(task, preset)), [err, setErr] = useState(null), [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(task), [found, setFound] = useState(null);
  const set = (k, v) => setF(x => ({ ...x, [k]: v }));
  const ev = k => e => set(k, e.target.type === 'checkbox' ? e.target.checked : e.target.value);
  const toggleIn = (k, v) => set(k, f[k].includes(v) ? f[k].filter(x => x !== v) : [...f[k], v]);
  const pv = preview(f);
  const servers = [...new Set((tools || []).map(t => t.group).filter(g => g && String(g).startsWith('mcp:')).map(g => g.slice(4)))].sort();
  const submit = async e => {
    e?.preventDefault?.();
    const { body, error } = taskBody(f);
    if (error) { setErr(error); return; }
    setBusy(true); setErr(null); setFound(null);
    try {
      if (saved) {
        const t = await c.patchTask(saved.id, body);
        setSaved(t); onSaved?.(t);
      } else {
        const t = await c.createTask(body);
        setSaved(t);
        if (t.check?.problems?.length) setFound(t.check); else onSaved?.(t);
      }
    } catch (x) {
      if (x?.code === 'task_problems' && x?.data) { setFound(x.data); setSaved(x.data.task || saved); } else setErr(x?.detail || x?.message || 'Not saved');
    }
    setBusy(false);
  };
  const area = { ...inputSt, height: 'auto', padding: '8px 9px', resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.45 };
  const field = (label, child, hint) => h('label', { style: { display: 'flex', flexDirection: 'column', gap: 5 } }, h('span', { style: label11 }, label), child,
    hint ? h('span', { style: { fontSize: 11.5, color: T.dim } }, hint) : null);
  const sel = { ...inputSt, height: 30, cursor: 'pointer' };
  const num = (k, lo, hi, w = 64, label = k) => h('input', { type: 'number', min: lo, max: hi, value: f[k], onChange: ev(k), 'aria-label': label, style: { ...inputSt, height: 30, width: w } });
  const time = (k, label) => h('input', { type: 'time', value: f[k], onChange: ev(k), 'aria-label': label, style: { ...inputSt, height: 30, width: 110 } });
  const check1 = (k, label) => h('label', { style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, color: T.tx } },
    h('input', { type: 'checkbox', checked: !!f[k], onChange: ev(k) }), label);
  const chip = (on, label, fn, title) => h('button', { key: label, type: 'button', 'aria-pressed': on ? 'true' : 'false', onClick: fn, title,
    style: { height: 24, padding: '0 8px', borderRadius: 99, border: '1px solid ' + (on ? T.cy : T.bd), background: on ? T.tcy : 'transparent', color: on ? T.tx : T.mut, font: 'inherit', fontSize: 11.5, cursor: 'pointer' } }, label);
  const row = (...kids) => h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 12.5 } }, ...kids);
  const scheduleFields = f.kind === 'hourly' ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } },
    row('Every', num('every', 1, 24, 60, 'Every how many hours'), 'hour(s), at minute', num('minute', 0, 59, 60, 'At minute')),
    row(check1('windowOn', 'Only between'), f.windowOn ? time('from', 'From') : null, f.windowOn ? 'and' : null, f.windowOn ? time('to', 'To') : null),
    check1('weekdays', 'Weekdays only'))
    : f.kind === 'weekly' ? row('On', h('select', { value: f.day, onChange: ev('day'), 'aria-label': 'Day of the week', style: sel }, DAYS.map((d, i) => h('option', { key: d, value: i }, d))), 'at', time('time', 'Time'))
      : f.kind === 'monthly' ? row('On day', num('day', 1, 31, 64, 'Day of the month'), 'at', time('time', 'Time'), +f.day > 28 ? h('span', { style: { color: T.dim, fontSize: 11.5 } }, 'a shorter month: its last day') : null)
        : f.kind === 'once' ? row('On', h('input', { type: 'datetime-local', value: f.at, onChange: ev('at'), 'aria-label': 'Date and time', style: { ...inputSt, height: 30, width: 210 } }),
          h('span', { style: { color: T.dim, fontSize: 11.5 } }, 'it runs once, then turns off'))
          : f.kind === 'event' ? row(h('span', { style: { color: T.mut } }, 'Set from the Calendar: open the event there to change it.'))
            : row('At', time('time', 'Time'));
  return h('div', { role: 'dialog', 'aria-modal': 'true', 'aria-label': saved ? `Edit ${saved.name}` : 'New scheduled task', onKeyDown: e => { if (e.key === 'Escape') onClose(); },
    style: { position: 'fixed', inset: 0, zIndex: 80, display: 'grid', placeItems: 'center', background: T.ov, padding: 16, overflowY: 'auto' } },
    h('form', { onSubmit: submit, style: { width: 'min(620px, 100%)', maxHeight: 'calc(100vh - 32px)', overflowY: 'auto', background: T.card, border: '1px solid ' + T.bds, borderRadius: 12,
      boxShadow: SHADOW, padding: 18, display: 'flex', flexDirection: 'column', gap: 12 } },
      h('h2', { style: { margin: 0, fontSize: 16, fontWeight: 600 } }, saved ? 'Scheduled task' : 'New scheduled task'),
      field('Name', h('input', { autoFocus: !task, value: f.name, onChange: ev('name'), maxLength: 120, 'aria-label': 'Task name', placeholder: 'e.g. Morning digest', style: { ...inputSt, height: 34 } })),
      field('Instructions', h('textarea', { value: f.instructions, onChange: ev('instructions'), rows: 6, maxLength: 16000, 'aria-label': 'Instructions',
        placeholder: 'What each run should do, in detail. A run reads these as your words, with no one there to ask.', style: area })),
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } }, h('span', { style: label11 }, 'Schedule'),
        h('div', { role: 'radiogroup', 'aria-label': 'How often', style: { display: 'flex', flexWrap: 'wrap', gap: 4 } },
          f.kind === 'event' ? chip(true, 'Before an event', () => {}) : KINDS.map(([k, l]) => chip(f.kind === k, l, () => setF(x => ({ ...x, kind: k, day: k === 'monthly' ? Math.max(1, +x.day || 1) : k === 'weekly' ? Math.min(6, +x.day || 0) : x.day,
            at: k === 'once' && !x.at ? defaultAt() : x.at }))))),
        scheduleFields,
        h('span', { role: 'status', style: { fontSize: 12, color: pv.error ? T.rd : T.mut } }, pv.error ? `The schedule: ${pv.error}` : `${pv.words} · next ${pv.next}`)),
      h('div', { style: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 } },
        field('Project', h('select', { value: f.project_id, onChange: ev('project_id'), 'aria-label': 'Project', style: sel },
          h('option', { value: '' }, 'None (standalone)'), (projects || []).map(p => h('option', { key: p.id, value: p.id }, p.name)))),
        field('Model', h('select', { value: f.model, onChange: ev('model'), 'aria-label': 'Model', style: sel },
          h('option', { value: '' }, f.project_id ? 'The project’s default' : 'The agent’s default'), (models?.models || []).map(m => h('option', { key: m.id, value: m.id }, m.name || m.id))))),
      f.project_id ? check1('only_own', 'Only its own folders (not the project’s): add them on its page') : null,
      field('Mode', h('select', { value: f.mode, onChange: ev('mode'), 'aria-label': 'Mode', style: sel }, MODES.map(([k, l]) => h('option', { key: k, value: k }, l))),
        f.mode === 'bypass' ? null : 'What would ask is refused: no one is there to answer a card.'),
      f.mode === 'bypass' ? h('div', { role: 'alert', style: { fontSize: 12, color: T.acc, background: T.tacc, borderRadius: 7, padding: '7px 9px' } }, BYPASS_WARNING) : null,
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } }, h('span', { style: label11 }, 'Allowed ahead of time'),
        field('Tools', h('input', { value: f.tools, onChange: ev('tools'), list: 'aichat-tool-names', 'aria-label': 'Pre-allowed tools', placeholder: 'e.g. workspace_write, web_*', style: { ...inputSt, height: 30, fontFamily: MONO, fontSize: 12 } }),
          'Tool names or globs, comma-separated: these run without the judge.'),
        h('datalist', { id: 'aichat-tool-names' }, (tools || []).slice(0, 400).map(t => h('option', { key: t.name, value: t.name }))),
        field('Sites', h('input', { value: f.sites, onChange: ev('sites'), disabled: f.anySite, 'aria-label': 'Pre-allowed sites', placeholder: 'e.g. news.ycombinator.com, weather.gov', style: { ...inputSt, height: 30, fontFamily: MONO, fontSize: 12 } })),
        check1('anySite', 'Every site (the judge’s URL rules still apply)'),
        servers.length ? h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' } }, h('span', { style: { fontSize: 12, color: T.mut, marginRight: 4 } }, 'MCP servers'),
          servers.map(s => chip(f.mcp.includes(s), s, () => toggleIn('mcp', s)))) : null),
      h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } }, h('span', { style: label11 }, 'Skills always on'),
        (settings?.skills || []).length ? h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 4 } }, settings.skills.map(s => chip(f.skills.includes(s.id), s.name || s.id, () => toggleIn('skills', s.id), s.description)))
          : h('span', { style: { fontSize: 12, color: T.mut } }, 'No skills to choose.')),
      h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center' } },
        check1('use_profile', 'Use my profile'), f.project_id ? check1('use_project_memory', 'Use the project’s memory') : null,
        h('label', { style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5 } }, 'Archive run chats after', num('keep_days', 1, 3650, 70, 'Days to keep run chats'), 'days')),
      found?.problems?.length ? h('div', { role: 'alert', style: { display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12.5, background: T.trd, borderRadius: 8, padding: '8px 10px' } },
        h('strong', null, 'Saved, but turned off until these are fixed:'),
        found.problems.map((p, i) => h('span', { key: i }, `${p.field}: ${p.detail}`, p.fix ? h('span', { style: { color: T.mut } }, ` (${p.fix})`) : null))) : null,
      found?.warnings?.length ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 3, fontSize: 12, color: T.mut } },
        found.warnings.map((w, i) => h('span', { key: i }, `⚠ ${w.field}: ${w.detail}`))) : null,
      err ? h('div', { role: 'alert', style: { color: T.rd, fontSize: 12.5 } }, err) : null,
      h('div', { style: { display: 'flex', justifyContent: 'flex-end', gap: 8 } },
        found && saved ? h(Btn, { kind: 'ghost', sm: true, label: 'Open the task', onClick: () => onSaved?.(saved) }) : null,
        h(Btn, { kind: 'ghost', sm: true, label: found ? 'Close' : 'Cancel', onClick: onClose }),
        h('button', { type: 'submit', disabled: busy, style: { height: 30, padding: '0 14px', borderRadius: 7, border: 0, background: T.acc, color: ON_ACC, font: 'inherit', fontSize: 12.5, fontWeight: 600, cursor: 'pointer' } },
          busy ? 'Saving…' : saved ? 'Save' : 'Create task'))));
}
