// Speech to Text's own tabs (plan 29.3): Transcribe (drop a recording; recent transcripts) and Models
// (download, load, unload). Uses only ctx (design brief §5); the file goes to Outputs first, then
// POST /v1/transcribe takes it by output id, so the recording stays next to its transcript.

import { panel, header, segmented, stat, fmtSecs, fmtAgo, requireRunning, callRoom, store, MONO } from '/mod-kit.js';
import { h } from '/mod-ui.js';

const PRESETS = [
  { value: 'fast', label: 'Fast' }, { value: 'balanced', label: 'Balanced' },
  { value: 'accurate', label: 'Accurate' }, { value: 'best', label: 'Best' },
];
const MEDIA = /^(audio|video)\//;
const tone = { done: 'green', failed: 'red', cancelled: 'dim', running: 'accent', queued: 'dim' };

export default {
  tabs: [{ id: 'transcribe', label: 'Transcribe', icon: 'wave' }, { id: 'models', label: 'Models', icon: 'cube' }],

  mount(el, ctx) {
    if (!requireRunning(el, ctx, 'speech to text')) return;
    return ctx.tab === 'models' ? models(el, ctx) : transcribe(el, ctx);
  },
};

function transcribe(el, ctx) {
  const { ui } = ctx;
  const st = { preset: store.get('stt.preset', 'balanced'), language: store.get('stt.language', '') };
  const timers = [];
  const picker = h('input', { type: 'file', accept: 'audio/*,video/*', multiple: true, hidden: true, onchange: e => { send(e.target.files); e.target.value = ''; } });
  const zone = h('div', {
    role: 'button', tabindex: '0', 'aria-label': 'Drop a recording here, or choose one',
    style: 'display:flex;flex-direction:column;align-items:center;gap:6px;padding:26px 16px;border:1px dashed var(--bds,#2A3547);border-radius:9px;cursor:pointer;text-align:center',
    onclick: () => picker.click(), onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); picker.click(); } },
    ondragover: e => { e.preventDefault(); zone.style.borderColor = 'var(--cy,#39C5CF)'; },
    ondragleave: () => { zone.style.borderColor = 'var(--bds,#2A3547)'; },
    ondrop: e => { e.preventDefault(); zone.style.borderColor = 'var(--bds,#2A3547)'; send(e.dataTransfer.files); },
  }, h('strong', { style: 'font-size:13px' }, 'Drop a recording here'),
    ui.text('Audio or video, any length. It is saved to Outputs, then transcribed to Markdown with [mm:ss] marks, subtitles and word times.', { muted: true, small: true }), picker);
  const preset = segmented(PRESETS, st.preset, v => { st.preset = v; store.set('stt.preset', v); }, 'Preset');
  const lang = ui.input({ placeholder: 'detect', value: st.language, oninput: e => { st.language = e.target.value.trim(); store.set('stt.language', st.language); } });
  lang.style.width = '90px';
  const status = h('div', { role: 'status', style: 'font-size:12px;color:var(--mut,#8A94A6);min-height:16px' });
  const list = h('div', { style: 'display:flex;flex-direction:column;gap:8px' });

  async function send(files) {
    const media = [...(files || [])].filter(f => MEDIA.test(f.type || '') || /\.(wav|mp3|flac|ogg|opus|m4a|aac|mp4|webm|mov|mkv)$/i.test(f.name || ''));
    if (!media.length) return ctx.toast('Choose an audio or video file', 'info');
    for (const f of media) {
      status.textContent = `Uploading ${f.name}…`;
      try {
        const out = await ctx.api.uploadOutput(f);
        await callRoom(ctx, 'POST', '/v1/transcribe', { json: { audio: `output:${out.id}`, preset: st.preset, language: st.language || null, title: f.name.replace(/\.[^.]+$/, '') } });
      } catch (e) {
        if (!e.cancelled) ctx.toast(`${f.name}: ${e.detail || e.message}`, 'error');
      }
    }
    status.textContent = '';
    refresh();
  }

  function jobRow(j) {
    const text = h('pre', { hidden: true, style: `margin:0;white-space:pre-wrap;font-family:${MONO};font-size:12px;line-height:1.6;max-height:360px;overflow:auto;background:var(--inset,#131926);border-radius:7px;padding:10px` }, j.transcript || '');
    const acts = [];
    if (j.state === 'done' && j.transcript) acts.push(ui.button('Show text', () => { text.hidden = !text.hidden; }, { small: true }));
    if (j.state === 'done' && j.result?.output) acts.push(ui.button('Outputs', () => ctx.navigate('#/outputs?service=stt'), { small: true }));
    if (j.state === 'queued' || j.state === 'running') acts.push(ui.button('Cancel', () => ctx.call('POST', `/v1/jobs/${j.id}/cancel`).then(refresh), { small: true }));
    const gpu = j.stage === 'waiting_gpu' && j.ahead?.length ? `after ${j.ahead[0].service}${j.ahead[0].label ? ` (${j.ahead[0].label})` : ''}${j.eta_s ? `, about ${Math.max(1, Math.round(j.eta_s / 60))} min` : ''}` : null;
    const meta = [gpu, j.model, j.duration != null ? fmtSecs(j.duration) : null, j.rtf != null ? `${(1 / j.rtf).toFixed(0)}× real time` : null, fmtAgo(j.created)].filter(Boolean).join(' · ');
    return h('div', { style: 'display:flex;flex-direction:column;gap:6px;padding:10px;border:1px solid var(--bd,#1D2430);border-radius:8px' },
      h('div', { style: 'display:flex;align-items:center;gap:8px;min-width:0' },
        h('strong', { style: 'font-size:12.5px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap' }, j.label),
        ui.badge(j.stage === 'waiting_gpu' ? 'Waiting for the GPU…' : j.state === 'running' ? `${j.stage} ${Math.round(j.progress * 100)}%` : j.state, tone[j.state]), ...acts),
      h('span', { style: 'font-size:11.5px;color:var(--mut,#8A94A6)' }, j.error ? `${meta} · ${j.error}` : meta),
      text);
  }

  async function refresh() {
    let jobs = [];
    try { jobs = (await ctx.call('GET', '/v1/jobs')).json.jobs || []; } catch { /* the next poll tries again */ }
    list.replaceChildren(...(jobs.length ? jobs.slice(0, 20).map(jobRow) : [ui.text('No transcripts yet.', { muted: true })]));
    if (jobs.some(j => j.state === 'queued' || j.state === 'running')) timers.push(setTimeout(refresh, 1200));
  }

  el.append(h('div', { style: 'display:flex;flex-direction:column;gap:12px;max-width:900px' },
    panel(header('Transcribe a recording', h('span', { style: 'font-size:12px;color:var(--mut,#8A94A6)' }, 'Language'), lang, preset), zone, status),
    panel(header('Recent transcripts', ui.button('Refresh', refresh, { small: true })), list)));
  refresh();
  ctx.on('output', refresh);
  return () => timers.forEach(clearTimeout);
}

function models(el, ctx) {
  const { ui } = ctx;
  const body = h('div', { style: 'display:flex;flex-direction:column;gap:12px;max-width:900px' });
  el.append(body);

  async function draw() {
    let m;
    try { m = (await ctx.call('GET', '/v1/models')).json; } catch (e) { body.replaceChildren(ui.text(e.detail || 'Could not read the models', { muted: true })); return; }
    const eng = m.engine || {};
    const busy = eng.state === 'loading';
    const row = x => h('div', { style: 'display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--bd,#1D2430)' },
      h('div', { style: 'flex:1;min-width:0;display:flex;flex-direction:column;gap:2px' },
        h('span', { style: 'font-size:13px;font-weight:600' }, x.name, x.preset ? h('span', { style: 'font-weight:400;color:var(--mut,#8A94A6)' }, ` · ${x.preset}${x.default ? ' (default)' : ''}`) : null),
        h('span', { style: 'font-size:11.5px;color:var(--mut,#8A94A6)' }, `${x.size} · ${x.device} at ${x.precision} · ${x.note}`)),
      x.loaded ? ui.badge('loaded', 'green') : x.downloaded ? ui.badge('downloaded') : ui.badge('not downloaded', 'dim'),
      x.loaded ? ui.button('Unload', () => act('POST', '/v1/unload'), { small: true, disabled: busy })
        : ui.button(x.downloaded ? 'Load' : 'Download & load', () => act('POST', '/v1/load', { model: x.name }), { small: true, disabled: busy }));
    const notices = (eng.notices || []).slice(-3).map(n => ui.text(`${new Date(n.ts * 1000).toLocaleTimeString()} · ${n.kind === 'fell-back' ? 'moved to the CPU' : 'restarted'}: ${n.detail}`, { small: true, muted: true }));
    body.replaceChildren(
      panel(header('Engine'), h('div', { style: 'display:flex;gap:24px;flex-wrap:wrap' },
        stat('State', eng.message || eng.state || '—'), stat('Model', eng.model || 'none'), stat('Runs on', eng.device ? `${eng.device} · ${eng.precision}` : (m.gpu ? 'GPU available' : 'CPU')),
        stat('Restarts', String(eng.restarts ?? 0))),
        eng.fell_back ? ui.text('The GPU faulted repeatedly, so the model moved to the CPU until it is loaded again.', { small: true }) : null,
        eng.error ? ui.text(eng.error, { small: true }) : null, ...notices),
      panel(header('Models', ui.button('Refresh', draw, { small: true })), h('div', null, ...(m.models || []).map(row))));
    if (busy) setTimeout(draw, 1000);
  }

  async function act(method, path, json) {
    try { await callRoom(ctx, method, path, json ? { json } : {}); }
    catch (e) { if (!e.cancelled) ctx.toast(e.detail || e.message, 'error'); }
    draw();
  }
  draw();
}
