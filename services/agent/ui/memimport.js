// Importing another assistant's memory on the Memory tab (plan memory-import 2.1). Three steps in one card:
// 1. the prompt to paste into the other assistant (Copy), 2. its answer pasted back, 3. the preview, entry by entry,
// with what each fact would do and a choice per fact (Save, Review, Skip; the agent's default and its reason), then
// Save. A saved import can be undone as a whole, here or from the Imports list. Claude's export file can be chosen
// instead of pasting (3.1), and Export shows the memory in the same format (3.2).
// The data is this mod's /v1/memory/imports routes (api_imports.py).

export const FROM = { chatgpt: 'ChatGPT', claude: 'Claude', gemini: 'Gemini', other: 'another assistant' };
const SECTION = { instructions: 'Instructions', identity: 'Identity', career: 'Career', projects: 'Projects', preferences: 'Preferences' };
const CHOICES = [['save', 'Save'], ['review', 'Review'], ['skip', 'Skip']];
const STATE = { reading: 'reading…', ready: 'not saved yet', saved: 'saved', undone: 'undone', failed: 'failed' };

/** The evidence that says a fact came from an import ({import, from, line, …}), or null. */
export function importOf(f) {
  return (f.evidence || []).find(e => e.import) || null;
}

/** The preview's entries grouped by section, in the order they came: [{ label, lines }]. */
export function sections(lines) {
  const out = new Map();
  for (const li of lines) {
    const label = SECTION[li.section] || (li.section ? li.section[0].toUpperCase() + li.section.slice(1) : 'Other');
    if (!out.has(label)) out.set(label, []);
    out.get(label).push(li);
  }
  return [...out.entries()].map(([label, items]) => ({ label, lines: items }));
}

/** Each fact's choice: the person's pick, else the preview's default. */
export function choicesOf(lines, picks = {}) {
  const out = {};
  for (const li of lines) for (const f of li.facts) out[f.key] = picks[f.key] || f.choice;
  return out;
}

/** How many facts each choice holds now, and how many are already known. */
export function countsOf(lines, picks = {}) {
  const c = { save: 0, review: 0, skip: 0, same: 0, unread: 0 };
  const ch = choicesOf(lines, picks);
  for (const li of lines) {
    if (li.error) c.unread++;
    for (const f of li.facts) {
      if (f.op === 'same') c.same++;
      else c[ch[f.key]]++;
    }
  }
  return c;
}

/** What a fact does beside being new, in words. */
export function opText(f) {
  if (f.op === 'same') return 'already known';
  if (f.op === 'replaces' && f.held) return `replaces: ${f.held.text}`;
  return '';
}

/** A saved import's outcome, in words. */
export function savedText(s) {
  return [`Imported ${s.saved}`, s.review && `${s.review} wait in Review`, s.same && `${s.same} already known`,
    s.skipped && `${s.skipped} skipped`, s.failed && `${s.failed} couldn’t be saved`].filter(Boolean).join(' · ');
}

export function importCard(ctx, fail, render) {
  const { ui } = ctx, h = ui.h;
  const call = (m, p, o) => ctx.call(m, p, o).then(r => { if (r.status >= 400) throw r.json || { detail: `HTTP ${r.status}` }; return r.json; });
  const st = importCard.state || (importCard.state = { open: false, id: null, source: 'chatgpt', text: '', picks: {}, imp: null, timer: null, prompt: null });
  const reset = () => Object.assign(st, { id: null, text: '', picks: {}, imp: null });

  function ask() {
    const box = h('pre', { style: 'margin:0;max-height:150px;overflow:auto;white-space:pre-wrap;font-size:12px;line-height:1.5;padding:10px 12px;border-radius:8px;background:var(--inset,#131926);border:1px solid var(--bd,#1D2430)' }, st.prompt || '');
    const from = ui.select(Object.entries(FROM).map(([value, label]) => ({ value, label: value === 'other' ? 'Other' : label })),
      { value: st.source, onchange: e => { st.source = e.target.value; } });
    const answer = ui.textarea({ value: st.text, rows: 8, placeholder: 'Paste the whole answer here, code block and all', oninput: e => { st.text = e.target.value; } });
    return [
      h('div', { style: 'display:flex;flex-direction:column;gap:6px' },
        h('strong', { style: 'font-size:13px' }, '1. Ask your other assistant'),
        ui.text('Copy this, send it in a new chat there, and copy its whole answer. ChatGPT also shows its saved memories in Settings → Personalization → Manage memories; Claude in Settings → Your Claude.', { small: true, muted: true }),
        box,
        h('div', null, ui.button('Copy the prompt', async () => {
          try { await navigator.clipboard.writeText(st.prompt || ''); ctx.toast('Copied', 'success'); } catch { ctx.toast('Select the text and copy it', 'error'); }
        }, { small: true }))),
      h('div', { style: 'display:flex;flex-direction:column;gap:6px' },
        h('strong', { style: 'font-size:13px' }, '2. Paste its answer'),
        answer,
        h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, ui.text('From', { small: true, muted: true }), from,
          h('span', { style: 'flex:1' }),
          ui.button('Read it', async () => {
            try { const r = await call('POST', '/v1/memory/imports', { json: { text: st.text, source: st.source } }); st.id = r.id; st.imp = r; render(); } catch (e) { fail(e); }
          }, { kind: 'primary' }))),
      h('div', { style: 'display:flex;flex-direction:column;gap:6px' },
        h('strong', { style: 'font-size:13px' }, 'Or choose Claude’s export file'),
        ui.text('Claude → Settings → Privacy → Export data emails a zip; choose it (the first one, if there are several) or the memories.json inside. ChatGPT’s export holds only your chats, so use the prompt for ChatGPT.', { small: true, muted: true }),
        h('input', { type: 'file', accept: '.zip,.json,application/zip,application/json', style: 'font-size:12.5px', onchange: e => readFile(e.target.files?.[0]) })),
      ui.text('Nothing is saved until you look at what it found and press Save.', { small: true, muted: true }),
    ];
  }

  function readFile(file) {
    if (!file) return;
    const r = new FileReader();
    r.onload = async () => {
      try {
        const data = String(r.result).split(',', 2)[1] || '';
        const imp = await call('POST', '/v1/memory/imports/file', { json: { name: file.name, data, source: 'claude' } });
        st.id = imp.id; st.imp = imp; render();
      } catch (e) { fail(e); }
    };
    r.onerror = () => fail({ detail: 'The file couldn’t be read' });
    r.readAsDataURL(file);
  }

  function chooser(f, redraw) {
    const now = st.picks[f.key] || f.choice;
    return h('div', { style: 'display:flex;gap:2px;flex:0 0 auto' }, ...CHOICES.map(([c, label]) =>
      ui.button(label, () => { st.picks[f.key] = c; redraw(); }, { small: true, kind: c === now ? (c === 'skip' ? 'secondary' : 'primary') : 'ghost' })));
  }

  function factRow(f, redraw) {
    const op = opText(f), skipped = (st.picks[f.key] || f.choice) === 'skip' && f.op !== 'same';
    return h('div', { style: 'display:flex;gap:8px;align-items:flex-start;padding:4px 0 4px 12px' },
      h('div', { style: `flex:1;min-width:0;display:flex;flex-direction:column;gap:3px${skipped ? ';opacity:.5' : ''}` },
        h('div', { style: 'font-size:13px;overflow-wrap:anywhere' }, f.text),
        h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;align-items:center' },
          ui.badge(f.kind, f.kind === 'preference' ? 'accent' : 'dim'),
          f.about.length ? ui.text(f.about.join(', '), { small: true, muted: true }) : null,
          op ? ui.badge(op, f.op === 'same' ? 'green' : 'dim') : null,
          f.why && f.op !== 'same' && (st.picks[f.key] || f.choice) === 'review' ? ui.badge(`waits: ${f.why}`, 'accent') : null)),
      f.op === 'same' ? null : chooser(f, redraw));
  }

  function preview(redraw) {
    const imp = st.imp, lines = imp.lines || [];
    const c = countsOf(lines, st.picks);
    const all = (sec, choice) => e => { e?.preventDefault?.(); for (const li of sec.lines) for (const f of li.facts) if (f.op !== 'same') st.picks[f.key] = choice; redraw(); };
    return [
      h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' },
        h('strong', { style: 'font-size:13px' }, `3. What it found in ${imp.total} entries from ${FROM[imp.source] || imp.source}`),
        h('span', { style: 'flex:1' }),
        ui.button('Start over', () => { reset(); render(); }, { small: true, kind: 'ghost' })),
      ui.text([`${c.save} to save`, c.review && `${c.review} to Review`, c.skip && `${c.skip} skipped`, c.same && `${c.same} already known`,
        c.unread && `${c.unread} ${c.unread === 1 ? 'entry' : 'entries'} it couldn’t read`].filter(Boolean).join(' · '), { muted: true }),
      ...sections(lines).map(sec => h('details', { open: true, style: 'border-top:1px solid var(--bd,#1D2430);padding-top:6px' },
        h('summary', { style: 'cursor:pointer;display:flex;gap:8px;align-items:center;font-size:13px;font-weight:600' },
          `${sec.label} (${sec.lines.length})`, h('span', { style: 'flex:1' }),
          ui.text('All:', { small: true, muted: true }),
          ...CHOICES.map(([ch, label]) => ui.button(label, all(sec, ch), { small: true, kind: 'ghost' }))),
        ...sec.lines.map(li => h('div', { style: 'padding:6px 0;display:flex;flex-direction:column;gap:2px' },
          ui.text(`${li.date || 'no date'} · ${li.text}`, { small: true, muted: true }),
          li.error ? h('div', { style: 'padding-left:12px' }, ui.badge(li.error, 'red')) : null,
          li.entity ? h('div', { style: 'padding-left:12px' }, ui.text(`Entry: ${li.entity.name}${li.entity.aliases.length ? ` (also ${li.entity.aliases.join(', ')})` : ''}`, { small: true, muted: true })) : null,
          ...li.facts.map(f => factRow(f, redraw)))))),
      h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' },
        h('span', { style: 'flex:1' }),
        ui.button(c.review ? `Save ${c.save}, send ${c.review} to Review` : `Save ${c.save}`, async () => {
          try {
            st.imp = await call('POST', `/v1/memory/imports/${st.id}/save`, { json: { choices: choicesOf(lines, st.picks) } });
            ctx.toast(savedText(st.imp.saved), 'success'); render();
          } catch (e) { fail(e); }
        }, { kind: 'primary' })),
    ];
  }

  function done() {
    const s = st.imp.saved || {};
    return [
      h('strong', { style: 'font-size:13px' }, savedText(s)),
      ui.text('Saved facts are in use now. The ones waiting are on Review, each with the reason.', { small: true, muted: true }),
      h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' },
        s.review ? h('a', { href: '#/s/agent/review', style: 'text-decoration:none' }, ui.button('Review →', null, { small: true })) : null,
        ui.button('Undo import', () => undo(st.id), { small: true, kind: 'danger' }),
        ui.button('Import more', () => { reset(); render(); }, { small: true }),
        ui.button('Close', () => { reset(); st.open = false; render(); }, { small: true, kind: 'ghost' })),
    ];
  }

  async function undo(id) {
    if (!(await ctx.confirm({ title: 'Undo this import?', body: 'What it added is taken out, and what it replaced comes back. Facts you changed since stay.', danger: true }))) return;
    try {
      const r = await call('DELETE', `/v1/memory/imports/${id}`);
      ctx.toast(`Undone: ${r.undone.undone} facts` + (r.undone.kept ? `; ${r.undone.kept} you changed since were kept` : ''), 'success');
      if (st.id === id) reset();
      render();
    } catch (e) { fail(e); }
  }

  async function list() {
    const rows = await call('GET', '/v1/memory/imports', { query: { limit: 20 } }).catch(() => []);
    if (!rows.length) return null;
    return h('details', null, h('summary', { style: 'cursor:pointer;font-size:12.5px' }, `Imports (${rows.length})`),
      ...rows.map(r => h('div', { style: 'display:flex;gap:8px;align-items:center;padding:4px 0;font-size:12.5px;flex-wrap:wrap' },
        h('span', { style: 'flex:1;min-width:0' }, `${new Date(r.made * 1000).toLocaleDateString()} · ${FROM[r.source] || r.source} · ${r.total} entries · ${STATE[r.state] || r.state}`
          + (r.state === 'saved' && r.saved ? ` · ${savedText(r.saved)}` : r.state === 'failed' && r.error ? `: ${r.error}` : '')),
        r.state === 'ready' || r.state === 'reading' ? ui.button('Open', () => { reset(); st.id = r.id; st.open = true; render(); }, { small: true }) : null,
        r.state === 'saved' ? ui.button('Undo', () => undo(r.id), { small: true, kind: 'ghost' }) : null)));
  }

  /** The import card (null while closed) and the Imports list, for the Memory tab. */
  return async function draw() {
    clearTimeout(st.timer);
    const history = await list();
    if (!st.open) return { card: null, history };
    if (st.prompt == null) st.prompt = (await call('GET', '/v1/memory/imports/prompt').catch(() => ({ prompt: '' }))).prompt;
    if (st.id) st.imp = await call('GET', `/v1/memory/imports/${st.id}`).catch(e => { fail(e); reset(); return null; });
    const card = ui.card();
    const redraw = () => card.replaceChildren(...body(redraw).flat().filter(Boolean));
    const body = r => {
      const head = h('div', { style: 'display:flex;gap:8px;align-items:center' }, h('h2', { style: 'margin:0;font-size:15px' }, 'Import memories from another assistant'),
        h('span', { style: 'flex:1' }), ui.button('×', () => { st.open = false; render(); }, { small: true, kind: 'ghost' }));
      const imp = st.imp;
      if (!imp) return [head, ...ask()];
      if (imp.state === 'reading') {
        st.timer = setTimeout(render, 2500);
        return [head, ui.text(`Reading ${imp.done} of ${imp.total} entries with the agent’s model… (about a minute per 20)`, { muted: true }),
          ui.text('You can leave this page; it keeps going, and Imports below opens it again.', { small: true, muted: true })];
      }
      if (imp.state === 'failed') return [head, ui.badge(`It couldn’t read it: ${imp.error || 'unknown error'}`, 'red'), ui.button('Start over', () => { reset(); render(); }, { small: true })];
      if (imp.state === 'saved') return [head, ...done()];
      if (imp.state === 'undone') { reset(); return [head, ...ask()]; }
      return [head, ...preview(r)];
    };
    redraw();
    return { card, history };
  };
}

/** Your memory as text in the prompt's format (plan memory-import 3.2), to copy or download and paste into another
 * assistant (Claude: Settings → Your Claude → Start import) or another GAIFA. */
export async function exportCard(ctx, fail, close) {
  const { ui } = ctx, h = ui.h;
  const r = await ctx.call('GET', '/v1/memory/export');
  if (r.status >= 400) { fail(r.json || { detail: `HTTP ${r.status}` }); return null; }
  const { text, count } = r.json;
  const download = () => {
    const a = h('a', { href: URL.createObjectURL(new Blob([text], { type: 'text/markdown' })), download: `memory-${new Date().toISOString().slice(0, 10)}.md` });
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  return ui.card(
    h('div', { style: 'display:flex;gap:8px;align-items:center' }, h('h2', { style: 'margin:0;font-size:15px' }, `Export your memory (${count})`),
      h('span', { style: 'flex:1' }), ui.button('×', close, { small: true, kind: 'ghost' })),
    ui.text('What the agent holds now, in the same format the import prompt asks for: paste it into another assistant (Claude: Settings → Your Claude → Start import) or another GAIFA.', { small: true, muted: true }),
    count ? h('pre', { style: 'margin:0;max-height:260px;overflow:auto;white-space:pre-wrap;font-size:12px;line-height:1.5;padding:10px 12px;border-radius:8px;background:var(--inset,#131926);border:1px solid var(--bd,#1D2430)' }, text)
      : ui.text('Nothing saved yet.', { muted: true }),
    count ? h('div', { style: 'display:flex;gap:8px' },
      ui.button('Copy', async () => { try { await navigator.clipboard.writeText(text); ctx.toast('Copied', 'success'); } catch { ctx.toast('Select the text and copy it', 'error'); } }, { small: true, kind: 'primary' }),
      ui.button('Download .md', download, { small: true })) : null);
}
