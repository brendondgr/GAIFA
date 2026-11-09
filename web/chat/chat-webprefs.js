// Settings → Permissions → Screening and Agent → Reading web pages (plan settings-redesign 2.1, 4.3): the choices for
// which model screens pages for instructions aimed at an AI (config.toml [agent.screen], utils/tools/screen.py) and how
// web_fetch returns a long page ([agent.web] relevance, utils/tools/webread.py). The values are rows of the Settings
// page's draft (web/settings/schema.js); `ScreenModelPick` edits the screening model there, with the choices from
// GET /api/web/reading (api.getWebReading). Pure parts tested in utils/tests/web/chat-webprefs.test.mjs.

import { h, T, MONO, inputSt } from './chat-ui.js';

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
export function screenPatch(way, { model, threshold } = {}) {
  if (way === 'judge') return { backend: null, model: null, url: null, threshold: null };
  if (way === 'decide') return { backend: 'decide', model: model || 'd3-lite', url: null, threshold: threshold ?? 0.95 };
  return { backend: 'relay', model: model || null, url: null, threshold: null };
}

/** A number of days for [outputs] hidden_keep_days, or an error. */
export function checkDays(v) {
  const s = String(v ?? '').trim();
  if (!/^\d+(\.\d+)?$/.test(s)) return { error: 'A number of days, 0 or more' };
  const n = Number(s);
  return n > 3650 ? { error: 'At most 3650 days' } : { value: n };
}

const sel = { ...inputSt, height: 28, fontSize: 12.5 };
const row = (label, hint, control) => h('div', { style: { display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' } },
  h('div', { style: { flex: '1 1 220px', minWidth: 0 } }, h('div', { style: { fontWeight: 500 } }, label), hint ? h('div', { style: { fontSize: 12, color: T.mut } }, hint) : null), control);
/** A model picker: the backend's choices, else a text box. */
function ModelPick({ label, value, choices, placeholder, onChange }) {
  const list = [...new Set([...(choices || []), ...(value ? [value] : [])])];
  return list.length
    ? h('select', { 'aria-label': label, value: value || '', style: sel, onChange: e => onChange(e.target.value) },
      value ? null : h('option', { value: '' }, 'pick one'), list.map(c => h('option', { key: c, value: c }, c)))
    : h('input', { 'aria-label': label, value: value || '', placeholder, style: { ...sel, width: 180 }, onChange: e => onChange(e.target.value) });
}

/** "Screen pages with" on the Settings page's draft (settings-redesign 2.1): the way (the judge's decision model, another
 *  decision model, a chat model), its model from GET /api/web/reading's choices, and for a decision model its threshold.
 *  (No "confirm with the judge's chat model": the judge is a decision model only, plan web-approvals.) `screen` is the
 *  draft's [agent.screen]; `onChange(patch)` merges into it. */
export function ScreenModelPick({ screen, reading, onChange }) {
  const sc = screen || {}, way = screenWay(sc);
  const judge = reading?.judge ? `${reading.judge.model} (decision model)` : '';
  const now = reading?.screen ? `Now: ${reading.screen.model}.` : '';
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 10, padding: '14px 0' } },
    row('Screen pages with', [judge ? `The judge is ${judge}.` : '', now].filter(Boolean).join(' '),
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' } },
        h('select', { 'aria-label': 'Screen pages with', value: way, style: sel, onChange: e => onChange(screenPatch(e.target.value, { threshold: sc.threshold })) },
          SCREEN_WAYS.map(([k, l]) => h('option', { key: k, value: k }, l))),
        way === 'judge' ? null : h(ModelPick, { label: 'Screening model', value: sc.model || '', choices: reading?.choices?.[way], placeholder: way === 'decide' ? 'd3-lite' : 'a model name', onChange: v => onChange({ model: v || null }) }))),
    way === 'decide' ? row('Threshold', 'A passage passes when the decision model is at least this sure it’s for a human reader.',
      h('input', { type: 'number', min: 0.5, max: 1, step: 0.01, value: sc.threshold ?? 0.95, 'aria-label': 'Screening threshold', style: { ...sel, width: 80, fontFamily: MONO }, onChange: e => onChange({ threshold: Number(e.target.value) }) })) : null,
    way === 'decide' && reading && !reading.decide_up ? h('span', { role: 'note', style: { fontSize: 12, color: T.acct } }, 'The decide mod isn’t running: start it on its page, or pages are screened by fixed patterns only.') : null);
}
