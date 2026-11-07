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
  replaceChildren(...kids) { this.children = [...kids]; }
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

// memory-import 2.1: the Import card's preview, choices, Save and Undo import, against the fake DOM.
const I = await import(pathToFileURL(path.join(root, 'services/agent/ui/memimport.js')).href);
const PREVIEW = {
  id: 'imp_1', made: 1794000000, source: 'claude', state: 'ready', done: 3, total: 3, error: null, saved: null, undone: null,
  lines: [
    { n: 1, section: 'instructions', date: '2026-05-02', text: 'Never push unless told to.', entity: null, error: null,
      facts: [{ key: '1.1', text: 'Never push unless told to.', kind: 'preference', about: ['you'], op: 'adds', held: null, choice: 'save', why: '' }] },
    { n: 2, section: 'projects', date: '2026-02-14', text: 'Lantern (formerly Firefly): a reading app. Pitched for $40k.',
      entity: { name: 'Lantern', aliases: ['Firefly'] }, error: null,
      facts: [{ key: '2.1', text: 'Lantern is a reading app.', kind: 'fact', about: ['projects/Lantern'], op: 'adds', held: null, choice: 'save', why: '' },
              { key: '2.2', text: 'Lantern was pitched for $40k.', kind: 'fact', about: ['projects/Lantern'], op: 'adds', held: null, choice: 'review', why: 'sensitive: money' }] },
    { n: 3, section: 'preferences', date: null, text: 'Prefers dark themes.', entity: null, error: null,
      facts: [{ key: '3.1', text: 'The user prefers dark themes.', kind: 'preference', about: ['you'], op: 'same', held: { id: 'f_9', text: 'The user prefers dark themes.' }, choice: 'save', why: 'already known' }] }],
};

test('the import preview: sections, counts, what each fact does', () => {
  assert.deepEqual(I.sections(PREVIEW.lines).map(s => [s.label, s.lines.length]), [['Instructions', 1], ['Projects', 1], ['Preferences', 1]]);
  assert.deepEqual(I.countsOf(PREVIEW.lines), { save: 2, review: 1, skip: 0, same: 1, unread: 0 });
  assert.deepEqual(I.countsOf(PREVIEW.lines, { '2.1': 'skip' }), { save: 1, review: 1, skip: 1, same: 1, unread: 0 });
  assert.deepEqual(I.choicesOf(PREVIEW.lines, { '2.2': 'save' }), { '1.1': 'save', '2.1': 'save', '2.2': 'save', '3.1': 'save' });
  assert.equal(I.opText({ op: 'replaces', held: { text: 'Into Blender' } }), 'replaces: Into Blender');
  assert.equal(I.savedText({ saved: 9, review: 3, same: 0, skipped: 1, failed: 0 }), 'Imported 9 · 3 wait in Review · 1 skipped');
  const imp = { id: 'f_x', evidence: [{ import: 'imp_1', from: 'claude', line: 'Prefers tea.' }] };
  assert.equal(M.importText(imp), 'imported from Claude · “Prefers tea.”');
  assert.deepEqual(M.byChat([imp, { id: 'f_y', evidence: [{ thread: 't1' }] }]).map(g => [g.thread, g.import?.import || null, g.items.length]),
    [['', 'imp_1', 1], ['t1', null, 1]]);
});

test('the Import card: choose per fact, Save with the choices, then Undo import', async () => {
  const { createUi } = await import(pathToFileURL(path.join(root, 'web/mod-ui.js')).href);
  const ui = createUi();
  let imp = structuredClone(PREVIEW);
  const calls = [];
  const ctx = { ui, toast: () => {}, confirm: async () => true, call: async (m, p, o) => {
    calls.push([m, p, o?.json]);
    if (p === '/v1/memory/imports') return { status: 200, json: [] };
    if (p === '/v1/memory/imports/prompt') return { status: 200, json: { prompt: 'Export all of my stored memories…' } };
    if (m === 'POST' && p.endsWith('/save')) { imp = { ...imp, state: 'saved', saved: { saved: 1, review: 2, same: 1, skipped: 0, failed: 0 } }; return { status: 200, json: imp }; }
    if (m === 'DELETE') return { status: 200, json: { ...imp, state: 'undone', undone: { undone: 3, kept: 0 } } };
    return { status: 200, json: imp };
  } };
  I.importCard.state = { open: true, id: 'imp_1', source: 'claude', text: '', picks: {}, imp: null, timer: null, prompt: null };
  let renders = 0;
  const draw = I.importCard(ctx, e => { throw e; }, () => { renders++; });
  const { card } = await draw();
  const text = () => card.textContent;
  assert.match(text(), /What it found in 3 entries from Claude/);
  assert.match(text(), /2 to save · 1 to Review · 1 already known/);
  assert.match(text(), /waits: sensitive: money/);
  assert.match(text(), /Entry: Lantern \(also Firefly\)/);
  assert.match(text(), /already known/);
  const buttons = () => card.findAll(e => e.tagName === 'BUTTON');
  buttons().filter(b => b.textContent === 'Review')[1].dispatch('click');        // 1.1's own row: Instructions' "All:" row comes first
  assert.match(text(), /1 to save · 2 to Review · 1 already known/);
  buttons().find(b => /^Save 1, send 2 to Review$/.test(b.textContent)).dispatch('click');
  await new Promise(r => setTimeout(r, 0));
  assert.deepEqual(calls.find(c => c[1].endsWith('/save'))[2], { choices: { '1.1': 'review', '2.1': 'save', '2.2': 'review', '3.1': 'save' } });
  const again = await draw();
  assert.match(again.card.textContent, /Imported 1 · 2 wait in Review · 1 already known/);
  again.card.findAll(e => e.tagName === 'BUTTON').find(b => b.textContent === 'Undo import').dispatch('click');
  await new Promise(r => setTimeout(r, 0));
  assert.ok(calls.some(c => c[0] === 'DELETE' && c[1] === '/v1/memory/imports/imp_1'));
  assert.equal(I.importCard.state.id, null);
  assert.ok(renders >= 2);
});
