// Speech (tts) page inside GAIFA: Speak and Voices tabs (design brief Part B3). Calls LocalTTS's
// own API through ctx.call (GAIFA's proxy, so memory is managed). History is the generic Outputs tab.
import { chartCard, charts, rh, waveform, wavSamples } from '/mod-charts.js';
import { requireRunning, callRoom, segmented, header, panel, columns, stat, store, fmtSecs, MONO } from '/mod-kit.js';

const FORMATS = ['wav', 'mp3', 'flac', 'ogg'];
const MAX_TEXT = 20000;
const SAMPLE = 'Hello, and welcome. This is a short sample of my voice, recorded so that I sound the same every time you hear me.';
const TAG_RE = /^\([a-z][a-z \-]*\)[.,!?]?$/i;

export default {
  tabs: [{ id: 'speak', label: 'Speak', icon: 'wave' }, { id: 'voices', label: 'Voices', icon: 'mic' }],

  mount(el, ctx) {
    if (!requireRunning(el, ctx, 'Speech')) return;
    const cleanups = [];
    const done = () => cleanups.forEach(f => { try { f(); } catch { /* already gone */ } });
    (ctx.tab === 'voices' ? voicesTab : speakTab)(el, ctx, cleanups);
    return done;
  },
};

// ui.field grows to 220 px wide in a row; in a column it must not grow tall.
const colField = ui => (...a) => { const f = ui.field(...a); f.style.flex = '0 0 auto'; return f; };
const b64ToBlob = (b64, type) => new Blob([Uint8Array.from(atob(b64), c => c.charCodeAt(0))], { type });
const errText = e => e.detail || e.message || 'Request failed';

async function loadVoices(ctx) {
  const r = await ctx.call('GET', '/v1/voices');
  return { custom: r.json.custom || [], kokoro: r.json.kokoro || [] };
}

// ------------------------------------------------------------------ Speak
function speakTab(el, ctx, cleanups) {
  const { ui } = ctx, h = ui.h;
  const st = Object.assign({ engine: 'breeze', voice: '', kvoice: 'af_heart', direction: '', speed: 1, format: 'wav', timings: true }, store.get('tts.speak', {}));
  const save = () => store.set('tts.speak', { engine: st.engine, voice: st.voice, kvoice: st.kvoice, format: st.format, timings: st.timings, speed: st.speed });
  let voices = { custom: [], kokoro: [] };

  const text = ui.textarea({ rows: 7, placeholder: 'Type what to say…', value: store.get('tts.draft', '') });
  text.style.minHeight = '140px';
  text.setAttribute('aria-label', 'Text to speak');
  const count = h('span', { style: `font-family:${MONO};font-size:11.5px;color:var(--mut,#8A94A6)` });
  const onText = () => { count.textContent = `${text.value.length.toLocaleString()} / ${MAX_TEXT.toLocaleString()}`; count.style.color = text.value.length > MAX_TEXT ? 'var(--rd,#F85149)' : 'var(--mut,#8A94A6)'; store.set('tts.draft', text.value); };
  text.addEventListener('input', onText); onText();

  const engine = segmented([{ value: 'breeze', label: 'Breeze TTS 2' }, { value: 'kokoro', label: 'Kokoro' }], st.engine, v => { st.engine = v; save(); fill(); }, 'Engine');
  const voiceSel = ui.select([], { onchange: () => { if (st.engine === 'breeze') st.voice = voiceSel.value; else st.kvoice = voiceSel.value; save(); } });
  voiceSel.setAttribute('aria-label', 'Voice');
  const direction = ui.input({ placeholder: 'e.g. warm and unhurried, smiling', value: st.direction });
  direction.addEventListener('input', () => { st.direction = direction.value; });
  const speed = h('input', { type: 'range', min: '0.5', max: '2', step: '0.05', value: String(st.speed), style: 'width:100%', 'aria-label': 'Speed' });
  const speedOut = h('span', { style: `font-family:${MONO};font-size:12px;min-width:42px;text-align:right` });
  const onSpeed = () => { st.speed = Number(speed.value); speedOut.textContent = `${st.speed.toFixed(2)}×`; save(); };
  speed.addEventListener('input', onSpeed); onSpeed();
  const format = ui.select(FORMATS, { value: st.format, onchange: () => { st.format = format.value; save(); } });
  format.setAttribute('aria-label', 'Format');
  const timings = h('input', { type: 'checkbox', checked: st.timings, onchange: () => { st.timings = timings.checked; save(); } });

  const dirField = ui.field('Delivery direction', direction, 'Breeze only. With no saved voice, it describes the voice itself.');
  const speedField = ui.field('Speed', h('div', { style: 'display:flex;gap:8px;align-items:center' }, speed, speedOut));
  const enhanceBtn = ui.button('Enhance', () => enhance(), { title: 'Add vocal tags with an LLM' });
  const genBtn = ui.button('Generate', () => generate(), { kind: 'primary' });
  const enhancePanel = h('div');
  const result = h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' });

  function fill() {
    engine.set(st.engine);
    const breeze = st.engine === 'breeze';
    const opts = breeze
      ? [{ value: '', label: 'No saved voice (describe it below)' }, ...voices.custom.map(v => ({ value: v.name, label: `${v.name} · ${v.source === 'design' ? 'designed' : 'cloned'}` }))]
      : voices.kokoro.map(v => ({ value: v, label: `${v}  (${v[0] === 'a' ? 'American' : 'British'} ${v[1] === 'f' ? 'female' : 'male'})` }));
    voiceSel.replaceChildren(...opts.map(o => h('option', { value: o.value }, o.label)));
    voiceSel.value = breeze ? (opts.some(o => o.value === st.voice) ? st.voice : '') : (voices.kokoro.includes(st.kvoice) ? st.kvoice : 'af_heart');
    dirField.style.display = breeze ? 'flex' : 'none';
    speedField.style.display = breeze ? 'none' : 'flex';
    enhanceBtn.style.display = breeze ? 'inline-flex' : 'none';
  }

  async function enhance() {
    const t = text.value.trim();
    if (!t) return ctx.toast('Type some text first', 'info');
    const style = ui.select([{ value: 'subtle', label: 'Subtle' }, { value: 'expressive', label: 'Expressive' }], { value: store.get('tts.enhanceStyle', 'subtle') });
    enhanceBtn.disabled = true; enhanceBtn.textContent = 'Enhancing…';
    enhancePanel.replaceChildren(panel(header('Enhance'), ui.text('Asking the LLM for vocal tags…', { muted: true })));
    try {
      const r = (await ctx.call('POST', '/v1/enhance', { json: { text: t, style: style.value, direction: st.direction || null } })).json;
      const diff = h('p', { style: 'margin:0;line-height:1.9;font-size:13px;white-space:pre-wrap' },
        r.text.split(/(\s+)/).map(tok => TAG_RE.test(tok.trim()) && !t.includes(tok.trim().replace(/[.,!?]$/, ''))
          ? h('mark', { style: 'background:var(--tacc,rgba(255,178,36,.13));color:var(--acct,#FFB224);border-radius:4px;padding:1px 4px;font-family:' + MONO + ';font-size:12px' }, tok)
          : tok));
      const accept = () => { text.value = r.text; onText(); if (r.delivery) { direction.value = st.direction = r.delivery; } enhancePanel.replaceChildren(); ctx.toast('Enhanced text applied', 'success'); };
      enhancePanel.replaceChildren(panel(
        header(`Enhance · ${r.tags_added} tag${r.tags_added === 1 ? '' : 's'} added`, ui.badge(r.model || 'LLM')),
        diff,
        r.delivery ? ui.text(`Suggested delivery: ${r.delivery}`, { muted: true }) : null,
        r.warning ? ui.badge(r.warning, 'red') : null,
        ui.row(ui.button('Use this', accept, { kind: 'primary', small: true }), ui.button('Discard', () => enhancePanel.replaceChildren(), { small: true, kind: 'ghost' }),
          h('span', { style: 'flex:1' }), ui.field('Style', style), ui.button('Again', () => { store.set('tts.enhanceStyle', style.value); enhance(); }, { small: true }))));
    } catch (e) {
      enhancePanel.replaceChildren(panel(header('Enhance'), ui.badge(errText(e), 'red'), ui.text('Enhance uses the LLM relay (:4000). Is a model running?', { muted: true })));
    } finally { enhanceBtn.disabled = false; enhanceBtn.textContent = 'Enhance'; }
  }

  async function generate() {
    const t = text.value.trim();
    if (!t) return ctx.toast('Type some text first', 'info');
    if (t.length > MAX_TEXT) return ctx.toast(`Text is over ${MAX_TEXT} characters`, 'error');
    const breeze = st.engine === 'breeze';
    if (breeze && !voiceSel.value && !st.direction.trim()) return ctx.toast('Pick a saved voice, or describe the voice in Delivery direction', 'info');
    const body = { text: t, engine: st.engine, format: st.format, timings: st.timings, request_id: Math.random().toString(16).slice(2, 14) };
    if (breeze) { if (voiceSel.value) body.voice = voiceSel.value; if (st.direction.trim()) body.instruction = st.direction.trim(); }
    else { body.voice = voiceSel.value; body.speed = st.speed; }
    genBtn.disabled = true; genBtn.textContent = 'Generating…';
    const t0 = performance.now();
    const note = ui.text(ctx.service.load === 'loaded' ? 'Speaking…' : `Loading ${breeze ? 'Breeze (about 30 s cold)' : 'Kokoro'}, then speaking…`, { muted: true });
    const pending = panel(header('Generating'), note);
    result.prepend(pending);
    // GAIFA's GPU queue (plan 31.3): while the request waits for another mod's GPU work, say so.
    const said = note.textContent;
    const gpuWait = setInterval(async () => {
      try {
        const w = ((await ctx.call('GET', '/v1/status')).json.jobs || []).find(j => j.stage === 'waiting_gpu');
        const a = w?.ahead?.[0];
        note.textContent = w ? `Waiting for the GPU${a ? `: ${a.service}${a.label ? ` (${a.label})` : ''}` : ''}${w.eta_s ? `, about ${Math.max(1, Math.round(w.eta_s / 60))} min` : ''}…` : said;
      } catch { /* the next tick tries again */ }
    }, 1500);
    cleanups.push(() => clearInterval(gpuWait));
    try {
      const r = await callRoom(ctx, 'POST', '/v1/speech', { json: body });
      clearInterval(gpuWait);
      pending.remove();
      showResult(r, body, (performance.now() - t0) / 1000);
    } catch (e) {
      pending.remove();
      if (!e.cancelled) ctx.toast(errText(e), 'error');
    } finally { clearInterval(gpuWait); genBtn.disabled = false; genBtn.textContent = 'Generate'; }
  }

  function showResult(r, body, secs) {
    let blob, words = null, meta = {};
    if (r.json) {
      const j = r.json;
      blob = b64ToBlob(j.audio, `audio/${j.format === 'mp3' ? 'mpeg' : j.format}`);
      words = j.timings?.words || null;
      meta = { engine: j.engine, voice: j.voice, saved: j.saved, duration: j.timings?.duration, rtf: j.stats?.rtf };
    } else {
      blob = r.blob;
      meta = { engine: body.engine, voice: body.voice || 'design' };
    }
    const url = URL.createObjectURL(blob);
    cleanups.push(() => URL.revokeObjectURL(url));
    const audio = h('audio', { controls: true, src: url, preload: 'auto', style: 'width:100%;height:36px' });
    const wave = h('div', { style: 'cursor:pointer;border-radius:6px;background:var(--inset,#131926);padding:6px' });
    const wordsEl = words ? h('p', { style: 'margin:0;line-height:1.9;font-size:13.5px' }, words.map(w => h('span', { 'data-s': w.start, 'data-e': w.end, style: 'border-radius:3px;padding:0 1px;cursor:pointer' }, w.w + ' '))) : null;
    let svg = null;
    blob.arrayBuffer().then(buf => {
      if (body.format !== 'wav') return;
      svg = waveform(wavSamples(buf), { height: 46 });
      wave.append(svg);
    });
    wave.addEventListener('click', e => { const r0 = wave.getBoundingClientRect(); if (audio.duration) audio.currentTime = ((e.clientX - r0.left) / r0.width) * audio.duration; });
    if (wordsEl) wordsEl.addEventListener('click', e => { const s = e.target.dataset?.s; if (s != null) { audio.currentTime = Number(s); audio.play(); } });
    audio.addEventListener('timeupdate', () => {
      const t = audio.currentTime;
      if (svg && audio.duration) svg.setProgress(t / audio.duration);
      if (wordsEl) for (const s of wordsEl.children) { const on = t >= Number(s.dataset.s) && t < Number(s.dataset.e); s.style.background = on ? 'var(--tacc,rgba(255,178,36,.13))' : ''; s.style.color = on ? 'var(--acct,#FFB224)' : ''; }
    });
    const card = panel(
      header(`${meta.engine === 'kokoro' ? 'Kokoro' : 'Breeze'} · ${meta.voice || '—'}`,
        meta.saved && meta.saved !== 'no' ? ui.button('Open in Outputs', () => ctx.navigate('#/s/tts/outputs'), { small: true, kind: 'ghost' }) : null,
        h('a', { href: url, download: `${(body.text.slice(0, 32).replace(/[^a-z0-9]+/gi, '-') || 'speech')}.${body.format}`, style: 'font-size:12px;color:var(--acct,#FFB224)' }, 'Download')),
      body.format === 'wav' ? wave : null, audio, wordsEl,
      h('div', { style: 'display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:10px' },
        stat('Audio', meta.duration != null ? `${meta.duration.toFixed(2)} s` : '—'), stat('Took', fmtSecs(secs)),
        stat('Real-time factor', meta.rtf != null ? String(meta.rtf) : '—'), stat('Saved', meta.saved && meta.saved !== 'no' ? meta.saved : 'not saved')));
    result.prepend(card);
    while (result.children.length > 3) result.lastChild.remove();
    audio.play().catch(() => { /* autoplay blocked: the controls are there */ });
  }

  const compose = panel(
    h('div', { style: 'display:flex;align-items:center;gap:10px;flex-wrap:wrap' }, engine, h('span', { style: 'flex:1' }), count),
    text,
    h('div', { style: 'display:flex;gap:10px;flex-wrap:wrap' }, ui.field('Voice', voiceSel), dirField, speedField),
    h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:center' },
      ui.field('Format', format), h('label', { style: 'display:flex;gap:6px;align-items:center;font-size:12px;flex:1 1 180px' }, timings, 'Word highlight (Breeze: aligned with Whisper)'),
      enhanceBtn, genBtn),
  );
  text.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') generate(); });

  const clips = chartCard({
    title: 'Clips per day', ranges: ['7d', '30d'], height: 130,
    load: range => ctx.call('GET', '/v1/hub/widgets/clips', { query: { range } }).then(r => r.json),
    draw: (d, o) => rh(charts.BarChart, { categories: d.categories, series: d.series.map(s => ({ label: s.name, values: s.values })), stacked: true, unit: 'count', ...o }),
  });
  const now = () => Date.now() / 1000;
  const lane = chartCard({
    title: 'Engine loaded · 24 h', height: 60, every: 60000,
    load: () => ctx.api.getTimeline({ range: '24h', services: 'tts' }),
    draw: (d, o) => rh(charts.Timeline, { from: d.from, to: d.to || now(), lanes: d.lanes.map(l => ({ ...l, label: 'Engine' })), label: o.label, table: o.table, minWidth: 0, labelW: 44, laneH: 26 }),
  });
  cleanups.push(clips.unmount, lane.unmount);
  const grid = columns(h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' }, compose, enhancePanel, result),
    h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' }, clips, lane));
  cleanups.push(grid.cleanup);
  el.append(grid);
  fill();
  loadVoices(ctx).then(v => { voices = v; fill(); }).catch(e => ctx.toast(errText(e), 'error'));
  ctx.on('output', ev => { if (ev.output?.service === 'tts') clips.refresh(); });
}

// ------------------------------------------------------------------ Voices
function voicesTab(el, ctx, cleanups) {
  const { ui } = ctx, h = ui.h;
  const grid = h('div', { style: 'display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px' });
  const side = h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' });
  const layout = columns(h('div', { style: 'display:flex;flex-direction:column;gap:12px;min-width:0' },
    panel(header('Saved voices', ui.button('Refresh', () => refresh(), { small: true, kind: 'ghost' })), grid)), side, 360);
  cleanups.push(layout.cleanup);
  el.append(layout);
  let current = [];

  async function refresh() {
    try { current = (await loadVoices(ctx)).custom; render(); } catch (e) { grid.replaceChildren(ui.badge(errText(e), 'red')); }
  }

  function render() {
    if (!current.length) { grid.replaceChildren(ui.empty('No saved voices yet', 'Clone one from a clip, or design one from a description.')); return; }
    grid.replaceChildren(...current.map(card));
  }

  function card(v) {
    // The reference clip loads through ctx.call on first play (no direct fetches; works on the mock too).
    const audio = h('div');
    const play = ui.button('▶ Play reference', async () => {
      play.disabled = true;
      try {
        const r = await ctx.call('GET', `/v1/voices/${encodeURIComponent(v.name)}/audio`);
        cleanups.push(() => URL.revokeObjectURL(r.url));
        audio.replaceChildren(h('audio', { controls: true, autoplay: true, src: r.url, style: 'width:100%;height:32px' }));
      } catch (e) { play.disabled = false; ctx.toast(errText(e), 'error'); }
    }, { small: true });
    audio.append(play);
    const body = h('div', { style: 'display:flex;flex-direction:column;gap:8px' });
    const view = () => body.replaceChildren(...[
      h('div', { style: 'display:flex;align-items:center;gap:8px' },
        h('strong', { style: 'font-size:14px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis' }, v.name),
        ui.badge(v.source === 'design' ? 'designed' : 'cloned', v.source === 'design' ? 'accent' : 'green')),
      h('div', { style: 'display:flex;gap:12px' }, stat('Reference', `${v.duration_s.toFixed(1)} s`), stat('Created', (v.created || '').slice(0, 10) || '—')),
      v.instruction ? ui.text(`“${v.instruction}”`, { muted: true, small: true }) : null,
      h('p', { title: v.transcript, style: 'margin:0;font-size:12px;color:var(--mut,#8A94A6);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden' }, v.transcript_auto ? `(Whisper) ${v.transcript}` : v.transcript),
      audio,
      ui.row(ui.button('Use', () => { const s = store.get('tts.speak', {}); store.set('tts.speak', { ...s, engine: 'breeze', voice: v.name }); ctx.navigate('#/s/tts/speak'); }, { small: true }),
        ui.button('Edit', edit, { small: true, kind: 'ghost' }),
        ui.button('Delete', del, { small: true, kind: 'danger' }))].filter(Boolean));
    function edit() {
      const name = ui.input({ value: v.name });
      const tr = ui.textarea({ value: v.transcript, rows: 4 });
      const field = colField(ui);
      body.replaceChildren(field('Name', name), field('Transcript', tr, 'The exact words in the reference clip; clone quality depends on it.'),
        ui.row(ui.button('Save', async () => {
          try {
            const patch = {};
            if (tr.value.trim() !== v.transcript) patch.transcript = tr.value.trim();
            if (name.value.trim() !== v.name) patch.rename = name.value.trim();
            if (Object.keys(patch).length) Object.assign(v, (await ctx.call('PATCH', `/v1/voices/${encodeURIComponent(v.name)}`, { json: patch })).json);
            view(); ctx.toast('Voice saved', 'success');
          } catch (e) { ctx.toast(errText(e), 'error'); }
        }, { kind: 'primary', small: true }), ui.button('Cancel', view, { small: true, kind: 'ghost' })));
    }
    async function del() {
      if (!await ctx.confirm({ title: `Delete voice “${v.name}”?`, body: 'Its reference clip and transcript are deleted for good. Clips already made with it stay in Outputs.', danger: true })) return;
      try { await ctx.call('DELETE', `/v1/voices/${encodeURIComponent(v.name)}`); ctx.toast(`Deleted ${v.name}`, 'success'); refresh(); } catch (e) { ctx.toast(errText(e), 'error'); }
    }
    view();
    return h('div', { style: 'border:1px solid var(--bd,#1D2430);border-radius:8px;padding:10px;background:var(--inset,#131926);min-width:0' }, body);
  }

  side.append(cloneForm(ctx, refresh, cleanups), designForm(ctx, refresh, cleanups));
  refresh();
}

function cloneForm(ctx, refresh, cleanups) {
  const { ui } = ctx, h = ui.h, field = colField(ui);
  const name = ui.input({ placeholder: 'e.g. Narrator' });
  const file = h('input', { type: 'file', accept: 'audio/*', style: 'font-size:12px' });
  const tr = ui.textarea({ rows: 3, placeholder: 'Optional. Leave empty and Whisper writes it.' });
  const preview = h('div');
  file.addEventListener('change', () => {
    const f = file.files[0];
    if (!f) return preview.replaceChildren();
    const url = URL.createObjectURL(f);
    cleanups.push(() => URL.revokeObjectURL(url));
    const a = h('audio', { controls: true, src: url, style: 'width:100%;height:32px' });
    a.addEventListener('loadedmetadata', () => { if (a.duration < 3 || a.duration > 60) ctx.toast(`The clip is ${a.duration.toFixed(1)} s; use 3–60 s (10–25 s works best)`, 'info'); });
    preview.replaceChildren(a);
    if (!name.value) name.value = f.name.replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9 _.\-]/g, ' ').trim().slice(0, 64);
  });
  const go = ui.button('Clone voice', async () => {
    if (!name.value.trim() || !file.files[0]) return ctx.toast('A name and a clip are needed', 'info');
    go.disabled = true; go.textContent = 'Cloning…';
    try {
      const form = { name: name.value.trim(), audio: file.files[0] };
      if (tr.value.trim()) form.transcript = tr.value.trim();
      const v = (await callRoom(ctx, 'POST', '/v1/voices', { form })).json;
      ctx.toast(v.note || v.warning || `Saved voice ${v.name}`, v.warning ? 'info' : 'success');
      name.value = ''; tr.value = ''; file.value = ''; preview.replaceChildren();
      refresh();
    } catch (e) { if (!e.cancelled) ctx.toast(errText(e), 'error'); } finally { go.disabled = false; go.textContent = 'Clone voice'; }
  }, { kind: 'primary' });
  return panel(header('Clone a voice'), ui.text('Upload 3–60 s of clean speech (10–25 s works best).', { muted: true, small: true }),
    field('Clip', file), preview, field('Name', name), field('Transcript', tr), ui.row(go));
}

function designForm(ctx, refresh, cleanups) {
  const { ui } = ctx, h = ui.h, field = colField(ui);
  const desc = ui.textarea({ rows: 3, placeholder: 'e.g. a calm older narrator with a slight rasp, low and warm' });
  const sample = ui.textarea({ rows: 2, value: SAMPLE });
  const name = ui.input({ placeholder: 'Name to save it as' });
  const out = h('div', { style: 'display:flex;flex-direction:column;gap:8px' });
  let seed = 42;
  const run = async () => {
    if (!desc.value.trim()) return ctx.toast('Describe the voice first', 'info');
    gen.disabled = true; gen.textContent = 'Generating…';
    try {
      const r = await callRoom(ctx, 'POST', '/v1/speech', { json: { text: sample.value.trim() || SAMPLE, engine: 'breeze', instruction: desc.value.trim(), seed, no_save: true, format: 'wav' } });
      const url = URL.createObjectURL(r.blob);
      cleanups.push(() => URL.revokeObjectURL(url));
      out.replaceChildren(h('audio', { controls: true, autoplay: true, src: url, style: 'width:100%;height:32px' }),
        ui.text(`Seed ${seed}. Regenerate for a different voice, or save this one.`, { muted: true, small: true }),
        field('Name', name),
        ui.row(ui.button('Save voice', save, { kind: 'primary', small: true }), ui.button('Regenerate', () => { seed = Math.floor(Math.random() * 1e6); run(); }, { small: true })));
    } catch (e) { if (!e.cancelled) ctx.toast(errText(e), 'error'); } finally { gen.disabled = false; gen.textContent = 'Generate sample'; }
  };
  async function save(e) {
    if (!name.value.trim()) return ctx.toast('Name the voice first', 'info');
    const btn = e?.currentTarget;
    if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
    try {
      // Same seed, text and description: Breeze makes the same sample again and keeps it as the reference.
      const v = (await callRoom(ctx, 'POST', '/v1/voices/design', { json: { name: name.value.trim(), instruction: desc.value.trim(), sample_text: sample.value.trim() || SAMPLE, seed } })).json;
      ctx.toast(`Saved voice ${v.name}`, 'success'); out.replaceChildren(); name.value = ''; refresh();
    } catch (err) { if (!err.cancelled) ctx.toast(errText(err), 'error'); if (btn) { btn.disabled = false; btn.textContent = 'Save voice'; } }
  }
  const gen = ui.button('Generate sample', run, { kind: 'primary' });
  return panel(header('Design a voice'), field('Description', desc), field('Sample text', sample), ui.row(gen), out);
}
