// The reply's Sources count what the user gave (chat-sources.js): pages attached with "Add a web page" (the user
// event's docs carry the page's url, or older events resolve it), and links the user typed that the turn fetched,
// marked "you shared" and listed first; snippets of numbered and relevance-shaped web_fetch content (webread.py).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const th = await load('chat/chat-thread.js');
const ct = await load('chat/chat-turn.js');
const src = await load('chat/chat-sources.js');

const wrap = (s, from) => `<untrusted source="${from}">\n${s}\n</untrusted>`;
const done = result => JSON.stringify({ status: 'done', result });
const turnOf = events => ct.groupTurns(th.buildView(events), {}).find(b => b.kind === 'turn');

function events({ docs, text }) {
  let seq = 0;
  const ev = (type, payload) => ({ seq: ++seq, ts: 1000 + seq, type, payload });
  const fetched = (id, url, title, content) => [
    ev('tool_call', { id, name: 'web_fetch', arguments: { url }, step: 's1', by: 'model' }),
    ev('tool_result', { id, name: 'web_fetch', status: 'done', content: done({ url, final_url: url, title: wrap(title, `web ${url}`), kind: 'text', content: wrap(content, `web ${url}`), truncated: true }),
      outputs: [{ n: 5, output_id: 'o_' + id, kind: 'text', title }] }),
  ];
  return [
    ev('user', { text, ...(docs ? { attachments: docs.map(d => d.id), docs } : {}) }),
    ...fetched('c1', 'https://other.example.org/a', 'Another page', '1| # Another page\n3| Source: <https://other.example.org/a>\n4| Fetched: x\n6| ---\n8| Plain words of the page start here.'),
    ...fetched('c2', 'https://docs.example.com/guide', 'The guide', 'About this page: A guide to gaiters.\n\n── lines 40–42 of 90 · under "Gear" ──\n40| Gaiters keep mud out.'),
    ev('assistant', { text: 'Answer.', step: 's2' }),
  ];
}

test('a page attached with "Add a web page" is a source, first, marked as shared', () => {
  const docs = [{ ref: '#1', id: 'o_att', name: 'Trek notes', kind: 'text', url: 'https://www.trek.example.net/notes', inline: true, text: '# Trek notes\n\nSource: <https://www.trek.example.net/notes>  \nFetched: x\n\n---\n\nBring gaiters in March.' },
    { ref: '#2', id: 'o_pdf', name: 'my.pdf', kind: 'document' }];
  const s = src.turnSources(turnOf(events({ docs, text: 'What should I pack?' })));
  assert.equal(s.count, 3);
  assert.deepEqual(s.read.map(p => [p.url, !!p.shared]), [['https://www.trek.example.net/notes', true], ['https://other.example.org/a', false], ['https://docs.example.com/guide', false]]);
  assert.deepEqual([s.read[0].title, s.read[0].n, s.read[0].output_id, s.read[0].snippet], ['Trek notes', 1, 'o_att', 'Bring gaiters in March.']);
});

test('older events: an attachment resolved through the outputs API counts too', () => {
  const docs = [{ ref: '#1', id: 'o_old', name: 'Old page', kind: 'text' }];
  const t = turnOf(events({ docs, text: 'hi' }));
  assert.equal(src.turnSources(t).read.length, 2, 'without the lookup it is not a source');
  const s = src.turnSources(t, [{ output_id: 'o_old', url: 'https://old.example.org/p', title: 'Old page' }]);
  assert.deepEqual(s.read.map(p => p.url), ['https://old.example.org/p', 'https://other.example.org/a', 'https://docs.example.com/guide']);
  assert.ok(s.read[0].shared);
});

test('a link the user typed and the turn fetched is marked shared and comes first', () => {
  const s = src.turnSources(turnOf(events({ text: 'Summarise https://docs.example.com/guide.' })));
  assert.deepEqual(s.read.map(p => [p.url, !!p.shared]), [['https://docs.example.com/guide', true], ['https://other.example.org/a', false]]);
  const q = src.turnSources(turnOf(events({ text: '' }).map(e => e.type === 'user' ? { ...e, payload: { text: 'see', quotes: [{ text: 'https://docs.example.com/guide', reply: 'ok' }] } } : e)));
  assert.ok(!q.read.some(p => p.shared), 'a quoted part is not what the user typed');
  assert.deepEqual([...src.typedLinks('a (https://x.example.org/p_(q)). <https://y.example.org/z>, https://w.example.org/k!')],
    ['x.example.org/p_(q)', 'y.example.org/z', 'w.example.org/k']);
});

test('snippets of numbered and relevance-shaped pages', () => {
  const s = src.turnSources(turnOf(events({ text: 'x' })));
  assert.equal(s.read[0].snippet, 'Plain words of the page start here.');
  assert.equal(s.read[1].snippet, 'A guide to gaiters.');
  assert.equal(src.pageSnippet(wrap('── lines 3–4 of 9 ──\n3| Only **this**.', 'web u')), 'Only this.');
});
