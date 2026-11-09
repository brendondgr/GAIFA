// The Calendar page (calendar plan 3.2): the main view at #/calendar. The header (Today, ‹ ›, the range's title,
// Day · Week · Month · Agenda, quick add with a preview of what it read, search, New, the menu), the left column
// (a mini month, the calendars, the layers, to-dos, reminders), and the view. What it remembers (the view, the
// date, the layers) is kept on the hub (`calendar.*` in the page store). It follows the mod's `rev`.

import { addDays, parse, rangeOf, sameDay, startOfDay, step, titleOf, wall, ymd, WEEKDAYS, MONTHS, dow, timeText } from './cal-dates.js';
import { askScope, fieldsOf, popover, sheet, snack } from './cal-edit.js';
import { importSheet, proposalList, trashSheet } from './cal-files.js';
import { renderGrid } from './cal-grid.js';
import { renderAgenda, renderMonth } from './cal-month.js';
import { I, el, ensureCss, icon } from './cal-style.js';

export const VIEWS = [['day', 'Day', 'd'], ['week', 'Week', 'w'], ['month', 'Month', 'm'], ['agenda', 'Agenda', 'a']];
const LAYERS = [['tasks', 'Scheduled tasks', true], ['history', 'History', false]];

/** The key a press means, or null: t today, d/w/m/a views, j/k previous/next, n new, / search, Escape. */
export function keyAction(e) {
  if (e.metaKey || e.ctrlKey || e.altKey) return null;
  const t = e.target, typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || ''));
  if (e.key === 'Escape') return { kind: 'escape' };
  if (typing) return null;
  const v = VIEWS.find(x => x[2] === e.key);
  if (v) return { kind: 'view', view: v[0] };
  return { t: { kind: 'today' }, j: { kind: 'step', n: -1 }, k: { kind: 'step', n: 1 }, n: { kind: 'new' }, '/': { kind: 'search' } }[e.key] || null;
}

/** The preview under quick add: "Event · Fri Nov 13 · 13:00–14:30 · Weekly on Tue" plus what it assumed. */
export function previewText(p) {
  if (!p) return '';
  const when = p.kind === 'todo' ? (p.due ? timeText({ kind: 'todo', all_day: String(p.due).length === 10, due: p.due, start: p.due }) + ' · ' + parse(p.due).toDateString().slice(0, 10) : 'no date')
    : `${parse(p.start).toDateString().slice(0, 10)} · ${timeText({ kind: 'event', all_day: p.all_day, start: p.start, end: p.end })}`;
  return [p.kind === 'todo' ? 'To-do' : 'Event', p.title || '(no title)', when, p.repeat].filter(Boolean).join(' · ');
}

export function mountCalendar(root, ctx, client, store) {
  ensureCss();
  const st = {
    view: store?.get('calendar.view', null) || 'week', date: store?.get('calendar.date', null) ? parse(store.get('calendar.date')) : new Date(),
    layers: { tasks: true, history: false, ...(store?.get('calendar.layers', {}) || {}) },
    calendars: [], settings: null, occs: [], todos: [], alerts: [], unread: 0, rev: -1, q: '', results: null, side: false, projects: [], agendaDays: 30, extra: [],
  };
  if (isNaN(st.date)) st.date = new Date();
  const now = () => new Date();
  const page = el('div.cal');
  root.replaceChildren(page);
  let overlay = null, pop = null, alive = true, timer = 0;

  const save = () => { store?.set('calendar.view', st.view); store?.set('calendar.date', ymd(st.date), { wait: 800 }); store?.set('calendar.layers', st.layers); };
  const fail = e => ctx.toast?.(e?.detail || e?.message || String(e), 'error');
  const closePop = () => { pop?.remove(); pop = null; };
  const closeOverlay = () => { overlay?.remove(); overlay = null; };

  async function load() {
    const r = rangeOf(st.view, st.date, st.settings?.week_start || 0), to = st.view === 'agenda' ? addDays(r.from, st.agendaDays) : r.to;
    const [range, todos, alerts, cals] = await Promise.all([client.range(r.from.toISOString(), to.toISOString()), client.todos(), client.alerts('all').catch(() => ({ alerts: [], unread: 0 })), client.calendars()]);
    st.occs = range.occurrences; st.rev = range.rev; st.todos = todos.todos; st.alerts = alerts.alerts || []; st.unread = alerts.unread || 0; st.calendars = cals;
    st.extra = [];
    for (const layer of ctx.layers || []) if (st.layers[layer.id]) { try { st.extra.push(...await layer.load(r.from, to)); } catch { /* a layer that fails stays empty */ } }
    draw();
  }
  async function refresh() { try { await load(); } catch (e) { fail(e); } }

  // ---- writes, each with Undo ----------------------------------------------------------------------------------
  const undoable = (r, text) => { refresh(); if (r?.undo) snack(text, async () => { try { await client.undo(r.undo); refresh(); } catch (e) { fail(e); } }); };
  async function add(body, text = 'Added') { try { undoable(await client.add(body), text); } catch (e) { fail(e); } }
  async function change(o, body, verb = 'Change') {
    let scope = 'all', occurrence;
    if (o.recurring) { scope = await askScope(verb); if (!scope) return refresh(); occurrence = o.occurrence; }
    try { undoable(await client.patch(o.item_id, body, { occurrence, scope }), 'Changed'); } catch (e) { fail(e); refresh(); }
  }
  async function remove(o) {
    let scope = 'all', occurrence;
    if (o.recurring) { scope = await askScope('Delete'); if (!scope) return; occurrence = o.occurrence; }
    try { const r = await client.remove(o.item_id || o.id, { occurrence, scope }); undoable(r, r?.note ? 'Moved to the trash, kept 30 days' : 'Deleted'); } catch (e) { fail(e); }
  }
  async function toggleDone(o) {
    try { undoable(await client.done(o.item_id, o.recurring ? o.occurrence : undefined, o.done), o.done ? 'Marked not done' : 'Done'); } catch (e) { fail(e); }
  }

  // ---- open, edit ----------------------------------------------------------------------------------------------
  function open(o, anchor) {
    closePop();
    if (o.layer) { o.open?.(); return; }
    pop = popover(o, anchor, { close: closePop, edit: x => { closePop(); edit(x); }, done: x => { closePop(); toggleDone(x); }, remove: x => { closePop(); remove(x); } });
    document.body.append(pop);
  }
  async function edit(o, slot) {
    closeOverlay();
    let item = null;
    if (o) { try { item = await client.item(o.item_id || o.id); } catch (e) { return fail(e); } }
    const f = fieldsOf(item ? { ...item, ...(o?.recurring ? { start: o.start, end: o.end, due: o.due } : {}) } : null, slot || {});
    if (!f.calendar) f.calendar = (st.calendars.find(c => c.is_default) || st.calendars[0])?.id;
    if (!item && !f.alerts.length && st.settings) f.alerts = [...(f.kind === 'todo' ? st.settings.todo_alerts : st.settings.event_alerts)];
    overlay = sheet(f, { calendars: st.calendars, projects: st.projects, settings: st.settings, close: closeOverlay, parse: client.parse, extra: ctx.sheetExtra ? x => ctx.sheetExtra(x, item) : null,
      save: async body => { closeOverlay(); if (item) await change(o, body, 'Change'); else await add(body, body.kind === 'todo' ? 'To-do added' : 'Event added'); },
      remove: async () => { closeOverlay(); await remove(o); } });
    page.append(overlay);
  }

  // ---- the header ------------------------------------------------------------------------------------------------
  function header() {
    const seg = el('div.cal-seg', { role: 'group', 'aria-label': 'View' }, ...VIEWS.map(([k, l, key]) => el('button', { 'aria-pressed': String(st.view === k), title: `${l} (${key})`, onclick: () => setView(k) }, l)));
    const quick = el('input.cal-input', { 'data-keep': 'quick', placeholder: 'Add: lunch w/ Sam Fri 1pm · remind me to call the bank at 10', 'aria-label': 'Quick add' });
    const prev = el('div.cal-preview', { style: { display: 'none' } });
    let parsed = null, t = 0;
    quick.addEventListener('input', () => {
      clearTimeout(t);
      const text = quick.value.trim();
      if (!text) { prev.style.display = 'none'; parsed = null; return; }
      t = setTimeout(async () => {
        try { parsed = await client.parse(text); prev.replaceChildren(el('b', null, previewText(parsed)), parsed.assumed?.length ? el('div', null, 'Assumed: ', parsed.assumed.join(', ')) : null, el('div', null, 'Enter to add · Esc to clear')); }
        catch (e) { parsed = null; prev.replaceChildren(el('span', null, e?.detail || 'Couldn’t read a date or time')); }
        prev.style.display = 'block';
      }, 220);
    });
    quick.addEventListener('keydown', async e => {
      if (e.key === 'Escape') { quick.value = ''; prev.style.display = 'none'; quick.blur(); return; }
      if (e.key !== 'Enter' || !quick.value.trim()) return;
      let p = parsed;
      if (!p) { try { p = await client.parse(quick.value.trim()); } catch (err) { return fail(err); } }
      const body = { kind: p.kind, title: p.title || quick.value.trim(), rrule: p.rrule || undefined, ...(p.kind === 'todo' ? { due: p.due } : { start: p.start, end: p.end }) };
      quick.value = ''; prev.style.display = 'none'; parsed = null;
      await add(body, `Added: ${previewText(p)}`);
      const d = parse(p.start || p.due || '');
      if (!isNaN(d) && !inView(d)) { st.date = d; save(); refresh(); }
    });
    const search = el('input.cal-input', { 'data-keep': 'search', type: 'search', placeholder: 'Search', 'aria-label': 'Search the calendar', value: st.q, style: { width: '160px' } });
    search.addEventListener('input', () => { clearTimeout(search.t); search.t = setTimeout(async () => { st.q = search.value.trim(); st.results = st.q ? (await client.search(st.q)).items : null; drawBody(); }, 200); });
    const menu = el('button.cal-btn.icon.ghost', { 'aria-label': 'More', title: 'Import, export, trash, plan a day, settings', onclick: e => openMenu(e.currentTarget) }, icon(I.menu));
    return el('div.cal-head', null,
      el('div.cal-hrow', null,
        el('button.cal-btn.icon.ghost.cal-sidebtn', { 'aria-label': 'Show the calendars', 'aria-expanded': String(st.side), onclick: () => { st.side = !st.side; draw(); } }, icon(I.menu)),
        el('button.cal-btn', { onclick: () => { st.date = now(); save(); refresh(); }, title: 'Today (t)' }, 'Today'),
        el('button.cal-btn.icon.ghost', { onclick: () => go(-1), 'aria-label': 'Previous', title: 'Previous (j)' }, icon(I.left)),
        el('button.cal-btn.icon.ghost', { onclick: () => go(1), 'aria-label': 'Next', title: 'Next (k)' }, icon(I.right)),
        el('h1.cal-title', null, titleOf(st.view, st.date, st.settings?.week_start || 0)),
        el('span', { style: { flex: '1' } }), seg,
        el('button.cal-btn.pri', { onclick: () => edit(null, defaultSlot()), title: 'New (n)' }, icon(I.plus, 14), 'New'), menu),
      el('div.cal-hrow', null, el('div.cal-quick', null, quick, prev), search));
  }
  const inView = d => { const r = rangeOf(st.view, st.date, st.settings?.week_start || 0); return d >= r.from && d < r.to; };
  const defaultSlot = () => { const d = new Date(st.date), n = now(); d.setHours(sameDay(d, n) ? n.getHours() + 1 : 9, 0, 0, 0); return { start: wall(d), end: wall(new Date(d.getTime() + 3600000)) }; };
  function openMenu(anchor) {
    closePop();
    const r = anchor.getBoundingClientRect(), item = (label, d, fn) => el('button.cal-btn.ghost', { style: { justifyContent: 'flex-start', width: '100%' }, onclick: () => { closePop(); fn(); } }, icon(d, 14), label);
    pop = el('div.cal-pop', { style: { left: `${Math.max(8, r.right - 240)}px`, top: `${r.bottom + 6}px`, width: '240px', gap: '2px' } },
      item('Plan my day', I.clock, planDay), item('Import an .ics file…', I.upload, () => openImport()),
      el('a.cal-btn.ghost', { href: client.exportUrl(), download: 'gaifa-calendar.ics', style: { justifyContent: 'flex-start', width: '100%', textDecoration: 'none' }, onclick: closePop }, icon(I.download, 14), 'Export everything as .ics'),
      item('Trash', I.trash, async () => { closeOverlay(); overlay = await trashSheet({ client, restored: refresh, close: closeOverlay }); page.append(overlay); }),
      item('Settings', I.gear, () => ctx.navigate?.('#/s/calendar')));
    document.body.append(pop);
  }
  function openImport(file) {
    closeOverlay();
    overlay = importSheet({ client, calendars: st.calendars, close: closeOverlay, done: r => { closeOverlay(); undoable(r, `Added ${r.added}`); } }, file);
    page.append(overlay);
  }
  async function planDay() {
    try {
      const p = await client.plan(ymd(st.view === 'day' ? st.date : now()));
      closeOverlay();
      overlay = el('div.cal-sheet', { role: 'dialog', 'aria-label': 'Plan my day' },
        el('div', { style: { display: 'flex', alignItems: 'center', gap: '8px', padding: '12px 16px', borderBottom: '1px solid var(--cal-line)' } }, el('strong', { style: { flex: 1 } }, 'Plan my day'), el('button.cal-btn.icon.ghost', { onclick: closeOverlay, 'aria-label': 'Close' }, icon(I.x, 14))),
        el('div.bd', null, el('div.cal-muted', null, p.items.length ? 'Open to-dos placed in your free working time. Tick the blocks to add.' : 'Nothing to place: no open to-dos fit today’s free working time.'),
          proposalList(p, { calendars: st.calendars, accept: async b => { closeOverlay(); undoable(await client.accept(p.id, b), 'Day planned'); } })));
      page.append(overlay);
    } catch (e) { fail(e); }
  }
  function go(n) { st.date = step(st.view, st.date, n); st.agendaDays = 30; save(); refresh(); }
  function setView(v) { st.view = v; st.agendaDays = 30; save(); refresh(); }

  // ---- the left column -------------------------------------------------------------------------------------------
  function side() {
    const col = el('aside.cal-side', { class: st.side ? 'open' : '', 'aria-label': 'Calendars and lists' });
    col.append(mini());
    col.append(el('div.cal-sec', null, el('h3', null, el('span', null, 'Calendars'), el('button.cal-btn.icon.ghost', { style: { width: '22px', height: '22px' }, 'aria-label': 'New calendar', onclick: newCalendar }, icon(I.plus, 13))),
      ...st.calendars.map(c => el('div.cal-row', { onclick: async () => { try { await client.patchCalendar(c.id, { hidden: !c.hidden }); refresh(); } catch (e) { fail(e); } } },
        el('button.cal-check', { role: 'checkbox', 'aria-checked': String(!c.hidden), 'aria-label': `Show ${c.name}`, style: { borderColor: c.color, background: c.hidden ? 'transparent' : c.color } }),
        el('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, c.name), c.is_default ? el('span.cal-muted.cal-small', null, 'default') : null))));
    const layers = (ctx.layers || []).length ? LAYERS.filter(([id]) => (ctx.layers || []).some(l => l.id === id)) : [];
    if (layers.length) col.append(el('div.cal-sec', null, el('h3', null, el('span', null, 'Layers')),
      ...layers.map(([id, label]) => el('div.cal-row', { onclick: () => { st.layers[id] = !st.layers[id]; save(); refresh(); } },
        el('button.cal-check', { role: 'checkbox', 'aria-checked': String(!!st.layers[id]), 'aria-label': label }), el('span', null, label)))));
    const open = st.todos.filter(t => !t.done).slice(0, 12);
    col.append(el('div.cal-sec', null, el('h3', null, el('span', null, 'To-dos'), el('button.cal-btn.icon.ghost', { style: { width: '22px', height: '22px' }, 'aria-label': 'New to-do', onclick: () => edit(null, { kind: 'todo', start: ymd(st.date), all_day: true }) }, icon(I.plus, 13))),
      ...(open.length ? open.map(t => el('div.cal-row', { title: t.overdue ? 'Overdue' : '' },
        el('button.cal-check', { role: 'checkbox', 'aria-checked': 'false', 'aria-label': `Done: ${t.title}`, onclick: e => { e.stopPropagation(); toggleDone(t); } }),
        el('span', { style: { flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }, onclick: e => open1(t, e.currentTarget) }, t.title),
        el('span.cal-small', { style: { color: t.overdue ? 'var(--rd,#F85149)' : 'var(--mut,#8A94A6)', flex: 'none' } }, t.ts ? dueWords(t) : ''))) : [el('div.cal-muted', { style: { padding: '0 6px' } }, 'Nothing open.')])));
    const rem = st.alerts.filter(a => a.state === 'unread' || a.state === 'snoozed').slice(0, 8);
    col.append(el('div.cal-sec', null, el('h3', null, icon(I.bell, 12), el('span', null, `Reminders${st.unread ? ` · ${st.unread}` : ''}`),
      st.unread ? el('button.cal-btn.ghost', { style: { height: '22px', padding: '0 6px', fontSize: '11px' }, onclick: async () => { await client.seenAll(); refresh(); } }, 'Seen all') : null),
      ...(rem.length ? rem.map(a => el('div', { style: { padding: '4px 6px', borderRadius: '6px', background: a.state === 'unread' ? 'var(--cal-soft)' : 'transparent', display: 'flex', flexDirection: 'column', gap: '3px' } },
        el('div', { style: { fontWeight: a.state === 'unread' ? 600 : 400, fontSize: '12.5px' } }, a.title), el('div.cal-muted.cal-small', null, a.state === 'snoozed' ? 'snoozed' : a.body),
        el('div', { style: { display: 'flex', gap: '4px' } }, ...[['seen', 'Seen'], ['snooze', '10 min'], ...(a.kind === 'todo' ? [['done', 'Done']] : [])].map(([act, l]) =>
          el('button.cal-btn', { style: { height: '22px', padding: '0 7px', fontSize: '11px' }, onclick: async () => { try { await client.alert(a.id, act, act === 'snooze' ? 10 : undefined); refresh(); } catch (e) { fail(e); } } }, l))))) : [el('div.cal-muted', { style: { padding: '0 6px' } }, 'None waiting.')])));
    return col;
  }
  const open1 = (t, anchor) => open({ ...t, id: t.id || t.item_id }, anchor);
  const dueWords = t => { const d = new Date(t.ts * 1000), n = now(); return sameDay(d, n) ? (t.all_day ? 'today' : timeText(t).replace('Due ', '')) : sameDay(d, addDays(n, 1)) ? 'tomorrow' : `${MONTHS[d.getMonth()].slice(0, 3)} ${d.getDate()}`; };
  async function newCalendar() {
    const name = prompt('A name for the new calendar');
    if (!name?.trim()) return;
    try { await client.addCalendar({ name: name.trim() }); refresh(); } catch (e) { fail(e); }
  }
  function mini() {
    const ws = st.settings?.week_start || 0, m = rangeOf('month', st.date, ws), sel = rangeOf(st.view === 'agenda' ? 'day' : st.view, st.date, ws), n = now();
    const box = el('div.cal-sec');
    box.append(el('h3', null, el('span', null, `${MONTHS[st.date.getMonth()]} ${st.date.getFullYear()}`),
      el('button.cal-btn.icon.ghost', { style: { width: '22px', height: '22px' }, 'aria-label': 'Previous month', onclick: () => { st.date = step('month', st.date, -1); save(); refresh(); } }, icon(I.left, 13)),
      el('button.cal-btn.icon.ghost', { style: { width: '22px', height: '22px' }, 'aria-label': 'Next month', onclick: () => { st.date = step('month', st.date, 1); save(); refresh(); } }, icon(I.right, 13))));
    box.append(el('div.cal-mini', null, ...Array.from({ length: 7 }, (_, i) => el('div.wd', null, WEEKDAYS[(i + ws) % 7][0])),
      ...m.days.map(d => el('button', { class: [d.getMonth() !== st.date.getMonth() ? 'out' : '', d >= sel.from && d < sel.to ? 'in' : '', sameDay(d, n) ? 'today' : '', sameDay(d, st.date) ? 'sel' : ''].join(' '),
        'aria-label': d.toDateString(), onclick: () => { st.date = d; save(); refresh(); } }, d.getDate()))));
    return box;
  }

  // ---- the view --------------------------------------------------------------------------------------------------
  let bodyHost = null;
  function drawBody() {
    if (!bodyHost) return;
    const r = rangeOf(st.view, st.date, st.settings?.week_start || 0), occs = [...st.occs, ...st.extra];
    const on = { open, create: slot => edit(null, slot), day: d => { st.date = d; st.view = 'day'; save(); refresh(); },
      move: (o, start, end) => o.layer ? refresh() : change(o, { start, end }, 'Move'), more: () => { st.agendaDays += 30; refresh(); } };
    let view;
    if (st.results) view = renderAgenda({ from: new Date(2000, 0, 1), to: new Date(2100, 0, 1), occs: st.results.map(searchOcc), now: now(), on: { ...on, open: (o, a) => { st.date = new Date(o.ts * 1000); st.q = ''; st.results = null; save(); refresh().then(() => open(o, a)); }, more: () => {} } });
    else if (st.view === 'month') view = renderMonth({ days: r.days, month: st.date, occs, settings: st.settings, now: now(), on });
    else if (st.view === 'agenda') view = renderAgenda({ from: r.from, to: addDays(r.from, st.agendaDays), occs, now: now(), on });
    else view = renderGrid({ days: r.days, occs, settings: st.settings, now: now(), on });
    bodyHost.replaceChildren(view);
    const key = `${st.view}|${ymd(r.from)}`, sc = view.querySelector('.cal-scroll');
    if (sc) {
      if (st.scroll?.key === key && st.scroll.top != null) sc.scrollTop = st.scroll.top;   // a refresh keeps where you were
      else {
        st.scroll = { key, top: null };
        if (sc.clientHeight > 0 && sc.scrollHeight > sc.clientHeight) { view.scrollToStart?.(); st.scroll = { key, top: sc.scrollTop }; }   // laid out already
        else { const ro = new ResizeObserver(() => {   // once the grid has its height (the host lays it out later)
          if (!sc.isConnected) return ro.disconnect();
          if (sc.clientHeight > 0 && sc.scrollHeight > sc.clientHeight) { ro.disconnect(); view.scrollToStart?.(); st.scroll = { key, top: sc.scrollTop }; }
        });
        ro.observe(sc); }
      }
      sc.addEventListener('scroll', () => { st.scroll = { key, top: sc.scrollTop }; }, { passive: true });
    }
  }
  const searchOcc = it => ({ ...it, item_id: it.id, occurrence: it.start || it.due, ts: parse(it.start || it.due || ymd(now())).getTime() / 1000, end: it.end, recurring: !!it.rrule });
  function draw() {
    closePop();
    // a redraw (a refresh, a change elsewhere) keeps what's typed in quick add and search, and the focus
    const keep = [...page.querySelectorAll('[data-keep]')].map(n => ({ k: n.dataset.keep, v: n.value, f: document.activeElement === n, s: n.selectionStart }));
    const main = el('div.cal-main');
    bodyHost = el('div', { style: { flex: '1', minHeight: '0', display: 'flex', flexDirection: 'column' } });
    main.append(header(), bodyHost);
    page.replaceChildren(side(), main);
    if (overlay) page.append(overlay);
    for (const x of keep) {
      const n = page.querySelector(`[data-keep="${x.k}"]`);
      if (!n) continue;
      if (x.v && !n.value) { n.value = x.v; n.dispatchEvent(new Event('input')); }
      if (x.f) { n.focus(); try { n.setSelectionRange(x.s, x.s); } catch { /* search inputs */ } }
    }
    drawBody();
  }

  // ---- keys, drops, following changes ----------------------------------------------------------------------------
  const onKey = e => {
    const a = keyAction(e);
    if (!a || !page.isConnected) return;
    if (a.kind === 'escape') { if (pop) closePop(); else if (overlay) closeOverlay(); else if (st.side) { st.side = false; draw(); } return; }
    e.preventDefault();
    if (a.kind === 'view') setView(a.view);
    else if (a.kind === 'today') { st.date = now(); save(); refresh(); }
    else if (a.kind === 'step') go(a.n);
    else if (a.kind === 'new') edit(null, defaultSlot());
    else if (a.kind === 'search') page.querySelector('input[type=search]')?.focus();
  };
  const onDoc = e => { if (pop && !pop.contains(e.target) && !e.target.closest?.('.cal-ev,.cal-bar,.cal-chip,.cal-arow,.cal-todo,.cal-row,.cal-pop')) closePop(); };
  page.addEventListener('dragover', e => { if ([...(e.dataTransfer?.types || [])].includes('Files')) e.preventDefault(); });
  page.addEventListener('drop', e => { const f = e.dataTransfer?.files?.[0]; if (f && /\.ics$/i.test(f.name)) { e.preventDefault(); openImport(f); } });
  document.addEventListener('keydown', onKey);
  document.addEventListener('pointerdown', onDoc, true);
  const poll = async () => {
    if (!alive) return;
    if (!document.hidden) { try { const s = await client.status(); if (s.rev !== st.rev) await load(); } catch { /* the mod restarting */ } }
    timer = setTimeout(poll, 10000);
  };
  const offs = ['notification', 'badge'].map(t => ctx.on?.(t, ev => { if (ev.service === 'calendar') refresh(); }));

  (async () => {
    try { st.settings = await client.settings(); } catch { st.settings = null; }
    if (!store?.get('calendar.view', null) && st.settings?.default_view) st.view = st.settings.default_view;
    try { st.projects = (await ctx.projects?.()) || []; } catch { st.projects = []; }
    const want = ctx.params?.item;
    if (want && want.includes('@')) { const d = parse(want.split('@')[1]); if (!isNaN(d)) st.date = d; }
    await refresh();
    if (want) { const o = st.occs.find(x => x.id === want || x.item_id === want); if (o) open(o, page.querySelector(`[data-occ="${CSS.escape(o.id)}"]`)); }
    timer = setTimeout(poll, 10000);
  })();

  return () => { alive = false; clearTimeout(timer); document.removeEventListener('keydown', onKey); document.removeEventListener('pointerdown', onDoc, true); offs.forEach(f => f?.()); closePop(); };
}

export { dow, startOfDay };
