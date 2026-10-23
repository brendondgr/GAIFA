// Select → Reply: a selection in a rendered reply back to markdown (round trip over the renderer's tags,
// partial selections, code without its header bar, tables, citations, lists); the quote-replies: the draft list
// (add, edit, remove, order, no limit), the cards in the composer and on the user's message, the Reply popup,
// building the send payload (`quotes`, empty text with a reply), the older `quote` read as one, and the API.
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
const QR = await load('chat/chat-quote-reply.js');
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
  'Many passed [eecs.berkeley.edu #1:112-113; BLS] and [resume #8 p.1], not [Medium].',
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
  assert.equal(sel('See #3 p.14 now', ['#3', 0], ['p. 14', 5]), '#3 p.14');      // the chip shows "#3 p. 14"
  assert.equal(sel('Passed [bu.edu #3:9-35] then', ['Passed', 0], ['then', 4]), 'Passed [bu.edu #3:9-35] then');
  assert.equal(sel('> quoted one\n> quoted two', ['one', 0], ['two', 3]), '> one\n> quoted two');
});

test('lists: a numbered list keeps its numbers from where the selection starts; nested lists indent', () => {
  const md = '1. alpha\n2. beta\n3. gamma';
  assert.equal(sel(md, ['beta', 0], ['gamma', 5]), '2. beta\n3. gamma');
  assert.equal(sel(md, ['alpha', 5], ['beta', 4]), '2. beta');                // nothing of "alpha" was selected
  assert.equal(sel('- a\n- b\n- c', ['b', 0], ['c', 1]), '- b\n- c');
  assert.equal(sel('Note.\n\n4. delta\n5. epsilon', ['delta', 0], ['epsilon', 7]), '4. delta\n5. epsilon');   // a list that starts past 1
  assert.equal(sel('Note.\n\n4. delta\n5. epsilon', ['epsilon', 0], ['epsilon', 7]), '5. epsilon');
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

// ---------- the draft's quote-replies ----------
test('the draft list: add in order, edit a reply, remove one; no limit on how many; blank quotes add nothing', () => {
  let l = QR.addQuote([], { text: '**one**', seq: 3, reply: 'why?' });
  l = QR.addQuote(l, { text: 'two', reply: '' });
  l = QR.addQuote(l, { text: '  ', reply: 'x' });                       // nothing to quote
  assert.deepEqual(l.map(q => [q.text, q.reply, q.seq]), [['**one**', 'why?', 3], ['two', '', undefined]]);
  assert.notEqual(l[0].id, l[1].id);
  l = QR.editQuote(l, l[1].id, 'and this?');
  assert.equal(l[1].reply, 'and this?');
  const kept = QR.removeQuote(l, l[0].id);
  assert.deepEqual(kept.map(q => q.text), ['two']);
  let many = [];
  for (let i = 1; i <= 25; i++) many = QR.addQuote(many, { text: `Question ${i}?`, reply: `answer ${i}`, seq: 9 });
  assert.equal(many.length, 25);
  assert.equal(new Set(many.map(q => q.id)).size, 25);
  assert.deepEqual(QR.quotesPayload(many).slice(0, 2), [{ text: 'Question 1?', reply: 'answer 1', seq: 9 }, { text: 'Question 2?', reply: 'answer 2', seq: 9 }]);
  assert.equal(QR.quotesProblem(many), null);
});

test('sending: empty text is fine with a reply; the payload trims replies; the limits are the agent’s', () => {
  const qs = QR.addQuote([], { text: 'eggs', reply: '  how many?  ', seq: 4 }), blank = QR.addQuote([], { text: 'eggs', reply: ' ' });
  assert.equal(QR.canSendQuotes('', [], qs), true);
  assert.equal(QR.canSendQuotes('', [], blank), false);                  // nothing said
  assert.equal(QR.canSendQuotes('ok', [], blank), true);
  assert.equal(QR.canSendQuotes('', [{ id: 'a' }], blank), true);
  assert.equal(QR.canSendQuotes('', [], []), false);
  assert.deepEqual(QR.quotesPayload(qs), [{ text: 'eggs', reply: 'how many?', seq: 4 }]);
  assert.equal(QR.messageText('  ', [], qs), '');
  assert.equal(QR.messageText('', [{ id: 'a' }], blank), 'Here are the attached outputs.');
  assert.equal(QR.messageText('', [{ id: 'a' }], qs), '');
  assert.equal(QR.messageText(' hi ', [], []), 'hi');
  assert.match(QR.quotesProblem([{ text: 'a'.repeat(8001), reply: '' }]), /Quote 1 is over 8,000/);
  assert.match(QR.quotesProblem([{ text: 'a', reply: 'b'.repeat(4001) }]), /reply 1 is over 4,000/);
  const big = Array.from({ length: 17 }, () => ({ text: 'q'.repeat(8000), reply: 'r'.repeat(4000) }));
  assert.match(QR.quotesProblem(big), /204,000 characters in all; at most 200,000/);
  assert.equal(QR.canSendQuotes('hi', [], big), false);
});

test('the older single quote reads as one quote-reply with no reply; branches get editable cards', () => {
  assert.deepEqual(QR.quotesOf({ text: 'why?', quote: { text: '> x', seq: 3 } }), [{ text: '> x', reply: '', seq: 3 }]);
  assert.deepEqual(QR.quotesOf({ quotes: [{ text: 'a', reply: 'b' }, { text: ' ' }, { text: 'c', reply: 'd', seq: 2 }] }),
    [{ text: 'a', reply: 'b' }, { text: 'c', reply: 'd', seq: 2 }]);
  assert.deepEqual(QR.quotesOf({ text: 'hi' }), []);
  const cards = QR.draftQuotes({ quotes: [{ text: 'a', reply: 'b', seq: 5 }] });
  assert.ok(cards[0].id) ;
  assert.deepEqual({ ...cards[0], id: undefined }, { id: undefined, text: 'a', reply: 'b', seq: 5 });
});

test('the card preview: markdown as one line of plain text, clipped', () => {
  assert.equal(QR.plainPreview('### Step 2\n\n- **mix** the flour\n- add `3` eggs'), 'Step 2 mix the flour add 3 eggs');
  assert.equal(QR.plainPreview('See [the docs](https://a.b) and *this*.'), 'See the docs and this.');
  assert.equal(QR.plainPreview('| a | b |\n| --- | ---: |\n| 1 | 2 |'), 'a · b 1 · 2');
  assert.equal(QR.plainPreview('```python\nx = 1\n```'), 'x = 1');
  assert.equal(QR.plainPreview('> quoted\n>\n> more'), 'quoted more');
  assert.equal(QR.plainPreview('snake_case_name stays'), 'snake_case_name stays');
  const long = QR.plainPreview('word '.repeat(100), 40);
  assert.equal(long.length, 40); assert.ok(long.endsWith('…'));
});

// ---------- the composer ----------
const composer = (props = {}) => expand(Composer({ draft: 'why?', setDraft: () => {}, attachments: [], setAttachments: () => {}, onSend: () => {},
  onStop: () => {}, running: false, tools: [], index: [], settings: {}, onSettings: () => {}, skills: [], outputs: [], api: {}, onQuick: () => {}, ...props }));
const byLabel = (tree, l) => all(tree, n => n.props?.['aria-label'] === l)[0];
const sendBtn = tree => all(tree, n => n.type === 'button' && /^(Send|Queue)/.test(n.props?.title || ''))[0];
const cardsIn = tree => all(tree, n => n.props?.['data-quote-card'] !== undefined);
const text = n => (typeof n === 'string' ? n : Array.isArray(n) ? n.map(text).join('') : n?.props ? text(n.props.children) : '');

test('composer: one card per quote-reply, in order; × removes it; sending takes them all, even with no text', () => {
  let qs = QR.addQuote(QR.addQuote([], { text: '**three** eggs', seq: 7, reply: 'why three?' }), { text: 'flour', reply: '' });
  assert.equal(cardsIn(composer()).length, 0);                                       // none: no cards
  const updates = [], tree = composer({ quotes: qs, setQuotes: f => updates.push(f(qs)) });
  const cs = cardsIn(tree);
  assert.equal(cs.length, 2);
  assert.match(text(cs[0]), /three eggs.*why three\?.*Reply/);
  assert.match(text(cs[1]), /flour.*No reply/);
  assert.equal(byLabel(tree, 'Message').props.placeholder, 'Add a message, or just send your replies…');
  all(cs[0], n => n.props?.['aria-label'] === 'Remove this reply')[0].props.onClick();
  assert.deepEqual(updates[0].map(q => q.text), ['flour']);
  const sent = [], t2 = composer({ draft: '', quotes: qs, onSend: (...a) => sent.push(a) });
  assert.equal(sendBtn(t2).props.disabled, false);
  sendBtn(t2).props.onClick();
  assert.deepEqual(sent, [['', [], qs]]);
  const t3 = composer({ draft: '', quotes: QR.addQuote([], { text: 'x', reply: '' }) });   // nothing said: can't send
  assert.equal(sendBtn(t3).props.disabled, true);
  const t4 = composer({ onSend: (...a) => sent.push(a) });                           // without cards: an empty list
  sendBtn(t4).props.onClick();
  assert.deepEqual(sent[1], ['why?', [], []]);
});

test('composer: 25 cards wrap in a row that scrolls; too much in all says why and blocks Send', () => {
  let qs = [];
  for (let i = 1; i <= 25; i++) qs = QR.addQuote(qs, { text: `Question ${i}?`, reply: `answer ${i}` });
  const tree = composer({ quotes: qs });
  assert.equal(cardsIn(tree).length, 25);
  const row = all(tree, n => n.props?.['data-quote-cards'] !== undefined)[0];
  assert.equal(row.props.style.flexWrap, 'wrap');
  assert.equal(row.props.style.overflowY, 'auto');
  assert.ok(row.props.style.maxHeight && row.props.style.maxHeight !== 'none');
  const big = Array.from({ length: 17 }, () => ({ id: Math.random().toString(36), text: 'q'.repeat(8000), reply: 'r'.repeat(4000) }));
  const t2 = composer({ quotes: big });
  assert.match(text(all(t2, n => n.props?.role === 'alert')[0]), /at most 200,000/);
  assert.equal(sendBtn(t2).props.disabled, true);
});

// ---------- the Reply popup ----------
test('the Reply popup: the quote rendered, the reply editable with Save / Remove; read-only on a sent message', () => {
  const saved = [], removed = [], closed = [];
  const q = { id: 'a', text: '- add `3` eggs', reply: 'why three?', seq: 4 };
  const tree = expand(QR.QuoteReplyDialog({ q, editable: true, onSave: r => saved.push(r), onRemove: () => removed.push(1), onClose: () => closed.push(1) }));
  const dialog = all(tree, n => n.props?.role === 'dialog')[0];
  assert.equal(dialog.props['aria-label'], 'Reply');
  assert.equal(all(tree, n => n.props?.dangerouslySetInnerHTML)[0].props.dangerouslySetInnerHTML.__html, '<ul><li>add <code>3</code> eggs</li></ul>');
  const area = byLabel(tree, 'Your reply');
  assert.equal(area.props.value, 'why three?');
  all(tree, n => n.type === 'button' && text(n) === 'Save')[0].props.onClick();       // fixed-state React: the reply as it was
  assert.deepEqual(saved, ['why three?']);
  all(tree, n => n.type === 'button' && text(n) === 'Remove')[0].props.onClick();
  assert.deepEqual(removed, [1]);
  const went = [], view = expand(QR.QuoteReplyDialog({ q, editable: false, onClose: () => {}, ctx: { scrollToReply: s => went.push(s) } }));
  assert.equal(byLabel(view, 'Your reply'), undefined);
  assert.match(text(view), /why three\?/);
  all(view, n => n.type === 'button' && text(n) === 'Go to the quoted reply')[0].props.onClick();
  assert.deepEqual(went, [4]);
});

// ---------- the user's message ----------
test('the user card shows its quote-replies as cards above the text; an old single quote shows as one', () => {
  const UserCard = cards.cardFor({ kind: 'user' });
  const item = { kind: 'user', ev: { seq: 9, payload: { text: 'thanks', quotes: [{ text: '- add `3` eggs', reply: 'why three?', seq: 4 }, { text: 'bake', reply: 'how long?' }] } } };
  const tree = expand(UserCard({ item, ctx: {} }));
  const cs = cardsIn(tree);
  assert.equal(cs.length, 2);
  assert.match(text(cs[0]), /add 3 eggs.*why three\?/);
  assert.equal(all(cs[0], n => n.props?.['aria-label'] === 'Remove this reply').length, 0);   // sent: no ×
  const flat = JSON.stringify(tree);
  assert.ok(flat.indexOf('data-quote-card') < flat.indexOf('"thanks"'), 'the cards come first');
  const old = expand(UserCard({ item: { kind: 'user', ev: { seq: 3, payload: { text: 'why?', quote: { text: 'old part', seq: 2 } } } }, ctx: {} }));
  assert.equal(cardsIn(old).length, 1);
  assert.match(text(cardsIn(old)[0]), /old part.*No reply/);
  const empty = expand(UserCard({ item: { kind: 'user', ev: { seq: 4, payload: { text: '', quotes: [{ text: 'a', reply: 'b' }] } } }, ctx: {} }));
  assert.equal(cardsIn(empty).length, 1);
  const plain = expand(UserCard({ item: { kind: 'user', ev: { seq: 2, payload: { text: 'hi' } } }, ctx: {} }));
  assert.equal(cardsIn(plain).length, 0);
  assert.equal(cards.userCopy(item.ev.payload), '> - add `3` eggs\n\nwhy three?\n\n> bake\n\nhow long?\n\nthanks');
});

// ---------- the API ----------
test('send carries quotes: the live client in the body, the mock validates and stores them (25 of them too)', async () => {
  const bodies = [];
  const c = createLiveClient({ fetch: async (url, o) => { bodies.push(JSON.parse(o.body)); return { ok: true, status: 202, text: async () => '{}' }; } });
  await c.send('t1', '', [], {}, [{ id: 'x', text: '> x', reply: 'why?', seq: 3 }, { text: 'y', reply: '' }]);
  await c.send('t1', 'plain');
  assert.deepEqual(bodies, [{ text: '', attachments: [], quotes: [{ text: '> x', reply: 'why?', seq: 3 }, { text: 'y', reply: '' }] }, { text: 'plain', attachments: [] }]);
  const m = createMockClient({});
  const th = await m.create({});
  await assert.rejects(m.send(th.id, 'x', [], {}, [{ text: 'a', reply: '', seq: 999 }]), e => e.status === 422 && e.code === 'invalid_quote');
  await assert.rejects(m.send(th.id, 'x', [], {}, [{ text: 'a'.repeat(8001), reply: '' }]), e => e.status === 422);
  await assert.rejects(m.send(th.id, '', [], {}, [{ text: 'a', reply: ' ' }]), e => e.status === 422);
  await assert.rejects(m.send(th.id, 'x', [], {}, Array.from({ length: 17 }, () => ({ text: 'q'.repeat(8000), reply: 'r'.repeat(4000) }))), e => e.status === 422);
  const ev = await m.send(th.id, '', [], {}, [{ text: 'quoted', reply: 'my reply' }]);
  assert.deepEqual(ev.payload.quotes, [{ text: 'quoted', reply: 'my reply' }]);
  const many = Array.from({ length: 25 }, (_, i) => ({ text: `Q${i + 1}`, reply: `A${i + 1}` }));
  const ev2 = await m.send(th.id, '', [], {}, many);
  assert.equal(ev2.payload.quotes.length, 25);
  const ev3 = await m.send(th.id, 'why?', [], {}, { text: 'old style' });              // an older single quote
  assert.deepEqual(ev3.payload.quotes, [{ text: 'old style', reply: '' }]);
});

test('a picture in a reply quotes as its markdown (plan 47.3)', async () => {
  const mdm = await load('chat/chat-md.js');
  mdm.setChatOutputs([{ n: 1, output_id: 'aaaaaaaaaaaa', kind: 'image', title: 'Fox', url: '/api/outputs/aaaaaaaaaaaa/file' }]);
  assert.equal(md2md('Look: ![The fox](#1) there'), 'Look: ![The fox](#1) there');
  mdm.setChatOutputs([]);
});
