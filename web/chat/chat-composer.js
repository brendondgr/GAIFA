// The composer (plan 14.1): a growing text box (Enter sends, Shift+Enter is a new line), attachment
// chips from Outputs or from files uploaded here (the Upload button, dropping files on the box, or
// pasting a file; each becomes an output in outputs/uploads/, plan chat-uploads U.5; text, code and
// documents too, and a long paste becomes a file, plan 24.6: Ctrl+Shift+V pastes it as text), the quick actions (registry: on 'composer'), tool-group toggles, Stop, and
// slash commands (/compact, /clear, /model, /context and one per skill). Cards that wait for you (approvals,
// questions, parameter cards a button opened) dock on top of it (`dock`, plan 19.6). Web pages attach too
// (plan 30.8, chat-webpage.js): a pasted URL offers it, and the attach menu has "Add a web page".
// Quote-replies (Select → Reply, chat-quote-reply.js) are cards in the box, any number of them, each opening its
// Reply popup to edit; sending takes them with the message (the text may then be empty).
// Laid out after Claude Code's (plan 42.2): one line inside the box: + on the left (PLUS_ITEMS: upload, attach, tool
// groups, then the quick actions), the text between, and the microphone, Stop and Send on the right; the text grows
// upward to 40% of the window (boxMax) while the buttons stay on its bottom line. No hint line under it; the chat's controls sit there (chat-controls.js).

import { atToken, filterChoices, insertMention, mentionsIn, localChoices, useHubMentions, MentionList } from './chat-mentions.js';
import { h, T, MONO, Icon, Btn, Popover, label11, COL } from './chat-ui.js';
import { actionsFor } from './chat-actions.js';
import { MicButton } from './chat-mic.js';
import { ACCEPT, uploadable, toChip, pasteFile, chipIcon, chipSize } from './chat-files.js';
import { loneUrl, readPage, WebPageOffer, AddWebPage, WebBadge } from './chat-webpage.js';
import { QuoteCards, QuoteReplyDialog, editQuote, removeQuote, canSendQuotes, quotesProblem } from './chat-quote-reply.js';

export { uploadable, toChip, pasteFile } from './chat-files.js';

const R = () => globalThis.React;
/** The box's tallest text: 40% of the window, at least 120 px; then it scrolls (plan 42.2). */
export const boxMax = (vh = globalThis.innerHeight || 800) => Math.max(120, Math.floor(vh * 0.4));
/** The + menu's items, then the quick actions (the registry's `composer` actions). */
export const PLUS_ITEMS = [
  ['upload', 'upload', 'Upload files', 'Images, video, audio, text, code, PDFs and documents (or drop or paste them on the box)'],
  ['attach', 'clip', 'Attach an output or a web page', 'Something made here, or a page read and screened by the hub'],
  ['tools', 'sliders', 'Tool groups', 'Which tool groups this chat loads'],
];
export const COMMANDS = [
  { cmd: 'compact', hint: 'Summarize earlier messages now' },
  { cmd: 'clear', hint: 'Start a new chat' },
  { cmd: 'model', hint: 'Switch this chat’s model', arg: '<id>' },
  { cmd: 'context', hint: 'Show the context meter' },
  { cmd: 'clear-gpu', hint: 'Free the GPU: unload what is loaded (LLM engines only when named)', arg: '[mod…]' },   // plan 46.2
];
/** The slash commands for a draft like "/mo": built-ins, then skills. */
export function slashMatches(draft, skills = []) {
  const m = /^\/(\S*)$/.exec(draft || '');
  if (!m) return [];
  const q = m[1].toLowerCase();
  const all = [...COMMANDS, ...skills.map(s => ({ cmd: s.name, hint: s.description || `Use the ${s.name} skill`, arg: '<request>', skill: s }))];
  return all.filter(c => c.cmd.toLowerCase().startsWith(q)).slice(0, 8);
}

/** Uploads each file: { chips } for the ones that worked, { errors } ("name: why") for the rest. */
export async function uploadAll(api, files) {
  const done = await Promise.allSettled(files.map(f => api.uploadOutput(f)));
  return {
    chips: done.filter(r => r.status === 'fulfilled').map(r => toChip(r.value)),
    errors: done.flatMap((r, i) => r.status === 'rejected' ? [`${files[i].name || 'file'}: ${r.reason?.detail || r.reason?.message || 'upload failed'}`] : []),
  };
}

function AttachPicker({ api, outputs, chosen, onToggle, onReadPage }) {
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
    onReadPage ? h(AddWebPage, { onRead: onReadPage }) : null,
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

// Whole / Card on a document chip (plan 24.9): Whole sends all of it if it fits the window after the
// reply reserve, Card sends its card; neither is "auto" (whole up to Settings → Agent's size). The last
// choice is the chat's default (its settings.doc_mode).
function DocMode({ a, mode, onPick }) {
  const b = (m, label, title) => h('button', { type: 'button', 'aria-pressed': mode === m ? 'true' : 'false', title, 'data-docmode': m,
    onClick: () => onPick(mode === m ? 'auto' : m),
    style: { border: 0, borderRadius: 3, padding: '0 4px', height: 16, font: 'inherit', fontSize: 10, cursor: 'pointer', background: mode === m ? T.tcy : 'transparent', color: mode === m ? T.cy : T.dim } }, label);
  return h('span', { role: 'group', 'aria-label': `Send ${a.title || a.id} whole or as a card`, style: { display: 'inline-flex', gap: 1, padding: 1, borderRadius: 4, border: '1px solid ' + T.bd } },
    b('whole', 'Whole', 'Send all of it, if it fits the model’s window after the reply reserve (else a card, and a note says how much didn’t fit)'),
    b('card', 'Card', 'Send only its card (name, size, outline): the agent reads it in parts'));
}

const menuSt = { display: 'flex', alignItems: 'center', gap: 8, height: 30, padding: '0 9px', border: 0, borderRadius: 5, background: 'transparent', color: T.tx, font: 'inherit', fontSize: 12.5, cursor: 'pointer', textAlign: 'left' };

// controls: the row under the box (chat-controls.js: environment, mode, model; plan 42.3)
export function Composer({ draft, setDraft, attachments, setAttachments, onSend, onStop, running, tools, index, settings, onSettings, skills, outputs, api, onQuick, inputRef, disabled, dock, onOpen, quotes = [], setQuotes, controls = null, folders = [], voice = null }) {
  const React = R(), [pop, setPop] = React.useState(null), [sel, setSel] = React.useState(0);
  const own = React.useRef(null), ref = inputRef || own, picker = React.useRef(null), plain = React.useRef(false);
  const [uploading, setUploading] = React.useState(0), [upErr, setUpErr] = React.useState(null), [over, setOver] = React.useState(false);
  const [offer, setOffer] = React.useState(null), [reading, setReading] = React.useState(0), [qOpen, setQOpen] = React.useState(null);
  const sized = chips => chips.filter(c => c.kind === 'text' || c.kind === 'document').forEach(c => api.outputText?.(c.id, { limit: 1 })
    .then(w => setAttachments(a => a.map(x => x.id === c.id ? { ...x, pages: w.pages, lines: w.lines } : x))).catch(() => {}));
  const upload = async list => {
    const files = uploadable(list), skipped = [...(list || [])].filter(f => f && !files.includes(f));
    if (!files.length) { if (skipped.length) setUpErr(`Can't upload ${skipped.map(f => f.name || 'that file').join(', ')}: images, video, audio, text, code and documents (PDF, Word, EPUB…) only.`); return; }
    setUpErr(skipped.length ? `Skipped ${skipped.map(f => f.name).join(', ')}: not a kind GAIFA reads.` : null); setUploading(n => n + files.length);
    try {
      const { chips, errors } = await uploadAll(api, files);
      setAttachments(a => [...a, ...chips.filter(c => !a.some(x => x.id === c.id))]);
      sized(chips);
      if (errors.length) setUpErr(errors.join(' · '));
    } finally { setUploading(n => n - files.length); }
  };
  const attachPage = async url => {   // plan 30.8: the page read, saved and screened by the hub, attached like an upload
    setOffer(null); setUpErr(null); setReading(n => n + 1);
    try {
      const chip = await readPage(api, url);
      setAttachments(a => a.some(x => x.id === chip.id) ? a : [...a, chip]);
      sized([chip]);
    } catch (e) { setUpErr(`${url}: ${e?.detail || e?.message || 'couldn’t read the page'}${e?.data?.fix ? ` (${e.data.fix})` : ''}`); }
    finally { setReading(n => n - 1); }
  };
  const onPaste = e => {
    const f = uploadable(e.clipboardData?.files);
    if (f.length) { e.preventDefault(); upload(f); return; }
    if (plain.current) { plain.current = false; return; }        // Ctrl+Shift+V: into the box as it is
    const pf = pasteFile(e.clipboardData?.getData?.('text/plain'));
    if (pf && typeof File !== 'undefined') { e.preventDefault(); upload([new File([pf.body], pf.name, { type: 'text/plain' })]); return; }
    setOffer(loneUrl(e.clipboardData?.getData?.('text/plain')));   // a lone URL: pasted as text, and offered as a page
  };
  const hasFiles = e => [...(e.dataTransfer?.types || [])].includes('Files');
  const matches = slashMatches(draft, skills);
  // @-mentions (plan 48.2): the token at the caret, its choices, and what was picked for this message
  const [picked, setPicked] = React.useState([]), [mSel, setMSel] = React.useState(0), [caret, setCaret] = React.useState(null);
  const tok = matches.length ? null : atToken(draft, caret ?? draft.length);
  const hubM = useHubMentions(api, tok);
  const mItems = tok ? filterChoices([...localChoices(outputs, folders), ...hubM], tok) : [];
  React.useEffect(() => { setMSel(0); }, [mItems.length, tok?.query]);
  const pickM = m => {
    if (m.kind === 'output') setAttachments(a => a.some(x => x.id === m.id) ? a : [...a, { id: m.id, kind: m.output.kind, title: m.output.title, preview: m.output.preview, n: m.n }]);
    else setPicked(l => [...l.filter(x => !(x.kind === m.kind && x.id === m.id)), m]);
    const r = insertMention(draft, tok, m);
    setDraft(r.text); setCaret(r.caret);
    requestAnimationFrame(() => { const el = ref.current; if (el) { el.focus(); el.setSelectionRange(r.caret, r.caret); } });
  };
  React.useLayoutEffect(() => { const el = ref.current; if (!el) return; el.style.height = ''; if (draft && el.scrollHeight > el.clientHeight) el.style.height = Math.min(el.scrollHeight + 2, boxMax()) + 'px'; }, [draft]);
  React.useEffect(() => { setSel(0); }, [matches.length]);
  const qProblem = quotesProblem(quotes);
  const can = !disabled && !uploading && !reading && canSendQuotes(draft, attachments, quotes);
  const send = () => { if (can) { setOffer(null); onSend(draft, attachments, quotes, mentionsIn(draft, picked)); setPicked([]); } };   // the page clears the cards (and puts them back if it fails)
  const complete = c => { setDraft('/' + c.cmd + (c.arg ? ' ' : '')); ref.current?.focus(); };
  const onKey = e => {
    if (e.nativeEvent?.isComposing) return;
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'v' || e.key === 'V')) plain.current = true;
    if (mItems.length && !e.shiftKey) {        // the @-mention list
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); setMSel(i => (i + (e.key === 'ArrowDown' ? 1 : mItems.length - 1)) % mItems.length); return; }
      if (e.key === 'Tab' || e.key === 'Enter') { e.preventDefault(); pickM(mItems[Math.min(mSel, mItems.length - 1)]); return; }
      if (e.key === 'Escape') { e.preventDefault(); setCaret(-1); return; }
    }
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
      mItems.length ? h(MentionList, { items: mItems, sel: Math.min(mSel, mItems.length - 1), onPick: pickM }) : null,
      matches.length ? h('div', { role: 'listbox', 'aria-label': 'Commands', style: { position: 'absolute', left: 0, right: 0, bottom: 'calc(100% + 6px)', zIndex: 30, background: T.card, border: '1px solid ' + T.bds, borderRadius: 9, boxShadow: '0 12px 30px rgba(0,0,0,.3)', padding: 4 } },
        matches.map((c, i) => h('button', { key: c.cmd, type: 'button', role: 'option', 'aria-selected': i === sel ? 'true' : 'false', onMouseDown: e => { e.preventDefault(); complete(c); },
          style: { display: 'flex', alignItems: 'baseline', gap: 10, width: '100%', padding: '6px 9px', border: 0, borderRadius: 6, background: i === sel ? T.hov : 'transparent', color: T.tx, font: 'inherit', cursor: 'pointer', textAlign: 'left' } },
          h('span', { style: { fontFamily: MONO, fontSize: 12 } }, '/' + c.cmd, c.arg ? h('span', { style: { color: T.dim } }, ' ' + c.arg) : null),
          h('span', { style: { fontSize: 12, color: T.mut, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0 } }, c.skill ? 'skill · ' + c.hint : c.hint)))) : null,
      h('div', { className: 'aichat-box',
        onDragOver: e => { if (hasFiles(e)) { e.preventDefault(); setOver(true); } }, onDragLeave: () => setOver(false),
        onDrop: e => { if (!hasFiles(e)) return; e.preventDefault(); setOver(false); upload(e.dataTransfer.files); },
        style: { display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 8px 6px 10px', borderRadius: 10, border: `1px ${over ? 'dashed' : 'solid'} ${over ? T.cy : T.bds}`, background: over ? T.tcy : T.card } },
        h(QuoteCards, { quotes, onOpen: setQOpen, onRemove: i => setQuotes?.(l => removeQuote(l, l[i]?.id)) }),
        qOpen != null && quotes[qOpen] ? h(QuoteReplyDialog, { key: quotes[qOpen].id, q: quotes[qOpen], editable: true, onClose: () => setQOpen(null),
          onSave: r => setQuotes?.(l => editQuote(l, quotes[qOpen].id, r)), onRemove: () => setQuotes?.(l => removeQuote(l, quotes[qOpen].id)) }) : null,
        qProblem ? h('span', { role: 'alert', style: { fontSize: 11.5, color: T.rd } }, qProblem) : null,
        attachments.length ? h('div', { style: { display: 'flex', flexWrap: 'wrap', gap: 5 } }, attachments.map(a => h('span', { key: a.id, 'data-chip': a.kind, style: { display: 'inline-flex', alignItems: 'center', gap: 5, height: 24, padding: '0 4px 0 3px', borderRadius: 5, background: T.inset, border: '1px solid ' + T.bd, fontSize: 11.5, maxWidth: 340 } },
          a.preview ? h('img', { src: a.preview, alt: '', style: { width: 18, height: 18, objectFit: 'cover', borderRadius: 3 } }) : h(Icon, { d: chipIcon(a), size: 12 }),
          (a.kind === 'text' || a.kind === 'document') && onOpen
            ? h('button', { type: 'button', title: `Open ${a.title || a.id}`, onClick: () => onOpen(a.id), style: { border: 0, background: 'none', padding: 0, color: T.tx, font: 'inherit', cursor: 'pointer', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, (a.n ? `#${a.n} ` : '') + (a.title || a.id))
            : h('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, (a.n ? `#${a.n} ` : '') + (a.title || a.id)),
          chipSize(a) ? h('span', { style: { color: T.dim, fontFamily: MONO, fontSize: 10.5, whiteSpace: 'nowrap' } }, chipSize(a)) : null,
          a.web ? h(WebBadge, { web: a.web }) : null,
          a.kind === 'text' || a.kind === 'document' ? h(DocMode, { a, mode: a.mode || settings?.doc_mode || 'auto', onPick: m => {   // plan 24.9
            setAttachments(l => l.map(x => (x.id === a.id ? { ...x, mode: m } : x))); onSettings?.({ doc_mode: m }); } }) : null,
          h('button', { type: 'button', 'aria-label': `Remove ${a.title || a.id}`, onClick: () => toggleAtt(a), style: { border: 0, background: 'none', padding: 2, color: T.mut, cursor: 'pointer', display: 'flex' } }, h(Icon, { d: 'x', size: 11 }))))) : null,
        uploading ? h('span', { role: 'status', style: { fontSize: 11.5, color: T.mut } }, `Uploading ${uploading} file${uploading > 1 ? 's' : ''}…`) : null,
        reading ? h('span', { role: 'status', style: { fontSize: 11.5, color: T.mut } }, `Reading ${reading > 1 ? `${reading} pages` : 'the page'} and screening it…`) : null,
        offer && !reading ? h(WebPageOffer, { url: offer, onAttach: attachPage, onDismiss: () => setOffer(null) }) : null,
        upErr ? h('span', { role: 'alert', style: { fontSize: 11.5, color: T.rd } }, upErr) : null,
        h('div', { style: { display: 'flex', alignItems: 'flex-end', gap: 6, minWidth: 0 } },   // + · the text · mic, Stop, Send: one line that grows upward
          h('input', { ref: picker, type: 'file', multiple: true, accept: ACCEPT, hidden: true, 'aria-hidden': 'true',
            onChange: e => { upload(e.target.files); e.target.value = ''; } }),
          h('span', { style: { position: 'relative' } },
            h(Btn, { sm: true, icon: 'plus', title: 'Add: upload, attach, tool groups', 'aria-label': 'Add', 'aria-haspopup': 'menu', 'aria-expanded': pop ? 'true' : 'false',
              onClick: () => setPop(pop ? null : 'plus'), className: 'aichat-quiet', style: { width: 28, height: 28, borderRadius: 7, background: 'transparent', color: T.mut } }),
            h(Popover, { open: pop === 'plus', onClose: () => setPop(null), place: 'up-left', width: 260, label: 'Add', style: { padding: 4, gap: 0 } },
              PLUS_ITEMS.map(([k, ic, label, hint]) => h('button', { key: k, type: 'button', role: 'menuitem', title: hint, disabled: disabled && k === 'upload',
                onClick: () => { if (k === 'upload') { setPop(null); picker.current?.click(); } else setPop(k === 'attach' ? 'att' : 'tools'); }, style: menuSt },
                h(Icon, { d: ic, size: 13 }), label)),
              quick.length ? h('span', { style: { ...label11, padding: '8px 9px 2px' } }, 'Quick actions') : null,
              quick.map(a => h('button', { key: a.id, type: 'button', role: 'menuitem', onClick: () => { setPop(null); onQuick(a); }, title: `${a.label}: opens ${a.tool || 'it'} as a parameter card`, style: menuSt },
                h(Icon, { d: a.icon || 'wand', size: 13 }), a.label))),
            h(Popover, { open: pop === 'att', onClose: () => setPop(null), place: 'up-left', width: 340, label: 'Attach outputs' }, h(AttachPicker, { api, outputs, chosen: attachments, onToggle: toggleAtt, onReadPage: api.readWebPage ? url => { setPop(null); attachPage(url); } : null })),
            h(Popover, { open: pop === 'tools', onClose: () => setPop(null), place: 'up-left', width: 330, label: 'Tool groups' }, h(ToolGroups, { index, settings, onChange: onSettings }))),
          h('textarea', { ref, value: draft, rows: 1, disabled, onChange: e => { setDraft(e.target.value); setCaret(e.target.selectionStart); }, onKeyDown: onKey, 'aria-label': 'Message',
            onSelect: e => setCaret(e.target.selectionStart),
            onPaste,
            placeholder: running ? 'Add a message (it’s read after the current step)…' : quotes.length ? 'Add a message, or just send your replies…' : 'Message the agent, or / for commands',
            style: { flex: 1, minWidth: 0, alignSelf: 'center', minHeight: 22, maxHeight: boxMax(), resize: 'none', border: 0, outline: 'none', background: 'transparent', color: T.tx, font: 'inherit', fontSize: 13, lineHeight: 1.5, padding: '2px 0' } }),
          h(MicButton, { api, draft, setDraft, disabled }),   // only while the stt mod is up (plan 29.3)
          voice,                                               // voice mode (plan 49.2)
          running ? h(Btn, { sm: true, icon: 'stop', label: 'Stop', onClick: onStop, title: 'Stop the turn (and its running tool)', className: 'aichat-quiet', style: { background: 'transparent' } }) : null,
          h(Btn, { kind: 'pri', sm: true, icon: 'send', title: running ? 'Queue this message' : 'Send (Enter)', disabled: !can, onClick: send,
            style: { width: 30, height: 28, padding: 0, justifyContent: 'center', borderRadius: 7 } }))),
      controls || null));
}
