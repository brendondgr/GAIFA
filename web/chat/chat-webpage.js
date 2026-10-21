// Web pages as attachments (plan 30.8): a paste that is one http(s) URL offers to read the page, and the attach
// menu has "Add a web page". Reading goes through the hub (POST /api/web/read): the web mod saves the page as an
// output, the hub screens all of it for instructions aimed at an AI and keeps the report; the chip carries the
// output like an upload, with how the screening went. No approval card: it's your own action, like an upload.

import { h, T, MONO, Icon, Btn, Badge, inputSt, label11 } from './chat-ui.js';
import { toChip } from './chat-files.js';

const R = () => globalThis.React;

/** The URL when the whole paste is one http(s) URL (surrounding spaces, `<…>` allowed), else null. */
export function loneUrl(text) {
  const s = String(text ?? '').trim().replace(/^<(.*)>$/s, '$1');
  if (!s || s.length > 2048 || /\s/.test(s)) return null;
  const m = /^https?:\/\/[^\s/?#]+[^\s]*$/i.exec(s);
  if (!m) return null;
  try { const u = new URL(s); return /^https?:$/.test(u.protocol) && u.hostname.includes('.') ? s : null; } catch { return null; }
}

/** The host without www., for the chip. */
export function hostOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; }
}

/** A read page (POST /api/web/read) as an attachment chip: the output, plus where it came from and its screening. */
export function pageChip(r) {
  const s = r.screening;
  return { ...toChip(r.output), web: { url: r.final_url || r.url, host: hostOf(r.final_url || r.url), removed: s ? s.removed : null, checked: s ? s.checked : 'off' } };
}

/** The chip's screening badge: [label, tone, title]. */
export function screenBadge(web) {
  if (!web) return null;
  if (web.checked === 'off') return ['not screened', 'dim', 'Screening of pages is off (Settings → Agent)'];
  if (web.removed) return [`${web.removed} removed`, 'accent', `Screening removed ${web.removed} passage${web.removed === 1 ? '' : 's'} that looked like instructions aimed at an AI; the agent reads the page without them. The full page is the output.`];
  if (web.checked === 'patterns') return ['patterns only', 'accent', 'Checked by fixed patterns only: the screening model didn’t answer'];
  return ['checked', 'green', 'Screened: nothing aimed at an AI found'];
}

export function WebBadge({ web }) {
  const b = screenBadge(web);
  return b ? h(Badge, { tone: b[1], title: b[2] }, b[0]) : null;
}

/** "Read this page?" under a pasted URL. */
export function WebPageOffer({ url, onAttach, onDismiss }) {
  return h('div', { role: 'group', 'aria-label': 'Read the pasted page', style: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 11.5, color: T.mut, minWidth: 0 } },
    h(Icon, { d: 'globe', size: 12 }),
    h('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0, fontFamily: MONO } }, url),
    h(Btn, { sm: true, icon: 'clip', label: 'Attach as a web page', title: 'Read the page and attach it: the agent gets its text, screened for instructions aimed at an AI', onClick: () => onAttach(url) }),
    h('button', { type: 'button', 'aria-label': 'No thanks', onClick: onDismiss, style: { border: 0, background: 'none', padding: 2, color: T.mut, cursor: 'pointer', display: 'flex' } }, h(Icon, { d: 'x', size: 11 })));
}

/** The attach menu's "Add a web page (URL)". */
export function AddWebPage({ onRead }) {
  const React = R(), [v, setV] = React.useState(''), ok = loneUrl(v);
  const go = () => { if (ok) { onRead(ok); setV(''); } };
  return h(R().Fragment, null,
    h('span', { style: label11 }, 'Add a web page (URL)'),
    h('div', { style: { display: 'flex', gap: 6 } },
      h('input', { value: v, onChange: e => setV(e.target.value), onKeyDown: e => { if (e.key === 'Enter') { e.preventDefault(); go(); } },
        placeholder: 'https://…', 'aria-label': 'Web page URL', style: { ...inputSt, flex: 1 } }),
      h(Btn, { sm: true, label: 'Add', disabled: !ok, onClick: go, title: 'Read the page and attach it' })));
}

/** Reads `url` and returns its chip; errors carry the hub's (the web mod's) detail and fix. */
export async function readPage(api, url) {
  const r = await api.readWebPage(url);
  return pageChip(r);
}
