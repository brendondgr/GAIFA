// Select → Reply: a selection in a rendered reply back to markdown (round trip over the renderer's tags,
// partial selections, code without its header bar, tables, citations, lists), the composer's quote chip
// (add, remove, sending takes it), the quote on the user's message, and `quote` on the send API.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { parse, at } from './minidom.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);

// ---- a tiny React: elements as objects, function components expanded, hooks with fixed state ----
const Fragment = Symbol('Fragment');
globalThis.React = {
  Fragment, Component: class {},
  createElement: (type, props, ...children) => ({ type, props: { ...(props || {}), children: children.flat() } }),
  useState: init => [typeof init === 'function' ? init() : init, () => {}],
  useRef: v => ({ current: v }), useEffect: () => {}, useLayoutEffect: () => {}, useMemo: f => f(), useCallback: f => f,
};
const { renderMarkdown } = await load('chat/chat-md.js');
const Q = await load('chat/chat-quote.js');
const { Composer } = await load('chat/chat-composer.js');
const cards = await load('chat/chat-cards.js');
const { createLiveClient } = await load('chat/chat-api.js');
const { createMockClient } = await load('chat/chat-mock.js');

function expand(n) {
  if (n == null || n === false || typeof n !== 'object') return n;
  if (Array.isArray(n)) return n.map(expand);
  if (typeof n.type === 'function') return expand(n.type(n.props));
  return { ...n, props: { ...n.props, children: (n.props.children || []).map(expand) } };
}
function all(n, pred, out = []) {
  if (Array.isArray(n)) { n.forEach(x => all(x, pred, out)); return out; }
  if (!n || typeof n !== 'object') return out;
  if (pred(n)) out.push(n);
  all(n.props?.children, pred, out);
  return out;
}

const md2md = md => Q.htmlToMarkdown(parse(renderMarkdown(md)));
const sel = (md, a, b) => { const r = parse(renderMarkdown(md)); return Q.htmlToMarkdown(Q.clipTree(r, at(r, ...a), at(r, ...b))); };

// ---------- html → markdown ----------
const CORPUS = [
  'Just a sentence.',
  'Two lines\nin one paragraph.\n\nA second paragraph.',
  '# Title\n\n## Section\n\n### Sub\n\n#### Deep',
  'Some **bold**, *italic*, ~~gone~~ and `code` words.',
  '- one\n- **two**\n- three `x`',
  '1. first\n2. second\n3. third',
  '> a quote\n> on two lines',
  'Before\n\n---\n\nAfter',
  'See [the docs](https://example.com/a?b=1&c=2) and https://example.org/x for more.',
  'As the report says (#3 p.14), and the code at #2:88 and output:0123456789ab pp.3-5.',
  '```python\ndef f(x):\n    return x * 2  # double\n```',
  '```\nplain block\n  indented\n```',
  '| Name | Count | Price |\n| --- | :---: | ---: |\n| apples | 3 | $1.50 |\n| `pears` | 10 | **$2** |',
  '| a | b |\n| --- | --- |\n| pipe \\| inside | x |',
  '### Plan\n\n1. Mix the **flour**\n2. Add `3` eggs\n\n```js\nconst x = "<b>";\n```\n\n| k | v |\n| --- | ---: |\n| a | 1 |\n\nDone, see #1 p.2.',
];

test('round trip: renderMarkdown → htmlToMarkdown gives the markdown back', () => {
  for (const md of CORPUS) assert.equal(md2md(md), md);
});

test('the code block header bar (language, Copy) is left out; the language comes from data-lang', () => {
  const html = renderMarkdown('```bash\nls -la\n```');
  assert.match(html, /aichat-code-bar/);
  assert.equal(Q.htmlToMarkdown(parse(html)), '```bash\nls -la\n```');
  const r = parse(html);                                      // a selection starting in the bar's "Copy"
  assert.equal(Q.htmlToMarkdown(Q.clipTree(r, at(r, 'Copy', 2), at(r, 'la', 2))), '```bash\nls -la\n```');
  assert.equal(md2md('```\nhas ``` inside\n```'), '~~~\nhas ``` inside\n~~~');
});

test('partial selections keep what is selected, with its formatting', () => {
  const md = 'The **quick brown** fox jumps.\n\nSecond *para* here.';
  assert.equal(sel(md, ['quick', 2], ['fox', 3]), '**ick brown** fox');        // mid-word into a bold span
  assert.equal(sel(md, ['jumps', 0], ['here', 4]), 'jumps.\n\nSecond *para* here');   // across paragraphs
  assert.equal(sel(md, ['quick', 0], ['quick', 5]), '**quick**');             // inside one bold word
  assert.equal(sel('## Heading words', ['Heading', 0], ['Heading', 7]), '## Heading');
  assert.equal(sel('A [link text](https://a.b/c) here', ['link', 0], ['text', 4]), '[link text](https://a.b/c)');
  assert.equal(sel('See #3 p.14 now', ['#3', 0], ['p.14', 4]), '#3 p.14');
  assert.equal(sel('> quoted one\n> quoted two', ['one', 0], ['two', 3]), '> one\n> quoted two');
});

test('lists: a numbered list keeps its numbers from where the selection starts; nested lists indent', () => {
  const md = '1. alpha\n2. beta\n3. gamma';
  assert.equal(sel(md, ['beta', 0], ['gamma', 5]), '2. beta\n3. gamma');
  assert.equal(sel(md, ['alpha', 5], ['beta', 4]), '2. beta');                // nothing of "alpha" was selected
  assert.equal(sel('- a\n- b\n- c', ['b', 0], ['c', 1]), '- b\n- c');
  const nested = parse('<ul><li>top<ul><li>inner <strong>one</strong></li><li>inner two</li></ul></li><li>next</li></ul><ol><li>x<ol><li>y</li></ol></li></ol>');
  assert.equal(Q.htmlToMarkdown(nested), '- top\n  - inner **one**\n  - inner two\n- next\n\n1. x\n   1. y');
});

test('tables: one cell is its text; across cells, the touched rows whole under the header', () => {
  const md = '| Name | Count |\n| --- | ---: |\n| apples | 3 |\n| pears | 10 |\n| plums | 7 |';
  assert.equal(sel(md, ['apples', 1], ['apples', 4]), 'ppl');
  assert.equal(sel(md, ['3', 0], ['pears', 3]), '| Name | Count |\n| --- | ---: |\n| apples | 3 |\n| pears | 10 |');
  assert.equal(sel(md, ['Count', 0], ['apples', 6]), '| Name | Count |\n| --- | ---: |\n| apples | 3 |');
  assert.equal(sel('Intro text.\n\n' + md, ['text', 0], ['plums', 2]),
    'text.\n\n| Name | Count |\n| --- | ---: |\n| apples | 3 |\n| pears | 10 |\n| plums | 7 |');
});

test('code: part of a block stays a fenced block with its language; part of one line is inline code', () => {
  const md = '```python\nimport os\nprint(os.getcwd())\n```';
  assert.equal(sel(md, ['import', 0], ['print', 5]), '```python\nimport os\nprint\n```');
  assert.equal(sel(md, ['getcwd', 0], ['getcwd', 6]), '`getcwd`');
  assert.equal(sel('Run `make test` now', ['make', 0], ['test', 4]), '`make test`');
});

// ---------- the composer ----------
const composer = (props = {}) => expand(Composer({ draft: 'why?', setDraft: () => {}, attachments: [], setAttachments: () => {}, onSend: () => {},
  onStop: () => {}, running: false, tools: [], index: [], settings: {}, onSettings: () => {}, skills: [], outputs: [], api: {}, onQuick: () => {}, ...props }));
const byLabel = (tree, l) => all(tree, n => n.props?.['aria-label'] === l)[0];
const sendBtn = tree => all(tree, n => n.type === 'button' && /^(Send|Queue)/.test(n.props?.title || ''))[0];

test('composer: the quote chip shows the quote; × removes it; sending takes it and clears it', () => {
  const quote = { text: '**three** eggs', seq: 7 };
  assert.equal(all(composer(), n => n.props?.['data-quote'] !== undefined).length, 0);     // no quote: no chip
  const removed = [], tree = composer({ quote, setQuote: q => removed.push(q) });
  const chip = all(tree, n => n.props?.['data-quote'] !== undefined)[0];
  assert.ok(chip, 'a chip');
  assert.match(all(chip, n => n.props?.dangerouslySetInnerHTML)[0].props.dangerouslySetInnerHTML.__html, /<strong>three<\/strong> eggs/);
  assert.equal(byLabel(tree, 'Message').props.placeholder, 'Reply to the quoted part…');
  byLabel(tree, 'Remove the quote').props.onClick();
  assert.deepEqual(removed, [null]);
  const sent = [], cleared = [], t2 = composer({ quote, setQuote: q => cleared.push(q), onSend: (...a) => sent.push(a) });
  sendBtn(t2).props.onClick();
  assert.deepEqual(sent, [['why?', [], quote]]);
  assert.deepEqual(cleared, [null]);
  const t3 = composer({ onSend: (...a) => sent.push(a) });                                // without a quote: null
  sendBtn(t3).props.onClick();
  assert.deepEqual(sent[1], ['why?', [], null]);
});

// ---------- the user's message ----------
test('the user card shows the quote above the text, rendered, and a click goes to the reply', () => {
  const UserCard = cards.cardFor({ kind: 'user' });
  const went = [];
  const item = { kind: 'user', ev: { seq: 9, payload: { text: 'why three?', quote: { text: '- add `3` eggs', seq: 4 } } } };
  const tree = expand(UserCard({ item, ctx: { scrollToReply: s => went.push(s) } }));
  const q = all(tree, n => n.props?.['data-quote'] !== undefined)[0];
  assert.ok(q);
  const body = all(q, n => n.props?.dangerouslySetInnerHTML)[0];
  assert.equal(body.props.dangerouslySetInnerHTML.__html, '<ul><li>add <code>3</code> eggs</li></ul>');
  body.props.onClick({ target: { closest: () => null }, preventDefault() {} });
  assert.deepEqual(went, [4]);
  const flat = JSON.stringify(tree);
  assert.ok(flat.indexOf('data-quote') < flat.indexOf('why three?'), 'the quote comes first');
  const plain = expand(UserCard({ item: { kind: 'user', ev: { seq: 2, payload: { text: 'hi' } } }, ctx: {} }));
  assert.equal(all(plain, n => n.props?.['data-quote'] !== undefined).length, 0);
});

// ---------- the API ----------
test('send carries the quote: the live client in the body, the mock on the user event', async () => {
  const bodies = [];
  const c = createLiveClient({ fetch: async (url, o) => { bodies.push(JSON.parse(o.body)); return { ok: true, status: 202, text: async () => '{}' }; } });
  await c.send('t1', 'why?', [], {}, { text: '> x', seq: 3 });
  await c.send('t1', 'plain');
  await c.send('t1', 'no seq', [], {}, { text: 'y', seq: null });
  assert.deepEqual(bodies, [{ text: 'why?', attachments: [], quote: { text: '> x', seq: 3 } }, { text: 'plain', attachments: [] },
    { text: 'no seq', attachments: [], quote: { text: 'y' } }]);
  const m = createMockClient({});
  const th = await m.create({});
  await assert.rejects(m.send(th.id, 'x', [], {}, { text: 'a', seq: 999 }), e => e.status === 422);
  await assert.rejects(m.send(th.id, 'x', [], {}, { text: 'a'.repeat(8001) }), e => e.status === 422);
  const ev = await m.send(th.id, 'why?', [], {}, { text: 'quoted' });
  assert.deepEqual(ev.payload.quote, { text: 'quoted' });
});
