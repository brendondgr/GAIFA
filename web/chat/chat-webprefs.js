// Settings → Permissions → Screening and Agent → Reading web pages: which model screens pages for instructions aimed at an AI
// (config.toml [agent.screen], utils/tools/screen.py), how web_fetch returns a long page ([agent.web] relevance,
// utils/tools/webread.py), and when saved web pages are cleaned up ([outputs] hidden_keep_days, plan 30.9).
// Reads GET /api/web/reading (api.getWebReading: the models each backend offers, what relevance uses now) and saves
// through PUT /api/settings (api.saveSettings); a 422 invalid_config names the field. Pure parts tested in
// utils/tests/web/chat-webprefs.test.mjs.

import { h, T, MONO, Btn, Badge, cardSt, label11, inputSt } from './chat-ui.js';

const R = () => globalThis.React;

export const SCREEN_WAYS = [
  ['judge', 'Same as the judge'],
  ['decide', 'A decision model (decide)'],
  ['relay', 'Another chat model'],
];
export const RELEVANCE = [
  ['auto', 'Automatic', 'The decision model when the decide mod is up with its model loaded, else words in common'],
  ['decide', 'A decision model', 'The decide mod scores the best candidates: “does this passage help answer the question?”'],
  ['lexical', 'Words in common', 'Passages sharing the question’s words (fast, no model)'],
  ['off', 'Off', 'The page’s start, up to the call’s limit'],
];

/** Which "Screen pages with" choice `[agent.screen]` is: judge (no model of its own), decide or relay. */
export function screenWay(screen) {
  if (!screen || (!screen.backend && !screen.model)) return 'judge';
  return screen.backend === 'decide' ? 'decide' : 'relay';
}

/** The `screen` patch for a choice. The URL is left to the backend's default (null). */
export function screenPatch(way, { model, threshold, confirm } = {}) {
  if (way === 'judge') return { backend: null, model: null, url: null, threshold: null };
  if (way === 'decide') return { backend: 'decide', model: model || 'd3-lite', url: null, threshold: threshold ?? 0.95, confirm: confirm !== false };
  return { backend: 'relay', model: model || null, url: null, threshold: null };
}

/** A number of days for [outputs] hidden_keep_days, or an error. */
export function checkDays(v) {
  const s = String(v ?? '').trim();
  if (!/^\d+(\.\d+)?$/.test(s)) return { error: 'A number of days, 0 or more' };
  const n = Number(s);
  return n > 3650 ? { error: 'At most 3650 days' } : { value: n };
}

/** A number field saved when it loses focus: only a whole number that changed. */
function onNumber(e, was, go) {
  const v = Number(e.target.value);
  if (Number.isInteger(v) && v !== was) go(v);
}
const errText = e => String(e?.detail || e?.message || e).replace(/Value error, /g, '');
const sel = { ...inputSt, height: 28, fontSize: 12.5 };
const row = (label, hint, control) => h('div', { style: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' } },
  h('div', { style: { flex: '1 1 220px', minWidth: 0 } }, h('div', { style: { fontWeight: 500 } }, label), hint ? h('div', { style: { fontSize: 12, color: T.mut } }, hint) : null), control);
const check = (label, checked, onChange, title) => h('label', { title, style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5 } },
  h('input', { type: 'checkbox', checked: !!checked, onChange: e => onChange(e.target.checked) }), label);

/** A model picker: the backend's choices, else a text box. */
function ModelPick({ label, value, choices, placeholder, onChange }) {
  const list = [...new Set([...(choices || []), ...(value ? [value] : [])])];
  return list.length
    ? h('select', { 'aria-label': label, value: value || '', style: sel, onChange: e => onChange(e.target.value) },
      value ? null : h('option', { value: '' }, 'pick one'), list.map(c => h('option', { key: c, value: c }, c)))
    : h('input', { 'aria-label': label, value: value || '', placeholder, style: { ...sel, width: 180 }, onChange: e => onChange(e.target.value) });
}

export function WebReadingSection({ api, toast = () => {} }) {
  const React = R(), [cfg, setCfg] = React.useState(null), [st, setSt] = React.useState(null), [msg, setMsg] = React.useState(null);
  const [draft, setDraft] = React.useState(null), [busy, setBusy] = React.useState(false), [days, setDays] = React.useState('');
  const load = () => {
    api?.getSettings?.().then(s => { setCfg(s); setDays(String(s?.outputs?.hidden_keep_days ?? 0)); }, () => setCfg(null));
    api?.getWebReading?.().then(setSt, () => setSt(null));
  };
  React.useEffect(load, []);
  if (!cfg?.screen || !api?.saveSettings) return null;
  const sc = cfg.screen, web = cfg.web || null;
  const d = draft || { way: screenWay(sc), model: sc.model || '', threshold: sc.threshold ?? 0.95, confirm: sc.confirm !== false };
  const set = patch => setDraft({ ...d, ...patch });
  const save = async (body, what = 'Saved') => {
    setBusy(true); setMsg(null);
    try { const r = await api.saveSettings(body); setCfg(r.settings); setDraft(null); setDays(String(r.settings?.outputs?.hidden_keep_days ?? 0)); toast(what, 'success'); api.getWebReading?.().then(setSt, () => {}); }
    catch (e) { setMsg({ error: `Couldn’t save: ${errText(e)}` }); } finally { setBusy(false); }
  };
  const dirty = draft && (d.way !== screenWay(sc) || (d.way !== 'judge' && (d.model !== (sc.model || '') ||
    (d.way === 'decide' && (Number(d.threshold) !== (sc.threshold ?? 0.95) || d.confirm !== (sc.confirm !== false))))));
  const judge = st?.judge ? `${st.judge.model} (${st.judge.backend === 'decide' ? 'decision model' : 'chat model'})` : cfg.judge?.model;
  const now = st?.screen ? `Now: ${st.screen.model}${st.screen.confirm ? `, confirmed by ${st.screen.confirm}` : ''}.` : '';
  const dd = checkDays(days);
  return h('section', { style: cardSt({ pad: '14px 16px', gap: 10, style: { borderRadius: 10 } }) },
    h('h2', { style: { ...label11, margin: 0 } }, 'Reading web pages'),
    row('Screen fetched pages', 'Before the chat model reads a page, fixed patterns and a model remove passages that try to instruct an AI. The full page stays an output.',
      h('div', { style: { display: 'flex', gap: 12, flexWrap: 'wrap' } },
        check('Pages', sc.pages, v => save({ screen: { pages: v } })),
        check('Your documents', sc.documents, v => save({ screen: { documents: v } }), 'Uploads and files you attach'),
        check('Transcripts', sc.transcripts, v => save({ screen: { transcripts: v } })))),
    row('Screen pages with', [`The judge is ${judge || '—'}.`, now].filter(Boolean).join(' '),
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' } },
        h('select', { 'aria-label': 'Screen pages with', value: d.way, style: sel, onChange: e => set({ way: e.target.value, model: '' }) },
          SCREEN_WAYS.map(([k, l]) => h('option', { key: k, value: k }, l))),
        d.way === 'judge' ? null : h(ModelPick, { label: 'Screening model', value: d.model, choices: st?.choices?.[d.way], placeholder: d.way === 'decide' ? 'd3-lite' : 'a model name', onChange: v => set({ model: v }) }))),
    d.way === 'decide' ? row('Threshold', 'A passage passes when the decision model is at least this sure it’s for a human reader.',
      h('input', { type: 'number', min: 0.5, max: 1, step: 0.01, value: d.threshold, 'aria-label': 'Screening threshold', style: { ...sel, width: 80, fontFamily: MONO }, onChange: e => set({ threshold: Number(e.target.value) }) })) : null,
    d.way === 'decide' ? row('Confirm with the judge’s chat model', 'Decision models flag many ordinary passages; the judge’s chat model reads what it flags again and has the final say.',
      check('Let the judge’s chat model confirm what it flags', d.confirm, v => set({ confirm: v }))) : null,
    d.way === 'decide' && st && !st.decide_up ? h('span', { role: 'note', style: { fontSize: 12, color: T.acct } }, 'The decide mod isn’t running: start it on its page, or pages are screened by fixed patterns only.') : null,
    dirty ? h('div', { style: { display: 'flex', gap: 8 } },
      h(Btn, { kind: 'pri', sm: true, label: busy ? 'Saving…' : 'Save', disabled: busy || (d.way === 'relay' && !d.model), onClick: () => save({ screen: screenPatch(d.way, d) }) }),
      h(Btn, { kind: 'ghost', sm: true, label: 'Revert', onClick: () => setDraft(null) })) : null,
    row('Text per model call', 'Characters of passages in one screening call (800 suits a small model, 6000 a large one), and calls at once.',
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 6 } },
        h('input', { key: 'w' + sc.window_chars, type: 'number', min: 200, max: 20000, step: 200, defaultValue: sc.window_chars, 'aria-label': 'Characters per screening call', style: { ...sel, width: 86, fontFamily: MONO }, onBlur: e => onNumber(e, sc.window_chars, v => save({ screen: { window_chars: v } })) }),
        h('span', { style: { fontSize: 12, color: T.mut } }, 'chars ×'),
        h('input', { key: 'p' + sc.parallel, type: 'number', min: 1, max: 32, defaultValue: sc.parallel ?? 4, 'aria-label': 'Screening calls at once', style: { ...sel, width: 56, fontFamily: MONO }, onBlur: e => onNumber(e, sc.parallel ?? 4, v => save({ screen: { parallel: v } })) }))),
    web ? row('Long pages', `A page longer than the agent asked for comes back as its passages most relevant to the question, most relevant first, with line numbers to cite.${st?.relevance ? ` Now: ${RELEVANCE.find(r => r[0] === st.relevance)?.[1] || st.relevance}.` : ''}`,
      h('select', { 'aria-label': 'Long pages', value: web.relevance, style: sel, title: RELEVANCE.find(r => r[0] === web.relevance)?.[2], onChange: e => save({ web: { relevance: e.target.value } }) },
        RELEVANCE.map(([k, l, t]) => h('option', { key: k, value: k, title: t }, l)))) : null,
    web && (web.relevance === 'decide' || web.relevance === 'auto') ? row('Relevance model', 'The decision model that scores passages.',
      h(ModelPick, { label: 'Relevance model', value: web.model, choices: st?.choices?.decide, placeholder: 'd3-lite', onChange: v => v && save({ web: { model: v } }) })) : null,
    cfg.outputs ? row('Saved web pages', 'Pages the agent read are kept as hidden outputs (for citations and rereading). Delete them after this many days; 0 keeps them.',
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 6 } },
        h('input', { value: days, inputMode: 'decimal', 'aria-label': 'Delete saved web pages after (days)', 'aria-invalid': dd.error ? 'true' : 'false', style: { ...sel, width: 64, fontFamily: MONO }, onChange: e => setDays(e.target.value) }),
        h('span', { style: { fontSize: 12, color: T.mut } }, 'days'),
        h(Btn, { sm: true, label: 'Save', disabled: busy || !!dd.error || dd.value === cfg.outputs.hidden_keep_days, onClick: () => save({ outputs: { hidden_keep_days: dd.value } }) }),
        dd.error && days !== '' ? h('span', { role: 'alert', style: { fontSize: 12, color: T.rd } }, dd.error) : null,
        !dd.error && dd.value === 0 ? h(Badge, { tone: 'dim' }, 'kept') : null)) : null,
    msg ? h('span', { role: msg.error ? 'alert' : 'status', style: { fontSize: 12, color: msg.error ? T.rd : T.mut } }, msg.error || msg.ok) : null);
}

/** "Screen pages with" on the Settings page's draft (settings-redesign 2.1): the way (the judge, a decision model,
 *  another chat model), its model from GET /api/web/reading's choices, and for a decision model its threshold and
 *  whether the judge's chat model confirms. `screen` is the draft's [agent.screen]; `onChange(patch)` merges into it. */
export function ScreenModelPick({ screen, reading, onChange }) {
  const sc = screen || {}, way = screenWay(sc);
  const judge = reading?.judge ? `${reading.judge.model} (${reading.judge.backend === 'decide' ? 'decision model' : 'chat model'})` : '';
  const now = reading?.screen ? `Now: ${reading.screen.model}${reading.screen.confirm ? `, confirmed by ${reading.screen.confirm}` : ''}.` : '';
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10, padding: '14px 0' } },
    row('Screen pages with', [judge ? `The judge is ${judge}.` : '', now].filter(Boolean).join(' '),
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' } },
        h('select', { 'aria-label': 'Screen pages with', value: way, style: sel, onChange: e => onChange(screenPatch(e.target.value, { threshold: sc.threshold, confirm: sc.confirm })) },
          SCREEN_WAYS.map(([k, l]) => h('option', { key: k, value: k }, l))),
        way === 'judge' ? null : h(ModelPick, { label: 'Screening model', value: sc.model || '', choices: reading?.choices?.[way], placeholder: way === 'decide' ? 'd3-lite' : 'a model name', onChange: v => onChange({ model: v || null }) }))),
    way === 'decide' ? row('Threshold', 'A passage passes when the decision model is at least this sure it’s for a human reader.',
      h('input', { type: 'number', min: 0.5, max: 1, step: 0.01, value: sc.threshold ?? 0.95, 'aria-label': 'Screening threshold', style: { ...sel, width: 80, fontFamily: MONO }, onChange: e => onChange({ threshold: Number(e.target.value) }) })) : null,
    way === 'decide' ? row('Confirm with the judge’s chat model', 'Decision models flag many ordinary passages; the judge’s chat model reads what it flags again and has the final say.',
      check('Let the judge’s chat model confirm what it flags', sc.confirm !== false, v => onChange({ confirm: v }))) : null,
    way === 'decide' && reading && !reading.decide_up ? h('span', { role: 'note', style: { fontSize: 12, color: T.acct } }, 'The decide mod isn’t running: start it on its page, or pages are screened by fixed patterns only.') : null);
}
