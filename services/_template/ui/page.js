// __NAME__'s own tab inside AIHub (design brief §5). AIHub serves this file at
// /ui/services/__ID__/page.js and mounts it in the mod's page. Rules: use only `ctx`
// (no fetch, no raw colors; ctx.ui builds themed elements), and show a Start button
// when the mod isn't running. Return a cleanup function if you start timers or listeners.

export default {
  tabs: [{ id: 'hello', label: 'Hello', icon: 'wave' }],

  mount(el, ctx) {
    const { ui } = ctx;
    const svc = ctx.service;

    if (svc.state !== 'ready' && svc.state !== 'degraded') {
      el.append(ui.empty(`${svc.name} is not running`, 'Start it to try the Hello tab.',
        ui.button(`Start ${svc.name}`, () => ctx.api.startService(svc.id).catch(e => ctx.toast(e.detail, 'error')), { kind: 'primary' })));
      return;
    }

    const name = ui.input({ placeholder: 'world', name: 'name' });
    const result = ui.h('div');
    const send = ui.button('Say hello', null, { kind: 'primary', type: 'submit' });

    async function sayHello(e) {
      e.preventDefault();
      send.disabled = true;
      try {
        // ctx.call(method, path, opts) goes through AIHub's proxy: /api/s/<id>/v1/hello
        const res = await ctx.call('GET', '/v1/hello', { query: { name: name.value.trim() || 'world' } });
        result.replaceChildren(ui.text(`${res.status} · ${res.ms} ms`, { muted: true, mono: true }), ui.json(res.json));
      } catch (err) {
        ctx.toast(err.detail || 'Request failed', 'error');
      } finally {
        send.disabled = false;
      }
    }

    el.append(ui.card(
      ui.h('h2', { style: 'margin:0;font-size:15px' }, 'Say hello'),
      ui.text(`This tab comes from services/${svc.id}/ui/page.js. It calls GET /v1/hello through ctx.call.`, { muted: true }),
      ui.h('form', { onsubmit: sayHello, style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end' },
        ui.field('Name', name), send),
      result,
    ));

    // Live updates: ctx.on(type, fn) subscribes to AIHub events and is removed on unmount.
    ctx.on('service', ev => { if (ev.service.id === svc.id && ev.service.state === 'stopped') ctx.toast(`${svc.name} stopped`, 'info'); });
  },
};
