// A tiny DOM stand-in for Node tests: parses the HTML that chat-md.js `renderMarkdown` writes (tags with
// double-quoted attributes, `<br>` / `<hr>`, the five entities) into nodes with the parts of the DOM API the
// chat reads: nodeType, nodeName, nodeValue, childNodes, parentNode, getAttribute, textContent.

const ENT = { amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'" };
const decode = s => s.replace(/&(amp|lt|gt|quot|#39);/g, (_, e) => ENT[e]);
const VOID = new Set(['br', 'hr', 'img', 'input']);

class Node {
  constructor(type, name, value = null) { this.nodeType = type; this.nodeName = name; this.nodeValue = value; this.childNodes = []; this.parentNode = null; this.attrs = {}; }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  append(c) { c.parentNode = this; this.childNodes.push(c); return c; }
  get textContent() { return this.nodeType === 3 ? this.nodeValue : this.childNodes.map(c => c.textContent).join(''); }
}

/** HTML → a root element (`div.aichat-md` by default) holding the parsed nodes. */
export function parse(html, { tag = 'div', cls = 'aichat-md' } = {}) {
  const root = new Node(1, tag.toUpperCase());
  if (cls) root.attrs.class = cls;
  let cur = root;
  const re = /<(\/?)([a-zA-Z][\w-]*)((?:\s+[\w-]+(?:="[^"]*")?)*)\s*\/?>|([^<]+)/g;
  for (const m of html.matchAll(re)) {
    if (m[4] !== undefined) { cur.append(new Node(3, '#text', decode(m[4]))); continue; }
    const name = m[2].toLowerCase();
    if (m[1]) { while (cur !== root && cur.nodeName.toLowerCase() !== name) cur = cur.parentNode; if (cur !== root) cur = cur.parentNode; continue; }
    const el = cur.append(new Node(1, name.toUpperCase()));
    for (const a of m[3].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) el.attrs[a[1]] = a[2] === undefined ? '' : decode(a[2]);
    if (!VOID.has(name)) cur = el;
  }
  return root;
}

/** Every text node under `n`, in document order. */
export function texts(n, out = []) {
  if (n.nodeType === 3) out.push(n);
  n.childNodes.forEach(c => texts(c, out));
  return out;
}

/** A boundary point `k` characters into the first text node containing `needle` (after `skip` matches). */
export function at(root, needle, k = 0, skip = 0) {
  for (const t of texts(root)) {
    const i = t.nodeValue.indexOf(needle);
    if (i >= 0 && skip-- <= 0) return { node: t, offset: i + k };
  }
  throw new Error(`no text ${JSON.stringify(needle)}`);
}
