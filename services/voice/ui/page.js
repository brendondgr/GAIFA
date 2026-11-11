// Voice's own tab (plan voice-speech-model 2.4): whether the speech model is loaded, its two sizes with
// Load, Unload, and Try it (a conversation with no chat, through the same client as Chat's voice mode).
// Uses only ctx (design brief §5).

import { panel, header, stat, fmtBytes, requireRunning, callRoom } from '/mod-kit.js';
import { h } from '/mod-ui.js';

const NOTE = { q4_k_m: 'smaller, faster', q8_0: 'closer to the original' };

export default {
  tabs: [{ id: 'model', label: 'Model', icon: 'wave' }],

  mount(el, ctx) {
    if (!requireRunning(el, ctx, 'the voice model')) return;
    const { ui } = ctx;
    const body = h('div', { style: 'display:flex;flex-direction:column;gap:12px;max-width:900px' });
    const tryBox = h('div');
    el.append(body, tryBox);
    let timer = null, stopTry = null, alive = true;

    async function act(method, path, json) {
      try { await callRoom(ctx, method, path, json ? { json } : {}); }
      catch (e) { if (!e.cancelled) ctx.toast(e.data?.fix ? `${e.detail} Fix: ${e.data.fix}` : (e.detail || e.message), 'error'); }
      draw();
    }

    async function draw() {
      clearTimeout(timer);
      if (!alive) return;
      let st;
      try { st = (await ctx.call('GET', '/v1/status')).json; }
      catch (e) { body.replaceChildren(ui.text(e.detail || 'Could not read the status', { muted: true })); return; }
      const eng = st.engine || {};
      const busy = eng.state === 'loading' || st.sessions > 0;
      const row = m => h('div', { style: 'display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--bd,#1D2430)' },
        h('div', { style: 'flex:1;min-width:0;display:flex;flex-direction:column;gap:2px' },
          h('span', { style: 'font-size:13px;font-weight:600' }, `LFM3-Omni-2B ${m.label}`,
            h('span', { style: 'font-weight:400;color:var(--mut,#8A94A6)' }, ` · ${NOTE[m.quant] || ''}${m.default ? ' (default)' : ''}`)),
          h('span', { style: 'font-size:11.5px;color:var(--mut,#8A94A6)' }, m.present ? `${fmtBytes(m.size_bytes)} on disk · ${m.file}` : `${m.file} isn't downloaded: gaifa setup voice`)),
        m.loaded ? ui.badge('loaded', 'green') : m.present ? ui.badge('on disk') : ui.badge('not downloaded', 'dim'),
        m.loaded ? ui.button('Unload', () => act('POST', '/v1/unload'), { small: true, disabled: busy })
          : ui.button('Load', () => act('POST', '/v1/load', { quant: m.quant }), { small: true, disabled: busy || !m.present }));
      const first = (st.stats || []).find(s => /First audio/.test(s.label));
      body.replaceChildren(
        panel(header('Speech model'), h('div', { style: 'display:flex;gap:24px;flex-wrap:wrap' },
          stat('State', eng.state === 'ready' ? 'Loaded' : eng.state === 'loading' ? 'Loading…' : eng.state === 'failed' ? 'Failed' : 'Not loaded'),
          stat('Model', eng.state === 'ready' ? eng.label : '—'),
          stat('Conversation', st.sessions ? 'open' : 'none'),
          stat('First audio', first ? `${first.value} ms` : '—'),
          stat('Turn ends found by', st.vad === 'silero' ? 'Silero VAD' : 'loudness')),
          eng.error ? ui.text(eng.error, { small: true }) : null,
          ui.text('Chat\'s voice mode uses this model when Settings → Speech → Voice mode is set to "Speech model (local)". It unloads after 5 minutes without a conversation.', { muted: true, small: true })),
        panel(header('Sizes', ui.button('Refresh', draw, { small: true })), h('div', null, ...(st.models || []).map(row))));
      timer = setTimeout(draw, busy ? 1500 : 8000);
    }

    // Try it: Chat's live client, loaded when it exists (it ships with the Chat page).
    import('/chat/chat-voice-live.js').then(m => { if (alive && m.mountTry) stopTry = m.mountTry(tryBox, ctx, draw); }).catch(() => {});

    draw();
    ctx.on('service', ev => { if (ev.service.id === ctx.service.id) draw(); });
    return () => { alive = false; clearTimeout(timer); if (stopTry) stopTry(); };
  },
};
