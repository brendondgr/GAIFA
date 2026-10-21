// The agent's Learning page (plan 21.7; brief §5): what the agent has learned about you and how
// your tools are used. Preferences: what applies to your cards, with where it came from; forget any.
// Review: what the miner proposes, to approve or reject. Tool usage: calls, errors and how often you
// change each tool's card. The data is the hub's (/api/prefs, /api/tools/usage), through this mod.

const SOURCE = { stated: 'you said', inferred: 'learned', carried: 'this chat' };

export default {
  tabs: [{ id: 'learning', label: 'Preferences', icon: 'star' }, { id: 'review', label: 'Review', icon: 'check' },
         { id: 'usage', label: 'Tool usage', icon: 'chart' }, { id: 'harness', label: 'Harness', icon: 'layers' },
         { id: 'runs', label: 'Runs', icon: 'play' }, { id: 'library', label: 'Library', icon: 'file' }],

  mount(el, ctx) {
    const { ui } = ctx, h = ui.h, svc = ctx.service;
    if (svc.state !== 'ready' && svc.state !== 'degraded') {
      el.append(ui.empty(`${svc.name} is not running`, 'Start it to see what it has learned.',
        ui.button(`Start ${svc.name}`, () => ctx.api.startService(svc.id).catch(e => ctx.toast(e.detail, 'error')), { kind: 'primary' })));
      return;
    }
    const body = h('div', { style: 'display:flex;flex-direction:column;gap:12px' });
    el.append(body);
    const put = (...kids) => body.replaceChildren(...kids.filter(Boolean));          // leave out the parts that don't apply
    const fail = e => ctx.toast(e.detail || e.message || 'Request failed', 'error');
    const when = w => Object.entries(w || {}).map(([k, v]) => v === 'present' ? `with ${k}` : v === 'absent' ? `without ${k}` : `${k}=${v}`).join(', ');
    const valueText = v => typeof v === 'string' ? v : JSON.stringify(v);
    const what = p => p.tool ? `${p.tool} · ${p.field} = ${valueText(p.value)}` : valueText(p.value);

    function prefRow(p, actions) {
      return h('div', { style: 'display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-top:1px solid var(--bd,#1D2430)' },
        h('div', { style: 'flex:1;min-width:0;display:flex;flex-direction:column;gap:3px' },
          h('div', { style: 'font-size:13px;overflow-wrap:anywhere' }, what(p)),
          h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;align-items:center' },
            ui.badge(SOURCE[p.source] || p.source, p.source === 'stated' ? 'purple' : 'blue'),
            when(p.when) ? ui.text(when(p.when), { muted: true }) : null,
            p.cue ? ui.text(p.cue, { muted: true }) : null,
            ui.text(`seen ${p.seen}×${p.contradicted ? ` · against ${p.contradicted}×` : ''}${p.evidence?.length ? ` · ${p.evidence.length} pieces of evidence` : ''}`, { muted: true }),
            p.note ? ui.text(p.note, { muted: true }) : null)),
        h('div', { style: 'display:flex;gap:6px' }, ...actions));
    }

    async function preferences() {
      const rows = (await ctx.call('GET', '/v1/prefs', { query: { state: 'active' } })).json.filter(p => p.scope !== 'thread');
      const forget = p => ui.button('Forget', async () => {
        if (!(await ctx.confirm({ title: 'Forget this preference?', body: what(p), danger: true }))) return;
        await ctx.call('DELETE', `/v1/prefs/${p.id}`).catch(fail); render();
      });
      const tools = [...new Set(rows.filter(p => p.tool).map(p => p.tool))].sort();
      const about = rows.filter(p => !p.tool);
      put(
        ui.text('These fill your cards (marked "from your preferences") and tell the agent about you. Change a card and it learns; forget anything here.', { muted: true }),
        !rows.length ? ui.empty('Nothing learned yet', 'Say "from now on…" in a chat, or change the same setting on a few cards, and it shows up here.') : null,
        ...tools.map(t => ui.card(h('h2', { style: 'margin:0;font-size:14px' }, t), ...rows.filter(p => p.tool === t).map(p => prefRow(p, [forget(p)])))),
        about.length ? ui.card(h('h2', { style: 'margin:0;font-size:14px' }, 'About you'), ...about.map(p => prefRow(p, [forget(p)]))) : null);
    }

    async function review() {
      const rows = (await ctx.call('GET', '/v1/prefs', { query: { state: 'proposed' } })).json;
      const proposed = (await ctx.call('GET', '/v1/harness/versions')).json.filter(v => v.adopted_by === 'proposed');
      const decide = (p, verb, label, kind) => ui.button(label, async () => { await ctx.call('POST', `/v1/prefs/${p.id}/${verb}`).catch(fail); render(); }, { kind });
      put(
        h('div', { style: 'display:flex;gap:8px;align-items:center' },
          ui.text('What the agent noticed you choose again and again. Approve one and it fills your cards from then on.', { muted: true }),
          h('span', { style: 'flex:1' }),
          ui.button('Look again now', async () => { await ctx.call('POST', '/v1/learn/mine').catch(fail); render(); })),
        rows.length ? ui.card(...rows.map(p => prefRow(p, [decide(p, 'approve', 'Approve', 'primary'), decide(p, 'reject', 'Not this')])))
          : ui.empty('Nothing to review', 'Proposals appear after you change the same setting on cards in two chats.'),
        ...proposed.map(v => versionCard(v, true)));
    }

    async function usage() {
      const days = Number(ctx.params?.days || 30);
      const rows = (await ctx.call('GET', '/v1/learn/usage', { query: { days } })).json;
      const pct = (a, b) => (b ? `${Math.round((100 * a) / b)}%` : '—');
      put(
        ui.text(`The last ${days} days, real calls only (eval runs left out). "Changed" is how often you edited the card: what learning aims to bring down.`, { muted: true }),
        rows.length ? ui.table(rows.map(r => ({ Tool: r.tool, Calls: r.calls, Errors: `${r.errors} (${pct(r.errors, r.calls)})`, Refused: r.refused,
          Cards: r.cards, Changed: `${r.edited} (${pct(r.edited, r.cards)})`, Denied: r.denied,
          'Mean time': r.mean_ms == null ? '—' : r.mean_ms > 60000 ? `${(r.mean_ms / 60000).toFixed(1)} min` : `${(r.mean_ms / 1000).toFixed(1)} s` })))
          : ui.empty('No tool calls yet', 'Use the chat, and the tools it calls show up here.'));
    }

    // ---- the learner (plan 22.7) ----
    const when_ = ts => (ts ? new Date(ts * 1000).toLocaleString() : '');
    function versionCard(v, review = false) {
      const diff = h('pre', { style: 'display:none;margin:0;max-height:360px;overflow:auto;font-size:11.5px;white-space:pre-wrap' });
      const show = ui.button('Diff', async () => {
        if (diff.style.display === 'none') { diff.textContent = (await ctx.call('GET', `/v1/harness/versions/${v.n}/diff`)).json.diff || '(no change)'; diff.style.display = 'block'; }
        else diff.style.display = 'none';
      });
      const use = ui.button(review ? 'Use this version' : v.n === 0 ? 'Roll back to the base' : 'Activate', async () => {
        if (review && !(await ctx.confirm({ title: `Use harness version ${v.n}?`, body: 'It changes always-on text the agent reads on every call. The eval gate passed; you can roll back on the Harness tab.' }))) return;
        await ctx.call('POST', `/v1/harness/versions/${v.n}/activate`).catch(fail); render();
      }, { kind: review ? 'primary' : undefined });
      const gate = v.gate ? `gate ${v.gate.ok ? 'passed' : 'failed'}: ${Math.round((v.gate.candidate || 0) * 100)}% vs ${Math.round((v.gate.current || 0) * 100)}%` : '';
      return ui.card(h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' },
          h('strong', null, v.n === 0 ? 'Base (in git)' : `Version ${v.n}`), v.active ? ui.badge('active', 'green') : null,
          ui.badge(v.adopted_by, v.adopted_by === 'proposed' ? 'purple' : v.adopted_by === 'rejected' ? 'red' : 'blue'),
          ui.text([when_(v.created), (v.files || []).join(', '), gate].filter(Boolean).join(' · '), { muted: true }),
          h('span', { style: 'flex:1' }), v.n ? show : null, v.active && !review ? null : use),
        v.notes ? ui.text(v.notes, { muted: true }) : null, diff);
    }
    async function harness() {
      const vs = (await ctx.call('GET', '/v1/harness/versions')).json.filter(v => !['candidate', 'probed'].includes(v.adopted_by));
      put(ui.text('The agent\'s instructions: the base in git, and the versions the learner made from your chats. Activate any to roll back or forward.', { muted: true }),
        ...vs.reverse().map(v => versionCard(v)));
    }
    async function runs() {
      const r = (await ctx.call('GET', '/v1/learn/runs')).json;
      const now = ui.button('Learn now', async () => { await ctx.call('POST', '/v1/learn/run').then(() => ctx.toast('Learning: it pauses while you chat', 'info'), fail); setTimeout(render, 1500); }, { kind: 'primary' });
      const row = x => ui.card(h('div', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' },
          h('strong', null, when_(x.started)), ui.badge(x.state, x.state === 'done' ? 'green' : x.state === 'running' ? 'purple' : 'red'),
          ui.text(`${x.why} · ${x.stage}${x.ended ? ` · ${Math.round(x.ended - x.started)} s` : ''} · ${(x.ledger || []).length} model calls`, { muted: true })),
        ...(x.domains || []).map(d => ui.text(`${d.domain}: ${d.decision}${d.final ? ` (version ${d.final})` : ''} · ${d.chats.length} chats` +
          (d.gate ? ` · gate ${d.gate.ok ? 'passed' : 'failed'}` : '') + (d.notes ? ` · ${d.notes}` : ''))),
        x.error ? ui.badge(x.error, 'red') : null);
      put(h('div', { style: 'display:flex;gap:8px;align-items:center' },
          ui.text('Nightly, after an hour without a chat, or now. Each run reflects on new chats per area, tries two edits, replays your chats under them, and keeps only what the eval gate passes.', { muted: true }),
          h('span', { style: 'flex:1' }), r.running ? ui.badge(`running: ${r.running.stage}`, 'purple') : now),
        ...(r.runs.length ? r.runs.map(row) : [ui.empty('No runs yet', 'The first runs tonight, or press Learn now.')]));
    }
    async function library() {
      const lib = (await ctx.call('GET', '/v1/learn/library')).json;
      const areas = Object.entries(lib).filter(([, l]) => l.length);
      put(ui.text('Lessons the learner kept for its next rounds (the live agent never reads them).', { muted: true }),
        ...(areas.length ? areas.map(([d, l]) => ui.card(h('h2', { style: 'margin:0;font-size:14px' }, d),
          ...l.map(e => h('div', { style: `padding:6px 0;border-top:1px solid var(--bd,#1D2430);font-size:12.5px;display:flex;flex-direction:column;gap:2px${e.withdrawn ? ';opacity:.6' : ''}` },
            e.withdrawn ? h('div', null, ui.badge(`withdrawn: ${e.withdrawn}`, 'dim')) : null,
            h('div', null, h('strong', null, 'When '), e.cue), h('div', null, e.lesson), ui.text(`${e.evidence} · ${e.confidence}`, { muted: true })))))
          : [ui.empty('No lessons yet', 'Each improvement run may keep one per area.')]));
    }

    const views = { learning: preferences, review, usage, harness, runs, library };
    function render() { (views[ctx.tab] || preferences)().catch(fail); }
    render();
    ctx.on('pref', () => { if (ctx.tab !== 'usage') render(); });
  },
};
