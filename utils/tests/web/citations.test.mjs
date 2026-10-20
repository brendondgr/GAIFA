// Plan 24.7: citations in the agent's replies (#n p.14, #n:88, output:<id> forms) are parsed and
// rendered as links the chat opens in the viewer; the viewer's highlighter escapes and marks code.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const md = await import(pathToFileURL(path.join(root, 'web/chat/chat-md.js')).href);
const viewer = await import(pathToFileURL(path.join(root, 'web/outputs/viewer.js')).href);
const ID = '3f9c0a1b2c4d';

test('the citation forms', () => {
  assert.deepEqual(md.parseCitations('see #3 p.14 and #2:88.'), [{ text: '#3 p.14', ref: '#3', n: 3, page: 14 }, { text: '#2:88', ref: '#2', n: 2, line: 88 }]);
  assert.deepEqual(md.parseCitations(`(output:${ID} p.7) or output:${ID}:12`), [
    { text: `output:${ID} p.7`, ref: `output:${ID}`, id: ID, page: 7 }, { text: `output:${ID}:12`, ref: `output:${ID}`, id: ID, line: 12 }]);
  assert.deepEqual(md.parseCitations('#4 pp.3-5, #5 page 2, #6 p. 9').map(c => [c.n, c.page]), [[4, 3], [5, 2], [6, 9]]);
  assert.deepEqual(md.parseCitations('(#3 line 5) and #2, lines 9–12').map(c => [c.text, c.line]), [['#3 line 5', 5], ['#2, lines 9–12', 9]]);
  // not citations: a bare #n, a heading-like or HTML-entity #, a URL fragment, a time
  assert.deepEqual(md.parseCitations('#3 alone, &#39;x, see http://h/#3:88, at 10:30, issue#4 p.2'), []);
});

test('rendered as links with the page or line, and never inside code', () => {
  const html = md.renderMarkdown('The answer is on #3 p.14 (and `#3 p.2` in code), defined at #1:88.');
  assert.ok(html.includes('<a href="#" class="aichat-cite" data-cite="#3" data-page="14" title="Open #3 at page 14">#3 p.14</a>'), html);
  assert.ok(html.includes('data-cite="#1" data-line="88"'), html);
  assert.ok(html.includes('<code>#3 p.2</code>'), html);
  const out = md.renderMarkdown(`From output:${ID} p.2.`);
  assert.ok(out.includes(`data-cite="output:${ID}" data-page="2"`), out);
  assert.ok(!md.renderMarkdown('<b>#3 p.1</b>').includes('<b>'));
});

test('the highlighter escapes and marks keywords, strings and comments', () => {
  const py = viewer.highlightLine('def greet(name):  # say <hi>', 'python');
  assert.ok(py.includes('<span class="k">def</span>') && py.includes('<span class="c"># say &lt;hi&gt;</span>'), py);
  const js = viewer.highlightLine('const s = "a<b" // note', 'javascript');
  assert.ok(js.includes('<span class="k">const</span>') && js.includes('<span class="s">&quot;a&lt;b&quot;</span>') && js.includes('<span class="c">// note</span>'), js);
  assert.equal(viewer.highlightLine('plain <text>', ''), 'plain &lt;text&gt;');
  assert.equal(viewer.langOf('code:python'), 'python');
  assert.equal(viewer.langOf('markdown'), '');
});

test('the viewer opens a PDF citation at its page and text at its line', () => {
  assert.deepEqual(viewer.startAt({ subtype: 'pdf' }, { page: 7 }), { page: 7 });
  assert.deepEqual(viewer.startAt({ subtype: 'pdf' }, null), { page: 1 });
  assert.deepEqual(viewer.startAt({ subtype: 'code:python' }, { line: 88 }), { line: 88 });
  assert.deepEqual(viewer.startAt({ subtype: 'markdown' }, { page: 3 }), { line: 1 });
});
