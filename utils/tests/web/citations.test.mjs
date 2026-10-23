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
  assert.ok(html.includes('<a href="#" class="aichat-cite" data-cite="#3" data-page="14" data-src="#3 p.14" title="Open #3 at page 14"><span class="aichat-cite-name">#3</span><span class="aichat-cite-at">p. 14</span></a>'), html);
  assert.ok(html.includes('data-cite="#1" data-line="88"'), html);
  assert.ok(html.includes('<code>#3 p.2</code>'), html);
  const out = md.renderMarkdown(`From output:${ID} p.2.`);
  assert.ok(out.includes(`data-cite="output:${ID}" data-page="2"`), out);
  assert.ok(!md.renderMarkdown('<b>#3 p.1</b>').includes('<b>'));
});

test('a bracketed group of citations: its parts, with names and places', () => {
  assert.deepEqual(md.citeGroup('eecs.berkeley.edu #1:112'), [{ ref: '#1', n: 1, name: 'eecs.berkeley.edu', line: 112, at: 'L112' }]);
  assert.deepEqual(md.citeGroup('bu.edu #3:9-35')[0].at, 'L9–35');
  assert.deepEqual(md.citeGroup('research.com #7:29-37, 161-173')[0], { ref: '#7', n: 7, name: 'research.com', line: 29, at: 'L29–37, 161–173' });
  assert.deepEqual(md.citeGroup('coursera.org #6:16; BLS'), [{ ref: '#6', n: 6, name: 'coursera.org', line: 16, at: 'L16' }, { name: 'BLS' }]);
  assert.deepEqual(md.citeGroup('resume #8 p.1')[0], { ref: '#8', n: 8, name: 'resume', page: 1, at: 'p. 1' });
  assert.deepEqual(md.citeGroup('NVIDIA careers #1; Meta Research #2').map(c => [c.name, c.ref, c.at]), [['NVIDIA careers', '#1', undefined], ['Meta Research', '#2', undefined]]);
  assert.deepEqual(md.citeGroup(`output:${ID} pp.3-5`)[0], { ref: `output:${ID}`, id: ID, name: '', page: 3, at: 'pp. 3–5' });
  // not citation groups: no #n, or #n followed by something that isn't a place
  for (const t of ['Medium', 'x', '1', 'see #3 2024', 'issue#4']) assert.equal(md.citeGroup(t), null, t);
});

test('a group renders as chips: the icon for a hostname, the source title in the tip, plain parts unlinked', () => {
  const html = md.renderMarkdown('They passed. [eecs.berkeley.edu #1:112-113; BLS] And [Medium] stays, as does [a](https://x.org).',
    { cites: ref => (ref === '#1' ? 'Prelim "Advice"' : undefined) });
  assert.ok(html.includes('<span class="aichat-cites" data-src="eecs.berkeley.edu #1:112-113; BLS">'), html);
  assert.ok(html.includes('data-cite="#1" data-line="112" title="Open Prelim &quot;Advice&quot; (#1) at line 112">'), html);
  assert.ok(html.includes('<img class="aichat-cite-ico" src="/api/s/web/v1/favicon?host=eecs.berkeley.edu"'), html);
  assert.ok(html.includes('<span class="aichat-cite-name">eecs.berkeley.edu</span><span class="aichat-cite-at">L112–113</span></a>'), html);
  assert.ok(html.includes('<span class="aichat-cite aichat-cite-plain">BLS</span>'), html);
  assert.ok(html.includes('[Medium]') && html.includes('<a href="https://x.org"'), html);
  // a bare #n chip with no name shows its source's title; no icon for a name that isn't a hostname
  const bare = md.renderMarkdown('[#2; resume #8 p.1]', { cites: ref => (ref === '#2' ? 'The Year That Tried to Break Me' : undefined) });
  assert.ok(bare.includes('<span class="aichat-cite-name">The Year That Tried to Break Me</span>'), bare);
  assert.ok(!bare.includes('<img'), bare);
  assert.ok(!md.renderMarkdown('`[a #1:2]`').includes('aichat-cite'));
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
