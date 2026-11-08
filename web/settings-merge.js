// A save merged with what is saved now (plan settings-that-stick 2.1–2.2), as utils/settings_merge.py does it: a writer
// sends `base`, what each changed key held when it loaded the settings. Lists keep what others added and drop what this
// writer removed; tables merge entry by entry; a plain value both sides changed differently is a conflict. Used by the
// mock (web/mock.js) and by every writer to build its `base` (baseOf). Written by us (web/PATCHES.md).

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const key = v => JSON.stringify(v);
const isObj = v => v != null && typeof v === 'object' && !Array.isArray(v);

export class Conflict extends Error {
  constructor(field, current, yours) { super(field); this.field = field; this.current = current; this.yours = yours; }
}

export function mergeList(current, base, mine) {
  const baseK = new Set(base.map(key)), mineK = new Set(mine.map(key));
  const out = current.filter(x => !(baseK.has(key(x)) && !mineK.has(key(x))));
  const have = new Set(out.map(key));
  for (const x of mine) if (!baseK.has(key(x)) && !have.has(key(x))) { out.push(x); have.add(key(x)); }
  return out;
}

export function mergeValue(field, current, base, mine) {
  if (same(current, base) || same(current, mine) || same(base, mine)) return same(base, mine) ? current : mine;
  if (Array.isArray(current) && Array.isArray(base) && Array.isArray(mine)) return mergeList(current, base, mine);
  if (isObj(current) && isObj(base) && isObj(mine)) {
    const out = { ...current };
    for (const k of new Set([...Object.keys(base), ...Object.keys(mine)])) {
      const hasB = k in base, hasM = k in mine;
      if (hasB && hasM && same(base[k], mine[k])) continue;   // the writer didn't change this entry
      if (!hasM) delete out[k];
      else if (!hasB || !(k in current)) out[k] = mine[k];
      else out[k] = mergeValue(`${field}.${k}`, current[k], base[k], mine[k]);
    }
    return out;
  }
  throw new Conflict(field, current, mine);
}

/** `patch` with each key that has a `base` merged against `current` (section → key → value). */
export function rebase(current, patch, base) {
  if (!base) return patch;
  const out = {};
  for (const [sec, vals] of Object.entries(patch || {})) {
    const b = isObj(base[sec]) ? base[sec] : null, cur = current[sec] || {};
    if (!isObj(vals) || !b) { out[sec] = vals; continue; }
    out[sec] = Object.fromEntries(Object.entries(vals).map(([k, v]) => [k, k in b && k in cur ? mergeValue(`${sec}.${k}`, cur[k], b[k], v) : v]));
  }
  return out;
}

/** The `base` for `patch`: what each of its keys held in `loaded` (the settings the writer read). */
export function baseOf(patch, loaded) {
  const out = {};
  for (const [sec, vals] of Object.entries(patch || {})) {
    if (!isObj(vals) || !isObj(loaded?.[sec])) continue;
    for (const k of Object.keys(vals)) if (k in loaded[sec]) (out[sec] ||= {})[k] = JSON.parse(JSON.stringify(loaded[sec][k]));
  }
  return out;
}
