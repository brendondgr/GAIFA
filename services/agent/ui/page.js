// The agent's Learning page (plan 21.7; brief §5): what the agent has learned about you and how
// your tools are used. Preferences: what applies to your cards, with where it came from; forget any.
// Review: what the miner proposes, to approve or reject. Tool usage: calls, errors and how often you
// change each tool's card. The data is the hub's (/api/prefs, /api/tools/usage), through this mod.

const SOURCE = { stated: 'you said', inferred: 'learned', carried: 'this chat' };

export default {
  tabs: [{ id: 'learning', label: 'Preferences', icon: 'star' }, { id: 'review', label: 'Review', icon: 'check' },
         { id: 'usage', label: 'Tool usage', icon: 'chart' }],

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
      const decide = (p, verb, label, kind) => ui.button(label, async () => { await ctx.call('POST', `/v1/prefs/${p.id}/${verb}`).catch(fail); render(); }, { kind });
      put(
        h('div', { style: 'display:flex;gap:8px;align-items:center' },
          ui.text('What the agent noticed you choose again and again. Approve one and it fills your cards from then on.', { muted: true }),
          h('span', { style: 'flex:1' }),
          ui.button('Look again now', async () => { await ctx.call('POST', '/v1/learn/mine').catch(fail); render(); })),
        rows.length ? ui.card(...rows.map(p => prefRow(p, [decide(p, 'approve', 'Approve', 'primary'), decide(p, 'reject', 'Not this')])))
          : ui.empty('Nothing to review', 'Proposals appear after you change the same setting on cards in two chats.'));
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

    const views = { learning: preferences, review, usage };
    function render() { (views[ctx.tab] || preferences)().catch(fail); }
    render();
    ctx.on('pref', () => { if (ctx.tab !== 'usage') render(); });
  },
};
