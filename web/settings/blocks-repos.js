// Settings → Services → Repositories (plan mod-repos 3.5): relay, lcpp, tts and gen3d are their own
// repositories (git submodules). One row per mod: its repository and branch, the pinned and checked-out
// commits, its problems with their fix, and Update / Pin; Check now asks GitHub. Update first lists the
// incoming commits (GET /api/repos/{id}/incoming), then follows the hub's update to its result.
// Written by us (web/PATCHES.md); the pure parts are in repos-view.js.

import { h, T, MONO, Btn, Badge } from '../chat/chat-ui.js';
import { checkoutText, fetchedText, repoBadges, updateLine, updatePlan } from './repos-view.js';

const R = () => globalThis.React;
const ghUrl = url => { const m = /github\.com[:/](.+?)(?:\.git)?$/.exec(url || ''); return m ? `https://github.com/${m[1]}` : null; };

function RepoRow({ r, busy, onUpdate, onPin, last }) {
  const gh = ghUrl(r.url), badges = repoBadges(r), canPin = (r.problems || []).some(p => p.code === 'checkout_ahead_of_pin');
  const plan = updatePlan(r);
  return h('div', { style: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '6px 12px', padding: '10px 0', borderBottom: last ? 'none' : '1px solid ' + T.bd } },
    h('div', { style: { flex: '1 1 260px', minWidth: 0 } },
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
        h('span', { style: { fontWeight: 600 } }, r.id),
        gh ? h('a', { href: gh, target: '_blank', rel: 'noreferrer', style: { fontSize: 12, color: T.mut } }, gh.replace('https://github.com/', '')) : h('span', { style: { fontSize: 12, color: T.mut } }, r.url),
        h('span', { style: { fontSize: 12, color: T.dim, fontFamily: MONO } }, r.branch),
        ...badges.map(b => h(Badge, { key: b.code, tone: b.tone, title: b.title }, b.text))),
      h('div', { style: { fontSize: 12, color: T.mut, fontFamily: MONO, marginTop: 3 } },
        `pinned ${(r.pinned || '—').slice(0, 10)} · checkout ${checkoutText(r)}`),
      ...(r.problems || []).filter(p => p.level !== 'info' || p.code === 'fetch_failed').map(p => h('div', { key: p.code, style: { fontSize: 12, marginTop: 3, color: p.level === 'error' ? T.rd : T.mut } },
        p.title + '. ', p.fix ? h('span', { style: { fontFamily: MONO, fontSize: 11.5 } }, p.fix) : null))),
    h('div', { style: { display: 'flex', gap: 6, flex: 'none' } },
      canPin ? h(Btn, { sm: true, label: 'Pin', title: 'Record this checkout as GAIFA’s pin (staged)', disabled: busy, onClick: () => onPin(r) }) : null,
      h(Btn, { sm: true, kind: plan.can ? 'pri' : 'sec', label: 'Update…', disabled: busy || !plan.can, title: plan.can ? 'See what’s new, then update' : plan.why, onClick: () => onUpdate(r) })));
}

function Confirm({ r, incoming, err, onGo, onCancel }) {
  const plan = updatePlan(r, incoming);
  return h('div', { role: 'dialog', 'aria-label': `Update ${r.id}`, style: { margin: '8px 0', padding: 12, border: '1px solid ' + T.bds, borderRadius: 8, background: T.inset } },
    err ? h('div', { style: { color: T.rd, fontSize: 12.5 } }, String(err.detail || err.message || err))
      : !incoming ? h('div', { style: { fontSize: 12.5, color: T.mut } }, `Asking GitHub what’s new in ${r.id}…`)
        : h(R().Fragment, null,
          h('div', { style: { fontSize: 12.5, marginBottom: 8 } }, plan.can ? plan.text : plan.why),
          incoming.length ? h('ul', { style: { margin: '0 0 8px', paddingLeft: 18, fontSize: 12, fontFamily: MONO, color: T.mut, maxHeight: 180, overflow: 'auto' } },
            incoming.map(c => h('li', { key: c }, c))) : null),
    h('div', { style: { display: 'flex', gap: 8 } },
      h(Btn, { sm: true, kind: 'pri', label: `Update ${r.id}`, disabled: !incoming || !plan.can, onClick: onGo }),
      h(Btn, { sm: true, kind: 'ghost', label: 'Cancel', onClick: onCancel })));
}

export function RepositoriesTable({ ctx }) {
  const React = R(), api = ctx.api;
  const [body, setBody] = React.useState(ctx.repos || null), [err, setErr] = React.useState(null), [busy, setBusy] = React.useState(false);
  const [confirm, setConfirm] = React.useState(null);   // {r, incoming, err}
  const load = React.useCallback(async (how = 'get') => {
    try {
      const b = how === 'fetch' ? await api.fetchRepos() : await api.getRepos(how === 'refresh');
      setBody(b); setErr(null); ctx.onRepos?.(b);
      return b;
    } catch (e) { setErr(e); return null; }
  }, [api]);
  React.useEffect(() => { if (api.getRepos) load(); }, [load]);
  const running = !!body?.update?.running;
  React.useEffect(() => {                                   // follow an update until it ends
    if (!running) return undefined;
    const t = setInterval(() => load(), 1000);
    return () => clearInterval(t);
  }, [running, load]);
  if (!api.getRepos) return h('div', { style: { padding: '12px 0', color: T.mut, fontSize: 12.5 } }, 'This hub doesn’t serve /api/repos yet.');
  const act = async fn => { setBusy(true); try { await fn(); } catch (e) { ctx.toast?.(String(e.detail || e.message || e), 'error'); } finally { setBusy(false); } };
  const openUpdate = async r => {
    setConfirm({ r, incoming: null });
    try { const x = await api.repoIncoming(r.id); setConfirm(c => c && c.r.id === r.id ? { ...c, incoming: x.commits || [] } : c); }
    catch (e) { setConfirm(c => c && { ...c, err: e }); }
  };
  const go = () => act(async () => { const r = confirm.r; setConfirm(null); await api.updateRepo(r.id, {}); await load(); });
  const pin = r => act(async () => { const x = await api.pinRepo(r.id); ctx.toast?.(x.message); await load(); });
  const line = updateLine(body?.update);
  const list = body?.repos || [];
  return h('div', { style: { padding: '6px 0 12px' } },
    h('div', { style: { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', fontSize: 12.5, color: T.mut, padding: '6px 0' } },
      h('span', { style: { flex: '1 1 240px' } }, 'Each is a git submodule: GAIFA keeps the commit it was tested with, and you update it here or with ',
        h('code', { style: { fontFamily: MONO, fontSize: 12 } }, 'gaifa repos update <id>'), '.'),
      h('span', null, fetchedText(body?.last_fetch_ts)),
      h(Btn, { sm: true, label: busy ? 'Checking…' : 'Check now', disabled: busy || running, title: 'Ask GitHub what’s new in each', onClick: () => act(() => load('fetch')) })),
    err ? h('div', { role: 'alert', style: { color: T.rd, fontSize: 12.5, padding: '6px 0' } }, String(err.detail || err.message || err)) : null,
    line ? h('div', { role: 'status', style: { fontSize: 12.5, padding: '6px 0', color: { green: T.gr, red: T.rd, cyan: T.cy }[line.tone] } }, line.text) : null,
    confirm ? h(Confirm, { ...confirm, onGo: go, onCancel: () => setConfirm(null) }) : null,
    !body ? h('div', { style: { color: T.mut, fontSize: 12.5, padding: '6px 0' } }, 'Loading…')
      : !list.length ? h('div', { style: { color: T.mut, fontSize: 12.5, padding: '6px 0' } }, 'No mod here is its own repository (.gitmodules lists none).')
        : list.map((r, i) => h(RepoRow, { key: r.id, r, busy: busy || running, last: i === list.length - 1, onUpdate: openUpdate, onPin: pin })));
}

export const REPO_BLOCKS = { RepositoriesTable };
