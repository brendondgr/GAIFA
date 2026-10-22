// Plan 42.2: the message box after Claude Code's: + on the left (upload, attach, tool groups, the quick actions),
// the microphone, Stop and Send on the right, no hint line, the text growing to 40% of the window, and the
// controls row under the box.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
globalThis.React = {
  Fragment: Symbol('Fragment'),
  createElement: (type, props, ...children) => ({ type, props: { ...(props || {}), children: children.flat() } }),
  useState: init => [typeof init === 'function' ? init() : init, () => {}],
  useRef: v => ({ current: v }), useEffect: () => {}, useLayoutEffect: () => {}, useMemo: f => f(), useCallback: f => f,
};
const { Composer, PLUS_ITEMS, boxMax } = await import(pathToFileURL(path.join(root, 'web/chat/chat-composer.js')).href);
const { registerAction } = await import(pathToFileURL(path.join(root, 'web/chat/chat-actions.js')).href);

const all = (n, pred, out = []) => {
  if (Array.isArray(n)) { n.forEach(x => all(x, pred, out)); return out; }
  if (!n || typeof n !== 'object') return out;
  if (pred(n)) out.push(n);
  all(n.props?.children, pred, out);
  return out;
};
const text = n => (n == null || n === false ? '' : typeof n !== 'object' ? String(n) : Array.isArray(n) ? n.map(text).join('') : text(n.props?.children));
const box = (props = {}) => Composer({ draft: '', setDraft() {}, attachments: [], setAttachments() {}, onSend() {}, onStop() {}, running: false, tools: [], index: [],
  settings: {}, onSettings() {}, skills: [], outputs: [], api: {}, onQuick() {}, ...props });

test('the + menu: upload, attach, tool groups, then the quick actions', () => {
  registerAction({ id: 'layout-test', label: 'Make a picture', on: 'composer', icon: 'image', tool: 'comfy_generate_image', when: () => true });
  const tree = box({ index: [{ name: 'comfy_generate_image', mod: 'comfy' }] });
  const plus = all(tree, n => n.props?.['aria-label'] === 'Add')[0];
  assert.ok(plus, 'a + button');
  const menu = all(tree, n => n.props?.label === 'Add')[0];                    // its popover (rendered only while open)
  const items = menu.props.children.flat().filter(Boolean).filter(n => n.props?.role === 'menuitem').map(text);
  assert.deepEqual(items.slice(0, 3), PLUS_ITEMS.map(x => x[2]));
  assert.ok(items.includes('Make a picture'));
  assert.equal(all(tree, n => n.props?.label === 'Attach outputs').length, 1);   // what Attach and Tool groups open
  assert.equal(all(tree, n => n.props?.label === 'Tool groups').length, 1);
});

test('the right side: the microphone, Stop while a turn runs, then Send; no hint line', () => {
  const idle = box({ draft: 'hi' });
  assert.doesNotMatch(text(idle), /Enter sends/);
  const row = all(idle, n => n.type === 'div' && all(n, x => x.props?.['aria-label'] === 'Add').length && all(n, x => /^Send/.test(x.props?.title || '')).length)
    .filter(n => n.props.style?.display === 'flex' && n.props.style?.alignItems === 'center').pop();
  const kids = row.props.children.filter(Boolean);
  const titles = kids.map(k => k.props?.title || (typeof k.type === 'function' ? k.type.name : k.type));
  assert.ok(titles.indexOf('MicButton') > titles.findIndex(t => t === 'span'), 'the mic after the spacer');
  assert.match(titles[titles.length - 1], /^Send/);
  const busy = box({ draft: 'hi', running: true });
  assert.ok(all(busy, n => n.props?.title === 'Stop the turn (and its running tool)').length === 1);
  assert.ok(all(busy, n => n.props?.title === 'Queue this message').length === 1);
});

test('the text grows to 40% of the window (at least 120 px), and the controls row goes under the box', () => {
  assert.equal(boxMax(1000), 400);
  assert.equal(boxMax(200), 120);
  const area = all(box(), n => n.type === 'textarea')[0];
  assert.equal(area.props.style.maxHeight, boxMax());
  const tree = box({ controls: { type: 'div', props: { 'data-controls': true, children: ['CONTROLS'] } } });
  assert.match(text(tree), /CONTROLS$/);
});
