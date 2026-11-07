// services/agent/ui/memory.js (structured-memory 5.1): the Memory tab's tree rows and the Review tab's grouping.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const M = await import(pathToFileURL(path.join(root, 'services/agent/ui/memory.js')).href);

test('the tree flattens with headings and depth', () => {
  const rows = M.treeRows({ kinds: [{ kind: 'user', entities: [{ id: 'user', name: 'You', kind: 'user', facts: 2, children: [] }] },
    { kind: 'project', entities: [{ id: 'e1', name: 'GAIFA', kind: 'project', facts: 3, children: [{ id: 'e2', name: 'agent', kind: 'topic', facts: 1, children: [] }] }] }] });
  assert.deepEqual(rows.map(r => r.heading || `${'  '.repeat(r.depth)}${r.name}`), ['You', 'You', 'Projects', 'GAIFA', '  agent']);
});

test('proposals group by their chat, and say what approving does', () => {
  const f = (id, ev, extra = {}) => ({ id, evidence: ev, ...extra });
  const g = M.byChat([f('a', [{ thread: 't1', seq: 3 }]), f('b', [{ action: 'merge', entity: 'x', into: 'y' }]), f('c', [{ thread: 't1' }])]);
  assert.deepEqual(g.map(x => [x.thread, x.items.map(i => i.id)]), [['t1', ['a', 'c']], ['', ['b']]]);
  assert.equal(M.actionText(f('d', [{ thread: 't' }, { action: 'rename', entity: 'e', to: 'GAIFA' }])), 'renames it to GAIFA');
  assert.equal(M.actionText(f('e', [], { replaces: 'f_1' })), 'replaces an older fact');
  assert.equal(M.actionText(f('g', [])), '');
});

// memory-auto-learning 2.3: why a proposal waits, the quote, and Review's two lists, against a tiny fake DOM.
class FNode {}
class FText extends FNode { constructor(t) { super(); this.textContent = String(t); } }
class FEl extends FNode {
  constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.style = {}; this.listeners = {}; this.value = ''; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === 'value') this.value = String(v); }
  addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }
  dispatch(t) { for (const fn of this.listeners[t] || []) fn({ preventDefault() {}, target: this }); }
  append(...kids) { this.children.push(...kids); }
  get textContent() { return this.children.map(c => c.textContent).join(''); }
  findAll(pred, out = []) { if (pred(this)) out.push(this); for (const c of this.children) if (c instanceof FEl) c.findAll(pred, out); return out; }
}
for (const prop of ['value', 'disabled', 'type', 'rows', 'name', 'placeholder', 'autocomplete', 'href']) FEl.prototype[prop] ??= undefined;
globalThis.Node ??= FNode;
globalThis.document ??= { createElement: t => new FEl(t), createTextNode: t => new FText(t) };

test('why a proposal waits, and the words it came from', () => {
  assert.equal(M.whyText({ evidence: [{ thread: 't', why: 'not sure: 0.55' }, { thread: 't2', why: 'sensitive: health' }] }), 'sensitive: health');
  assert.equal(M.whyText({ evidence: [{ thread: 't' }] }), '');
  assert.equal(M.quoteOf({ evidence: [{ thread: 't', quote: 'I prefer tea' }] }), 'I prefer tea');
});

test('Review: what was learned on its own (Keep, Not this) and what needs a look, with the reason', async () => {
  const { createUi } = await import(pathToFileURL(path.join(root, 'web/mod-ui.js')).href);
  const ui = createUi();
  const fact = (id, text, ev, extra = {}) => ({ id, text, kind: 'fact', entities: [{ id: 'user', path: 'you' }], evidence: ev, ...extra });
  const learned = [fact('f_a', 'The user prefers Python.', [{ thread: 't1', quote: 'I prefer Python' }], { auto_at: 1794000000 })];
  const proposed = [fact('f_b', 'The user should cut caffeine.', [{ thread: 't1', why: 'sensitive: health' }])];
  const calls = [];
  const ctx = { ui, call: async (m, p, o) => { calls.push([m, p, o?.json]); return { status: 200, json: p === '/v1/memory/auto' ? learned : m === 'GET' ? proposed : {} }; } };
  let renders = 0;
  const parts = (await M.memoryReview(ctx, e => { throw e; }, () => { renders++; })).filter(Boolean);
  const text = parts.map(p => p.textContent).join('|');
  assert.match(text, /Learned on its own \(1\)/);
  assert.match(text, /you said “I prefer Python”/);
  assert.match(text, /Needs your look \(1\)/);
  assert.match(text, /waiting: sensitive: health/);
  const buttons = parts.flatMap(p => p.findAll(e => e.tagName === 'BUTTON'));
  const [keep] = buttons.filter(b => b.textContent === 'Keep');
  const [notThisLearned] = buttons.filter(b => b.textContent === 'Not this');
  keep.dispatch('click');
  notThisLearned.dispatch('click');
  await new Promise(r => setTimeout(r, 0));
  assert.deepEqual(calls.slice(2), [['POST', '/v1/memory/facts/f_a/keep', undefined], ['PATCH', '/v1/memory/facts/f_a', { state: 'rejected' }]]);
  assert.equal(renders, 2);
});

test('an entry\'s timeline: newest first, with spans and the chat', () => {
  const rows = M.timeline([
    { id: 'a', text: 'Into Blender', kind: 'interest', current: false, valid_from: '2026-09-02', valid_until: '2026-11-05', evidence: [{ thread: 't1' }] },
    { id: 'b', text: 'Into Unity', kind: 'interest', current: true, valid_from: '2026-11-05', valid_until: null, evidence: [] },
    { id: 'c', text: 'Works late', kind: 'fact', current: true, valid_from: null, recorded: Date.UTC(2026, 7, 3) / 1000, evidence: [] }]);
  assert.deepEqual(rows.map(r => [r.id, r.span, r.thread]), [['b', 'since 2026-11', ''], ['a', '2026-09 – 2026-11', 't1'], ['c', 'since 2026-08', '']]);
});
