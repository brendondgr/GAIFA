// The web mod's page (plan 30.8): Read a page. A URL → the hub's POST /api/web/read: this mod fetches the page and
// saves it as an output, the hub screens all of its text for instructions aimed at an AI (Settings → Agent's
// screening model) and keeps the report, so the agent's reads of it reuse it. Shows the markdown rendered (as the
// agent reads it, or as it was), what screening removed and why, Copy markdown and Open in Outputs.
// Only ctx is used (and the chat's Markdown renderer).

import { renderMarkdown, MD_CSS, installCopy } from '/chat/chat-md.js';

const CELL = 'padding:6px 10px;border-bottom:1px solid var(--bd,#1D2430);text-align:left;font-size:12.5px;vertical-align:top';
const CSS = MD_CSS + `
.aichat-md .web-removed{padding:4px 9px;border-radius:6px;border:1px dashed var(--acct,#FFB224);color:var(--acct,#FFB224);font-size:12px}`;

function style(doc) {
  if (doc.getElementById('gaifa-web-md')) return;
  const s = doc.createElement('style');
  s.id = 'gaifa-web-md';
  s.textContent = CSS;
  doc.head.append(s);
}

/** The rendered markdown, with each removal line marked. */
export function render(text) {
  return renderMarkdown(text).replace(/<p>\[removed by screening: ([^\]<]*)\]<\/p>/g, '<p class="web-removed">Removed by screening: $1</p>');
}

/** [label, tone] for the screening badge. */
export function screeningLabel(s) {
  if (!s) return ['not screened (off in Settings → Agent)', 'dim'];
  if (s.removed) return [`${s.removed} passage${s.removed === 1 ? '' : 's'} removed`, 'accent'];
  if (s.checked !== 'patterns+model') return ['patterns only: the screening model didn’t answer', 'accent'];
  return ['nothing aimed at an AI found', 'green'];
}

async function copy(ctx, text) {
  try { await navigator.clipboard.writeText(text); ctx.toast('Markdown copied', 'success'); } catch { ctx.toast('Couldn’t copy (the browser refused)', 'error'); }
}

function result(ctx, r) {
  const { ui } = ctx;
  const s = r.screening;
  let showScreened = true;
  const body = ui.h('div', { class: 'aichat-md', style: 'font-size:13px;max-height:70vh;overflow:auto;padding:4px 2px' });
  const draw = () => { body.innerHTML = render(showScreened ? r.screened : r.markdown); };
  const which = ui.select([{ value: 'screened', label: 'As the agent reads it' }, { value: 'original', label: 'As it was' }],
    { value: 'screened', onchange: ev => { showScreened = ev.target.value === 'screened'; draw(); } });
  draw();
  const [label, tone] = screeningLabel(s);
  const found = s && s.findings.length ? ui.h('div', { style: 'overflow:auto;max-width:100%' }, ui.h('table', { style: 'border-collapse:collapse;width:100%' },
    ui.h('thead', null, ui.h('tr', null, ['Line', 'Why', 'By', 'The passage began'].map(c => ui.h('th', { style: CELL + ';color:var(--mut,#8A94A6);font-weight:500' }, c)))),
    ui.h('tbody', null, s.findings.map(f => ui.h('tr', null,
      ui.h('td', { style: CELL }, ui.text(String(f.line), { mono: true })), ui.h('td', { style: CELL }, f.why),
      ui.h('td', { style: CELL }, f.by), ui.h('td', { style: CELL }, ui.text(f.excerpt, { mono: true }))))))) : null;
  return ui.card(
    ui.h('h2', { style: 'margin:0;font-size:15px' }, r.title || r.final_url),
    ui.text(r.final_url, { muted: true, mono: true }),
    ui.row(ui.badge(label, tone), ui.text(`${r.chars.toLocaleString()} characters` + (s ? ` · screened in ${(s.ms / 1000).toFixed(1)} s` + (s.model ? ` by ${s.model}` : '') : '')
      + (s && s.covered < r.chars ? ` · the first ${s.covered.toLocaleString()} screened now, the rest as the agent reads it` : ''), { muted: true })),
    found,
    ui.row(ui.button('Copy markdown', () => copy(ctx, showScreened ? r.screened : r.markdown), { small: true }),
      ui.button('Open in Outputs', () => ctx.navigate(`#/outputs/${r.output.id}`), { small: true, kind: 'ghost' }),
      ui.field('Show', which)),
    body);
}

function reader(el, ctx) {
  const { ui } = ctx;
  const out = ui.h('div', { style: 'display:flex;flex-direction:column;gap:14px;min-width:0' });
  const url = ui.input({ placeholder: 'https://…', type: 'url' });
  url.style.flex = '1';
  let busy = false;
  const go = async () => {
    const u = url.value.trim();
    if (!u || busy) return;
    busy = true;
    btn.disabled = true;
    out.replaceChildren(ui.text('Reading the page and screening it…', { muted: true }));
    try {
      const r = await ctx.api.readWebPage(u, { text: true });
      out.replaceChildren(result(ctx, r));
    } catch (e) {
      out.replaceChildren(ui.empty('Couldn’t read the page', `${e.detail || e.message || e}${e.data && e.data.fix ? ` (${e.data.fix})` : ''}`, null));
    } finally {
      busy = false;
      btn.disabled = false;
    }
  };
  const btn = ui.button('Read', go, { kind: 'primary' });
  url.addEventListener('keydown', ev => { if (ev.key === 'Enter') go(); });
  el.append(ui.card(
    ui.h('h2', { style: 'margin:0;font-size:15px' }, 'Read a page'),
    ui.text('The page is saved as an output (markdown, or a PDF document) and screened whole for instructions aimed at an AI, '
      + 'as the agent would read it. Public http(s) pages only; robots.txt is honoured. In Chat, paste a link or use the '
      + 'attach menu to give a page to the agent.', { muted: true }),
    ui.row(url, btn)), out);
  url.focus();
}

export default {
  tabs: [{ id: 'read', label: 'Read a page', icon: 'search' }],

  mount(el, ctx) {
    style(document);
    installCopy(document);
    if (ctx.service.state !== 'ready' && ctx.service.state !== 'degraded') {   // the shared box: Set up, Turn on or Start (mod-off.js)
      import('/mod-kit.js').then(k => k.requireRunning(el, ctx, 'Read a page'));
      return;
    }
    reader(el, ctx);
  },
};
