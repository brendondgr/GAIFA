// The chat mock's web research turn (chat-mock.js, `?mock`): a search, two pages read, a third that fails, an answer
// that cites them. The events have the agent's shapes (titles, snippets and page text wrapped as `<untrusted …>`, the
// result in `{status, result}`), so the reply bar's Sources and Copy (chat-sources.js, chat-copy.js) can be seen
// without the web mod. The icons still come from the web mod when it runs, else they are letters.

const wrap = (s, from) => `<untrusted source="${from}">\n${s}\n</untrusted>`;
const RESULTS = [
  ['Mont Blanc - Wikipedia', 'https://en.wikipedia.org/wiki/Mont_Blanc', 'Mont Blanc is the highest mountain in the Alps and Western Europe, rising 4,805.59 m above sea level (2021 survey).'],
  ['Mont Blanc | Height, Location, & Facts | Britannica', 'https://www.britannica.com/place/Mont-Blanc-mountain-Europe', 'Mont Blanc, highest mountain in Europe (15,771 feet), on the French-Italian border; its height changes with the ice cap.'],
  ['Mont Blanc measured again', 'https://www.chamonix.com/mont-blanc', ''],
  ['Mont Blanc : SummitPost', 'https://www.summitpost.org/mont-blanc/150231', 'Routes, conditions and photos of the Goûter, Trois Monts and Italian routes.'],
  ['The Mont Blanc massif', 'https://www.montblancmassif.com/', 'A guide to the peaks, huts and glaciers around Chamonix and Courmayeur.'],
];
const PAGES = {
  'https://en.wikipedia.org/wiki/Mont_Blanc': ['Mont Blanc', '**Mont Blanc** is the highest mountain in the [Alps](https://en.wikipedia.org/wiki/Alps) and Western Europe. Its summit is an ice dome whose height varies by a few metres from year to year; the 2021 measurement gave 4,805.59 m.'],
  'https://www.britannica.com/place/Mont-Blanc-mountain-Europe': ['Mont Blanc | mountain, Europe', '## Mont Blanc\n\nMont Blanc, highest mountain in Europe (15,771 feet [4,807 metres]). It lies in the Mont Blanc massif on the border between France and Italy.'],
};

/** The turn; `k` is chat-mock.js's helpers: { emit, say, usage, rid }. */
export async function webTurn(t, run, text, { emit, say, usage, rid }) {
  const q = text.replace(/^(please\s+)?(search( the web)?( for)?|look up)\s*/i, '').replace(/[?.!]+$/, '') || 'tallest mountain in the Alps';
  const s1 = await say(t, run, null, 'A fact about the world: search, read the best two pages and answer from them with links.', 2);
  const sid = rid('tc_');
  emit(t, 'tool_call', { id: sid, name: 'web_search', arguments: { query: q, limit: 8 }, step: s1, by: 'model' });
  await run.sleep(700);
  emit(t, 'tool_result', { id: sid, name: 'web_search', status: 'done', content: JSON.stringify({ status: 'done', result: { query: q,
    results: RESULTS.map(([title, url, snippet]) => ({ title: wrap(title, 'search results'), url, snippet: snippet ? wrap(snippet, 'search results') : '', engine: 'duckduckgo', published: null })),
    answers: [], suggestions: [], unresponsive: [] } }) });
  const s2 = await say(t, run, null, 'Wikipedia and Britannica first; the Chamonix page has no snippet, try it too.', 1);
  let n = t.events.filter(e => e.type === 'tool_result').reduce((a, e) => a + (e.payload.outputs?.length || 0), 0);
  for (const url of [...Object.keys(PAGES), 'https://www.chamonix.com/mont-blanc']) {
    const id = rid('tc_');
    emit(t, 'tool_call', { id, name: 'web_fetch', arguments: { url, max_chars: 6000 }, step: s2, by: 'model' });
    await run.sleep(600);
    const p = PAGES[url];
    if (!p) {
      emit(t, 'tool_result', { id, name: 'web_fetch', status: 'error', content: '{"status":"error"}', error: { code: 'robots_disallowed', detail: `${url}: robots.txt disallows it for automated fetches`, fix: 'try another source' } });
      continue;
    }
    const body = `# ${p[0]}\n\nSource: <${url}>  \nFetched: ${new Date().toISOString()}\n\n---\n\n${p[1]}`;
    emit(t, 'tool_result', { id, name: 'web_fetch', status: 'done',
      content: JSON.stringify({ status: 'done', result: { path: `/mock/outputs/web/${id}.md`, url, final_url: url, title: wrap(p[0], `web ${url}`), kind: 'text', content_type: 'text/html', chars: body.length, content: wrap(body, `web ${url}`), truncated: false } }),
      outputs: [{ n: ++n, output_id: rid('').slice(0, 12).padEnd(12, '0'), kind: 'text', title: p[0], summary: 'web page (mock)', url: '', preview: null }] });
  }
  await say(t, run, `**Mont Blanc** is the tallest mountain in the Alps, at about **4,806 m** ([Wikipedia](https://en.wikipedia.org/wiki/Mont_Blanc)). Its summit is an ice cap, so the height moves by a few metres between surveys: Britannica gives 4,807 m ([#${n}](https://www.britannica.com/place/Mont-Blanc-mountain-Europe)).\n\n**Sources:**\n- [Mont Blanc - Wikipedia](https://en.wikipedia.org/wiki/Mont_Blanc)\n- [Britannica](https://www.britannica.com/place/Mont-Blanc-mountain-Europe)`,
  'Both pages agree within the ice cap\'s variation; give the number with its source.', 1);
  usage(t);
  return 'idle';
}
