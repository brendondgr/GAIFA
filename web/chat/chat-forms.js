// The cards that ask the user something (plan 14.1, 14.5): the question card (ask_user) and the
// parameter card (an approval, or a tool opened by a button or a quick action). Forms are
// mod-form.js's schemaForm (the same form the mod pages use); file inputs (`x-kind`) offer the
// thread's earlier outputs of that kind. Written by us (web/PATCHES.md).

import { h, T, MONO, Icon, Btn, Badge, cardSt, label11, shortArgs, toolLabel } from './chat-ui.js';
import { registerCard, ErrorBox, ProgressBar, STATUS } from './chat-cards.js';
import { schemaForm } from '../mod-form.js';
import { labelOf } from '../mod-options.js';
import { createUi } from '../mod-ui.js';

const R = () => globalThis.React;
const XKIND_TO = { image: 'image', video: 'video', audio: 'audio', mesh: 'model3d' };
const KIND_ICON = { image: 'image', video: 'video', audio: 'wave', model3d: 'cube' };
const empty = v => v == null || v === '' || (Array.isArray(v) && !v.length);
const pick = (schema, names) => {
  const p = schema?.properties || {}, req = schema?.required || [];
  return { type: 'object', properties: Object.fromEntries(names.filter(n => p[n]).map(n => [n, p[n]])), required: req.filter(n => names.includes(n)) };
};
export const outputIdOf = v => { const s = v && typeof v === 'object' ? v.$file : v; return typeof s === 'string' && s.startsWith('output:') ? s.slice(7) : null; };

// ---------- schemaForm inside React ----------
export function SchemaFormHost({ schema, values, order, api, onChange, formKey, context, formRef }) {
  const React = R(), ref = React.useRef(null), cb = React.useRef(onChange), cx = React.useRef(context);
  cb.current = onChange; cx.current = context;
  React.useEffect(() => {
    const el = ref.current; if (!el) return undefined;
    // context: the card's other values (file inputs, the other form), so x-options choices fit them (plan 20.7)
    const f = schemaForm({ ui: createUi(), api }, schema, { values: values || {}, order: order || [], context: () => cx.current?.() });
    if (formRef) formRef.current = f;
    // `onchange` on schemaForm's element is a DOM property, so native change events bubbling from its
    // inputs call it too (with the Event): always hand on the form's values.
    f.onchange = v => cb.current?.(v && typeof v === 'object' && !(typeof Event !== 'undefined' && v instanceof Event) ? v : f.values());
    el.replaceChildren(f);
    cb.current?.(f.values());
    return () => el.replaceChildren();
  }, [formKey]);
  return h('div', { ref, style: { minWidth: 0 } });
}

// ---------- a file input: the thread's outputs of the right kind, then recent ones ----------
export function FilePicker({ name, prop, required, value, onChange, outputs, api }) {
  const React = R(), kind = XKIND_TO[prop['x-kind']] || null, [more, setMore] = React.useState(null);
  const sel = outputIdOf(value);
  const mine = (outputs || []).filter(o => !kind || o.kind === kind).slice().reverse();
  const seen = new Set(mine.map(o => o.output_id));
  const extra = (more || []).filter(o => !seen.has(o.output_id));
  const all = [...mine, ...extra], chosen = all.find(o => o.output_id === sel);
  const loadMore = async () => {
    try { const p = await api.listOutputs({ ...(kind ? { kind } : {}), limit: 12 }); setMore((p.items || []).map(o => ({ output_id: o.id, kind: o.kind, title: o.title, preview: o.preview || (o.kind === 'image' ? o.url : null) }))); }
    catch { setMore([]); }
  };
  const thumb = o => {
    const on = o.output_id === sel;
    return h('button', { key: o.output_id, type: 'button', title: (o.n ? `#${o.n} ` : '') + (o.title || o.output_id), 'aria-pressed': on ? 'true' : 'false',
      onClick: () => onChange(on ? null : { $file: 'output:' + o.output_id }),
      style: { position: 'relative', width: 64, height: 64, padding: 0, borderRadius: 6, overflow: 'hidden', cursor: 'pointer', flex: 'none', background: T.inset,
        border: `2px solid ${on ? T.cy : T.bd}`, display: 'grid', placeItems: 'center', color: T.mut } },
      o.preview ? h('img', { src: o.preview, alt: '', style: { width: '100%', height: '100%', objectFit: 'cover' } }) : h(Icon, { d: KIND_ICON[o.kind] || 'clip', size: 20 }),
      o.n ? h('span', { style: { position: 'absolute', left: 3, top: 3, padding: '0 4px', borderRadius: 3, fontFamily: MONO, fontSize: 10, background: T.card, color: T.tx } }, '#' + o.n) : null,
      on ? h('span', { style: { position: 'absolute', right: 3, bottom: 3, width: 16, height: 16, borderRadius: 99, background: T.cy, color: T.card, display: 'grid', placeItems: 'center' } }, h(Icon, { d: 'check', size: 11, sw: 2.6 })) : null);
  };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 } },
    h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' } },
      h('span', { style: { fontSize: 12, fontWeight: 500 } }, (prop.title || name) + (required ? ' *' : '')),
      h('span', { style: { fontSize: 11.5, color: T.mut, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0, flex: 1 } },
        chosen ? `${chosen.n ? '#' + chosen.n + ' · ' : ''}${chosen.title || ''}` : sel ? sel : `pick ${kind ? 'an ' + (kind === 'model3d' ? '3D model' : kind) : 'a file'}`)),
    h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' } },
      all.map(thumb),
      sel && !chosen ? h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.mut } }, sel) : null,
      more == null ? h(Btn, { sm: true, kind: 'ghost', icon: 'plus', label: all.length ? 'More from Outputs' : `Pick from Outputs`, onClick: loadMore }) : null,
      more && !all.length ? h('span', { style: { fontSize: 12, color: T.mut } }, 'No outputs of this kind yet.') : null));
}

// ---------- the parameter card ----------
// spec: {tool, arguments, ask_fields, schema, risk, description}. decided: {approve, arguments, reason} once done.
export function ParamCard({ spec, outputs, api, mods, decided, onRun, onCancel, runLabel = 'Run', cancelLabel = 'Cancel', title, note, compact, after }) {
  const React = R(), schema = spec.schema || { properties: {} }, props = schema.properties || {}, req = schema.required || [];
  const args = spec.arguments || {};
  const files = Object.keys(props).filter(k => props[k]?.['x-kind']);
  const missing = req.filter(k => !files.includes(k) && empty(args[k]));
  const main = [...new Set([...missing, ...(spec.ask_fields || []).filter(k => props[k] && !files.includes(k))])];
  const rest = Object.keys(props).filter(k => !files.includes(k) && !main.includes(k));
  const [fileVals, setFileVals] = React.useState(() => Object.fromEntries(files.map(k => [k, args[k] ?? null])));
  const vals = React.useRef({ main: {}, rest: {} }), forms = { main: React.useRef(null), rest: React.useRef(null) };
  const others = () => ({ ...args, ...vals.current.rest, ...vals.current.main, ...Object.fromEntries(Object.entries(fileVals).filter(([, v]) => !empty(v))) });
  React.useEffect(() => { forms.main.current?.refilter?.(); forms.rest.current?.refilter?.(); }, [JSON.stringify(fileVals)]);
  const by = spec.filled_by || {}, shown = k => `${k}: ${labelOf(props[k], args[k])}`;
  const mine = (spec.filled || []).filter(k => props[k] && /^pref:|^carried$/.test(by[k] || ''));
  const filledNote = (spec.filled || []).filter(k => props[k] && !mine.includes(k)).map(shown).join(', ');
  const prefNote = mine.map(k => shown(k) + (by[k] === 'carried' ? ' (as on your last card)' : '')).join(', ');
  const [err, setErr] = React.useState(null), [busy, setBusy] = React.useState(false);
  const key = spec.tool + JSON.stringify(Object.keys(props));
  const head = h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, minWidth: 0, flexWrap: 'wrap' } },
    h('span', { style: { color: T.pu, display: 'flex' } }, h(Icon, { d: 'sliders', size: 14 })),
    h('span', { style: { fontWeight: 600 } }, title || toolLabel(spec.tool, mods)),
    spec.risk ? h(Badge, { tone: spec.risk === 'destructive' ? 'red' : 'purple' }, spec.risk) : null,
    h('span', { style: { fontFamily: MONO, fontSize: 11, color: T.dim } }, spec.tool),
    h('span', { style: { flex: 1 } }),
    note ? h('span', { style: { fontSize: 11.5, color: T.mut } }, note) : null);

  if (decided) {
    const ran = decided.approve;
    return h('div', { style: cardSt({ pad: '8px 10px', gap: 4 }) }, head,
      h('div', { style: { display: 'flex', alignItems: 'baseline', gap: 6, fontSize: 12.5, color: ran ? T.tx : T.mut, minWidth: 0 } },
        h('span', { style: { color: ran ? T.gr : T.mut, display: 'flex', alignSelf: 'center' } }, h(Icon, { d: ran ? 'check' : 'x', size: 13, sw: 2.2 })),
        ran ? h('span', { style: { minWidth: 0, overflowWrap: 'anywhere' } }, 'Ran with ', h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: T.mut } }, shortArgs(decided.arguments || args, 400) || 'the defaults'))
          : h('span', null, 'Cancelled', decided.reason ? ` · ${decided.reason}` : '')), after || null);
  }

  const run = async () => {
    const out = { ...vals.current.rest, ...vals.current.main };
    for (const k of files) if (!empty(fileVals[k])) out[k] = fileVals[k];
    const need = req.filter(k => empty(out[k]));
    if (need.length) { setErr({ code: 'required', detail: `Fill in ${need.join(', ')} first.` }); return; }
    setBusy(true); setErr(null);
    try { await onRun(out); } catch (e) { setErr({ code: e.code, detail: e.detail || e.message, fix: e.data?.problems?.map(p => p.fix).filter(Boolean).join('; ') }); }
    setBusy(false);
  };
  const cancel = async () => { setBusy(true); try { await onCancel?.(); } catch (e) { setErr({ code: e.code, detail: e.detail || e.message }); } setBusy(false); };
  const given = Object.fromEntries(Object.entries(args).filter(([k]) => !main.includes(k) && !files.includes(k)));
  return h('div', { style: cardSt({ accent: T.bds, pad: compact ? '8px 10px' : '10px 12px', gap: 10 }), onKeyDown: e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(); } } }, head,
    spec.description && !compact ? h('div', { style: { fontSize: 12, color: T.mut, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' } }, spec.description.split('\n')[0]) : null,
    shortArgs(given) ? h('div', { title: shortArgs(given, 2000), style: { fontFamily: MONO, fontSize: 11.5, color: T.mut, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, shortArgs(given)) : null,
    files.map(k => h(FilePicker, { key: k, name: k, prop: props[k], required: req.includes(k), value: fileVals[k], outputs, api, onChange: v => setFileVals(s => ({ ...s, [k]: v })) })),
    prefNote ? h('div', { title: 'Learned from what you chose before (Learning page). Change it here and it learns again.', style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: T.pu } },
      h(Icon, { d: 'bulb', size: 12 }), 'From your preferences: ' + prefNote) : null,
    filledNote ? h('div', { style: { fontSize: 11.5, color: T.mut } }, 'Chosen for these inputs: ' + filledNote) : null,
    main.length ? h(SchemaFormHost, { formKey: key + ':main', schema: pick(schema, main), values: args, order: main, api, context: others, formRef: forms.main, onChange: v => { vals.current.main = v; } }) : null,
    rest.length ? h('details', { style: { borderTop: '1px solid ' + T.bd, paddingTop: 8 } },
      h('summary', { style: { cursor: 'pointer', fontSize: 12, color: T.mut } }, `All settings (${rest.length})`),
      h('div', { style: { paddingTop: 8 } }, h(SchemaFormHost, { formKey: key + ':rest', schema: pick(schema, rest), values: args, order: rest, api, context: others, formRef: forms.rest, onChange: v => { vals.current.rest = v; } }))) : null,
    err ? h(ErrorBox, { error: err }) : null,
    h('div', { style: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' } },
      h(Btn, { kind: 'pri', icon: 'play', label: busy ? 'Working…' : runLabel, disabled: busy, onClick: run }),
      onCancel ? h(Btn, { kind: 'ghost', label: cancelLabel, disabled: busy, onClick: cancel }) : null,
      h('span', { style: { fontSize: 11.5, color: T.dim, marginLeft: 'auto' } }, 'Ctrl+Enter runs')));
}

// The thread's approval items: the model's call, waiting for Run / Cancel.
function ApprovalCard({ item, ctx }) {
  const a = item.approval, d = item.decision;
  const decided = d ? { approve: d.approve, arguments: d.arguments || a.arguments, reason: d.reason } : item.result && !d ? { approve: false, reason: item.result.error?.detail } : null;
  // once approved: the run's live progress (and Stop), or how it ended
  const running = d?.approve && !item.result, r = item.result, pr = item.progress;
  const after = running ? h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
    h('div', { style: { flex: 1, minWidth: 0 } }, h(ProgressBar, { value: pr?.progress, note: [pr?.note, pr?.progress != null ? Math.round(pr.progress * 100) + '%' : null].filter(Boolean).join(' · ') || 'starting' })),
    ctx.cancel ? h(Btn, { sm: true, icon: 'stop', label: 'Stop', onClick: ctx.cancel }) : null)
    : r?.error && d?.approve ? h(ErrorBox, { error: r.error }) : r && d?.approve && r.status !== 'done' ? h(Badge, { tone: (STATUS[r.status] || ['dim'])[0] }, (STATUS[r.status] || [0, r.status])[1]) : null;
  return h(ParamCard, { spec: a, outputs: ctx.outputs, api: ctx.api, mods: ctx.mods, decided, after,
    onRun: args => ctx.decide(a, true, args), onCancel: () => ctx.decide(a, false) });
}

// ---------- the question card (ask_user) ----------
function QuestionCard({ item, ctx }) {
  const React = R(), qs = item.q.questions || [];
  const [sel, setSel0] = React.useState({}), [other, setOther0] = React.useState({}), [otherOpen, setOtherOpen] = React.useState({});
  // refs mirror the state so two quick clicks in one frame both count
  const selR = React.useRef(sel), otherR = React.useRef(other);
  const setSel = f => { selR.current = typeof f === 'function' ? f(selR.current) : f; setSel0(selR.current); };
  const setOther = f => { otherR.current = typeof f === 'function' ? f(otherR.current) : f; setOther0(otherR.current); };
  const forms = React.useRef({}), [busy, setBusy] = React.useState(false), [err, setErr] = React.useState(null);
  const wrap = (kids, accent) => h('div', { style: cardSt({ accent, pad: '10px 12px', gap: 10 }) },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 6, color: T.pu, fontSize: 12, fontWeight: 600 } }, h(Icon, { d: 'chat', size: 13 }), item.answer ? 'Answered' : 'The agent asks'), kids);
  if (item.answer || item.result) {
    const a = item.answer?.answers || {};
    if (!item.answer) return h('div', { style: { fontSize: 12, color: T.mut, display: 'flex', gap: 6, alignItems: 'center' } }, h(Icon, { d: 'x', size: 12 }), `Question not answered${item.result?.error?.detail ? ': ' + item.result.error.detail : ''}`);
    return h('div', { style: cardSt({ pad: '7px 10px', gap: 3 }) }, qs.map((q, i) => {
      const v = a[q.question], text = v == null ? '—' : Array.isArray(v) ? (v.join(', ') || 'none') : typeof v === 'object' ? shortArgs(v) : String(v);
      return h('div', { key: i, style: { display: 'flex', gap: 8, fontSize: 12.5, minWidth: 0, alignItems: 'baseline' } },
        h('span', { style: { color: T.gr, display: 'flex', alignSelf: 'center' } }, h(Icon, { d: 'check', size: 12, sw: 2.2 })),
        h('span', { style: { color: T.mut, whiteSpace: 'nowrap' } }, (q.header || q.question) + ':'), h('span', { style: { overflowWrap: 'anywhere' } }, text));
    }));
  }
  const pickedOf = (s, i) => s[i] || (qs[i].multi_select ? [] : null);
  const complete = (s, o, i) => qs[i].schema || qs[i].multi_select ? true : (!!pickedOf(s, i) || !!o[i]?.trim());  // picking none of a multi-select is an answer
  const answersOf = (s, o) => Object.fromEntries(qs.map((q, i) => {
    if (q.schema) return [q.question, forms.current[i] || {}];
    const typed = o[i]?.trim();
    if (q.multi_select) return [q.question, [...pickedOf(s, i), ...(typed ? [typed] : [])]];
    return [q.question, typed && !s[i] ? typed : s[i] || typed];
  }));
  const submit = async (s = selR.current, o = otherR.current) => {
    if (busy || !qs.every((_, i) => complete(s, o, i))) return;
    setBusy(true); setErr(null);
    try { await ctx.answer(item.q.id, answersOf(s, o)); } catch (e) { setErr({ code: e.code, detail: e.detail || e.message }); setBusy(false); }
  };
  const choose = (i, label) => {
    const q = qs[i];
    const cur = selR.current, next = { ...cur, [i]: q.multi_select ? (pickedOf(cur, i).includes(label) ? pickedOf(cur, i).filter(x => x !== label) : [...pickedOf(cur, i), label]) : label };
    const o = q.multi_select ? otherR.current : { ...otherR.current, [i]: '' };
    setSel(next); if (!q.multi_select) { setOther(o); setOtherOpen(x => ({ ...x, [i]: false })); }
    return [next, o];
  };
  const option = (q, i, opt, j) => {
    const on = q.multi_select ? pickedOf(sel, i).includes(opt.label) : sel[i] === opt.label;
    return h('button', { key: j, type: 'button', className: 'aichat-opt', role: q.multi_select ? 'checkbox' : 'radio', 'aria-checked': on ? 'true' : 'false', disabled: busy,
      onClick: () => choose(i, opt.label),
      onKeyDown: e => { if (e.key === 'Enter') { e.preventDefault(); const [s, o] = choose(i, opt.label); if (!q.multi_select) submit(s, o); } },
      style: { display: 'flex', alignItems: 'flex-start', gap: 9, width: '100%', textAlign: 'left', padding: '7px 10px', borderRadius: 7, cursor: 'pointer', font: 'inherit', color: T.tx,
        border: '1px solid ' + (on ? T.cy : T.bd), background: on ? T.tcy : T.inset } },
      h('span', { 'aria-hidden': true, style: { width: 14, height: 14, marginTop: 2, flex: 'none', borderRadius: q.multi_select ? 4 : 99, border: '1.5px solid ' + (on ? T.cy : T.bdh), background: on ? T.cy : 'transparent', display: 'grid', placeItems: 'center', color: T.card } },
        on ? (q.multi_select ? h(Icon, { d: 'check', size: 10, sw: 3 }) : h('span', { style: { width: 6, height: 6, borderRadius: 99, background: T.card } })) : null),
      h('span', { style: { display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0 } },
        h('span', { style: { fontWeight: 500, fontSize: 12.5 } }, opt.label),
        opt.description ? h('span', { style: { fontSize: 12, color: T.mut } }, opt.description) : null));
  };
  return wrap([
    ...qs.map((q, i) => h('fieldset', { key: i, style: { border: 0, margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 } },
      h('legend', { style: { padding: 0, marginBottom: 6, display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' } },
        q.header ? h('span', { style: label11 }, q.header) : null, h('span', { style: { fontWeight: 600, fontSize: 13 } }, q.question),
        q.multi_select ? h('span', { style: { fontSize: 11.5, color: T.mut } }, 'pick any') : null),
      q.schema ? h(SchemaFormHost, { formKey: item.q.id + ':' + i, schema: q.schema, api: ctx.api, onChange: v => { forms.current[i] = v; } }) : h('div', { role: q.multi_select ? 'group' : 'radiogroup', 'aria-label': q.question, style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 210px), 1fr))', gap: 6 } },
        (q.options || []).map((o, j) => option(q, i, o, j)),
        otherOpen[i] ? h('input', { autoFocus: true, value: other[i] || '', placeholder: 'Type your own…', 'aria-label': 'Other answer', disabled: busy,
          onChange: e => { const v = e.target.value; setOther(s => ({ ...s, [i]: v })); if (!q.multi_select && v) setSel(s => ({ ...s, [i]: null })); },
          onKeyDown: e => { if (e.key === 'Enter') { e.preventDefault(); submit(); } },
          style: { height: 'auto', minHeight: 34, padding: '0 10px', borderRadius: 7, border: '1px solid ' + T.cy, background: T.sb, color: T.tx, font: 'inherit', fontSize: 12.5, outline: 'none', minWidth: 0 } })
          : h('button', { type: 'button', className: 'aichat-opt', onClick: () => setOtherOpen({ ...otherOpen, [i]: true }), disabled: busy,
            style: { display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', borderRadius: 7, cursor: 'pointer', font: 'inherit', fontSize: 12.5, color: T.mut, border: '1px dashed ' + T.bds, background: 'transparent', textAlign: 'left' } },
          h(Icon, { d: 'edit', size: 12 }), 'Other…')))),
    err ? h(ErrorBox, { key: 'err', error: err }) : null,
    h('div', { key: 'foot', style: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' } },
      h(Btn, { kind: 'pri', label: busy ? 'Sending…' : 'Submit', disabled: busy || !qs.every((_, i) => complete(sel, other, i)), onClick: () => submit() }),
      h('span', { style: { fontSize: 11.5, color: T.dim } }, 'Enter picks an option · or just type a reply below')),
  ], T.bds);
}

// A tool opened by a result button or a quick action (not yet in the thread): runs via POST /action.
function ToolFormCard({ item, ctx }) {
  const t = item.tool;
  if (!t) return h('div', { style: cardSt() }, h('span', { style: { color: T.mut } }, 'Loading the tool…'));
  return h(ParamCard, { spec: { tool: t.name, arguments: item.args || {}, ask_fields: t.ask || [], schema: t.parameters, risk: t.risk, description: t.description }, title: item.label,
    outputs: ctx.outputs, api: ctx.api, mods: ctx.mods, note: 'runs without asking the model', onRun: args => ctx.runTool(item, args), onCancel: () => ctx.closeTool(item) });
}

registerCard('approval', ApprovalCard);
registerCard('question', QuestionCard);
registerCard('toolform', ToolFormCard);
