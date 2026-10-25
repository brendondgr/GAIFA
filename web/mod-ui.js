// ctx.ui for mod page modules (design brief §5, docs/mods.md): small DOM helpers that
// use GAIFA's theme variables, so a page looks native in both themes without raw colors.
// Written by us, not Claude Design. Every helper returns a plain DOM element.

const MONO = "'JetBrains Mono',ui-monospace,monospace";
const TONES = {
  green: ['var(--gr,#3FB950)', 'var(--tgr,rgba(63,185,80,.13))'],
  red: ['var(--rd,#F85149)', 'var(--trd,rgba(248,81,73,.13))'],
  accent: ['var(--acct,#FFB224)', 'var(--tacc,rgba(255,178,36,.13))'],
  dim: ['var(--mut,#8A94A6)', 'var(--inset,#131926)'],
};
const BUTTONS = {
  primary: 'background:var(--acc,#FFB224);color:#1A1200;border-color:transparent;font-weight:600',
  secondary: '',
  danger: 'background:var(--trd,rgba(248,81,73,.13));color:var(--rd,#F85149);border-color:var(--rd,#F85149)',
  ghost: 'background:transparent;border-color:transparent;color:var(--mut,#8A94A6)',
};
const CONTROL = 'height:32px;padding:0 10px;border-radius:6px;border:1px solid var(--bds,#2A3547);background:var(--sb,#0D1119);color:var(--tx,#E6EAF2);font:inherit;font-size:13px;min-width:0';

/** h('div', { style, onclick, class, ...attrs }, ...children). Children: strings, nodes, arrays, null. */
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs && (typeof attrs !== 'object' || attrs instanceof Node || Array.isArray(attrs))) { children.unshift(attrs); attrs = null; }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'class' || k === 'className') el.className = v;
    else if (k in el && typeof v !== 'string') el[k] = v;
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export const text = (s, o = {}) => h('p', { style: `margin:0;font-size:${o.small ? 11.5 : 12.5}px;${o.muted ? 'color:var(--mut,#8A94A6);' : ''}${o.mono ? `font-family:${MONO};` : ''}` }, s);

export const row = (...kids) => h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap;align-items:center' }, ...kids);
export const stack = (...kids) => h('div', { style: 'display:flex;flex-direction:column;gap:10px;min-width:0' }, ...kids);

export const card = (...kids) => h('section', { style: 'max-width:760px;background:var(--card,#11151D);border:1px solid var(--bd,#1D2430);border-radius:10px;padding:18px;display:flex;flex-direction:column;gap:14px;min-width:0' }, ...kids);

/** button(label, onClick, { kind: 'primary'|'secondary'|'danger'|'ghost', type, disabled, small }) */
export function button(label, onClick, o = {}) {
  const st = `display:inline-flex;align-items:center;justify-content:center;gap:6px;height:${o.small ? 28 : 32}px;padding:0 ${o.small ? 10 : 12}px;border-radius:6px;font:inherit;font-size:${o.small ? 12 : 12.5}px;font-weight:500;cursor:pointer;white-space:nowrap;border:1px solid var(--bds,#2A3547);background:var(--inset,#131926);color:var(--tx,#E6EAF2);${BUTTONS[o.kind || 'secondary'] || ''}`;
  return h('button', { type: o.type || 'button', style: st, onclick: onClick || null, disabled: !!o.disabled }, label);
}

/** input({ value, placeholder, name, type, oninput }) */
export const input = (o = {}) => h('input', { type: o.type || 'text', value: o.value ?? '', placeholder: o.placeholder, name: o.name, autocomplete: 'off', style: CONTROL, oninput: o.oninput });
export const textarea = (o = {}) => h('textarea', { placeholder: o.placeholder, name: o.name, rows: o.rows || 4, style: CONTROL.replace('height:32px;', '') + ';padding:8px 10px;resize:vertical', oninput: o.oninput }, o.value ?? '');

/** select([{ value, label }] or ['a', 'b'], { value, onchange }) */
export function select(options, o = {}) {
  const el = h('select', { style: CONTROL, onchange: o.onchange, name: o.name },
    options.map(x => (typeof x === 'object' ? x : { value: x, label: x })).map(x => h('option', { value: x.value }, x.label ?? x.value)));
  if (o.value != null) el.value = o.value;
  return el;
}

/** field('Name', control, 'optional hint'): a label wrapping its control */
export const field = (label, control, hint) => h('label', { style: 'display:flex;flex-direction:column;gap:5px;flex:1 1 220px;min-width:0' },
  h('span', { style: 'font-size:12px;font-weight:500' }, label), control,
  hint ? h('span', { style: 'font-size:11.5px;color:var(--mut,#8A94A6)' }, hint) : null);

/** json(value): formatted, selectable JSON */
export const json = value => h('pre', { style: `margin:0;background:var(--inset,#131926);border:1px solid var(--bd,#1D2430);border-radius:8px;padding:10px 12px;font-family:${MONO};font-size:12px;line-height:1.6;overflow:auto;max-height:420px;white-space:pre-wrap;word-break:break-word` },
  JSON.stringify(value, null, 2));

/** badge('ready', 'green' | 'red' | 'accent' | 'dim') */
export function badge(label, tone = 'dim') {
  const [fg, bg] = TONES[tone] || TONES.dim;
  return h('span', { style: `display:inline-flex;align-items:center;height:22px;padding:0 9px;border-radius:99px;font-size:11.5px;font-weight:500;color:${fg};background:${bg}` }, label);
}

/** empty(title, body, action?): the "nothing here / not running" state */
export const empty = (title, body, action) => h('div', { style: 'padding:44px 20px;display:flex;flex-direction:column;align-items:center;gap:10px;text-align:center;border:1px dashed var(--bds,#2A3547);border-radius:12px' },
  h('h2', { style: 'margin:0;font-size:16px' }, title),
  body ? h('p', { style: 'margin:0;color:var(--mut,#8A94A6);max-width:440px' }, body) : null,
  action || null);

/** table(rows, columns?): columns default to the first row's keys */
export function table(rows, columns) {
  const cols = columns || Object.keys(rows[0] || {});
  const cell = 'padding:6px 10px;border-bottom:1px solid var(--bd,#1D2430);text-align:left;font-size:12.5px';
  return h('div', { style: 'overflow:auto;max-width:100%' }, h('table', { style: 'border-collapse:collapse;width:100%' },
    h('thead', h('tr', cols.map(c => h('th', { style: cell + ';color:var(--mut,#8A94A6);font-weight:500' }, c)))),
    h('tbody', rows.map(r => h('tr', cols.map(c => h('td', { style: cell }, r[c] == null ? '' : String(r[c]))))))));
}

export function createUi() {
  return { h, text, row, stack, card, button, input, textarea, select, field, json, badge, empty, table };
}
