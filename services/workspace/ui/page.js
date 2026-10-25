// The Workspace page (plan 27.7, 33): Environments (named sets of folders: create, rename, delete; in each,
// add a folder, its level there, "allow Bypass", remove), Activity
// (each chat's turns with their changed files and Undo, recent runs, checkpoint usage) and Sandbox
// (the image: built or not, Build, the log; recent runs). Uses only ctx (design brief §5).

import { panel, header, stat, fmtAgo, fmtBytes, requireRunning, segmented, MONO } from '/mod-kit.js';
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
  tabs: [{ id: 'environments', label: 'Environments', icon: 'folder' }, { id: 'activity', label: 'Activity', icon: 'history' },
    { id: 'sandbox', label: 'Sandbox', icon: 'box' }],

  mount(el, ctx) {
    if (!requireRunning(el, ctx, 'the workspace folders')) return;
    if (ctx.tab === 'activity') return activity(el, ctx);
    if (ctx.tab === 'sandbox') return sandbox(el, ctx);
    return environments(el, ctx);           // also the old #/s/workspace/folders
  },
};

const fail = (ctx, e) => ctx.toast(e.detail || e.message || String(e), 'error');

// Environments (plan 34, after Claude's): named sets of folders a chat works in, each folder with its own
// level there. A chat picks one in its header; Default is what a chat without one uses.
function environments(el, ctx) {
  const { ui } = ctx;
  let envs = [], cur = 'default';
  const chips = h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;align-items:center' });
  const body = h('div', { style: 'display:flex;flex-direction:column;gap:12px' });
  const name = ui.input({ placeholder: 'Grants', name: 'env-name' });
  name.setAttribute('aria-label', 'New environment name');
  name.style.flex = '0 1 220px';
  el.append(h('div', { style: 'display:flex;flex-direction:column;gap:12px;max-width:980px' },
    panel(header('Environments'),
      ui.text('An environment is a set of folders the agent can use in a chat, each with its own level. Pick one under a chat’s message box (⌂), where you can also make one and add folders. New chats start in None (no folders). In a chat the agent can also ask to read a folder you name; you allow it in that chat, or add it here.', { muted: true, small: true }),
      chips,
      h('form', { style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:center', onsubmit: async e => {
        e.preventDefault();
        if (!name.value.trim()) return;
        try { const r = await ctx.call('POST', '/v1/environments', { json: { name: name.value.trim() } }); name.value = ''; cur = r.json.id; ctx.toast(`Created ${r.json.name}`, 'success'); draw(); }
        catch (err) { fail(ctx, err); }
      } }, name, ui.button('New environment', null, { type: 'submit', small: true }))),
    body));

  const envPath = (e, rest = '') => `/v1/environments/${encodeURIComponent(e.id)}${rest}`;
  async function patch(e, f, b) {
    try { await ctx.call('PATCH', envPath(e, `/folders/${encodeURIComponent(f.id)}`), { json: b }); } catch (err) { fail(ctx, err); }
    draw();
  }

  function row(e, f) {
    const level = ui.select(LEVELS.filter(([k]) => LEVELS.findIndex(x => x[0] === k) <= LEVELS.findIndex(x => x[0] === f.max_level))
      .map(([k, w]) => ({ value: k, label: w })), { value: f.level, onchange: ev => patch(e, f, { level: ev.target.value }) });
    level.setAttribute('aria-label', `Level of ${f.id} in ${e.name}`);
    const bypass = h('input', { type: 'checkbox', checked: !!f.allow_bypass, disabled: f.level === 'read', 'aria-label': `Allow Bypass in ${f.id}`,
      onchange: ev => patch(e, f, { allow_bypass: ev.target.checked }) });
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
        if (!(await ctx.confirm({ title: `Remove ${f.id} from ${e.name}?`, body: 'Chats in this environment can no longer use it. Its files are left alone.', danger: true }))) return;
        try { await ctx.call('DELETE', envPath(e, `/folders/${encodeURIComponent(f.id)}`)); draw(); } catch (err) { fail(ctx, err); }
      }, { small: true }));
  }

  function envPanel(e) {
    if (e.none) return panel(h('span', { style: 'font-size:14px;font-weight:600' }, e.name),   // plan 42.5: built in, nothing to change
      ui.text('No folders. A chat in None reads only the folders you allow in it when the agent asks; it can’t be renamed, deleted or given folders. New chats start here until you pick another environment.', { muted: true, small: true }));
    const path = ui.input({ placeholder: '/home/you/Projects/my-app', name: 'path' });
    path.setAttribute('aria-label', `Folder path to add to ${e.name}`);
    path.style.flex = '1 1 320px';
    const lvl = ui.select(LEVELS.map(([k, w]) => ({ value: k, label: w })), { value: 'read' });
    lvl.setAttribute('aria-label', 'Level of the new folder');
    lvl.style.flex = '0 0 auto';
    const rename = ui.button('Rename', async () => {
      const box = ui.input({ value: e.name, name: 'rename' });
      box.setAttribute('aria-label', `New name for ${e.name}`);
      const save = async () => {
        const v = box.value.trim();
        if (v && v !== e.name) { try { await ctx.call('PUT', envPath(e), { json: { name: v } }); } catch (err) { fail(ctx, err); } }
        draw();
      };
      box.onkeydown = ev => { if (ev.key === 'Enter') save(); if (ev.key === 'Escape') draw(); };
      title.replaceChildren(box, ui.button('Save', save, { small: true, kind: 'primary' }));
      box.focus();
    }, { small: true });
    const del = e.default ? null : ui.button('Delete', async () => {
      if (!(await ctx.confirm({ title: `Delete ${e.name}?`, body: 'Chats that use it go back to Default. The folders and their files are left alone.', danger: true }))) return;
      try { await ctx.call('DELETE', envPath(e)); cur = 'default'; draw(); } catch (err) { fail(ctx, err); }
    }, { small: true, kind: 'danger' });
    const title = h('div', { style: 'display:flex;align-items:center;gap:8px;flex:1;min-width:0' },
      h('span', { style: 'font-size:14px;font-weight:600' }, e.name), e.default ? ui.badge('default', 'dim') : null,
      h('span', { style: MUT }, `${e.folders.length} folder${e.folders.length === 1 ? '' : 's'}`));
    return panel(
      h('div', { style: 'display:flex;align-items:center;gap:8px;flex-wrap:wrap' }, title, rename, del),
      e.default ? ui.text('Chats without an environment, and chats whose environment was deleted, use this one.', { muted: true, small: true }) : null,
      h('form', { style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:center', onsubmit: async ev => {
        ev.preventDefault();
        if (!path.value.trim()) return;
        try { await ctx.call('POST', envPath(e, '/folders'), { json: { path: path.value.trim(), level: lvl.value } }); ctx.toast(`Added to ${e.name}`, 'success'); draw(); }
        catch (err) { fail(ctx, err); }
      } }, path, lvl, ui.button('Add folder', null, { kind: 'primary', type: 'submit', small: true })),
      h('div', { style: MUT }, LEVELS.map(([, w, d]) => `${w}: ${d}`).join(' · ') + '. The GAIFA folder and its models stay at Read.'),
      h('div', null, ...(e.folders.length ? e.folders.map(f => row(e, f)) : [ui.text('No folders yet. Add one above.', { muted: true })])));
  }

  async function draw() {
    try { envs = (await ctx.call('GET', '/v1/environments')).json.environments || []; }
    catch (e) { body.replaceChildren(ui.text(e.detail || 'Could not read the environments', { muted: true })); return; }
    if (!envs.some(e => e.id === cur)) cur = envs[0]?.id || 'default';
    chips.replaceChildren(segmented(envs.map(e => ({ value: e.id, label: `${e.name} (${e.folders.length})` })), cur, v => { cur = v; draw(); }, 'Environments'));
    const e = envs.find(x => x.id === cur);
    body.replaceChildren(...(e ? [envPanel(e)] : []));
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
