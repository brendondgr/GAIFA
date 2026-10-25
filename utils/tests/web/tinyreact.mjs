// A minimal stand-in for React in Node tests: elements as objects, function components expanded once, hooks
// with fixed state (useState keeps its first value; effects never run; nothing mounts). Import it before the
// module under test. `render(el)` expands a tree; `all`, `text`, `find` read it.
const Fragment = Symbol('Fragment');
globalThis.React = {
  Fragment,
  createElement: (type, props, ...children) => ({ type, props: { ...(props || {}), children: children.flat(Infinity) } }),
  useState: init => [typeof init === 'function' ? init() : init, () => {}],
  useRef: v => ({ current: v }), useEffect: () => {}, useLayoutEffect: () => {}, useMemo: f => f(), useCallback: f => f,
  useImperativeHandle: () => {}, forwardRef: f => props => f(props, null),
};

export function render(n) {
  if (n == null || n === false || n === true || typeof n !== 'object') return n;
  if (Array.isArray(n)) return n.map(render);
  if (typeof n.type === 'function') return render(n.type(n.props));
  return { ...n, props: { ...n.props, children: (n.props.children || []).map(render) } };
}
export function all(n, pred, out = []) {
  if (Array.isArray(n)) { n.forEach(x => all(x, pred, out)); return out; }
  if (!n || typeof n !== 'object') return out;
  if (pred(n)) out.push(n);
  all(n.props?.children, pred, out);
  return out;
}
export const text = n => (n == null || n === false || n === true ? '' : typeof n !== 'object' ? String(n) : Array.isArray(n) ? n.map(text).join('') : text(n.props?.children));
export const find = (n, pred) => all(n, pred)[0] || null;
