// Plan 24.6: the composer's files: every new extension is uploadable, long pastes become files
// (2000 characters or 40 lines), a single fenced block or JSON picks the extension, and the chips.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const files = await import(pathToFileURL(path.join(root, 'web/chat/chat-files.js')).href);
const composer = await import(pathToFileURL(path.join(root, 'web/chat/chat-composer.js')).href);

const TEXT = ['md', 'markdown', 'txt', 'log', 'rst', 'py', 'js', 'mjs', 'ts', 'tsx', 'jsx', 'rs', 'go', 'c', 'h', 'cpp', 'hpp', 'cc', 'java', 'kt',
  'swift', 'rb', 'php', 'lua', 'sh', 'bash', 'zsh', 'fish', 'ps1', 'sql', 'r', 'jl', 'cs', 'toml', 'yaml', 'yml', 'ini', 'cfg', 'conf',
  'env.example', 'xml', 'html', 'htm', 'css', 'scss', 'json', 'jsonl', 'csv', 'tsv', 'srt', 'vtt', 'ipynb'];
const DOCS = ['pdf', 'docx', 'epub', 'pptx', 'xlsx', 'odt'];

test('uploadable takes every new extension, by name, in any case', () => {
  for (const e of TEXT) assert.equal(files.kindOf(`notes.${e}`), 'text', e);
  for (const e of DOCS) assert.equal(files.kindOf(`paper.${e.toUpperCase()}`), 'document', e);
  const f = (name, type = '') => ({ name, type });
  const list = [f('a.png', 'image/png'), f('b.txt', 'text/plain'), f('c.MOV'), f('d.pdf', 'application/pdf'), f('e.py'), f('.env.example'),
    f('f.exe', 'application/octet-stream'), f('g'), null];
  assert.deepEqual(composer.uploadable(list).map(x => x.name), ['a.png', 'b.txt', 'c.MOV', 'd.pdf', 'e.py', '.env.example']);
  assert.ok(TEXT.concat(DOCS).every(e => files.ACCEPT.includes('.' + e)) && files.ACCEPT.startsWith('image/*,video/*,audio/*'));
});

test('a paste over 2000 characters or 40 lines becomes a file', () => {
  const at = new Date(2026, 9, 20, 14, 30, 12);
  assert.equal(files.pasteFile('short text', at), null);
  assert.equal(files.pasteFile('x'.repeat(2000), at), null);
  assert.equal(files.pasteFile(Array(40).fill('l').join('\n'), at), null);
  assert.deepEqual(files.pasteFile('x'.repeat(2001), at), { name: 'pasted-143012.md', body: 'x'.repeat(2001) });
  const lines = Array(41).fill('a line').join('\n');
  assert.equal(files.pasteFile(lines, at).name, 'pasted-143012.md');
});

test('one fenced block with a language, or JSON, picks the extension', () => {
  const at = new Date(2026, 9, 20, 9, 5, 7), code = Array(50).fill('print("hi")').join('\n');
  assert.deepEqual(files.pasteFile('```python\n' + code + '\n```', at), { name: 'pasted-090507.py', body: code + '\n' });
  assert.equal(files.pasteFile('```js\n' + code + '\n```\n', at).name, 'pasted-090507.js');
  assert.equal(files.pasteFile('~~~bash\n' + code + '\n~~~', at).name, 'pasted-090507.sh');
  assert.equal(files.pasteFile('```klingon\n' + code + '\n```', at).name, 'pasted-090507.md');          // unknown language
  assert.equal(files.pasteFile('```py\n' + code + '\n```\nand more\n```js\nx\n```', at).name, 'pasted-090507.md');  // two blocks
  assert.equal(files.pasteFile('intro\n```py\n' + code + '\n```', at).name, 'pasted-090507.md');        // not the whole paste
  const json = JSON.stringify({ rows: Array(300).fill({ a: 1, b: 'two' }) }, null, 1);
  assert.deepEqual(files.pasteFile(json, at), { name: 'pasted-090507.json', body: json + '\n' });
  assert.equal(files.pasteFile('{' + 'x'.repeat(3000), at).name, 'pasted-090507.md');                  // not valid JSON
});

test('chips: subtype, icon and size', () => {
  assert.deepEqual(files.toChip({ id: 'o1', kind: 'document', subtype: 'pdf', title: 'a.pdf', url: '/u', preview: null }),
    { id: 'o1', kind: 'document', title: 'a.pdf', preview: null, subtype: 'pdf' });
  assert.equal(files.chipIcon({ kind: 'text', subtype: 'code:python' }), 'code');
  assert.equal(files.chipIcon({ kind: 'text', subtype: 'markdown' }), 'doc');
  assert.equal(files.chipIcon({ kind: 'document' }), 'doc');
  assert.equal(files.chipIcon({ kind: 'audio' }), 'wave');
  assert.equal(files.chipSize({ pages: 12 }), '12 pages');
  assert.equal(files.chipSize({ lines: 1 }), '1 line');
  assert.equal(files.chipSize({}), '');
});
