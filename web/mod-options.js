// Choices that depend on the inputs (plan 20.7): the card's side of the hub's `x-options`
// (utils/tools/options.py; brief §11.12). An enum property may carry `x-options`, one entry per value:
// {label, needs, excludes, default, good_for, speed, kind, allows: {param: values}}; a property with
// `x-depends-on` takes only what its parent's chosen option allows. Pure: tested in modpage.test.mjs.
// Import as '/mod-options.js'.

export const present = (vals, name) => {
  const v = vals?.[name];
  return v !== undefined && v !== null && v !== '' && !(Array.isArray(v) && !v.length) && !(typeof v === 'object' && !Array.isArray(v) && !Object.keys(v).length);
};
export const optionsOf = p => (p && p['x-options'] && typeof p['x-options'] === 'object' ? p['x-options'] : null);
export const fits = (opt, vals) => (opt?.needs || []).every(n => present(vals, n)) && !(opt?.excludes || []).some(n => present(vals, n));

/** The values of `name` that fit the other values (its whole enum when nothing is declared). */
export function choices(schema, name, vals) {
  const props = schema?.properties || {}, p = props[name] || {};
  let out = [...(p.enum || [])];
  const o = optionsOf(p);
  if (o) out = out.filter(v => fits(o[String(v)] || {}, vals));
  const dep = p['x-depends-on'];
  const parentOpt = dep ? optionsOf(props[dep])?.[String(vals?.[dep] ?? defaultOf(schema, dep, vals) ?? '')] : null;
  const allowed = parentOpt?.allows?.[name];
  if (Array.isArray(allowed)) out = out.filter(v => allowed.includes(v));
  return out;
}

/** The value the hub fills when `name` is left out: the `default` option that fits, else null. */
export function defaultOf(schema, name, vals) {
  const o = optionsOf(schema?.properties?.[name]);
  if (!o) return null;
  const hit = Object.entries(o).find(([, opt]) => opt?.default && fits(opt, vals));
  return hit ? hit[0] : null;
}

/** A value's label: its option's `label`, else the value. */
export const labelOf = (p, v) => String(optionsOf(p)?.[String(v)]?.label || v);

/** One line of help for a value: what it's good for and how long it takes. */
export function helpOf(p, v) {
  const opt = optionsOf(p)?.[String(v)];
  return opt ? [opt.good_for, opt.speed].filter(Boolean).join(' · ') : '';
}
