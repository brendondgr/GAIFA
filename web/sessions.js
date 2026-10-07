// Sessions (plan Phase 15, Wire 15; brief §11.14): the Sessions panel (save the current setup,
// switch with a dry-run plan first and live step progress, rename, delete) and the "Restore last
// session?" prompt after an unclean shutdown. Plain ES module on the page's React; Hub.dc.html
// mounts it in a dialog (from the Chat page and the palette) and as Settings → Sessions.

import { h, T, MONO, Icon, Btn, Badge, inputSt, label11, fmtAgo } from './chat/chat-ui.js';

const R = () => globalThis.React;
const GB = 1e9;
const ACTION = { stop_llm: ['stop', 'Stop LLM'], unload: ['download', 'Unload'], start: ['play', 'Start'], launch_llm: ['send', 'Launch LLM'], load: ['send', 'Load'], skip: ['x', 'Skip'] };
const fGB = b => (b == null ? '' : `${b < 0 ? '−' : b > 0 ? '+' : ''}${(Math.abs(b) / GB).toFixed(1)} GB`);
const DISMISS = 'aihub.sessions.restoreDismissed';
const ago = ts => { const a = fmtAgo(ts); return a === 'now' ? 'just now' : `${a} ago`; };

/** The plan of a restore: steps (with live status while it runs) and the memory line. */
export function PlanView({ plan, status = {}, running }) {
  const m = plan.memory;
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
    !plan.steps.length ? h('div', { style: { fontSize: 12.5, color: T.mut } }, 'Nothing to do: this setup is already what runs.') : null,
    h('ol', { style: { listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 3 } },
      plan.steps.map((st, i) => {
        const s = status[i], [ic] = ACTION[st.action] || ['info'];
        const mark = s?.ok === true ? h('span', { style: { color: T.gr, display: 'flex' } }, h(Icon, { d: 'check', size: 13, sw: 2.2 }))
          : s?.ok === false ? h('span', { style: { color: T.rd, display: 'flex' } }, h(Icon, { d: 'x', size: 13, sw: 2.2 }))
            : running && i === Object.keys(status).length ? h('span', { style: { width: 10, height: 10, margin: 1.5, borderRadius: 99, border: '2px solid ' + T.acc, borderTopColor: 'transparent', animation: 'aisesspin .8s linear infinite' } })
              : h('span', { style: { width: 10, height: 10, margin: 1.5, borderRadius: 99, border: '1.5px solid ' + T.bdh } });
        return h('li', { key: i, style: { display: 'flex', alignItems: 'center', gap: 8, padding: '5px 8px', borderRadius: 6, background: T.inset, fontSize: 12.5, opacity: st.action === 'skip' ? 0.7 : 1 } },
          mark, h('span', { style: { color: T.mut, display: 'flex' } }, h(Icon, { d: ic, size: 13 })),
          h('span', { style: { flex: 1, minWidth: 0, overflowWrap: 'anywhere' } }, st.detail, s?.error ? h('span', { style: { color: T.rd } }, ' · ', s.error) : null),
          st.bytes ? h('span', { style: { fontFamily: MONO, fontSize: 11.5, color: st.bytes < 0 ? T.gr : T.mut } }, fGB(st.bytes)) : null);
      })),
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: 12, color: T.mut } },
      h('span', { style: { fontFamily: MONO, fontSize: 11.5 } }, `${(m.available_bytes / GB).toFixed(1)} available ${m.freed_bytes ? '+ ' + (m.freed_bytes / GB).toFixed(1) + ' freed ' : ''}− ${(m.needed_bytes / GB).toFixed(1)} needed − ${(m.reserve_bytes / GB).toFixed(0)} reserve = ${(m.after_bytes / GB).toFixed(1)} GB`),
      h(Badge, { tone: m.fits ? 'green' : 'accent', title: m.fits ? 'Everything fits' : 'Loading will make room by unloading other mods first, or may fall short' }, m.fits ? 'fits' : 'tight')));
}

function Row({ s, api, toast, on, open, setOpen, reload }) {
  const React = R(), [plan, setPlan] = React.useState(null), [err, setErr] = React.useState(null), [edit, setEdit] = React.useState(null);
  const [status, setStatus] = React.useState({}), [running, setRunning] = React.useState(false), [done, setDone] = React.useState(null);
  const isOpen = open === s.id;
  React.useEffect(() => {
    if (!isOpen) { setPlan(null); setStatus({}); setDone(null); return undefined; }
    setErr(null); api.restoreSession(s.id, { dryRun: true }).then(setPlan, e => setErr(e.detail || String(e)));
    return undefined;
  }, [isOpen]);
  React.useEffect(() => {
    if (!running || !on) return undefined;
    return on('session_step', ev => {
      if (ev.session !== s.id) return;
      setStatus(st => { const i = Object.keys(st).length; return { ...st, [i]: ev.step }; });
    });
  }, [running]);
  const run = async () => {
    setRunning(true); setStatus({}); setDone(null);
    try {
      const r = await api.restoreSession(s.id);
      setStatus(Object.fromEntries((r.results || []).map((x, i) => [i, x])));
      setDone(r.ok ? 'ok' : 'problems');
      toast(r.ok ? `Switched to ${s.name}` : `Switched to ${s.name}, with problems`, r.ok ? 'success' : 'warn');
    } catch (e) { setErr(e.detail || String(e)); }
    setRunning(false);
  };
  const rename = async () => {
    const v = (edit || '').trim(); setEdit(null);
    if (!v || v === s.name) return;
    try { await api.renameSession(s.id, v); reload(); } catch (e) { toast(e.detail || String(e), 'error'); }
  };
  // delete asks in place (the panel may itself be a dialog): first click arms, second deletes
  const [sure, setSure] = React.useState(false);
  React.useEffect(() => { if (!sure) return undefined; const t = setTimeout(() => setSure(false), 3500); return () => clearTimeout(t); }, [sure]);
  const del = async () => {
    if (!sure) { setSure(true); return; }
    try { await api.deleteSession(s.id); toast('Session deleted', 'success'); reload(); } catch (e) { toast(e.detail || String(e), 'error'); }
  };
  return h('li', { style: { display: 'flex', flexDirection: 'column', gap: 8, padding: '9px 10px', borderRadius: 8, border: '1px solid ' + (isOpen ? T.bds : T.bd), background: isOpen ? T.card : 'transparent' } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 } },
      h('span', { style: { color: s.auto ? T.mut : T.pu, display: 'flex' } }, h(Icon, { d: s.auto ? 'refresh' : 'bookmark', size: 15 })),
      h('div', { style: { flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 1 } },
        edit != null ? h('input', { autoFocus: true, value: edit, 'aria-label': 'Session name', onChange: e => setEdit(e.target.value), onBlur: rename,
          onKeyDown: e => { if (e.key === 'Enter') rename(); if (e.key === 'Escape') { e.stopPropagation(); setEdit(null); } }, style: { ...inputSt, height: 26 } })
          : h('div', { style: { display: 'flex', alignItems: 'center', gap: 6 } }, h('span', { style: { fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, s.name),
            s.auto ? h(Badge, null, 'auto') : null, h('span', { title: 'Saved ' + ago(s.updated_ts), style: { fontFamily: MONO, fontSize: 11, color: T.dim } }, fmtAgo(s.updated_ts))),
        h('div', { title: s.summary, style: { fontSize: 12, color: T.mut, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, s.summary)),
      isOpen ? null : h(Btn, { sm: true, kind: 'pri', icon: 'refresh', label: 'Switch', title: 'See the plan first', onClick: () => setOpen(s.id) }),
      h(Btn, { sm: true, kind: 'ghost', icon: 'edit', title: 'Rename', onClick: () => setEdit(s.name) }),
      h(Btn, { sm: true, kind: sure ? 'danger' : 'ghost', icon: 'trash', title: sure ? 'Click again to delete (nothing is stopped)' : 'Delete', label: sure ? 'Delete?' : undefined, onClick: del })),
    isOpen ? h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
      err ? h('div', { role: 'alert', style: { fontSize: 12.5, color: T.rd } }, err) : null,
      plan ? h(PlanView, { plan, status, running }) : !err ? h('div', { style: { fontSize: 12, color: T.mut } }, 'Working out the plan…') : null,
      h('div', { style: { display: 'flex', gap: 8, alignItems: 'center' } },
        done ? h(Badge, { tone: done === 'ok' ? 'green' : 'accent' }, done === 'ok' ? 'switched' : 'finished with problems')
          : h(Btn, { kind: 'pri', sm: true, icon: 'play', label: running ? 'Switching…' : `Switch to ${s.name}`, disabled: !plan || running, onClick: run }),
        h(Btn, { kind: 'ghost', sm: true, label: done ? 'Close' : 'Cancel', disabled: running, onClick: () => setOpen(null) }))) : null);
}

/** The Sessions panel. on(type, fn) → unsubscribe: the hub's events (for session_step). */
export function SessionsPanel({ api, toast = () => {}, on, focus, onClose }) {
  const React = R(), [list, setList] = React.useState(null), [name, setName] = React.useState(''), [busy, setBusy] = React.useState(false);
  const [open, setOpen] = React.useState(focus && focus !== 'save' ? focus : null), [err, setErr] = React.useState(null);
  const reload = () => api.listSessions().then(setList, e => setErr(e.detail || String(e)));
  React.useEffect(() => { reload(); if (!on) return undefined; return on('session', () => reload()); }, []);
  React.useEffect(() => { if (typeof document !== 'undefined' && !document.getElementById('aises-css')) { const st = document.createElement('style'); st.id = 'aises-css'; st.textContent = '@keyframes aisesspin{to{transform:rotate(360deg)}}'; document.head.appendChild(st); } }, []);
  const save = async () => {
    const n = name.trim(); if (!n) return;
    setBusy(true);
    try { const s = await api.saveSession(n); setName(''); toast(`Saved “${s.name}”`, 'success'); reload(); } catch (e) { toast(e.detail || String(e), 'error'); }
    setBusy(false);
  };
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 } },
    h('div', { style: { display: 'flex', alignItems: 'flex-start', gap: 10 } },
      h('div', { style: { flex: 1, minWidth: 0 } }, h('h2', { style: { margin: 0, fontSize: 15, fontWeight: 600 } }, 'Sessions'),
        h('div', { style: { fontSize: 12, color: T.mut } }, 'A session is a setup: which services run, which are loaded, and the LLMs that are up. Switching shows the plan first.')),
      onClose ? h(Btn, { kind: 'ghost', sm: true, icon: 'x', title: 'Close', onClick: onClose }) : null),
    h('div', { style: { display: 'flex', gap: 8, alignItems: 'center' } },
      h('input', { autoFocus: focus === 'save', value: name, onChange: e => setName(e.target.value), onKeyDown: e => { if (e.key === 'Enter') save(); }, placeholder: 'Name this setup, e.g. “Image work”', 'aria-label': 'Session name', maxLength: 80, style: { ...inputSt, flex: 1 } }),
      h(Btn, { kind: 'sec', icon: 'bookmark', label: busy ? 'Saving…' : 'Save current setup', disabled: !name.trim() || busy, onClick: save })),
    err ? h('div', { role: 'alert', style: { color: T.rd, fontSize: 12.5 } }, err) : null,
    list == null ? h('div', { style: { color: T.mut, fontSize: 12.5 } }, 'Loading…')
      : !list.length ? h('div', { style: { color: T.mut, fontSize: 12.5, padding: '14px 0' } }, 'No sessions yet. Save the current setup to switch back to it later.')
        : h('div', { style: { display: 'flex', flexDirection: 'column', gap: 6 } }, h('span', { style: label11 }, `${list.length} saved`),
          h('ul', { style: { listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 6 } },
            list.map(s => h(Row, { key: s.id, s, api, toast, on, open, setOpen, reload })))));
}

/** "Restore last session?" after an unclean shutdown (dismissal remembered for this tab). */
export function RestorePrompt({ api, onRestore }) {
  const React = R(), [st, setSt] = React.useState(null);
  React.useEffect(() => {
    let dismissed = false;
    try { dismissed = sessionStorage.getItem(DISMISS) === '1'; } catch { /* private window */ }
    if (dismissed) return;
    api.getSessionState?.().then(x => { if (x?.unclean_shutdown && x.last_auto && !x.restoring) setSt(x); }).catch(() => {});
  }, []);
  if (!st) return null;
  const close = () => { try { sessionStorage.setItem(DISMISS, '1'); } catch { /* ignore */ } setSt(null); };
  return h('div', { role: 'alertdialog', 'aria-label': 'Restore last session', style: { position: 'fixed', top: 56, right: 16, zIndex: 94, width: 'min(380px, calc(100vw - 32px))', padding: '12px 14px', borderRadius: 10,
    background: T.card, border: '1px solid ' + T.bds, boxShadow: '0 14px 40px rgba(0,0,0,.35)', display: 'flex', flexDirection: 'column', gap: 8 } },
    h('div', { style: { display: 'flex', gap: 8, alignItems: 'center', fontWeight: 600 } }, h('span', { style: { color: T.pu, display: 'flex' } }, h(Icon, { d: 'refresh', size: 15 })), 'Restore last session?'),
    h('div', { style: { fontSize: 12.5, color: T.mut } }, `AIHub didn’t shut down cleanly. The last setup (saved ${ago(st.last_auto.updated_ts)}): ${st.last_auto.summary}.`),
    h('div', { style: { display: 'flex', gap: 8 } }, h(Btn, { kind: 'pri', sm: true, label: 'Restore…', onClick: () => { close(); onRestore(st.last_auto.id); } }), h(Btn, { kind: 'ghost', sm: true, label: 'Dismiss', onClick: close })));
}
