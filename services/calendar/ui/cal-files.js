// Import, export and the trash (calendar plan 3.6), and the proposal list that imports, day plans and the
// agent's proposals share (the chat card draws the same list, 4.4): every item ticked except those already
// here or unreadable, a calendar to add them to, and Add N.

import { parse, timeText } from './cal-dates.js';
import { I, el, icon } from './cal-style.js';

/** The ticks a proposal starts with: every item that can be added and isn't already here. */
export const initialTicks = p => new Set((p.items || []).filter(r => !r.problem && !r.already).map(r => r.pid));

/** "Add 3" / "Add 1" / "Nothing ticked". */
export const addLabel = n => n ? `Add ${n}` : 'Nothing ticked';

/** One proposed item's time in words. */
export function rowTime(v) {
  if (!v?.start && !v?.due) return '';
  const s = v.start || v.due, d = parse(s);
  const day = d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  if (v.kind === 'todo') return `${day} · ${timeText({ kind: 'todo', all_day: String(v.due || '').length === 10, due: v.due, start: v.due })}`;
  return `${day} · ${timeText({ kind: 'event', all_day: v.all_day, start: v.start, end: v.end })}`;
}

/** The list with its controls. a: {calendars, accept({ids, calendar}) → Promise, close?, title?} */
export function proposalList(p, a) {
  const ticks = initialTicks(p);
  let calendar = (a.calendars || []).find(c => c.is_default)?.id || '';
  const root = el('div', { style: { display: 'flex', flexDirection: 'column', gap: '8px', minWidth: 0 } });
  const draw = () => {
    const n = ticks.size;
    root.replaceChildren(
      el('div', { style: { display: 'flex', flexDirection: 'column', gap: '2px', maxHeight: '360px', overflowY: 'auto' } },
        ...(p.items || []).map(r => {
          const v = r.view || r.fields || {}, can = !r.problem;
          return el('label.cal-row', { style: { cursor: can ? 'pointer' : 'default', opacity: can ? 1 : 0.6 } },
            el('input', { type: 'checkbox', checked: ticks.has(r.pid), disabled: !can, onchange: e => { if (e.target.checked) ticks.add(r.pid); else ticks.delete(r.pid); draw(); } }),
            el('span', { style: { flex: 1, minWidth: 0 } }, el('div', { style: { fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, v.title || '(no title)'),
              el('div.cal-muted.cal-small', null, r.problem ? `Can't add: ${r.problem.detail}` : [rowTime(v), v.repeat, r.already ? 'already here' : ''].filter(Boolean).join(' · '))));
        })),
      p.skipped?.length ? el('details.cal-muted.cal-small', null, el('summary', null, `${p.skipped.length} skipped`), ...p.skipped.map(s => el('div', null, `${s.title}: ${s.why}`))) : null,
      el('div', { style: { display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' } },
        a.calendars?.length ? (() => { const s = el('select.cal-input', { onchange: e => { calendar = e.target.value; } }, ...a.calendars.map(c => el('option', { value: c.id }, c.name))); s.value = calendar; return s; })() : null,
        el('button.cal-btn.pri', { disabled: !n, onclick: async e => { e.target.disabled = true; try { await a.accept({ ids: [...ticks], calendar }); } finally { e.target.disabled = false; } } }, addLabel(n)),
        el('button.cal-btn.ghost', { onclick: () => { if (ticks.size) ticks.clear(); else initialTicks(p).forEach(x => ticks.add(x)); draw(); } }, ticks.size ? 'Untick all' : 'Tick all'),
        a.close ? el('button.cal-btn.ghost', { onclick: a.close }, 'Cancel') : null));
  };
  draw();
  return root;
}

/** The import sheet: pick or drop an .ics, then its proposal. a: {client, calendars, done(result), close} */
export function importSheet(a, file) {
  const root = el('div.cal-sheet', { role: 'dialog', 'aria-label': 'Import an .ics file' });
  const body = el('div.bd');
  const head = el('div', { style: { display: 'flex', alignItems: 'center', gap: '8px', padding: '12px 16px', borderBottom: '1px solid var(--cal-line)' } },
    el('strong', { style: { flex: 1 } }, 'Import a calendar file'), el('button.cal-btn.icon.ghost', { onclick: a.close, 'aria-label': 'Close' }, icon(I.x, 14)));
  const read = async f => {
    body.replaceChildren(el('div.cal-muted', null, `Reading ${f.name}…`));
    try {
      const p = await a.client.importIcs(f);
      body.replaceChildren(el('div.cal-muted', null, `${p.items.length} item${p.items.length === 1 ? '' : 's'} in ${f.name}. Nothing is added until you choose.`),
        proposalList(p, { calendars: a.calendars, accept: async b => a.done(await a.client.accept(p.id, b)) }));
    } catch (e) { body.replaceChildren(el('div', { style: { color: 'var(--rd,#F85149)' } }, e?.detail || String(e)), pick()); }
  };
  const pick = () => {
    const input = el('input', { type: 'file', accept: '.ics,text/calendar', style: { display: 'none' }, onchange: e => e.target.files[0] && read(e.target.files[0]) });
    return el('div', { style: { border: '1px dashed var(--bds,#2A3547)', borderRadius: '10px', padding: '28px 16px', textAlign: 'center', display: 'flex', flexDirection: 'column', gap: '10px', alignItems: 'center' } },
      icon(I.upload, 22), el('div', null, 'Drop an .ics file here'), el('div.cal-muted', null, 'from Google Calendar, Outlook, Apple Calendar or a course site'),
      el('button.cal-btn', { onclick: () => input.click() }, 'Choose a file…'), input);
  };
  body.append(pick());
  root.addEventListener('dragover', e => e.preventDefault());
  root.addEventListener('drop', e => { e.preventDefault(); const f = e.dataTransfer?.files?.[0]; if (f) read(f); });
  root.append(head, body);
  if (file) read(file);
  return root;
}

/** The trash: deleted items with Restore. a: {client, restored(), close} */
export async function trashSheet(a) {
  const root = el('div.cal-sheet', { role: 'dialog', 'aria-label': 'Trash' });
  const body = el('div.bd');
  root.append(el('div', { style: { display: 'flex', alignItems: 'center', gap: '8px', padding: '12px 16px', borderBottom: '1px solid var(--cal-line)' } },
    el('strong', { style: { flex: 1 } }, 'Trash'), el('span.cal-muted.cal-small', null, 'kept 30 days'), el('button.cal-btn.icon.ghost', { onclick: a.close, 'aria-label': 'Close' }, icon(I.x, 14))), body);
  const draw = async () => {
    const { items } = await a.client.trash();
    body.replaceChildren(...(items.length ? items.map(it => el('div.cal-row', { style: { cursor: 'default' } }, el('span.cal-dot', { style: { background: it.color } }),
      el('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, it.title),
      el('button.cal-btn', { onclick: async () => { await a.client.restore(it.id); a.restored(); draw(); } }, 'Restore'))) : [el('div.cal-muted', null, 'The trash is empty.')]));
  };
  await draw();
  return root;
}
