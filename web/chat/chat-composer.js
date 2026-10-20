// The composer (plan 14.1): a growing text box (Enter sends, Shift+Enter is a new line), attachment
// chips from Outputs or from files uploaded here (the Upload button, dropping files on the box, or
// pasting an image; each becomes an output in outputs/uploads/, plan chat-uploads U.5), the quick actions (registry: on 'composer'), tool-group toggles, Stop, and
// slash commands (/compact, /clear, /model, /context and one per skill). Cards that wait for you (approvals,
// questions, parameter cards a button opened) dock on top of it (`dock`, plan 19.6).

import { h, T, MONO, Icon, Btn, Popover, chipSt, label11, COL } from './chat-ui.js';
import { actionsFor } from './chat-actions.js';
import { MicButton } from './chat-mic.js';

const R = () => globalThis.React;
export const COMMANDS = [
  { cmd: 'compact', hint: 'Summarize earlier messages now' },
  { cmd: 'clear', hint: 'Start a new chat' },
  { cmd: 'model', hint: 'Switch this chat’s model', arg: '<id>' },
  { cmd: 'context', hint: 'Show the context meter' },
];
/** The slash commands for a draft like "/mo": built-ins, then skills. */
export function slashMatches(draft, skills = []) {
  const m = /^\/(\S*)$/.exec(draft || '');
  if (!m) return [];
  const q = m[1].toLowerCase();
  const all = [...COMMANDS, ...skills.map(s => ({ cmd: s.name, hint: s.description || `Use the ${s.name} skill`, arg: '<request>', skill: s }))];
  return all.filter(c => c.cmd.toLowerCase().startsWith(q)).slice(0, 8);
}

const MEDIA_EXT = /\.(png|jpe?g|webp|gif|bmp|avif|mp4|webm|mov|mkv|wav|mp3|flac|ogg|opus|m4a|aac)$/i;
/** The files in a drop or paste (or a file picker) that can be uploaded: images, video and audio. */
export function uploadable(list) {
  return [...(list || [])].filter(f => f && (/^(image|video|audio)\//.test(f.type || '') || MEDIA_EXT.test(f.name || '')));
}
/** An uploaded output as an attachment chip. */
export const toChip = o => ({ id: o.id, kind: o.kind, title: o.title, preview: o.preview || (o.kind === 'image' ? o.url : null) });
/** Uploads each file: { chips } for the ones that worked, { errors } ("name: why") for the rest. */
export async function uploadAll(api, files) {
  const done = await Promise.allSettled(files.map(f => api.uploadOutput(f)));
  return {
    chips: done.filter(r => r.status === 'fulfilled').map(r => toChip(r.value)),
    errors: done.flatMap((r, i) => r.status === 'rejected' ? [`${files[i].name || 'file'}: ${r.reason?.detail || r.reason?.message || 'upload failed'}`] : []),
  };
}

function AttachPicker({ api, outputs, chosen, onToggle }) {
  const React = R(), [recent, setRecent] = React.useState(null);
  React.useEffect(() => { api.listOutputs({ limit: 24 }).then(p => setRecent(p.items || [])).catch(() => setRecent([])); }, []);
  const mine = (outputs || []).slice().reverse().map(o => ({ id: o.output_id, kind: o.kind, title: o.title, preview: o.preview, n: o.n }));
  const seen = new Set(mine.map(o => o.id));
  const rest = (recent || []).filter(o => !seen.has(o.id)).map(o => ({ id: o.id, kind: o.kind, title: o.title, preview: o.preview || (o.kind === 'image' ? o.url : null) }));
  const tile = o => {
    const on = chosen.some(c => c.id === o.id);
    return h('button', { key: o.id, type: 'button', title: (o.n ? `#${o.n} ` : '') + (o.title || o.id), 'aria-pressed': on ? 'true' : 'false', onClick: () => onToggle(o),
      style: { position: 'relative', aspectRatio: '1', borderRadius: 6, overflow: 'hidden', padding: 0, cursor: 'pointer', background: T.inset, border: `2px solid ${on ? T.cy : T.bd}`, color: T.mut, display: 'grid', placeItems: 'center' } },
      o.preview ? h('img', { src: o.preview, alt: '', style: { width: '100%', height: '100%', objectFit: 'cover' } }) : h(Icon, { d: { audio: 'wave', video: 'video', model3d: 'cube' }[o.kind] || 'clip', size: 18 }),
      o.n ? h('span', { style: { position: 'absolute', left: 3, top: 3, padding: '0 4px', borderRadius: 3, fontFamily: MONO, fontSize: 10, background: T.card, color: T.tx } }, '#' + o.n) : null);
  };
  const grid = list => h('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(58px, 1fr))', gap: 6 } }, list.map(tile));
  return h(R().Fragment, null,
    mine.length ? h('span', { style: label11 }, 'In this chat') : null, mine.length ? grid(mine) : null,
    h('span', { style: label11 }, 'Recent outputs'), recent == null ? h('span', { style: { color: T.mut, fontSize: 12 } }, 'Loading…') : rest.length ? grid(rest) : h('span', { style: { color: T.mut, fontSize: 12 } }, 'Nothing yet.'));
}

function ToolGroups({ index, settings, onChange }) {
  const mods = [...new Set((index || []).filter(t => t.mod !== 'hub').map(t => t.mod))];
  const pinned = settings?.pinned || [], disabled = settings?.disabled || [];
  const set = (mod, v) => onChange({ pinned: v === 'pin' ? [...new Set([...pinned, mod])] : pinned.filter(x => x !== mod), disabled: v === 'off' ? [...new Set([...disabled, mod])] : disabled.filter(x => x !== mod) });
  const seg = (mod, v, label, cur) => h('button', { key: v, type: 'button', 'aria-pressed': cur === v ? 'true' : 'false', onClick: () => set(mod, v),
    style: { height: 22, padding: '0 8px', border: 0, borderRadius: 4, font: 'inherit', fontSize: 11.5, cursor: 'pointer', background: cur === v ? T.hov : 'transparent', color: cur === v ? T.tx : T.mut, boxShadow: cur === v ? '0 0 0 1px ' + T.bds : 'none' } }, label);
  return h(R().Fragment, null,
    h('span', { style: label11 }, 'Tool groups in this chat'),
    h('span', { style: { fontSize: 11.5, color: T.mut } }, 'Auto: the agent loads a group when it needs it. Pinned: always loaded. Off: never used.'),
    mods.length ? mods.map(mod => {
      const cur = disabled.includes(mod) ? 'off' : pinned.includes(mod) ? 'pin' : 'auto', n = index.filter(t => t.mod === mod).length;
      return h('div', { key: mod, style: { display: 'flex', alignItems: 'center', gap: 8 } },
        h('span', { style: { flex: 1, fontSize: 12.5, color: cur === 'off' ? T.mut : T.tx } }, mod, h('span', { style: { color: T.dim, fontFamily: MONO, fontSize: 11, marginLeft: 6 } }, n)),
        h('span', { role: 'group', 'aria-label': mod, style: { display: 'inline-flex', padding: 2, borderRadius: 6, border: '1px solid ' + T.bd, background: T.sb } },
          seg(mod, 'auto', 'Auto', cur), seg(mod, 'pin', 'Pinned', cur), seg(mod, 'off', 'Off', cur)));
    }) : h('span', { style: { color: T.mut, fontSize: 12 } }, 'Loading the tool catalog…'));
}

export function Composer({ draft, setDraft, attachments, setAttachments, onSend, onStop, running, tools, index, settings, onSettings, skills, outputs, api, onQuick, inputRef, disabled, dock }) {
  const React = R(), [pop, setPop] = React.useState(null), [sel, setSel] = React.useState(0);
  const own = React.useRef(null), ref = inputRef || own, picker = React.useRef(null);
  const [uploading, setUploading] = React.useState(0), [upErr, setUpErr] = React.useState(null), [over, setOver] = React.useState(false);
  const upload = async list => {
    const files = uploadable(list);
    if (!files.length) { if ([...(list || [])].length) setUpErr('Only images, video and audio can be uploaded.'); return; }
    setUpErr(null); setUploading(n => n + files.length);
    try {
      const { chips, errors } = await uploadAll(api, files);
      setAttachments(a => [...a, ...chips.filter(c => !a.some(x => x.id === c.id))]);
      if (errors.length) setUpErr(errors.join(' · '));
    } finally { setUploading(n => n - files.length); }
  };
  const hasFiles = e => [...(e.dataTransfer?.types || [])].includes('Files');
  const matches = slashMatches(draft, skills);
  React.useLayoutEffect(() => { const el = ref.current; if (!el) return; el.style.height = ''; if (draft && el.scrollHeight > el.clientHeight) el.style.height = Math.min(el.scrollHeight + 2, 220) + 'px'; }, [draft]);
  React.useEffect(() => { setSel(0); }, [matches.length]);
  const can = !disabled && !uploading && (draft.trim() || attachments.length);
  const send = () => { if (can) onSend(draft, attachments); };
  const complete = c => { setDraft('/' + c.cmd + (c.arg ? ' ' : '')); ref.current?.focus(); };
  const onKey = e => {
    if (e.nativeEvent?.isComposing) return;
    if (matches.length) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); setSel(i => (i + (e.key === 'ArrowDown' ? 1 : matches.length - 1)) % matches.length); return; }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && draft !== '/' + matches[sel].cmd)) { e.preventDefault(); const c = matches[sel]; if (c.arg || e.key === 'Tab') complete(c); else onSend('/' + c.cmd, []); return; }
    }
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  };
  const quick = actionsFor('composer', { tools: index });
  const toggleAtt = o => setAttachments(a => a.some(x => x.id === o.id) ? a.filter(x => x.id !== o.id) : [...a, o]);
  return h('div', { style: { flex: 'none', padding: '0 12px 12px', background: T.bg } },
    h('div', { style: { maxWidth: COL, margin: '0 auto', position: 'relative' } },
      dock && dock.length ? h('div', { role: 'region', 'aria-label': 'Waiting for you', style: { display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 8, maxHeight: '50vh', overflowY: 'auto', minWidth: 0 } },
        dock.length > 1 ? h('div', { style: { ...label11, color: T.pu } }, `Waiting for you · ${dock.length}`) : null, dock) : null,
      matches.length ? h('div', { role: 'listbox', 'aria-label': 'Commands', style: { position: 'absolute', left: 0, right: 0, bottom: 'calc(100% + 6px)', zIndex: 30, background: T.card, border: '1px solid ' + T.bds, borderRadius: 9, boxShadow: '0 12px 30px rgba(0,0,0,.3)', padding: 4 } },
        matches.map((c, i) => h('button', { key: c.cmd, type: 'button', role: 'option', 'aria-selected': i === sel ? 'true' : 'false', onMouseDown: e => { e.preventDefault(); complete(c); },
          style: { display: 'flex', alignItems: 'baseline', gap: 10, width: '100%', padding: '6px 9px', border: 0, borderRadius: 6, background: i === sel ? T.hov : 'transparent', color: T.tx, font: 'inherit', cursor: 'pointer', textAlign: 'left' } },
          h('span', { style: { fontFamily: MONO, fontSize: 12 } }, '/' + c.cmd, c.arg ? h('span', { style: { color: T.dim } }, ' ' + c.arg) : null),
          h('span', { style: { fontSize: 12, color: T.mut, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 } }, c.skill ? 'skill · ' + c.hint : c.hint)))) : null,
      h('div', { className: 'aichat-box',
        onDragOver: e => { if (hasFiles(e)) { e.preventDefault(); setOver(true); } }, onDragLeave: () => setOver(false),
        onDrop: e => { if (!hasFiles(e)) return; e.preventDefault(); setOver(false); upload(e.dataTransfer.files); },
        style: { display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 8px 6px 10px', borderRadius: 10, border: `1px ${over ? 'dashed' : 'solid'} ${over ? T.cy : T.bds}`, background: over ? T.tcy : T.card } },
        attachments.length ? h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 5 } }, attachments.map(a => h('span', { key: a.id, style: { display: 'inline-flex', alignItems: 'center', gap: 5, height: 24, padding: '0 4px 0 3px', borderRadius: 5, background: T.inset, border: '1px solid ' + T.bd, fontSize: 11.5, maxWidth: 220 } },
          a.preview ? h('img', { src: a.preview, alt: '', style: { width: 18, height: 18, objectFit: 'cover', borderRadius: 3 } }) : h(Icon, { d: 'clip', size: 12 }),
          h('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, (a.n ? `#${a.n} ` : '') + (a.title || a.id)),
          h('button', { type: 'button', 'aria-label': `Remove ${a.title || a.id}`, onClick: () => toggleAtt(a), style: { border: 0, background: 'none', padding: 2, color: T.mut, cursor: 'pointer', display: 'flex' } }, h(Icon, { d: 'x', size: 11 }))))) : null,
        uploading ? h('span', { role: 'status', style: { fontSize: 11.5, color: T.mut } }, `Uploading ${uploading} file${uploading > 1 ? 's' : ''}…`) : null,
        upErr ? h('span', { role: 'alert', style: { fontSize: 11.5, color: T.rd } }, upErr) : null,
        h('textarea', { ref, value: draft, rows: 1, disabled, onChange: e => setDraft(e.target.value), onKeyDown: onKey, 'aria-label': 'Message',
          onPaste: e => { const f = uploadable(e.clipboardData?.files); if (f.length) { e.preventDefault(); upload(f); } },
          placeholder: running ? 'Add a message (it’s read after the current step)…' : 'Message the agent, or / for commands',
          style: { width: '100%', minHeight: 22, maxHeight: 220, resize: 'none', border: 0, outline: 'none', background: 'transparent', color: T.tx, font: 'inherit', fontSize: 13, lineHeight: 1.5, padding: '2px 0' } }),
        h('div', { style: { display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap', minWidth: 0 } },
          h('input', { ref: picker, type: 'file', multiple: true, accept: 'image/*,video/*,audio/*', hidden: true, 'aria-hidden': 'true',
            onChange: e => { upload(e.target.files); e.target.value = ''; } }),
          h(Btn, { kind: 'ghost', sm: true, icon: 'upload', title: 'Upload an image, video or audio file (or drop or paste it here)', disabled, onClick: () => picker.current?.click() }),
          h(MicButton, { api, draft, setDraft, disabled }),   // only while the stt mod is up (plan 29.3)
          h('span', { style: { position: 'relative' } },
            h(Btn, { kind: 'ghost', sm: true, icon: 'clip', title: 'Attach an output', onClick: () => setPop(pop === 'att' ? null : 'att') }),
            h(Popover, { open: pop === 'att', onClose: () => setPop(null), place: 'up-left', width: 340, label: 'Attach outputs' }, h(AttachPicker, { api, outputs, chosen: attachments, onToggle: toggleAtt }))),
          h('span', { style: { position: 'relative' } },
            h(Btn, { kind: 'ghost', sm: true, icon: 'sliders', title: 'Tool groups', onClick: () => setPop(pop === 'tools' ? null : 'tools') }),
            h(Popover, { open: pop === 'tools', onClose: () => setPop(null), place: 'up-left', width: 330, label: 'Tool groups' }, h(ToolGroups, { index, settings, onChange: onSettings }))),
          h('span', { style: { width: 1, height: 16, background: T.bd, margin: '0 4px' } }),
          quick.map(a => h('button', { key: a.id, type: 'button', onClick: () => onQuick(a), title: `${a.label}: opens ${a.tool || 'it'} as a parameter card`, style: chipSt(false, { sm: true }) },
            a.icon ? h(Icon, { d: a.icon, size: 12 }) : null, a.label)),
          h('span', { style: { flex: 1 } }),
          running ? h(Btn, { sm: true, icon: 'stop', label: 'Stop', onClick: onStop, title: 'Stop the turn (and its running tool)' }) : null,
          h(Btn, { kind: 'pri', sm: true, icon: 'send', title: running ? 'Queue this message' : 'Send (Enter)', disabled: !can, onClick: send }))),
      h('div', { style: { textAlign: 'center', fontSize: 11, color: T.dim, paddingTop: 5 } }, 'Enter sends · Shift+Enter new line · / commands · drop or paste images to upload')));
}
