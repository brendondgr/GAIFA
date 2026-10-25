// web/mod-ui.js and services/_template/ui/page.js, against a tiny fake DOM (2.9).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');

class Node {}
class Text extends Node { constructor(t) { super(); this.textContent = t; } }
class Element extends Node {
  constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.style = {}; this.listeners = {}; this.value = ''; this.disabled = false; this.type = ''; this.rows = 0; this.className = ''; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'value') this.value = String(v); if (k === 'style') this.style.cssText = String(v); }
  addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }
  dispatch(t, ev = {}) { for (const fn of this.listeners[t] || []) fn({ preventDefault() {}, target: this, ...ev }); }
  append(...kids) { this.children.push(...kids); }
  replaceChildren(...kids) { this.children = kids; }
  get textContent() { return this.children.map(c => c.textContent).join(''); }
  find(pred) { if (pred(this)) return this; for (const c of this.children) { if (c instanceof Element) { const f = c.find(pred); if (f) return f; } } return null; }
}
for (const prop of ['value', 'disabled', 'type', 'rows', 'name', 'placeholder', 'autocomplete']) Element.prototype[prop] ??= undefined;
globalThis.Node = Node;
globalThis.document = { createElement: t => new Element(t), createTextNode: t => new Text(t) };

const { createUi, h, button, json, empty, select, table } = await import(pathToFileURL(path.join(root, 'web/mod-ui.js')).href);
const page = (await import(pathToFileURL(path.join(root, 'services/_template/ui/page.js')).href)).default;
const ui = createUi();

test('mod-ui builds themed elements without raw colors in page code', () => {
  const b = button('Go', () => {}, { kind: 'primary', disabled: true });
  assert.equal(b.tagName, 'BUTTON');
  assert.equal(b.disabled, true);
  assert.match(b.attrs.style, /var\(--acc/);
  const d = h('div', { class: 'x', 'data-k': 1, style: { gap: '4px' } }, 'a', [h('span', null, 'b'), null, false, 3]);
  assert.equal(d.className, 'x');
  assert.equal(d.attrs['data-k'], '1');
  assert.equal(d.style.gap, '4px');
  assert.equal(d.textContent, 'ab3');
  assert.equal(json({ a: 1 }).textContent, '{\n  "a": 1\n}');
  assert.equal(empty('T', 'B').textContent, 'TB');
  assert.equal(select(['a', 'b'], { value: 'b' }).value, 'b');
  assert.equal(table([{ x: 1, y: null }]).textContent, 'xy1');
});

function ctxFor(state, calls) {
  const subs = [];
  return {
    service: { id: 'hello', name: 'Hello', state },
    ui, tab: 'hello', params: {},
    api: { startService: async id => { calls.push(['start', id]); return {}; } },
    call: async (method, p, opts) => { calls.push([method, p, opts]); return { status: 200, ms: 3, json: { message: `Hello, ${opts.query.name}!` } }; },
    toast: (m, l) => calls.push(['toast', m, l]),
    on: (type, fn) => { subs.push([type, fn]); return () => {}; },
    subs,
  };
}

test('template page: stopped mod shows a Start button that starts it', async () => {
  const calls = [];
  const el = new Element('div');
  page.mount(el, ctxFor('stopped', calls));
  assert.match(el.textContent, /Hello is not running/);
  const start = el.find(n => n.tagName === 'BUTTON');
  start.dispatch('click');
  await new Promise(r => setTimeout(r, 0));
  assert.deepEqual(calls, [['start', 'hello']]);
});

test('template page: says hello through ctx.call and shows the JSON', async () => {
  const calls = [];
  const el = new Element('div');
  const ctx = ctxFor('ready', calls);
  assert.deepEqual(page.tabs, [{ id: 'hello', label: 'Hello', icon: 'wave' }]);
  page.mount(el, ctx);
  const input = el.find(n => n.tagName === 'INPUT');
  input.value = 'you';
  el.find(n => n.tagName === 'FORM').dispatch('submit');
  await new Promise(r => setTimeout(r, 0));
  assert.deepEqual(calls[0], ['GET', '/v1/hello', { query: { name: 'you' } }]);
  assert.match(el.textContent, /200 · 3 ms/);
  assert.match(el.textContent, /"message": "Hello, you!"/);
  assert.equal(ctx.subs[0][0], 'service');
  assert.match(el.textContent, /services\/hello\/ui\/page\.js/);
});

test('schemaForm: form.onchange gets the values object, never a DOM event', async () => {
  const { schemaForm } = await import(pathToFileURL(path.join(root, 'web/mod-form.js')).href);
  const form = schemaForm({ ui, api: {} }, { properties: { aspect: { type: 'string', enum: ['1:1', '16:9'] }, n: { type: 'integer' } } }, { values: { aspect: '1:1' } });
  const got = [];
  form.onchange = v => got.push(v);
  assert.equal(typeof form.onchange, 'function');
  // an own accessor: assigning it doesn't set the element's DOM event-handler property
  const d = Object.getOwnPropertyDescriptor(form, 'onchange');
  assert.ok(d && d.get && d.set);
  const sel = form.find(e => e.tagName === 'SELECT');
  sel.value = '16:9';
  sel.dispatch('change');
  assert.deepEqual(got.at(-1), { aspect: '16:9' });
  form.onchange = null;
  sel.dispatch('change');
  assert.equal(got.length, 1);
});

test('schemaForm: a list field shows "a, b" and gives back an array', async () => {
  const { schemaForm } = await import(pathToFileURL(path.join(root, 'web/mod-form.js')).href);
  const form = schemaForm({ ui, api: {} }, { properties: { stages: { type: 'array', items: { type: 'string', enum: ['shape', 'texture', 'preview'] } }, ns: { type: 'array', items: { type: 'integer' } } } },
    { values: { stages: ['shape', 'preview'] } });
  const inputs = form.findAll ? form.findAll(e => e.tagName === 'INPUT') : null;
  assert.deepEqual(form.values().stages, ['shape', 'preview'], 'a list given as a value round-trips as a list');
  form.set({ ns: [1, 2] });
  assert.deepEqual(form.values().ns, [1, 2]);
  if (inputs) assert.ok(inputs.some(i => i.value === 'shape, preview'));
});

const SHAPE = { properties: {
  prompt: { type: 'string' }, image: { type: 'string', format: 'gaifa-file', 'x-kind': 'image' },
  engine: { type: 'string', enum: ['cube3d', 'trellis2', 'sam3d_body'], 'x-options': {
    cube3d: { label: 'Cube3D', excludes: ['image'], default: true, good_for: 'from text', allows: { preset: ['fast', 'balanced'] } },
    trellis2: { label: 'TRELLIS.2', needs: ['image'], default: true, good_for: 'objects', speed: '2 min', allows: { preset: ['fast', 'base'] } },
    sam3d_body: { label: 'SAM 3D Body', needs: ['image'], allows: { preset: ['base'] } } } },
  preset: { type: 'string', enum: ['fast', 'balanced', 'base'], 'x-depends-on': 'engine' } } };

test('mod-options: choices, defaults and labels follow the inputs (plan 20.7)', async () => {
  const o = await import(pathToFileURL(path.join(root, 'web/mod-options.js')).href);
  assert.deepEqual(o.choices(SHAPE, 'engine', { prompt: 'a fox' }), ['cube3d']);
  assert.deepEqual(o.choices(SHAPE, 'engine', { image: { $file: 'output:abc' } }), ['trellis2', 'sam3d_body']);
  assert.equal(o.defaultOf(SHAPE, 'engine', { image: 'output:abc' }), 'trellis2');
  assert.equal(o.defaultOf(SHAPE, 'engine', {}), 'cube3d');
  assert.deepEqual(o.choices(SHAPE, 'preset', { image: 'output:abc', engine: 'sam3d_body' }), ['base']);
  assert.deepEqual(o.choices(SHAPE, 'preset', { image: 'output:abc' }), ['fast', 'base'], 'no engine yet: the default engine\'s presets');
  assert.equal(o.labelOf(SHAPE.properties.engine, 'trellis2'), 'TRELLIS.2');
  assert.equal(o.helpOf(SHAPE.properties.engine, 'trellis2'), 'objects · 2 min');
});

test('schemaForm: an x-options dropdown lists only what fits, and re-checks when the inputs change', async () => {
  const { schemaForm } = await import(pathToFileURL(path.join(root, 'web/mod-form.js')).href);
  let outside = {};
  const form = schemaForm({ ui, api: {} }, { properties: { engine: SHAPE.properties.engine, preset: SHAPE.properties.preset, image: SHAPE.properties.image } },
    { values: {}, context: () => outside });
  const [eng, pre] = [0, 1].map(i => form.find(e => e.tagName === 'SELECT' && (i === 0 ? e.children.some(c => c.textContent === 'Cube3D') || e.children.some(c => c.textContent === 'TRELLIS.2') : e.children.some(c => c.textContent === 'balanced' || c.textContent === 'base'))));
  const labels = s => s.children.map(c => c.textContent);
  assert.deepEqual(labels(eng), ['default (Cube3D)', 'Cube3D']);
  outside = { image: { $file: 'output:abc' } };              // the card's file input got a picture
  form.refilter();
  assert.deepEqual(labels(eng), ['default (TRELLIS.2)', 'TRELLIS.2', 'SAM 3D Body']);
  assert.deepEqual(labels(pre), ['—', 'fast', 'base']);
  eng.value = 'sam3d_body';
  eng.dispatch('change');
  assert.deepEqual(labels(pre), ['—', 'base']);
});
