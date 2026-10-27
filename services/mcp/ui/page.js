// The MCP servers page (plan mcp-client 3.1). Servers: presets ready to add (Blender, 5.1), each server's state, its tools with a risk each and a switch,
// Approve (and what changed since the last approval), Start / Stop, Remove; Add a server. Import: what other apps on
// this machine already configure (names and commands, never secret values), each added unapproved.

const RISKS = ['read', 'write', 'generate', 'network', 'execute', 'destructive'];
const STATE = { approved: ['approved', 'green'], needs_approval: ['needs approval', 'accent'], changed: ['tools changed', 'red'] };
const SESSION = { running: 'green', stopped: 'dim', starting: 'accent', failed: 'red' };

/** "uvx --from 'a b' x" → ["uvx", "--from", "a b", "x"]: words, quotes kept together. */
export function splitArgs(s) {
  const out = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let m;
  while ((m = re.exec(s || ''))) out.push(m[1] ?? m[2] ?? m[3]);
  return out;
}

/** What changed in a server's tools since they were approved, in words. */
export function diffText(d) {
  if (!d) return '';
  const parts = [d.added?.length && `new: ${d.added.join(', ')}`, d.removed?.length && `gone: ${d.removed.join(', ')}`,
    d.changed?.length && `changed: ${d.changed.join(', ')}`].filter(Boolean);
  return parts.join(' · ') || 'the list changed';
}

export default {
  tabs: [{ id: 'servers', label: 'Servers', icon: 'layers' }, { id: 'import', label: 'Import', icon: 'copy' }],

  mount(el, ctx) {
    const { ui } = ctx, h = ui.h, svc = ctx.service;
    if (svc.state !== 'ready' && svc.state !== 'degraded') {
      el.append(ui.empty(`${svc.name} is not running`, 'Start it to add MCP servers and approve their tools.',
        ui.button(`Start ${svc.name}`, () => ctx.api.startService(svc.id).catch(e => ctx.toast(e.detail, 'error')), { kind: 'primary' })));
      return;
    }
    const body = h('div', { style: 'display:flex;flex-direction:column;gap:12px' });
    el.append(body);
    const put = (...kids) => body.replaceChildren(...kids.flat().filter(Boolean));
    const fail = e => ctx.toast(e.detail || e.message || 'Request failed', 'error');
    const call = (m, p, o) => ctx.call(m, p, o).then(r => { if (r.status >= 400) throw r.json || { detail: `HTTP ${r.status}` }; return r.json; });
    const open = new Set();                                  // servers whose tools are shown
    const looked = {};                                       // server → GET ?tools=true

    function toolTable(s, t) {
      const deny = new Set(s.deny || []);
      return h('div', { style: 'display:flex;flex-direction:column;gap:2px' }, ...t.tools.map(x => {
        const risk = ui.select(RISKS, { value: x.risk, onchange: e => call('PATCH', `/v1/servers/${s.id}`, { json: { risks: { ...(s.risks || {}), [x.name]: e.target.value } } }).then(render, fail) });
        const on = h('input', { type: 'checkbox', checked: !deny.has(x.name), title: 'Offered to chats',
          onchange: e => { const d = new Set(deny); e.target.checked ? d.delete(x.name) : d.add(x.name); call('PATCH', `/v1/servers/${s.id}`, { json: { deny: [...d] } }).then(render, fail); } });
        const flagged = (s.approved?.findings || []).filter(f => f.tool === x.name);
        return h('div', { style: 'display:flex;gap:10px;align-items:flex-start;padding:6px 0;border-top:1px solid var(--bd,#1D2430)' },
          on, h('div', { style: 'flex:1;min-width:0' },
            h('div', { style: 'font-size:13px;font-weight:500' }, `mcp_${s.id}_${x.name}`),
            ui.text(x.description || '', { small: true, muted: true }),
            ...flagged.map(f => ui.text(`Screening: ${f.why}${f.excerpt ? ` (“${f.excerpt}”)` : ''}`, { small: true }))),
          risk);
      }));
    }

    function serverCard(s) {
      const [label, tone] = STATE[s.approval.state] || [s.approval.state, 'dim'];
      const t = looked[s.id];
      const launch = s.transport === 'http' ? s.url : [s.command, ...(s.args || [])].join(' ');
      const look = ui.button(open.has(s.id) ? 'Hide tools' : 'Tools', async () => {
        if (open.has(s.id)) { open.delete(s.id); return render(); }
        try { looked[s.id] = await call('GET', `/v1/servers/${s.id}`, { query: { tools: true } }); open.add(s.id); render(); } catch (e) { fail(e); }
      }, { small: true });
      const approve = t && s.approval.state !== 'approved' ? ui.button(s.approval.state === 'changed' ? 'Approve the change' : `Approve ${t.tools.length} tools`, async () => {
        if (!(await ctx.confirm({ title: `Offer ${s.name}'s tools to your chats?`,
          body: 'Each call still goes through your permissions: reading runs, anything else asks first (Auto: the judge decides). A tool that runs code is "execute".' }))) return;
        try { await call('POST', `/v1/servers/${s.id}/approve`, { json: { hash: t.hash } }); delete looked[s.id]; open.delete(s.id); render(); ctx.toast('Approved', 'success'); } catch (e) { fail(e); }
      }, { kind: 'primary', small: true }) : null;
      const env = Object.entries(s.env || {});
      return ui.card(
        h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' },
          h('strong', null, s.name), ui.badge(s.id, 'dim'), ui.badge(label, tone),
          ui.badge(s.session.state, SESSION[s.session.state] || 'dim'), s.enabled ? null : ui.badge('off', 'dim'),
          h('span', { style: 'flex:1' }),
          s.session.state === 'running' ? ui.button('Stop', () => call('POST', `/v1/servers/${s.id}/stop`).then(render, fail), { small: true })
            : ui.button('Start', () => call('POST', `/v1/servers/${s.id}/start`).then(render, fail), { small: true }),
          look, approve,
          ui.button(s.enabled ? 'Turn off' : 'Turn on', () => call('PATCH', `/v1/servers/${s.id}`, { json: { enabled: !s.enabled } }).then(render, fail), { small: true, kind: 'ghost' }),
          ui.button('Remove', async () => {
            if (!(await ctx.confirm({ title: `Remove ${s.name}?`, body: 'Its tools leave your chats. Add it again any time.', danger: true }))) return;
            call('DELETE', `/v1/servers/${s.id}`).then(render, fail);
          }, { small: true, kind: 'ghost' })),
        ui.text(launch, { small: true, mono: true, muted: true }),
        s.description ? ui.text(s.description, { small: true, muted: true }) : null,
        env.length ? ui.text('Environment: ' + env.map(([k, v]) => `${k}=${v}`).join('  '), { small: true, mono: true, muted: true }) : null,
        s.session.error ? ui.text(`Didn't start: ${s.session.error}`, { small: true }) : null,
        s.approval.state === 'changed' ? ui.text(`Its tools changed since you approved them (${diffText(s.approval.diff)}): they're held until you look and approve again.`, { small: true }) : null,
        open.has(s.id) && t ? toolTable(s, t) : null);
    }

    function addForm() {
      const id = ui.input({ placeholder: 'blender' }), name = ui.input({ placeholder: 'Blender' });
      const kind = ui.select([{ value: 'stdio', label: 'A program (stdio)' }, { value: 'http', label: 'A URL (Streamable HTTP)' }], { value: 'stdio' });
      const cmd = ui.input({ placeholder: 'uvx mcp-for-blender   or   https://host/mcp' });
      const env = ui.input({ placeholder: 'NAME=value or NAME=${SECRET}, comma-separated' });
      cmd.style.minWidth = '320px';
      return ui.card(h('strong', null, 'Add a server'),
        ui.text('Secrets go in services/mcp/.env; write them here as ${NAME}. Its tools wait until you approve them.', { small: true, muted: true }),
        h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end' },
          ui.field('Id', id), ui.field('Name', name), ui.field('Kind', kind), ui.field('Command or URL', cmd), ui.field('Environment', env),
          ui.button('Add', async () => {
            const words = splitArgs(cmd.value.trim()), http = kind.value === 'http';
            const vars = Object.fromEntries(env.value.split(',').map(x => x.trim()).filter(Boolean).map(x => [x.split('=')[0].trim(), x.slice(x.indexOf('=') + 1).trim()]));
            const json = { id: id.value.trim(), name: name.value.trim(), transport: kind.value, env: vars,
              ...(http ? { url: cmd.value.trim() } : { command: words[0], args: words.slice(1) }) };
            try { await call('POST', '/v1/servers', { json }); render(); ctx.toast('Added: look at its tools, then approve them', 'success'); } catch (e) { fail(e); }
          }, { kind: 'primary' })));
    }

    function presetRow(presets) {
      const todo = presets.filter(p => !p.added);
      return todo.length ? ui.card(h('strong', null, 'Ready to add'), ...todo.map(p => h('div', { style: 'display:flex;gap:10px;align-items:center;flex-wrap:wrap' },
        h('div', { style: 'flex:1;min-width:0' }, h('strong', { style: 'font-size:13px' }, p.name), ui.text(p.available ? p.description : `Can't run here: ${p.why}`, { small: true, muted: true })),
        ui.button(`Add ${p.name}`, async () => {
          try { await call('POST', `/v1/presets/${p.id}`); ctx.toast(`Added ${p.name}: press Tools, look, then approve`, 'success'); render(); } catch (e) { fail(e); }
        }, { small: true, kind: 'primary', disabled: !p.available })))) : null;
    }

    async function servers() {
      const [rows, presets] = await Promise.all([call('GET', '/v1/servers'), call('GET', '/v1/presets').catch(() => [])]);
      put(ui.text('Other MCP servers whose tools your chats can use. A server\'s tools reach your chats only after you approve them, and if they change, they wait until you look again.', { muted: true }),
        presetRow(presets),
        rows.length ? rows.map(serverCard) : ui.empty('No servers yet', 'Add one below, or import what other apps here already use.'),
        addForm());
    }

    async function imports() {
      const { found } = await call('GET', '/v1/import');
      put(ui.text('MCP servers that Claude Code, Codex, Cursor, Claude Desktop, Gemini CLI, VS Code and your workspace folders\' project files configure. Only names and commands are read: an imported server names its variables as ${NAME}, for you to put in services/mcp/.env.', { muted: true }),
        found.length ? ui.card(...found.map(e => h('div', { style: 'display:flex;gap:10px;align-items:center;padding:6px 0;border-top:1px solid var(--bd,#1D2430);flex-wrap:wrap' },
          h('div', { style: 'flex:1;min-width:0' }, h('strong', { style: 'font-size:13px' }, e.name), ' ', ui.badge(e.app, 'dim'),
            ui.text(`${e.transport === 'http' ? e.url : [e.command, ...e.args].join(' ')} · ${e.scope}`, { small: true, mono: true, muted: true }),
            e.env_names.length ? ui.text(`Needs: ${e.env_names.join(', ')}`, { small: true, muted: true }) : null),
          e.added ? ui.badge('added', 'green') : ui.button('Add', async () => {
            const sid = e.name.toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '');
            try { await call('POST', `/v1/import/${e.key}`); ctx.toast(`Added ${e.name}: approve its tools on Servers`, 'success'); render(); }
            catch (err) {
              if (err.code !== 'exists') return fail(err);
              try { await call('POST', `/v1/import/${e.key}`, { query: { id: `${sid}-${e.app.toLowerCase().replace(/[^a-z]+/g, '-')}`.slice(0, 32) } }); render(); } catch (e2) { fail(e2); }
            }
          }, { small: true })))) : ui.empty('Nothing found', 'No other app here configures an MCP server.'));
    }

    const views = { servers, import: imports };
    function render() { (views[ctx.tab] || servers)().catch(fail); }
    render();
  },
};
