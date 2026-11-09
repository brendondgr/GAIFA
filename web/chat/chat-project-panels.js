// The project page's side column (plan projects 5.2): Instructions, Files, Pages, Memory, Folders and Defaults, each a
// panel with a header and its own Add / Edit; then Delete project. They follow the agent's `project` and
// `project_source` events (the page reloads the project). Pure helpers first (tested in
// utils/tests/web/chat-project.test.mjs). Written by us (web/PATCHES.md).

import { h, T, MONO, Icon, Btn, Popover, inputSt, label11 } from './chat-ui.js';
import { shortPath, LEVEL_WORD } from './chat-env.js';
import { MODES } from './chat-header.js';

const R = () => globalThis.React;
// A page's freshness: fetched again when a question needs it and its copy is older than this (null: never on its own)
export const FRESHNESS = [[900, '15 min'], [3600, '1 h'], [21600, '6 h'], [86400, '1 day'], [604800, '1 week'], [null, 'Never refresh automatically']];
export const freshLabel = s => (FRESHNESS.find(f => f[0] === (s ?? null)) || [null, s ? `${Math.round(s / 60)} min` : 'Never refresh automatically'])[1];

/** "fetched 2 h ago", "fetching…", "never fetched": a page's copy, for its row. */
export function pageAge(src, now = Date.now() / 1000) {
  if (src.status === 'fetching') return 'fetching…';
  if (!src.fetched) return 'never fetched';
  const d = Math.max(0, now - src.fetched);
  const ago = d < 60 ? 'just now' : d < 3600 ? `${Math.floor(d / 60)} min ago` : d < 86400 ? `${Math.floor(d / 3600)} h ago` : `${Math.floor(d / 86400)} d ago`;
  return 'fetched ' + ago;
}
/** A size in characters as the agent counts (4 to a token): "~12k tokens". */
export function sizeWords(chars) {
  const t = Math.round((chars || 0) / 4);
  return t >= 1000 ? `~${(t / 1000).toFixed(t >= 10000 ? 0 : 1)}k tokens` : `~${t} tokens`;
}
/** The environments with `id` moved to `to` (0: the primary); unknown ids leave the list as it was. */
export function moveEnv(envs, id, to) {
  const list = [...(envs || [])], i = list.indexOf(id);
  if (i < 0) return list;
  list.splice(i, 1);
  list.splice(Math.max(0, Math.min(list.length, to)), 0, id);
  return list;
}
/** What the folders panel lists: the project's environments (primary first) with their names and folder counts.
 * `missing`: the workspace mod's list doesn't have it (not said while that list is unknown: `envs` null). */
export function envRows(ids, envs) {
  return (ids || []).map((id, i) => {
    const e = (envs || []).find(x => x.id === id);
    return { id, name: e?.name || id, folders: (e?.folders || []).length, primary: i === 0, missing: Array.isArray(envs) && !e };
  });
}

// ---------- shared bits ----------
export function Panel({ title, icon, count, actions, children, open: open0 = true }) {
  const React = R(), [open, setOpen] = React.useState(open0);
  return h('section', { 'aria-label': title, style: { border: '1px solid ' + T.bd, borderRadius: 10, background: T.card } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px' } },
      h('button', { type: 'button', onClick: () => setOpen(!open), 'aria-expanded': open ? 'true' : 'false',
        style: { display: 'flex', alignItems: 'center', gap: 7, flex: 1, minWidth: 0, border: 0, background: 'none', color: T.tx, font: 'inherit', fontSize: 13, fontWeight: 600, cursor: 'pointer', padding: 0, textAlign: 'left' } },
        h(Icon, { d: icon, size: 14 }), title, count != null ? h('span', { style: { fontSize: 11.5, color: T.dim, fontWeight: 400 } }, count) : null),
      actions || null),
    open ? h('div', { style: { padding: '0 12px 12px', display: 'flex', flexDirection: 'column', gap: 6 } }, children) : null);
}
const rowSt = { display: 'flex', alignItems: 'center', gap: 8, minHeight: 30, fontSize: 12.5, minWidth: 0 };
const ell = { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 };
const iconBtn = (icon, label, onClick, color = T.mut) => h('button', { type: 'button', onClick, title: label, 'aria-label': label,
  style: { border: 0, background: 'none', color, cursor: 'pointer', padding: 3, display: 'flex', flex: 'none' } }, h(Icon, { d: icon, size: 13 }));
const muted = text => h('div', { style: { fontSize: 12, color: T.mut } }, text);

// ---------- Instructions ----------
export function InstructionsPanel({ p, onSave }) {
  const React = R(), [v, setV] = React.useState(p.instructions || ''), [busy, setBusy] = React.useState(false), [edit, setEdit] = React.useState(false);
  React.useEffect(() => { if (!edit) setV(p.instructions || ''); }, [p.instructions]);
  const dirty = v !== (p.instructions || '');
  return h(Panel, { title: 'Instructions', icon: 'edit', actions: edit ? null : h(Btn, { kind: 'ghost', sm: true, label: p.instructions ? 'Edit' : 'Add', onClick: () => setEdit(true) }) },
    edit ? h(React.Fragment, null,
      h('textarea', { value: v, onChange: e => setV(e.target.value), rows: 8, maxLength: 16000, autoFocus: true, 'aria-label': 'Project instructions',
        placeholder: 'What every chat in this project should follow (markdown)', style: { ...inputSt, height: 'auto', padding: '8px 9px', resize: 'vertical', fontFamily: MONO, fontSize: 12, lineHeight: 1.5 } }),
      h('div', { style: { display: 'flex', gap: 8, alignItems: 'center' } },
        h(Btn, { kind: 'pri', sm: true, label: busy ? 'Saving…' : 'Save', disabled: busy || !dirty, onClick: async () => { setBusy(true); try { await onSave({ instructions: v }); setEdit(false); } finally { setBusy(false); } } }),
        h(Btn, { kind: 'ghost', sm: true, label: 'Cancel', onClick: () => { setV(p.instructions || ''); setEdit(false); } }),
        h('span', { style: { marginLeft: 'auto', fontSize: 11, color: T.dim } }, `${v.length.toLocaleString()} / 16,000`)))
      : p.instructions ? h('div', { style: { fontSize: 12.5, color: T.mut, whiteSpace: 'pre-wrap', maxHeight: 160, overflow: 'auto' } }, p.instructions)
        : muted('Every chat in the project follows these, after AGENT.md.'));
}

// ---------- Files ----------
export function FilesPanel({ p, c, api, toast, openOutput }) {
  const React = R(), [picking, setPicking] = React.useState(false), fileRef = React.useRef(null);
  const files = (p.sources || []).filter(s => s.kind === 'file');
  const add = async (oid, title) => { try { await c.addSource(p.id, { kind: 'file', output_id: oid, ...(title ? { title } : {}) }); } catch (e) { toast(e?.detail || 'Not added', 'error'); } };
  const upload = async list => {
    for (const f of [...(list || [])]) {
      try { const o = await api.uploadOutput(f); await add(o.id, o.title); } catch (e) { toast(e?.detail || `${f.name} wasn’t uploaded`, 'error'); }
    }
  };
  return h(Panel, { title: 'Files', icon: 'doc', count: files.length || null, actions: h('span', { style: { position: 'relative' } },
    h(Btn, { kind: 'ghost', sm: true, icon: 'plus', label: 'Add', onClick: () => setPicking(!picking) }),
    h('input', { ref: fileRef, type: 'file', multiple: true, hidden: true, 'aria-label': 'Upload files to the project', accept: '.md,.markdown,.txt,.rst,.pdf,.docx,.epub,.odt,.html,.htm,.csv,.json,.py,.js,.ts,.toml,.yaml,.yml',
      onChange: e => { setPicking(false); upload(e.target.files); e.target.value = ''; } }),
    h(Popover, { open: picking, onClose: () => setPicking(false), width: 300, label: 'Add a file' },
      h('button', { type: 'button', onClick: () => fileRef.current?.click(), style: { ...rowSt, border: 0, background: 'none', color: T.tx, font: 'inherit', cursor: 'pointer', padding: '4px 2px' } },
        h(Icon, { d: 'upload', size: 13 }), 'Upload from this computer'),
      h(OutputPicker, { api, onPick: o => { setPicking(false); add(o.id, o.title); } }))) },
    files.length ? files.map(s => h('div', { key: s.id, style: rowSt },
      h(Icon, { d: 'doc', size: 13 }),
      h('a', { href: '#', onClick: e => { e.preventDefault(); openOutput?.(s.output_id); }, title: s.title, style: { ...ell, flex: 1, color: T.tx, textDecoration: 'none' } }, s.title),
      h('span', { style: { fontSize: 11, color: T.dim, flex: 'none' } }, sizeWords(s.chars)),
      iconBtn('x', `Remove ${s.title} from the project (it stays in Outputs)`, () => c.removeSource(p.id, s.id).catch(e => toast(e?.detail || 'Not removed', 'error')))))
      : muted('Upload a file or pick one from Outputs: texts and documents.'));
}

function OutputPicker({ api, onPick }) {
  const React = R(), [items, setItems] = React.useState(null), [q, setQ] = React.useState('');
  React.useEffect(() => {
    Promise.all(['document', 'text'].map(kind => api.listOutputs?.({ kind, limit: 30 }).then(r => r.items || [], () => [])))
      .then(([a, b]) => setItems([...a, ...b].sort((x, y) => (y.created_ts || 0) - (x.created_ts || 0))), () => setItems([]));
  }, []);
  const shown = (items || []).filter(o => !q || String(o.title || '').toLowerCase().includes(q.toLowerCase())).slice(0, 12);
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4, borderTop: '1px solid ' + T.bd, paddingTop: 6 } },
    h('span', { style: label11 }, 'From Outputs'),
    h('input', { value: q, onChange: e => setQ(e.target.value), placeholder: 'Search outputs', 'aria-label': 'Search outputs', style: { ...inputSt, height: 28 } }),
    items == null ? muted('Loading…') : !shown.length ? muted('No texts or documents.') :
      shown.map(o => h('button', { key: o.id, type: 'button', onClick: () => onPick(o), title: o.title,
        style: { ...rowSt, border: 0, background: 'none', color: T.tx, font: 'inherit', cursor: 'pointer', padding: '2px', textAlign: 'left' } },
        h(Icon, { d: 'doc', size: 12 }), h('span', { style: { ...ell, flex: 1 } }, o.title || o.id))));
}

// ---------- Pages ----------
export function PagesPanel({ p, c, toast }) {
  const React = R(), [adding, setAdding] = React.useState(false), [url, setUrl] = React.useState(''), [menu, setMenu] = React.useState(null);
  const pages = (p.sources || []).filter(s => s.kind === 'page');
  const add = async () => {
    const u = url.trim();
    if (!/^https?:\/\//i.test(u)) { toast('A page is an http:// or https:// address', 'error'); return; }
    try { await c.addSource(p.id, { kind: 'page', url: u }); setUrl(''); setAdding(false); } catch (e) { toast(e?.detail || 'Not added', 'error'); }
  };
  const act = (fn, ok) => fn.then(() => ok && toast(ok, 'success'), e => toast(e?.detail || 'That didn’t work', 'error'));
  return h(Panel, { title: 'Pages', icon: 'globe', count: pages.length || null, actions: h(Btn, { kind: 'ghost', sm: true, icon: 'plus', label: 'Add', onClick: () => setAdding(!adding) }) },
    adding ? h('form', { onSubmit: e => { e.preventDefault(); add(); }, style: { display: 'flex', gap: 6 } },
      h('input', { autoFocus: true, value: url, onChange: e => setUrl(e.target.value), placeholder: 'https://…', 'aria-label': 'Page address', style: { ...inputSt, flex: 1, height: 30 } }),
      h(Btn, { kind: 'pri', sm: true, label: 'Add', onClick: add })) : null,
    pages.length ? pages.map(s => h('div', { key: s.id, style: { display: 'flex', flexDirection: 'column', gap: 2, padding: '4px 0', borderTop: '1px solid ' + T.bd } },
      h('div', { style: rowSt },
        h(Icon, { d: 'globe', size: 13 }),
        h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer', title: s.url, style: { ...ell, flex: 1, color: T.tx, textDecoration: 'none' } }, s.title || s.url),
        h('span', { style: { position: 'relative', flex: 'none' } },
          iconBtn('more', `More for ${s.title || s.url}`, () => setMenu(menu === s.id ? null : s.id)),
          h(Popover, { open: menu === s.id, onClose: () => setMenu(null), width: 230, label: 'Page', style: { gap: 2, padding: 4 } },
            h('button', { type: 'button', onClick: () => { setMenu(null); act(c.refreshSource(p.id, s.id)); }, style: { ...rowSt, border: 0, background: 'none', color: T.tx, font: 'inherit', cursor: 'pointer', padding: '0 6px' } }, h(Icon, { d: 'refresh', size: 13 }), 'Refresh now'),
            h('span', { style: { ...label11, padding: '4px 6px 0' } }, 'Fetch again when older than'),
            FRESHNESS.map(([v, l]) => h('button', { key: String(v), type: 'button', role: 'menuitemradio', 'aria-checked': (s.max_age_s ?? null) === v ? 'true' : 'false',
              onClick: () => { setMenu(null); act(c.patchSource(p.id, s.id, { max_age_s: v })); },
              style: { ...rowSt, minHeight: 26, border: 0, background: (s.max_age_s ?? null) === v ? T.hov : 'none', color: T.tx, font: 'inherit', cursor: 'pointer', padding: '0 6px', borderRadius: 5 } },
              h('span', { style: { width: 14, display: 'flex' } }, (s.max_age_s ?? null) === v ? h(Icon, { d: 'check', size: 12 }) : null), l)),
            h('button', { type: 'button', onClick: () => { setMenu(null); act(c.removeSource(p.id, s.id)); }, style: { ...rowSt, border: 0, background: 'none', color: T.rd, font: 'inherit', cursor: 'pointer', padding: '0 6px' } }, h(Icon, { d: 'trash', size: 13 }), 'Remove')))),
      h('div', { style: { display: 'flex', gap: 8, fontSize: 11, color: T.dim, paddingLeft: 21, flexWrap: 'wrap' } },
        h('span', { style: { ...ell, fontFamily: MONO, maxWidth: 180 } }, s.url.replace(/^https?:\/\/(www\.)?/, '')),
        h('span', { style: { color: s.status === 'error' ? T.rd : s.status === 'fetching' ? T.acc : T.dim } }, s.status === 'error' ? `failed: ${s.error || 'error'}` : pageAge(s)),
        h('span', null, freshLabel(s.max_age_s)))))
      : muted('Link pages: they are fetched again when a question needs them fresh.'));
}

// ---------- Memory ----------
export function MemoryPanel({ p, c, toast }) {
  const React = R(), [mem, setMem] = React.useState(null), [edit, setEdit] = React.useState(null);
  const load = () => c.projectMemory(p.id).then(setMem, () => setMem({ entity: null, facts: [] }));
  React.useEffect(() => { load(); }, [p.id, p.updated]);
  const facts = mem?.facts || [];
  const save = async (f, text) => { try { await c.patchProjectFact(p.id, f.id, { text }); setEdit(null); load(); } catch (e) { toast(e?.detail || 'Not saved', 'error'); } };
  const forget = async f => { try { await c.forgetProjectFact(p.id, f.id); load(); } catch (e) { toast(e?.detail || 'Not forgotten', 'error'); } };
  return h(Panel, { title: 'Memory', icon: 'bookmark', count: facts.length || null,
    actions: mem?.entity ? h('a', { href: '#/s/agent/memory', style: { fontSize: 12 } }, 'Open in Memory') : null },
    mem == null ? muted('Loading…') : facts.length ? facts.map(f => h('div', { key: f.id, style: { ...rowSt, alignItems: 'flex-start' } },
      edit?.id === f.id
        ? h('input', { autoFocus: true, value: edit.text, onChange: e => setEdit({ ...edit, text: e.target.value }), 'aria-label': 'Fact',
          onKeyDown: e => { if (e.key === 'Enter') save(f, edit.text); if (e.key === 'Escape') setEdit(null); }, onBlur: () => setEdit(null), style: { ...inputSt, flex: 1, height: 28 } })
        : h('span', { style: { flex: 1, minWidth: 0, color: f.state === 'proposed' ? T.mut : T.tx } }, f.text, f.state === 'proposed' ? h('span', { style: { fontSize: 11, color: T.dim } }, ' (waiting in Review)') : null),
      iconBtn('edit', 'Edit', () => setEdit({ id: f.id, text: f.text })),
      iconBtn('trash', 'Forget', () => forget(f))))
      : muted('What its chats teach the agent about the work lands here, used only in this project’s chats.'));
}

// ---------- Folders ----------
export function FoldersPanel({ p, c, api, envs, toast }) {
  const React = R(), [own, setOwn] = React.useState(null), [adding, setAdding] = React.useState(false), [path, setPath] = React.useState(''), [drag, setDrag] = React.useState(null);
  const load = () => c.projectFolders(p.id).then(setOwn, () => setOwn([]));
  React.useEffect(() => { load(); }, [p.id, p.updated]);
  const rows = envRows(p.environments, envs);
  const setEnvs = list => c.patchProject(p.id, { environments: list }).catch(e => toast(e?.detail || 'Not changed', 'error'));
  const others = (envs || []).filter(e => !e.none && !e.project && !(p.environments || []).includes(e.id));
  const addFolder = async v => {
    const fp = String(v || '').trim();
    if (!fp) return;
    try { await c.addProjectFolder(p.id, { path: fp, level: 'read' }); setPath(''); setAdding(false); load(); } catch (e) { toast([e?.detail, e?.data?.fix].filter(Boolean).join(' — ') || 'Not added', 'error'); }
  };
  const pick = async () => {
    try {
      const r = (await api.callService('workspace', 'POST', '/v1/pick-folder', { json: { start: '/', title: 'Add a folder to the project' } })).json;
      if (r?.path) addFolder(r.path); else if (!r?.cancelled) setAdding(true);
    } catch { setAdding(true); }            // no chooser on this desktop: type the path
  };
  return h(Panel, { title: 'Folders', icon: 'folder' },
    h('span', { style: label11 }, 'Environments'),
    rows.length ? rows.map((r, i) => h('div', { key: r.id, draggable: true, onDragStart: () => setDrag(r.id), onDragOver: e => e.preventDefault(),
      onDrop: () => { if (drag && drag !== r.id) setEnvs(moveEnv(p.environments, drag, i)); setDrag(null); }, style: { ...rowSt, cursor: 'grab' } },
      h(Icon, { d: 'home', size: 13 }), h('span', { style: { ...ell, flex: 1 } }, r.name, r.missing ? ' (deleted)' : ''),
      r.primary ? h('span', { style: { fontSize: 11, color: T.cy } }, 'primary') : iconBtn('up', `Make ${r.name} the primary environment`, () => setEnvs(moveEnv(p.environments, r.id, 0))),
      h('span', { style: { fontSize: 11, color: T.dim } }, `${r.folders} folder${r.folders === 1 ? '' : 's'}`),
      iconBtn('x', `Stop using ${r.name}`, () => setEnvs((p.environments || []).filter(x => x !== r.id)))))
      : muted('No environment: its chats use their own.'),
    others.length ? h('select', { value: '', 'aria-label': 'Add an environment', onChange: e => e.target.value && setEnvs([...(p.environments || []), e.target.value]),
      style: { ...inputSt, height: 28, cursor: 'pointer' } }, h('option', { value: '' }, '+ Add an environment…'), others.map(e => h('option', { key: e.id, value: e.id }, e.name))) : null,
    h('div', { style: { display: 'flex', alignItems: 'center', marginTop: 6 } }, h('span', { style: { ...label11, flex: 1 } }, 'Its own folders'),
      h(Btn, { kind: 'ghost', sm: true, icon: 'plus', label: 'Add folder', onClick: pick })),
    adding ? h('form', { onSubmit: e => { e.preventDefault(); addFolder(path); }, style: { display: 'flex', gap: 6 } },
      h('input', { autoFocus: true, value: path, onChange: e => setPath(e.target.value), placeholder: '/home/you/folder', 'aria-label': 'Folder path', style: { ...inputSt, flex: 1, height: 28, fontFamily: MONO, fontSize: 12 } }),
      h(Btn, { kind: 'pri', sm: true, label: 'Add', onClick: () => addFolder(path) })) : null,
    own == null ? muted('Loading…') : own.length ? own.map(f => h('div', { key: f.id, style: rowSt },
      h(Icon, { d: 'folder', size: 13 }), h('span', { title: f.path, style: { ...ell, flex: 1, fontFamily: MONO, fontSize: 11.5 } }, shortPath(f.path)),
      h('select', { value: f.level, 'aria-label': `Level of ${f.path}`, onChange: e => c.patchProjectFolder(p.id, f.id, { level: e.target.value }).then(load, x => toast(x?.detail || 'Not changed', 'error')),
        style: { ...inputSt, height: 26, fontSize: 11.5, cursor: 'pointer' } }, Object.entries(LEVEL_WORD).map(([k, l]) => h('option', { key: k, value: k, disabled: f.max_level && ['read', 'edit', 'run', 'run_net'].indexOf(k) > ['read', 'edit', 'run', 'run_net'].indexOf(f.max_level) }, l))),
      iconBtn('x', `Remove ${f.path} from the project (its files are left alone)`, () => c.removeProjectFolder(p.id, f.id).then(load, x => toast(x?.detail || 'Not removed', 'error')))))
      : muted('Folders only this project’s chats use. They start at Read.'));
}

// ---------- Defaults ----------
export function DefaultsPanel({ p, models, tools, skills, onSave }) {
  const d = p.defaults || {};
  const mods = [...new Set((tools || []).map(t => t.group || t.mod).filter(g => g && !String(g).startsWith('mcp:')))].sort();
  const servers = [...new Set((tools || []).map(t => t.group).filter(g => g && String(g).startsWith('mcp:')))].sort();
  const toggle = (key, v) => onSave({ defaults: { ...d, [key]: (d[key] || []).includes(v) ? (d[key] || []).filter(x => x !== v) : [...(d[key] || []), v] } });
  const chip = (on, label, fn, title) => h('button', { key: label, type: 'button', 'aria-pressed': on ? 'true' : 'false', onClick: fn, title,
    style: { height: 24, padding: '0 8px', borderRadius: 99, border: '1px solid ' + (on ? T.cy : T.bd), background: on ? T.tcy : 'transparent', color: on ? T.tx : T.mut, font: 'inherit', fontSize: 11.5, cursor: 'pointer' } }, label);
  const sel = { ...inputSt, height: 28, cursor: 'pointer', flex: 1 };
  return h(Panel, { title: 'Defaults', icon: 'sliders', open: false },
    muted('A new chat in the project starts with these; its composer still changes them for that chat.'),
    h('label', { style: rowSt }, h('span', { style: { width: 64, color: T.mut } }, 'Model'),
      h('select', { value: d.model || '', 'aria-label': 'Default model', onChange: e => onSave({ defaults: { ...d, model: e.target.value || null } }), style: sel },
        h('option', { value: '' }, 'The agent’s default'), (models?.models || []).map(m => h('option', { key: m.id, value: m.id }, m.name || m.id)))),
    h('label', { style: rowSt }, h('span', { style: { width: 64, color: T.mut } }, 'Mode'),
      h('select', { value: d.mode || '', 'aria-label': 'Default mode', onChange: e => onSave({ defaults: { ...d, mode: e.target.value || null } }), style: sel },
        h('option', { value: '' }, 'Manual (as any new chat)'), MODES.map(([k, l]) => h('option', { key: k, value: k }, l)))),
    mods.length ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } }, h('span', { style: label11 }, 'Tool groups turned off'),
      h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 4 } }, mods.map(m => chip((d.disabled || []).includes(m), m, () => toggle('disabled', m), `Turn ${m} off in this project's new chats`)))) : null,
    servers.length ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } }, h('span', { style: label11 }, 'MCP servers on'),
      h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 4 } }, servers.map(g => chip((d.mcp_on || []).includes(g), g.slice(4), () => toggle('mcp_on', g))))) : null,
    h('div', { style: { display: 'flex', flexDirection: 'column', gap: 4 } }, h('span', { style: label11 }, 'Skills always on'),
      (skills || []).length ? h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 4 } }, skills.map(s => chip((d.skills || []).includes(s.id), s.name || s.id, () => toggle('skills', s.id), s.description)))
        : muted('No skills to choose.')));
}

