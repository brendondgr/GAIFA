// The Workspace page (plan 27.7): Folders (add one, its level, "allow Bypass", remove), Activity
// (each chat's turns with their changed files and Undo, recent runs, checkpoint usage) and Sandbox
// (the image: built or not, Build, the log; recent runs). Uses only ctx (design brief §5).

import { panel, header, stat, fmtAgo, fmtBytes, requireRunning, MONO } from '/mod-kit.js';
import { h } from '/mod-ui.js';

const LEVELS = [
  ['read', 'Read', 'list, read, search, read-only git'],
  ['edit', 'Edit', 'also change files in place (checkpointed, undo per turn)'],
  ['run', 'Run', 'also run commands in the sandbox, no internet'],
  ['run_net', 'Run + network', 'the sandbox with full internet'],
];
const MUT = 'font-size:11.5px;color:var(--mut,#8A94A6)';
const ROW = 'display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:9px 0;border-bottom:1px solid var(--bd,#1D2430);min-width:0';
const tone = { done: 'green', timeout: 'red', cancelled: 'dim', error: 'red', running: 'accent' };

export default {
  tabs: [{ id: 'folders', label: 'Folders', icon: 'folder' }, { id: 'activity', label: 'Activity', icon: 'history' },
    { id: 'sandbox', label: 'Sandbox', icon: 'box' }],

  mount(el, ctx) {
    if (!requireRunning(el, ctx, 'the workspace folders')) return;
    if (ctx.tab === 'activity') return activity(el, ctx);
    if (ctx.tab === 'sandbox') return sandbox(el, ctx);
    return folders(el, ctx);
  },
};

const fail = (ctx, e) => ctx.toast(e.detail || e.message || String(e), 'error');

function folders(el, ctx) {
  const { ui } = ctx;
  const path = ui.input({ placeholder: '/home/you/Projects/my-app', name: 'path', 'aria-label': 'Folder path' });
  path.style.flex = '1 1 320px';
  const list = h('div');
  el.append(h('div', { style: 'display:flex;flex-direction:column;gap:12px;max-width:980px' },
    panel(header('Add a folder'),
      ui.text('The agent can read a folder you add here, and nothing else on your machine. New folders start at Read; raise one to let the agent edit in place or run code. The AIHub folder and its models stay at Read.', { muted: true, small: true }),
      h('form', { style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:center', onsubmit: async e => {
        e.preventDefault();
        if (!path.value.trim()) return;
        try { await ctx.call('POST', '/v1/folders', { json: { path: path.value.trim() } }); path.value = ''; ctx.toast('Added at Read', 'success'); draw(); }
        catch (err) { fail(ctx, err); }
      } }, path, ui.button('Add folder', null, { kind: 'primary', type: 'submit' }))),
    panel(header('Folders', ui.button('Refresh', () => draw(), { small: true })),
      h('div', { style: MUT }, LEVELS.map(([, w, d]) => `${w}: ${d}`).join(' · ')), list)));

  async function patch(f, body) {
    try { await ctx.call('PATCH', `/v1/folders/${encodeURIComponent(f.id)}`, { json: body }); draw(); }
    catch (e) { fail(ctx, e); draw(); }
  }

  function row(f) {
    const level = ui.select(LEVELS.filter(([k]) => LEVELS.findIndex(x => x[0] === k) <= LEVELS.findIndex(x => x[0] === f.max_level))
      .map(([k, w]) => ({ value: k, label: w })), { value: f.level, onchange: e => patch(f, { level: e.target.value }) });
    level.setAttribute('aria-label', `Level of ${f.id}`);
    const bypass = h('input', { type: 'checkbox', checked: !!f.allow_bypass, disabled: f.level === 'read', 'aria-label': `Allow Bypass in ${f.id}`,
      onchange: e => patch(f, { allow_bypass: e.target.checked }) });
    return h('div', { style: ROW },
      h('div', { style: 'flex:1 1 300px;min-width:0;display:flex;flex-direction:column;gap:2px' },
        h('span', { style: 'font-size:13px;font-weight:600' }, f.name || f.id, h('span', { style: `font-weight:400;font-family:${MONO};font-size:11px;color:var(--dim,#5E6878)` }, `  ${f.id}`)),
        h('span', { style: `${MUT};font-family:${MONO};overflow-wrap:anywhere` }, f.path),
        f.capped ? h('span', { style: MUT }, `Capped at ${f.max_level === 'read' ? 'Read' : f.max_level}: ${f.capped}`) : null,
        !f.exists ? h('span', { style: 'font-size:11.5px;color:var(--rd,#F85149)' }, 'This folder no longer exists') : null),
      level,
      h('label', { style: 'display:flex;align-items:center;gap:6px;font-size:12px', title: 'Offer the Bypass chat mode in this folder: edits and sandbox commands run without asking (your machine still asks)' },
        bypass, 'allow Bypass'),
      ui.button('Remove', async () => {
        if (!(await ctx.confirm({ title: `Remove ${f.id}?`, body: 'The agent can no longer use it. Its files are left alone.', danger: true }))) return;
        try { await ctx.call('DELETE', `/v1/folders/${encodeURIComponent(f.id)}`); draw(); } catch (e) { fail(ctx, e); }
      }, { small: true }));
  }

  async function draw() {
    try {
      const fs = (await ctx.call('GET', '/v1/folders')).json.folders || [];
      list.replaceChildren(...(fs.length ? fs.map(row) : [ui.text('No folders yet. Add one above.', { muted: true })]));
    } catch (e) { list.replaceChildren(ui.text(e.detail || 'Could not read the folders', { muted: true })); }
  }
  draw();
}

function activity(el, ctx) {
  const { ui } = ctx;
  const body = h('div', { style: 'display:flex;flex-direction:column;gap:12px;max-width:980px' });
  el.append(body);
  const chat = t => (t.thread && t.thread !== '_direct' ? h('a', { href: `#/chat/${encodeURIComponent(t.thread)}`, style: 'font-size:12px' }, 'Open chat →') : h('span', { style: MUT }, 'not from a chat'));

  async function undo(t) {
    try {
      const r = await ctx.call('POST', `/v1/checkpoints/${encodeURIComponent(t.thread)}/${encodeURIComponent(t.turn)}/undo`);
      ctx.toast(r.json?.detail || 'Undone', 'success');
    } catch (e) {
      const c = e.data?.data?.conflicts || e.data?.conflicts;
      if (c?.length) {
        await ctx.confirm({ title: 'Not undone: files changed since', body: c.map(x => `${x.folder}:${x.rel}: ${x.detail}\n${x.diff}`).join('\n\n').slice(0, 4000) });
      } else fail(ctx, e);
    }
    draw();
  }

  function turnRow(t) {
    return h('div', { style: ROW },
      h('div', { style: 'flex:1 1 320px;min-width:0;display:flex;flex-direction:column;gap:3px' },
        h('span', { style: 'font-size:12.5px' }, h('strong', null, `${t.changes} change${t.changes === 1 ? '' : 's'}`), ` · ${t.tools.join(', ')} · ${fmtAgo(t.updated_ts)}`),
        h('span', { style: `${MUT};font-family:${MONO};overflow-wrap:anywhere` }, t.files.map(f => `${f.folder}:${f.rel}`).join('  '))),
      chat(t),
      t.undone_ts ? ui.badge('undone', 'dim') : ui.button('Undo', () => undo(t), { small: true }));
  }

  function runRow(r) {
    return h('div', { style: ROW },
      h('div', { style: 'flex:1 1 320px;min-width:0;display:flex;flex-direction:column;gap:3px' },
        h('span', { style: `font-family:${MONO};font-size:12px;overflow-wrap:anywhere` }, r.command),
        h('span', { style: MUT }, [r.folder, r.where === 'host' ? 'on your machine' : r.network ? 'sandbox + internet' : 'sandbox',
          r.ms != null ? `${(r.ms / 1000).toFixed(1)} s` : null, fmtAgo(r.started)].filter(Boolean).join(' · '))),
      ui.badge(r.state === 'done' ? `exit ${r.exit_code}` : r.state, r.state === 'done' ? (r.exit_code === 0 ? 'green' : 'red') : tone[r.state]),
      r.thread ? chat(r) : null,
      r.state === 'running' ? ui.button('Stop', () => ctx.call('POST', `/v1/runs/${r.id}/cancel`).then(draw, e => fail(ctx, e)), { small: true }) : null);
  }

  async function draw() {
    let cps = { turns: [], usage: {} }, runs = [];
    try { cps = (await ctx.call('GET', '/v1/checkpoints')).json; } catch { /* shown empty */ }
    try { runs = (await ctx.call('GET', '/v1/runs', { query: { limit: 30 } })).json.runs || []; } catch { /* shown empty */ }
    const u = cps.usage || {};
    body.replaceChildren(
      panel(header('Checkpoints'), h('div', { style: 'display:flex;gap:24px;flex-wrap:wrap' },
        stat('Turns kept', String(u.turns ?? 0)), stat('Size', fmtBytes(u.bytes || 0)), stat('Kept for', `${u.keep_days ?? 14} days or ${fmtBytes(u.keep_bytes || 2e9)}`))),
      panel(header('Edits by turn', ui.button('Refresh', draw, { small: true })),
        ui.text('Every change the agent makes is saved first. Undo puts each file of a turn back as it was; it refuses if you changed a file since.', { muted: true, small: true }),
        h('div', null, ...(cps.turns.length ? cps.turns.map(turnRow) : [ui.text('No edits yet.', { muted: true })]))),
      panel(header('Recent runs'), h('div', null, ...(runs.length ? runs.map(runRow) : [ui.text('No runs yet.', { muted: true })]))));
  }
  draw();
  ctx.on('tool_call', ev => { if (String(ev.call?.tool || '').startsWith('workspace_') && ev.call?.status !== 'running') draw(); });
}

function sandbox(el, ctx) {
  const { ui } = ctx;
  const body = h('div', { style: 'display:flex;flex-direction:column;gap:12px;max-width:980px' });
  el.append(body);
  let timer = 0;

  async function draw() {
    let s;
    try { s = (await ctx.call('GET', '/v1/sandbox')).json; } catch (e) { body.replaceChildren(ui.text(e.detail || 'Could not read the sandbox', { muted: true })); return; }
    const state = s.building ? 'building…' : s.exists ? 'built' : s.podman ? 'not built' : 'podman missing';
    body.replaceChildren(
      panel(header('Sandbox image', s.podman ? ui.button(s.exists ? 'Rebuild' : 'Build', build, { kind: s.exists ? undefined : 'primary', small: true, disabled: s.building }) : null),
        h('div', { style: 'display:flex;gap:24px;flex-wrap:wrap' }, stat('State', state), stat('Image', s.image), stat('Id', s.id || '—'), stat('Size', s.size_mb ? `${s.size_mb} MB` : '—')),
        ui.text(`Commands run here: ${s.toolchain}. The folder is mounted at its own path; nothing else of your home is visible; no internet unless the folder is at Run + network and the call asks for it.`, { muted: true, small: true }),
        s.build_log_tail ? h('pre', { style: `margin:0;max-height:240px;overflow:auto;font-family:${MONO};font-size:11.5px;background:var(--inset,#131926);border-radius:7px;padding:8px;white-space:pre-wrap` }, s.build_log_tail) : null));
    if (s.building) timer = setTimeout(draw, 2000);
  }

  async function build() {
    try { await ctx.call('POST', '/v1/sandbox/build'); ctx.toast('Building the sandbox image (a few minutes)…', 'info'); } catch (e) { fail(ctx, e); }
    draw();
  }
  draw();
  return () => clearTimeout(timer);
}
