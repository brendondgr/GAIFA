// The reply bar (chat-sources.js, chat-copy.js): a turn's sources from its own events (read vs found, the
// snippet, dedupe by URL, the count, a capped result), the icon URL, the three ways to copy, and the
// remembered default (the most picked way in the last 24 hours).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const load = f => import(pathToFileURL(path.join(root, 'web', f)).href);
const th = await load('chat/chat-thread.js');
const ct = await load('chat/chat-turn.js');
const src = await load('chat/chat-sources.js');
const cp = await load('chat/chat-copy.js');

const wrap = (s, from) => `<untrusted source="${from}">\n${s}\n</untrusted>`;
const hit = (title, url, snippet) => ({ title: wrap(title, 'search results'), url, snippet: snippet ? wrap(snippet, 'search results') : '', engine: 'ddg', published: null });
const page = (url, title, body, final = url) => ({ path: '/x/outputs/web/2026-10-21/p.md', url, final_url: final, title: wrap(title, `web ${final}`), kind: 'text', content_type: 'text/html', chars: 900,
  content: wrap(`# ${title}\n\nSource: <${final}>  \nFetched: 2026-10-21T10:24:03-04:00  \nPublished: 2026-01-02\n\n---\n\n${body}`, `web ${final}`), truncated: false, published: null });
const done = (result, extra = {}) => JSON.stringify({ status: 'done', result, ...extra });

/** A turn that searched twice, read three pages (one twice, one via a redirect), and failed one fetch. */
function webEvents() {
  let seq = 0;
  const ev = (type, payload) => ({ seq: ++seq, ts: 1000 + seq, type, payload });
  const call = (id, name, args, step) => ev('tool_call', { id, name, arguments: args, step, by: 'model' });
  const res = (id, name, content, o = {}) => ev('tool_result', { id, name, status: 'done', content, ...o });
  return [
    ev('user', { text: 'Leather or synthetic boots for Torres del Paine in March?' }),
    ev('thinking', { text: 'Gear advice depends on real conditions; search first.', seconds: 3, step: 's1' }),
    call('c1', 'web_search', { query: 'Torres del Paine boots March', limit: 8 }, 's1'),
    res('c1', 'web_search', done({ query: 'Torres del Paine boots March', results: [
      hit('W Trek guide', 'https://www.example.org/w-trek/', 'The W trek takes 4–5 days; waterproof boots are a must.'),
      hit('Weather in March', 'https://weather.example.com/tdp/march', ''),
      hit('Best boots 2024', 'https://shoes.example.net/best-boots', 'Leather lasts longer but needs breaking in.'),
      hit('W Trek guide (dup)', 'http://example.org/w-trek', 'duplicate'),
    ], answers: [], suggestions: [], unresponsive: [] })),
    ev('thinking', { text: 'Read the two best.', seconds: 1, step: 's2' }),
    call('c2', 'web_fetch', { url: 'https://www.example.org/w-trek/', max_chars: 6000 }, 's2'),
    call('c3', 'web_fetch', { url: 'https://weather.example.com/tdp/march' }, 's2'),
    res('c2', 'web_fetch', done(page('https://www.example.org/w-trek/', 'How to hike the W', 'Day one starts at the Torres.')), { outputs: [{ n: 1, output_id: 'aaaaaaaaaaaa', kind: 'text', title: 'How to hike the W' }] }),
    res('c3', 'web_fetch', done(page('https://weather.example.com/tdp/march', 'TdP weather in March',
      '## Averages\n\nIn **Torres del Paine**, March highs are [52°F](https://weather.example.com/f) and lows 39°F. ' + 'Windy and wet. '.repeat(30), 'https://weather.example.com/tdp/march-2')),
    { outputs: [{ n: 2, output_id: 'bbbbbbbbbbbb', kind: 'text', title: 'TdP weather' }] }),
    ev('assistant', { text: 'Let me check one more.', step: 's3' }),
    call('c4', 'web_fetch', { url: 'https://example.org/w-trek' }, 's3'),                       // the same page again
    call('c5', 'web_fetch', { url: 'https://down.example.org/x' }, 's3'),
    call('c6', 'web_search', { query: 'gaiters Patagonia' }, 's3'),
    res('c4', 'web_fetch', done(page('https://example.org/w-trek', 'How to hike the W', 'again'))),
    ev('tool_result', { id: 'c5', name: 'web_fetch', status: 'error', content: '{"status":"error"}', error: { code: 'http_error', detail: 'https://down.example.org/x answered HTTP 503' } }),
    // a result the hub capped: only a preview of its JSON survives
    res('c6', 'web_search', JSON.stringify({ status: 'done', result: { truncated: true, bytes: 9000, full: '/api/tools/calls/c6/result',
      preview: JSON.stringify({ query: 'gaiters Patagonia', results: [hit('Gaiters "explained"', 'https://gear.example.com/gaiters', 'Keep mud out.'), hit('Cut off', 'https://cut.example.com/a', 'tru')] }).slice(0, 330) } })),
    ev('assistant', { text: 'Leather boots, and bring gaiters ([#1](https://www.example.org/w-trek/)). See #2 p.1 and (#2).\n\n**Sources:**\n- [How to hike the W](https://www.example.org/w-trek/)\n- [Weather](https://weather.example.com/tdp/march-2)', step: 's4' }),
  ];
}
const turnOf = events => ct.groupTurns(th.buildView(events), {}).find(b => b.kind === 'turn');

test('sources: pages read (deduped by URL, redirects folded) vs search results found, and the count', () => {
  const s = src.turnSources(turnOf(webEvents()));
  assert.equal(s.count, 2);
  assert.deepEqual(s.read.map(p => p.url), ['https://www.example.org/w-trek/', 'https://weather.example.com/tdp/march-2']);
  assert.deepEqual(s.read.map(p => [p.site, p.host, p.title, p.n, p.output_id]),
    [['www.example.org', 'example.org', 'How to hike the W', 1, 'aaaaaaaaaaaa'], ['weather.example.com', 'weather.example.com', 'TdP weather in March', 2, 'bbbbbbbbbbbb']]);
  assert.deepEqual(s.found.map(p => p.url), ['https://shoes.example.net/best-boots', 'https://gear.example.com/gaiters'], 'not opened; the dup and the failed fetch are not "found"');
  assert.equal(s.found[1].title, 'Gaiters "explained"');
  assert.deepEqual(s.queries, ['Torres del Paine boots March', 'gaiters Patagonia']);
  assert.deepEqual(src.iconSites(s), ['www.example.org', 'weather.example.com', 'shoes.example.net']);
});

test('sources: the snippet is the search snippet, else the start of the page as plain text', () => {
  const [w, weather] = src.turnSources(turnOf(webEvents())).read;
  assert.equal(w.snippet, 'The W trek takes 4–5 days; waterproof boots are a must.');
  assert.ok(weather.snippet.startsWith('Averages In Torres del Paine, March highs are 52°F and lows 39°F. Windy'), weather.snippet);
  assert.ok(weather.snippet.length <= 201 && weather.snippet.endsWith('…'));
  assert.ok(!/untrusted|Source:|Fetched:|\*\*|\]\(/.test(weather.snippet));
});

test('sources: none for a turn without web tools; unsafe URLs are dropped', () => {
  assert.deepEqual(src.turnSources(turnOf([{ seq: 1, ts: 1, type: 'user', payload: { text: 'hi' } }, { seq: 2, ts: 2, type: 'assistant', payload: { text: 'Hello', step: 's' } }])),
    { read: [], found: [], queries: [], count: 0 });
  assert.equal(src.safeUrl('javascript:alert(1)'), null);
  assert.equal(src.safeUrl('data:text/html,x'), null);
  assert.equal(src.safeUrl('https://ok.example/a b'), 'https://ok.example/a%20b');
  assert.equal(src.unwrap(wrap('x <b>', 'web y')), 'x <b>');
});

test('favicon URLs: through the hub to the web mod, only for public DNS names', () => {
  assert.equal(src.faviconUrl('www.Example.org'), '/api/s/web/v1/favicon?host=www.example.org');
  assert.equal(src.faviconUrl('en.wikipedia.org', 'http://127.0.0.1:7000'), 'http://127.0.0.1:7000/api/s/web/v1/favicon?host=en.wikipedia.org');
  for (const h of ['localhost', '127.0.0.1', '10.1.2.3', 'nas.local', 'router.lan', '[::1]', '', null, 'a..b', 'x'])
    assert.equal(src.faviconUrl(h), null, String(h));
});

test('copy: text only drops links, citations and the Sources list', () => {
  const ev = webEvents(), t = turnOf(ev), text = t.answer.text;
  assert.equal(cp.copyText('text', { text, turn: t }), 'Leather boots, and bring gaiters. See and.');
  assert.equal(cp.textOnly('Read [the guide](https://a.example/x) and <https://b.example/y> (#3 p.14). `[#1](u)` stays.\n\n```\n[x](y) #2 p.3\n```'),
    'Read the guide and https://b.example/y. `[#1](u)` stays.\n\n```\n[x](y) #2 p.3\n```');
  assert.equal(cp.textOnly('A fact [#2](https://x.example/p), another (#1, #3).\n\n## Sources\n1. [X](https://x.example/p)\n2. https://y.example'), 'A fact, another.');
  assert.equal(cp.textOnly('They passed [eecs.berkeley.edu #1:112; BLS], and [Medium] says so [resume #8 p.1].'), 'They passed, and [Medium] says so.');
  assert.equal(cp.cutSources('Sources matter.\n\nSources: we read many.'), 'Sources matter.\n\nSources: we read many.', 'not a list: kept');
});

test('copy: including citations keeps the reply and lists the pages read', () => {
  const t = turnOf(webEvents()), text = t.answer.text;
  const out = cp.copyText('cites', { text, turn: t });
  assert.ok(out.startsWith('Leather boots, and bring gaiters ([#1](https://www.example.org/w-trek/)). See #2 p.1 and (#2).\n\nSources\n'), out);
  assert.ok(out.endsWith('1. How to hike the W — https://www.example.org/w-trek/\n2. TdP weather in March — https://weather.example.com/tdp/march-2'), out);
  assert.equal(out.match(/Sources/g).length, 1, "the model's own list is replaced");
  assert.equal(cp.copyText('cites', { text: 'Plain answer.', turn: null }), 'Plain answer.');
});

test('copy: including thinking and steps lists them in order before the answer', () => {
  const t = turnOf(webEvents()), out = cp.copyText('steps', { text: t.answer.text, turn: t });
  const [steps, answer] = out.split('\n\nAnswer\n');
  assert.deepEqual(steps.split('\n'), [
    'Thinking and steps',
    '- Thought (3s): Gear advice depends on real conditions; search first.',
    '- Searched the web: “Torres del Paine boots March”',
    '- Thought (1s): Read the two best.',
    '- Read “How to hike the W” (https://www.example.org/w-trek/)',
    '- Read “TdP weather in March” (https://weather.example.com/tdp/march-2)',
    '- Said: Let me check one more.',
    '- Read “How to hike the W” (https://example.org/w-trek)',
    "- Couldn't read https://down.example.org/x (https://down.example.org/x answered HTTP 503)",
    '- Searched the web: “gaiters Patagonia”',
  ]);
  assert.ok(answer.includes('\n\nSources\n1. How to hike the W'));
});

test('copy: the default is the way picked most in the last 24 hours, ties to the latest', () => {
  const H = 3600e3, now = 10 * 86400e3;
  assert.equal(cp.defaultMode([], now), 'text');
  assert.equal(cp.defaultMode(null, now), 'text');
  const log = [{ mode: 'steps', ts: now - 30 * H }, { mode: 'steps', ts: now - 25 * H }, { mode: 'cites', ts: now - 2 * H }];
  assert.equal(cp.defaultMode(log, now), 'cites', 'older than a day doesn\'t count');
  assert.equal(cp.defaultMode([...log, { mode: 'text', ts: now - H }], now), 'text', 'a tie goes to the latest pick');
  assert.equal(cp.defaultMode([...log, { mode: 'text', ts: now - H }, { mode: 'cites', ts: now - 3 * H }], now), 'cites');
  assert.equal(cp.defaultMode([{ mode: 'bogus', ts: now }, { mode: 'steps', ts: now - 1 }], now), 'steps');
  assert.equal(cp.defaultMode(log, now + 23 * H), 'text', 'everything expired');
  let l = [];
  for (let i = 0; i < 70; i++) l = cp.recordMode(l, i % 2 ? 'cites' : 'steps', now + i);
  assert.equal(l.length, 50);
  assert.deepEqual(cp.recordMode([{ mode: 'text', ts: now - 25 * H }], 'steps', now), [{ mode: 'steps', ts: now }], 'old picks are pruned');
});
