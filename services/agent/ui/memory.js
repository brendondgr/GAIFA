// The agent's Memory tab and the memory part of Review (plan structured-memory 5.1). Memory is entries in a tree
// (you, projects, people, places, tools, topics, organizations) and the facts about them; a fact is replaced, never
// overwritten, and every change can be undone. What the agent learned on its own is saved when it's sure and the
// user said it (listed in Review under "Learned on its own"); the rest waits in Review with the reason
// (memory-auto-learning 2.3).
// The data is this mod's /v1/memory/… routes.

const KIND_LABEL = { user: 'You', project: 'Projects', person: 'People', place: 'Places', tool: 'Tools', topic: 'Topics', organization: 'Organizations' };
const SOURCE = { stated: 'you said', inferred: 'learned', imported: 'imported' };
const enc = encodeURIComponent;

/** Group proposals by the chat they came from (the first evidence with a thread). */
export function byChat(facts) {
  const out = new Map();
  for (const f of facts) {
    const t = (f.evidence || []).find(e => e.thread)?.thread || '';
    if (!out.has(t)) out.set(t, []);
    out.get(t).push(f);
  }
  return [...out.entries()].map(([thread, items]) => ({ thread, items }));
}

/** What a proposal does when approved, in words. */
export function actionText(f) {
  const a = (f.evidence || []).find(e => e.action);
  if (!a) return f.replaces ? 'replaces an older fact' : '';
  return { rename: `renames it to ${a.to}`, merge: 'merges the two entries', retire: 'stops remembering that fact' }[a.action] || '';
}

/** Why a proposal waits for you (memory-auto-learning 2.1), from its newest evidence: "sensitive: health", "not sure: 0.55". */
export function whyText(f) {
  const ev = [...(f.evidence || [])].reverse().find(e => e.why);
  return ev ? ev.why : '';
}

/** The words a fact came from, if the learner kept them. */
export function quoteOf(f) {
  return [...(f.evidence || [])].reverse().find(e => e.quote)?.quote || '';
}

/** Flatten the tree into rows with their depth, for drawing. */
export function treeRows(tree) {
  const out = [];
  const walk = (e, depth) => { out.push({ ...e, depth }); (e.children || []).forEach(c => walk(c, depth + 1)); };
  for (const k of tree.kinds || []) {
    out.push({ heading: KIND_LABEL[k.kind] || k.kind, kind: k.kind });
    k.entities.forEach(e => walk(e, 0));
  }
  return out;
}

export function memoryTab(ctx, put, fail, render) {
  const { ui } = ctx, h = ui.h;
  const call = (m, p, o) => ctx.call(m, p, o).then(r => { if (r.status >= 400) throw r.json || { detail: `HTTP ${r.status}` }; return r.json; });
  const state = memoryTab.state || (memoryTab.state = { sel: 'user', q: '' });
  const when = ts => (ts ? new Date(ts * 1000).toLocaleDateString() : '');
  const act = (fn, done) => async () => { try { await fn(); if (done) ctx.toast(done, 'success'); render(); } catch (e) { fail(e); } };

  function factRow(f, { history = false } = {}) {
    const edit = h('div', { style: 'display:none;gap:6px;align-items:center' });
    const box = ui.input({ value: f.text });
    box.style.flex = '1';
    edit.append(box, ui.button('Save', act(() => call('PATCH', `/v1/memory/facts/${f.id}`, { json: { text: box.value } }), 'Saved'), { kind: 'primary', small: true }),
      ui.button('Cancel', () => { edit.style.display = 'none'; shown.style.display = 'flex'; }, { small: true, kind: 'ghost' }));
    const shown = h('div', { style: 'display:flex;gap:8px;align-items:flex-start' },
      h('div', { style: 'flex:1;min-width:0;display:flex;flex-direction:column;gap:3px' },
        h('div', { style: `font-size:13px;overflow-wrap:anywhere${history ? ';text-decoration:line-through;opacity:.7' : ''}` }, f.text),
        h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;align-items:center' },
          ui.badge(f.kind, f.kind === 'preference' ? 'accent' : 'dim'),
          ui.badge(`${SOURCE[f.source] || f.source} ${when(f.recorded)}`, f.source === 'stated' ? 'green' : 'dim'),
          ui.text([f.valid_from && `from ${f.valid_from}`, f.valid_until && `until ${f.valid_until}`,
            f.seen > 1 && `said ${f.seen}×`, f.entities.filter(e => e.id !== state.sel).map(e => e.path).join(', ')].filter(Boolean).join(' · '), { small: true, muted: true }))),
      history ? null : ui.button('Edit', () => { shown.style.display = 'none'; edit.style.display = 'flex'; }, { small: true, kind: 'ghost' }),
      ui.button('Forget', async () => {
        if (!(await ctx.confirm({ title: 'Forget this for good?', body: f.text, danger: true }))) return;
        act(() => call('DELETE', `/v1/memory/facts/${f.id}`), 'Forgotten')();
      }, { small: true, kind: 'ghost' }));
    return h('div', { style: 'padding:8px 0;border-top:1px solid var(--bd,#1D2430)' }, shown, edit);
  }

  function entityView(e) {
    const title = h('h2', { style: 'margin:0;font-size:16px' }, e.id === 'user' ? 'You' : e.name);
    const rename = ui.input({ value: e.name });
    const renameRow = h('div', { style: 'display:none;gap:6px' }, rename,
      ui.button('Rename', act(() => call('PATCH', `/v1/memory/entities/${e.id}`, { json: { name: rename.value } }), 'Renamed: the old name stays an alias'), { kind: 'primary', small: true }));
    const alias = ui.input({ placeholder: 'Another name it goes by' });
    const summary = ui.textarea({ value: e.summary || '', rows: 2, placeholder: 'One sentence on what it is' });
    summary.style.flex = '1';
    return ui.card(
      h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, title, ui.badge(e.path, 'dim'),
        h('span', { style: 'flex:1' }),
        e.id === 'user' ? null : ui.button('Rename', () => { renameRow.style.display = renameRow.style.display === 'none' ? 'flex' : 'none'; }, { small: true })),
      renameRow,
      e.id === 'user' ? null : h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;align-items:center' },
        ui.text('Also called:', { small: true, muted: true }),
        ...(e.aliases.length ? e.aliases.map(a => h('span', { style: 'display:inline-flex;gap:2px;align-items:center' }, ui.badge(a, 'dim'),
          ui.button('×', act(() => call('PATCH', `/v1/memory/entities/${e.id}`, { json: { aliases_remove: [a] } })), { small: true, kind: 'ghost' })))
          : [ui.text('nothing else', { small: true, muted: true })]),
        alias, ui.button('Add', act(() => call('PATCH', `/v1/memory/entities/${e.id}`, { json: { aliases_add: [alias.value] } })), { small: true })),
      e.anchors.length ? ui.text('Anchored to ' + e.anchors.map(a => `${a.kind} ${a.value}`).join(', '), { small: true, muted: true }) : null,
      e.id === 'user' ? null : h('div', { style: 'display:flex;gap:6px;align-items:flex-end' }, summary,
        ui.button('Save', act(() => call('PATCH', `/v1/memory/entities/${e.id}`, { json: { summary: summary.value } }), 'Saved'), { small: true })),
      h('div', null, h('strong', { style: 'font-size:13px' }, `What you know (${e.facts.length})`),
        ...(e.facts.length ? e.facts.map(f => factRow(f)) : [ui.text('Nothing yet.', { muted: true })])),
      e.proposed.length ? ui.text(`${e.proposed.length} more wait in Review.`, { small: true, muted: true }) : null,
      e.children.length ? h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;align-items:center' }, ui.text('Inside it:', { small: true, muted: true }),
        ...e.children.map(c => ui.button(c.name, () => { state.sel = c.id; render(); }, { small: true }))) : null,
      e.history.length ? h('details', null, h('summary', { style: 'cursor:pointer;font-size:12.5px' }, `Earlier (${e.history.length}): replaced or ended`),
        ...e.history.map(f => factRow(f, { history: true }))) : null,
      e.log.length ? h('details', null, h('summary', { style: 'cursor:pointer;font-size:12.5px' }, 'History'),
        ...e.log.slice(0, 30).map(l => h('div', { style: 'display:flex;gap:8px;align-items:center;padding:4px 0;font-size:12px' },
          h('span', { style: 'flex:1;min-width:0' }, l.summary || l.op), ui.text(`${l.by} · ${new Date(l.ts * 1000).toLocaleString()}`, { small: true, muted: true }),
          ['undo', 'forget', 'fact_kept'].includes(l.op) ? null : ui.button('Undo', act(() => call('POST', `/v1/memory/undo/${l.id}`), 'Undone'), { small: true, kind: 'ghost' })))) : null);
  }

  function newMemory() {
    const text = ui.input({ placeholder: 'A fact, as one sentence ("Prefers 16:9 images")' });
    const about = ui.input({ placeholder: 'About (names or paths, comma-separated; empty: you)' });
    const kind = ui.select(['fact', 'preference', 'event', 'procedure'], { value: 'fact' });
    text.style.flex = '2';
    about.style.flex = '1';
    return ui.card(h('strong', null, 'Remember something'), h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap' }, text, about, kind,
      ui.button('Save', act(() => call('POST', '/v1/memory/facts', { json: { text: text.value, kind: kind.value,
        about: about.value.split(',').map(s => s.trim()).filter(Boolean) } }), 'Remembered'), { kind: 'primary' })));
  }

  async function searchResults(q) {
    const r = await call('GET', '/v1/memory/search', { query: { q } });
    return ui.card(h('strong', null, `Found for “${q}”`),
      ...(r.entities || []).map(e => ui.button(`${e.path}${e.aliases.length ? ` (also ${e.aliases.join(', ')})` : ''}`, () => { state.sel = e.id; state.q = ''; render(); }, { small: true })),
      ...(r.facts.length ? r.facts.map(f => h('div', { style: 'padding:6px 0;border-top:1px solid var(--bd,#1D2430);font-size:13px' }, f.text,
        ui.text(f.about.join(', '), { small: true, muted: true }))) : [ui.text(r.entities?.length ? 'No facts.' : 'Nothing matches.', { muted: true })]),
      r.meaning ? null : ui.text('Searched by names and words only: the Embeddings mod isn’t running.', { small: true, muted: true }));
  }

  return async function memory() {
    const [tree, e] = await Promise.all([call('GET', '/v1/memory/tree'), call('GET', `/v1/memory/entities/${enc(state.sel)}`).catch(() => null)]);
    if (!e) { state.sel = 'user'; return render(); }
    const search = ui.input({ value: state.q, placeholder: 'Search memory (names, words, meaning)' });
    search.style.flex = '1';
    search.addEventListener('keydown', ev => { if (ev.key === 'Enter') { state.q = search.value.trim(); render(); } });
    const side = h('nav', { style: 'flex:0 0 220px;display:flex;flex-direction:column;gap:2px;min-width:0' },
      ...treeRows(tree).map(r => r.heading
        ? h('div', { style: 'font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--mut,#8A94A6);margin-top:10px' }, r.heading)
        : h('button', { type: 'button', onclick: () => { state.sel = r.id; state.q = ''; render(); },
          style: `text-align:left;border:0;border-radius:6px;padding:4px 8px 4px ${8 + r.depth * 14}px;font:inherit;font-size:12.5px;cursor:pointer;` +
            `background:${r.id === state.sel ? 'var(--inset,#131926)' : 'transparent'};color:var(--tx,#E6EAF2);display:flex;gap:6px` },
          h('span', { style: 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap' }, r.kind === 'user' ? 'You' : r.name),
          h('span', { style: 'color:var(--mut,#8A94A6)' }, String(r.facts)))));
    put(
      h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' },
        ui.text('What the agent knows about you and your work. Each entry keeps its old names, so a rename never loses anything; every change can be undone.', { muted: true }),
        h('span', { style: 'flex:1' }), tree.proposed ? ui.badge(`${tree.proposed} to review`, 'accent') : null),
      h('div', { style: 'display:flex;gap:6px' }, search, ui.button('Search', () => { state.q = search.value.trim(); render(); })),
      state.q ? await searchResults(state.q) : null,
      h('div', { style: 'display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap' }, side,
        h('div', { style: 'flex:1 1 420px;min-width:0;display:flex;flex-direction:column;gap:12px' }, entityView(e), newMemory())));
  };
}

/** The memory proposals for the Review tab, grouped by the chat they came from. */
export async function memoryReview(ctx, fail, render) {
  const { ui } = ctx, h = ui.h;
  const call = (m, p, o) => ctx.call(m, p, o).then(r => { if (r.status >= 400) throw r.json || { detail: `HTTP ${r.status}` }; return r.json; });
  const [facts, learned] = await Promise.all([call('GET', '/v1/memory/facts', { query: { state: 'proposed' } }),
    call('GET', '/v1/memory/auto', { query: { days: 14 } }).catch(() => [])]);
  const decide = (f, state, label, kind) => ui.button(label, async () => {
    try { await call('PATCH', `/v1/memory/facts/${f.id}`, { json: { state } }); render(); } catch (e) { fail(e); }
  }, { kind, small: true });
  const row = f => {
    const box = ui.input({ value: f.text });
    box.style.flex = '1';
    const edit = h('div', { style: 'display:none;gap:6px' }, box,
      ui.button('Approve as edited', async () => {
        try { await call('PATCH', `/v1/memory/facts/${f.id}`, { json: { text: box.value, state: 'active' } }); render(); } catch (e) { fail(e); }
      }, { kind: 'primary', small: true }));
    return h('div', { style: 'padding:8px 0;border-top:1px solid var(--bd,#1D2430);display:flex;flex-direction:column;gap:4px' },
      h('div', { style: 'display:flex;gap:8px;align-items:flex-start' },
        h('div', { style: 'flex:1;min-width:0' }, h('div', { style: 'font-size:13px;overflow-wrap:anywhere' }, f.text),
          ui.text([f.entities.map(e => e.path).join(', '), f.kind, actionText(f)].filter(Boolean).join(' · '), { small: true, muted: true }),
          whyText(f) ? ui.badge(`waiting: ${whyText(f)}`, 'accent') : null),
        decide(f, 'active', 'Approve', 'primary'),
        ui.button('Edit', () => { edit.style.display = edit.style.display === 'none' ? 'flex' : 'none'; }, { small: true }),
        decide(f, 'rejected', 'Not this', 'ghost')),
      edit);
  };
  const keep = f => ui.button('Keep', async () => {
    try { await call('POST', `/v1/memory/facts/${f.id}/keep`); render(); } catch (e) { fail(e); }
  }, { small: true });
  const learnedRow = f => h('div', { style: 'padding:8px 0;border-top:1px solid var(--bd,#1D2430);display:flex;gap:8px;align-items:flex-start' },
    h('div', { style: 'flex:1;min-width:0' }, h('div', { style: 'font-size:13px;overflow-wrap:anywhere' }, f.text),
      ui.text([f.entities.map(e => e.path).join(', '), f.kind, `saved ${new Date(f.auto_at * 1000).toLocaleDateString()}`,
        quoteOf(f) && `you said “${quoteOf(f)}”`].filter(Boolean).join(' · '), { small: true, muted: true })),
    keep(f), decide(f, 'rejected', 'Not this', 'ghost'));
  const learnedCard = learned.length ? ui.card(
    h('div', { style: 'display:flex;gap:8px;align-items:center' },
      h('strong', { style: 'font-size:13px' }, `Learned on its own (${learned.length})`),
      ui.text('in the last 14 days; already in use. Not this takes one back.', { small: true, muted: true }),
      h('span', { style: 'flex:1' }),
      learned.length > 1 ? ui.button('Keep all', async () => {
        try { for (const f of learned) await call('POST', `/v1/memory/facts/${f.id}/keep`); render(); } catch (e) { fail(e); }
      }, { small: true }) : null),
    ...learned.map(learnedRow)) : null;
  const groups = byChat(facts);
  return [
    ...(learnedCard ? [learnedCard] : []),
    h('strong', { style: 'font-size:13px' }, groups.length ? `Needs your look (${facts.length})` : 'Needs your look'),
    ui.text('What the agent learned but wasn’t sure enough about, or that is personal. Nothing here is used until you approve it.', { muted: true }),
    ...(groups.length ? groups.map(g => ui.card(
      h('div', { style: 'display:flex;gap:8px;align-items:center' },
        g.thread ? h('a', { href: `#/chat/${g.thread}`, style: 'font-size:13px;font-weight:500' }, 'From this chat') : h('strong', null, 'Not from a chat (tidying, or added here)'),
        h('span', { style: 'flex:1' }),
        g.items.length > 1 ? ui.button('Approve all', async () => {
          try { for (const f of g.items) await call('PATCH', `/v1/memory/facts/${f.id}`, { json: { state: 'active' } }); render(); } catch (e) { fail(e); }
        }, { small: true }) : null),
      ...g.items.map(row)))
      : [ui.empty('No memories to review', 'After a chat goes quiet, what you said there that is worth keeping shows up here.')]),
  ];
}
